"""Recovery checks use a stateful Compose fake; no Docker mutation is performed."""
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("vps_bootstrap", ROOT / "bootstrap.py")
bootstrap = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bootstrap)


class ComposeFake:
    def __init__(self, *, existing=False, guard=False, exposed=False):
        self.existing = existing
        self.guard = guard
        self.exposed = exposed
        self.fail_all_up = False
        self.fail_health = False
        self.commands = []
        self.guard_installations = 0

    def __call__(self, command, *, capture=False, input_text=None):
        self.commands.append(command)
        if command[-3:] == ["ps", "--all", "--quiet"]:
            return "backend-id\n" if self.existing else ""
        if "ps" in command and command[-1] == "frontend":
            return "frontend-id\n" if self.exposed else ""
        if command[-1].startswith("SELECT to_regclass"):
            return "t\n" if self.guard else "f\n"
        if input_text:
            self.guard_installations += 1
            self.guard = True
        if "up" in command:
            self.existing = True
            if command[-1] != "backend" and self.fail_all_up:
                raise subprocess.CalledProcessError(1, command)
        if command[0].endswith("health.sh") and self.fail_health:
            raise subprocess.CalledProcessError(1, command)
        return ""


class BootstrapTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        (self.directory / "single-user.sql").write_text("TEST SINGLE OWNER GUARD")
        self.revision = patch.object(bootstrap, "current_revision", return_value="a" * 40)
        self.revision.start()
        self.addCleanup(self.revision.stop)

    def execute(self, fake):
        with patch.object(bootstrap, "run", side_effect=fake):
            bootstrap.initialize(self.directory)

    def test_partial_install_starts_missing_services_without_replacing_running_work(self):
        fake = ComposeFake(existing=True)
        self.execute(fake)
        commands = fake.commands
        self.assertFalse(any("build" in command for command in commands))
        up_commands = [command for command in commands if "up" in command]
        self.assertEqual(len(up_commands), 2)
        for command in up_commands:
            self.assertIn("--no-recreate", command)
            self.assertIn("--no-build", command)
        self.assertEqual(fake.guard_installations, 1)
        self.assertTrue((self.directory / ".bootstrap-complete").is_file())
        self.assertEqual((self.directory / ".bootstrap-complete").stat().st_mode & 0o777, 0o600)

    def test_first_install_refreshes_infrastructure_images(self):
        fake = ComposeFake()
        self.execute(fake)
        self.assertIn([str(self.directory / "compose.sh"), "pull", "--ignore-buildable", "postgres", "redis", "caddy"], fake.commands)

    def test_first_install_builds_each_shared_image_only_once(self):
        fake = ComposeFake()
        self.execute(fake)
        builds = [command for command in fake.commands if "build" in command]
        self.assertEqual(builds, [[str(self.directory / "compose.sh"), "build", "--pull", "backend", "frontend", "postgres"]])

    def test_failed_first_start_is_not_complete_and_rerun_resumes(self):
        fake = ComposeFake()
        fake.fail_all_up = True
        with self.assertRaises(subprocess.CalledProcessError):
            self.execute(fake)
        self.assertFalse((self.directory / ".bootstrap-complete").exists())
        self.assertTrue((self.directory / ".bootstrap-started").exists())
        self.assertTrue(fake.guard)
        fake.fail_all_up = False
        fake.commands.clear()
        self.execute(fake)
        self.assertFalse(any("build" in command for command in fake.commands))
        self.assertEqual(fake.guard_installations, 1, "A guarded database must not be modified again during resume")
        self.assertTrue((self.directory / ".bootstrap-complete").exists())

    def test_existing_completed_install_only_checks_health_and_does_not_restart(self):
        bootstrap.write_marker(self.directory / ".bootstrap-complete", "a" * 40)
        fake = ComposeFake(existing=True, guard=True)
        self.execute(fake)
        self.assertEqual(fake.commands, [[str(self.directory / "health.sh")]])
        fake.fail_health = True
        with self.assertRaisesRegex(bootstrap.BootstrapError, "No services were restarted"):
            self.execute(fake)
        self.assertFalse(any("up" in command for command in fake.commands))

    def test_health_failure_does_not_write_success_marker(self):
        fake = ComposeFake(existing=True, guard=True)
        fake.fail_health = True
        with self.assertRaises(subprocess.CalledProcessError):
            self.execute(fake)
        self.assertFalse((self.directory / ".bootstrap-complete").exists())

    def test_changed_revision_or_unguarded_exposed_frontend_require_recovery(self):
        bootstrap.write_marker(self.directory / ".bootstrap-started", "b" * 40)
        fake = ComposeFake(existing=True)
        with self.assertRaisesRegex(bootstrap.BootstrapError, "different source revision"):
            self.execute(fake)
        self.assertEqual(fake.commands, [])
        (self.directory / ".bootstrap-started").unlink()
        fake.exposed = True
        with self.assertRaisesRegex(bootstrap.BootstrapError, "frontend is already running"):
            self.execute(fake)
        self.assertEqual(fake.guard_installations, 0)
        self.assertFalse((self.directory / ".bootstrap-complete").exists())


if __name__ == "__main__":
    unittest.main()
