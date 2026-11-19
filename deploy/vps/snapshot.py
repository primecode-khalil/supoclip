"""Copy quiesced media volumes. /snapshot is an explicitly supplied private mount."""
from pathlib import Path
import hashlib
import json
import tarfile

root = Path("/snapshot")
if not root.is_dir():
    raise SystemExit("Mount a private destination directory at /snapshot")
manifest = {}
for source in ("uploads", "clips", "recordings"):
    destination = root / f"{source}.tar.gz"
    # Exclusive creation prevents overwriting an existing backup.
    with destination.open("xb") as output:
        with tarfile.open(fileobj=output, mode="w|gz") as archive:
            archive.add(Path("/sources") / source, arcname=source)
    checksum = hashlib.sha256()
    with destination.open("rb") as content:
        for block in iter(lambda: content.read(1024 * 1024), b""):
            checksum.update(block)
    destination.chmod(0o600)
    manifest[destination.name] = {"sha256": checksum.hexdigest(), "bytes": destination.stat().st_size}
with (root / "media-manifest.json").open("x") as output:
    json.dump(manifest, output, indent=2)
print("Media snapshot completed. Copy it off the VPS before relying on it for disaster recovery.")
