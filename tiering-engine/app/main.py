"""Scan-and-tier / rehydrate entrypoint: one pass over one volume root.

Runs as a k8s CronJob per volume (tier) or a one-off Job (rehydrate). Usage:
    python -m app.main tier /mnt/vol1 --target azure --cold-after-days 30
    python -m app.main tier /mnt/vol1 --target local --archive-dir /archive
    python -m app.main rehydrate /mnt/vol1 --target azure

The azure target reads MINIFILES_AZURE_CONN_STRING and
MINIFILES_AZURE_CONTAINER from the environment (a k8s Secret in-cluster).
"""

import argparse
import logging
import os
from pathlib import Path

from app.scanner import STUB_SUFFIX, find_cold_files
from app.tierer import (
    AzureBlobTarget,
    FileChangedError,
    LocalArchiveTarget,
    TierTarget,
    rehydrate,
    tier_file,
)

log = logging.getLogger("minifiles.tiering")


def run_scan(volume_root: Path, target: TierTarget, cold_after_seconds: float) -> tuple[int, int]:
    """Returns (files_tiered, bytes_tiered)."""
    files = bytes_ = 0
    for cold in find_cold_files(volume_root, cold_after_seconds):
        try:
            tier_file(cold, volume_root, target)
        except FileChangedError:
            continue  # got warm between scan and tier
        files += 1
        bytes_ += cold.size_bytes
    return files, bytes_


def run_rehydrate(volume_root: Path, target: TierTarget) -> int:
    """Restore every tiered file under volume_root; returns files restored."""
    restored = 0
    for stub_path in sorted(volume_root.rglob(f"*{STUB_SUFFIX}")):
        rehydrate(stub_path, target)
        restored += 1
    return restored


def make_target(args: argparse.Namespace) -> TierTarget:
    if args.target == "azure":
        conn = os.environ.get("MINIFILES_AZURE_CONN_STRING")
        container = os.environ.get("MINIFILES_AZURE_CONTAINER", "tiered")
        if not conn:
            raise SystemExit("MINIFILES_AZURE_CONN_STRING is required for --target azure")
        return AzureBlobTarget.from_connection_string(
            conn, container, key_prefix=args.key_prefix
        )
    if args.archive_dir is None:
        raise SystemExit("--archive-dir is required for --target local")
    return LocalArchiveTarget(args.archive_dir)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["tier", "rehydrate"])
    parser.add_argument("volume_root", type=Path)
    parser.add_argument("--target", choices=["local", "azure"], default="local")
    parser.add_argument("--archive-dir", type=Path, help="local target only")
    parser.add_argument("--key-prefix", default="", help="e.g. 'vol-abc123/' to scope blobs per volume")
    parser.add_argument("--cold-after-days", type=float, default=30)
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO)
    target = make_target(args)
    if args.command == "tier":
        files, bytes_ = run_scan(args.volume_root, target, args.cold_after_days * 86400)
        log.info("tiered %d files, %d bytes", files, bytes_)
    else:
        restored = run_rehydrate(args.volume_root, target)
        log.info("rehydrated %d files", restored)


if __name__ == "__main__":
    main()
