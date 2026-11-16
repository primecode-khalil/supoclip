"""Run with python3 -m unittest discover -s deploy/vps -p 'test_*.py'."""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("vps_preflight", ROOT / "preflight.py")
preflight = importlib.util.module_from_spec(spec)
spec.loader.exec_module(preflight)


class PreflightTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.environment = (ROOT / ".env.example").read_text()
        for index, name in enumerate(("POSTGRES_PASSWORD", "REDIS_PASSWORD", "BACKEND_AUTH_SECRET", "APP_SETTINGS_ENCRYPTION_KEY", "BETTER_AUTH_SECRET", "INITIAL_SETUP_TOKEN")):
            self.environment = self.environment.replace(f"{name}=\n", f"{name}={chr(97 + index) * 64}\n")
        (self.directory / ".env").write_text(self.environment)
        (self.directory / ".env").chmod(0o600)
        (self.directory / "rclone.conf").touch(mode=0o600)
        result = subprocess.run(["docker", "compose", "--env-file", str(self.directory / ".env"), "-f", str(ROOT / "compose.yml"), "config", "--format", "json"], capture_output=True, text=True, check=True)
        self.config = json.loads(result.stdout)

    def test_boots_without_provider_keys_but_with_protected_initial_owner(self):
        preflight.validate(self.config, self.directory)
        self.assertEqual(self.config["services"]["frontend"]["environment"]["SELF_HOST_SINGLE_USER"], "true")
        for name, service in self.config["services"].items():
            if name != "caddy":
                self.assertFalse(service.get("ports"), name)
        self.assertEqual(self.config["services"]["frontend"]["build"]["target"], "runner")

    def test_refuses_readable_private_env(self):
        (self.directory / ".env").chmod(0o644)
        with self.assertRaisesRegex(SystemExit, "chmod 600"):
            preflight.validate(self.config, self.directory)

    def test_dedicated_upload_endpoint_requires_plain_https_address(self):
        frontend = self.config["services"]["frontend"]["environment"]
        for url in ("http://uploads.example.com/upload", "https://user:secret@uploads.example.com/upload", "https://uploads.example.com/upload?token=value", "https://uploads.example.com/upload#part", "https://uploads.example.com:not-a-port/upload"):
            with self.subTest(url=url):
                frontend["UPLOAD_PUBLIC_URL"] = url
                with self.assertRaisesRegex(SystemExit, "UPLOAD_PUBLIC_URL"):
                    preflight.validate(self.config, self.directory)
        frontend["UPLOAD_PUBLIC_URL"] = "https://uploads.example.com/backend/upload"
        preflight.validate(self.config, self.directory)

    def test_refuses_unprotected_setup_and_reused_server_secrets(self):
        frontend = self.config["services"]["frontend"]["environment"]
        frontend["INITIAL_SETUP_TOKEN"] = ""
        with self.assertRaisesRegex(SystemExit, "INITIAL_SETUP_TOKEN"):
            preflight.validate(self.config, self.directory)
        frontend["INITIAL_SETUP_TOKEN"] = "z" * 64
        frontend["BETTER_AUTH_SECRET"] = self.config["services"]["backend"]["environment"]["BACKEND_AUTH_SECRET"]
        with self.assertRaisesRegex(SystemExit, "distinct"):
            preflight.validate(self.config, self.directory)

    def test_https_override_replaces_http_port_and_proxy_file(self):
        result = subprocess.run(["docker", "compose", "--env-file", str(self.directory / ".env"), "-f", str(ROOT / "compose.yml"), "-f", str(ROOT / "compose.https.yml"), "config", "--format", "json"], capture_output=True, text=True, check=True)
        caddy = json.loads(result.stdout)["services"]["caddy"]
        self.assertEqual({port["published"] for port in caddy["ports"]}, {"80", "443"})
        mount = next(value for value in caddy["volumes"] if value["target"] == "/etc/caddy/Caddyfile")
        self.assertTrue(mount["source"].endswith("Caddyfile.https"))

    def external_https_config(self):
        services = self.config["services"]
        services["frontend"]["environment"]["BETTER_AUTH_URL"] = "https://clips.example.com"
        services["frontend"]["build"]["args"]["NEXT_PUBLIC_API_URL"] = "https://clips.example.com/backend"
        services["caddy"]["environment"]["APP_DOMAIN"] = "clips.example.com"
        for mount in services["caddy"]["volumes"]:
            if mount["target"] == "/etc/caddy/Caddyfile":
                mount["source"] = str(ROOT / "Caddyfile.external-https")
        services["caddy"]["ports"] = [{"host_ip": "10.42.0.1", "published": "13107", "target": 80, "protocol": "tcp"}]
        return self.config

    def test_accepts_external_https_without_requesting_a_second_certificate(self):
        preflight.validate(self.external_https_config(), self.directory)

    def test_external_https_refuses_public_or_wildcard_http_binding(self):
        config = self.external_https_config()
        for host in ("0.0.0.0", "::", "144.91.80.31", ""):
            with self.subTest(host=host):
                config["services"]["caddy"]["ports"][0]["host_ip"] = host
                with self.assertRaisesRegex(SystemExit, "private or loopback"):
                    preflight.validate(config, self.directory)

    def test_external_https_refuses_plain_http_origin(self):
        config = self.external_https_config()
        config["services"]["frontend"]["environment"]["BETTER_AUTH_URL"] = "http://clips.example.com"
        with self.assertRaisesRegex(SystemExit, "external HTTPS proxy requires an HTTPS"):
            preflight.validate(config, self.directory)

    def test_compose_wrapper_selects_private_external_https_mode(self):
        setup = self.directory / "external-proxy"
        shutil.copytree(ROOT, setup, ignore=shutil.ignore_patterns("__pycache__", ".env", "rclone.conf", ".bootstrap*"))
        environment = self.environment.replace("VPS_EXTERNAL_HTTPS=false", "VPS_EXTERNAL_HTTPS=true")
        environment = environment.replace("http://localhost:3107", "https://clips.example.com")
        environment = environment.replace("APP_DOMAIN=localhost", "APP_DOMAIN=clips.example.com")
        environment = environment.replace("HTTP_BIND=0.0.0.0", "HTTP_BIND=10.42.0.1")
        (setup / ".env").write_text(environment)
        (setup / ".env").chmod(0o600)
        (setup / "rclone.conf").touch(mode=0o600)
        result = subprocess.run([str(setup / "compose.sh"), "config", "--format", "json"], capture_output=True, text=True, check=True)
        config = json.loads(result.stdout)
        preflight.validate(config, setup)
        self.assertEqual(config["services"]["caddy"]["ports"][0]["host_ip"], "10.42.0.1")
        (setup / ".env").write_text(environment.replace("VPS_HTTPS=false", "VPS_HTTPS=true"))
        conflict = subprocess.run([str(setup / "compose.sh"), "config", "--quiet"], capture_output=True, text=True)
        self.assertNotEqual(conflict.returncode, 0)
        self.assertIn("not both", conflict.stderr)

    def test_private_initialization_never_overwrites_existing_secrets(self):
        setup = self.directory / "clean"
        setup.mkdir()
        shutil.copyfile(ROOT / ".env.example", setup / ".env.example")
        shutil.copyfile(ROOT / "init-env.py", setup / "init-env.py")
        first = subprocess.run(["python3", str(setup / "init-env.py")], capture_output=True, text=True, check=True)
        before = (setup / ".env").read_bytes()
        self.assertEqual((setup / ".env").stat().st_mode & 0o777, 0o600)
        values = dict(line.split("=", 1) for line in before.decode().splitlines() if line and not line.startswith("#") and "=" in line)
        self.assertGreaterEqual(len(values["INITIAL_SETUP_TOKEN"]), 32)
        self.assertNotIn(values["INITIAL_SETUP_TOKEN"], first.stdout)
        second = subprocess.run(["python3", str(setup / "init-env.py")], capture_output=True, text=True)
        self.assertNotEqual(second.returncode, 0)
        self.assertEqual((setup / ".env").read_bytes(), before)

    def test_installer_prepares_without_starting_and_preserves_second_run(self):
        checkout = self.directory / "checkout"
        (checkout / "deploy").mkdir(parents=True)
        shutil.copytree(ROOT, checkout / "deploy/vps", ignore=shutil.ignore_patterns("__pycache__", ".env", "rclone.conf", ".https-enabled"))
        installer = ROOT.parents[1] / "install.sh"
        shutil.copyfile(installer, checkout / "install.sh")
        binary_directory = self.directory / "bin"
        binary_directory.mkdir()
        (binary_directory / "uname").write_text('#!/bin/sh\ncase "$1" in -s) echo Linux ;; -m) echo x86_64 ;; esac\n')
        (binary_directory / "uname").chmod(0o755)
        env = {**os.environ, "PATH": str(binary_directory) + os.pathsep + os.environ["PATH"]}
        command = ["bash", str(checkout / "install.sh"), "--directory", str(checkout), "--no-start"]
        first = subprocess.run(command, env=env, capture_output=True, text=True, check=True)
        private = checkout / "deploy/vps/.env"
        before = private.read_bytes()
        self.assertIn("No images were built or containers started", first.stdout)
        self.assertNotIn("Initial owner setup token (keep private):", first.stdout)
        second = subprocess.run(command, env=env, capture_output=True, text=True, check=True)
        self.assertIn("Preserving the existing private configuration", second.stdout)
        self.assertEqual(private.read_bytes(), before)
        self.assertIn(b"BACKEND_PLATFORM=linux/amd64", before)

    def test_installer_selects_arm64_without_requiring_amd64_emulation(self):
        checkout = self.directory / "arm-checkout"
        (checkout / "deploy").mkdir(parents=True)
        shutil.copytree(ROOT, checkout / "deploy/vps", ignore=shutil.ignore_patterns("__pycache__", ".env", "rclone.conf"))
        shutil.copyfile(ROOT.parents[1] / "install.sh", checkout / "install.sh")
        binary_directory = self.directory / "arm-bin"
        binary_directory.mkdir()
        (binary_directory / "uname").write_text('#!/bin/sh\ncase "$1" in -s) echo Linux ;; -m) echo aarch64 ;; esac\n')
        (binary_directory / "uname").chmod(0o755)
        env = {**os.environ, "PATH": str(binary_directory) + os.pathsep + os.environ["PATH"]}
        subprocess.run(["bash", str(checkout / "install.sh"), "--directory", str(checkout), "--no-start"], env=env, capture_output=True, text=True, check=True)
        self.assertIn("BACKEND_PLATFORM=linux/arm64", (checkout / "deploy/vps/.env").read_text())


    def test_remote_bootstrap_clones_feature_branch_and_supports_commit_pins(self):
        binary_directory = self.directory / "remote-bin"
        binary_directory.mkdir()
        (binary_directory / "uname").write_text('#!/bin/sh\ncase "$1" in -s) echo Linux ;; -m) echo x86_64 ;; esac\n')
        (binary_directory / "uname").chmod(0o755)
        (binary_directory / "git").write_text("""#!/usr/bin/env python3
import json, os, pathlib, shutil, sys
with open(os.environ['FAKE_GIT_LOG'], 'a') as output:
    output.write(json.dumps(sys.argv[1:]) + '\\n')
if sys.argv[1] == 'clone':
    destination = pathlib.Path(sys.argv[-1])
    (destination / 'deploy').mkdir(parents=True)
    shutil.copytree(os.environ['FAKE_VPS_TEMPLATE'], destination / 'deploy/vps', ignore=shutil.ignore_patterns('__pycache__', '.env', 'rclone.conf', '.bootstrap*'))
""")
        (binary_directory / "git").chmod(0o755)
        log = self.directory / "git-commands.jsonl"
        env = {**os.environ, "PATH": str(binary_directory) + os.pathsep + os.environ["PATH"],
               "FAKE_GIT_LOG": str(log), "FAKE_VPS_TEMPLATE": str(ROOT)}
        env.pop("SUPOCLIP_REF", None)
        installer = ROOT.parents[1] / "install.sh"
        branch_target = self.directory / "remote-branch"
        subprocess.run(["bash", str(installer), "--directory", str(branch_target), "--no-start"], env=env, capture_output=True, text=True, check=True)
        commands = [json.loads(line) for line in log.read_text().splitlines()]
        self.assertEqual(commands[0][0:3], ["clone", "--branch", "feat/recording-foundation"])
        self.assertTrue((branch_target / "deploy/vps/.env").exists())
        commit_target = self.directory / "remote-commit"
        commit = "a" * 40
        subprocess.run(["bash", str(installer), "--directory", str(commit_target), "--ref", commit, "--no-start"], env=env, capture_output=True, text=True, check=True)
        commands = [json.loads(line) for line in log.read_text().splitlines()]
        self.assertTrue(any(command[2:] == ["fetch", "--depth", "1", "origin", commit] for command in commands))
        self.assertTrue(any(command[-3:] == ["checkout", "--detach", "FETCH_HEAD"] for command in commands))



if __name__ == "__main__":
    unittest.main()
