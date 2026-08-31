"""Scan-and-tier entrypoint: one pass over one volume root.

Runs as a k8s CronJob per volume (M2). Usage:
    python -m app.main /mnt/vol1 --archive-dir /archive --cold-after-days 30
"""

import argparse
import logging
from pathlib import Path

from app.scanner import find_cold_files
from app.tierer import FileChangedError, LocalArchiveTarget, tier_file

log = logging.getLogger("minifiles.tiering")


def run_scan(volume_root: Path, target, cold_after_seconds: float) -> tuple[int, int]:
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


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("volume_root", type=Path)
    parser.add_argument("--archive-dir", type=Path, required=True)
    parser.add_argument("--cold-after-days", type=float, default=30)
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO)
    target = LocalArchiveTarget(args.archive_dir)  # M2: AzureBlobTarget
    files, bytes_ = run_scan(args.volume_root, target, args.cold_after_days * 86400)
    log.info("tiered %d files, %d bytes", files, bytes_)


if __name__ == "__main__":
    main()
