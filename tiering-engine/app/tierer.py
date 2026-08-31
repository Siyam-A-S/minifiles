"""Tier targets and the tiering operation.

Tiering a file = upload bytes to the target, then atomically replace the
original with a stub metadata file (write temp + rename) so a crash between
upload and replace leaves the original intact (worst case: an orphaned upload,
which a later idempotent run reconciles).
"""

import hashlib
import json
import os
import time
from pathlib import Path
from typing import Protocol

from app.scanner import STUB_SUFFIX, ColdFile


class TierTarget(Protocol):
    def upload(self, key: str, path: Path) -> str:
        """Upload file bytes under key; return a locator (URL/path)."""
        ...

    def download(self, key: str, dest: Path) -> None: ...


class LocalArchiveTarget:
    """Dev/test target: 'tiers' into a local archive directory."""

    def __init__(self, archive_dir: Path) -> None:
        self.archive_dir = archive_dir
        archive_dir.mkdir(parents=True, exist_ok=True)

    def upload(self, key: str, path: Path) -> str:
        dest = self.archive_dir / key
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(path.read_bytes())
        return str(dest)

    def download(self, key: str, dest: Path) -> None:
        dest.write_bytes((self.archive_dir / key).read_bytes())


class AzureBlobTarget:
    """M2: azure-storage-blob upload to the cool tier.

    Plan: container per volume, key = relative path; set StandardBlobTier.COOL
    on upload; SAS/managed identity for auth. See docs/roadmap.md M2.
    """

    def __init__(self, container_url: str) -> None:
        raise NotImplementedError("M2 — see docs/roadmap.md")


def tier_file(cold: ColdFile, volume_root: Path, target: TierTarget) -> Path:
    """Tier one file; returns the stub path. Re-checks freshness before acting."""
    st = cold.path.stat()
    if st.st_atime != cold.atime:
        raise FileChangedError(f"{cold.path} was accessed after scan; skipping")

    key = str(cold.path.relative_to(volume_root))
    checksum = hashlib.sha256(cold.path.read_bytes()).hexdigest()
    locator = target.upload(key, cold.path)

    stub = {
        "key": key,
        "locator": locator,
        "size_bytes": cold.size_bytes,
        "sha256": checksum,
        "tiered_at": time.time(),
    }
    stub_path = cold.path.with_name(cold.path.name + STUB_SUFFIX)
    tmp_path = stub_path.with_suffix(".tmp")
    tmp_path.write_text(json.dumps(stub, indent=2))
    os.replace(tmp_path, stub_path)  # atomic: stub appears fully-formed or not at all
    cold.path.unlink()
    return stub_path


def rehydrate(stub_path: Path, target: TierTarget) -> Path:
    """Restore a tiered file from its stub; verifies checksum, removes the stub."""
    stub = json.loads(stub_path.read_text())
    original = stub_path.with_name(stub_path.name.removesuffix(STUB_SUFFIX))
    tmp_path = original.with_suffix(original.suffix + ".rehydrating")
    target.download(stub["key"], tmp_path)
    digest = hashlib.sha256(tmp_path.read_bytes()).hexdigest()
    if digest != stub["sha256"]:
        tmp_path.unlink()
        raise ChecksumMismatchError(f"{original}: expected {stub['sha256']}, got {digest}")
    os.replace(tmp_path, original)
    stub_path.unlink()
    return original


class FileChangedError(Exception):
    pass


class ChecksumMismatchError(Exception):
    pass
