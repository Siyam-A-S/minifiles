import json
import os
import time
from pathlib import Path

from app.main import run_scan
from app.scanner import find_cold_files
from app.tierer import LocalArchiveTarget, rehydrate

DAY = 86400


def _make_file(root: Path, rel: str, content: bytes, age_days: float) -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    old = time.time() - age_days * DAY
    os.utime(path, (old, old))
    return path


def test_scanner_finds_only_cold_files(tmp_path):
    _make_file(tmp_path, "cold.txt", b"old", age_days=60)
    _make_file(tmp_path, "sub/also-cold.txt", b"old", age_days=45)
    _make_file(tmp_path, "hot.txt", b"new", age_days=0)

    cold = {c.path.name for c in find_cold_files(tmp_path, cold_after_seconds=30 * DAY)}
    assert cold == {"cold.txt", "also-cold.txt"}


def test_tier_and_rehydrate_roundtrip(tmp_path):
    vol = tmp_path / "vol"
    archive = tmp_path / "archive"
    content = b"important bytes"
    original = _make_file(vol, "data/report.csv", content, age_days=60)
    target = LocalArchiveTarget(archive)

    files, bytes_ = run_scan(vol, target, cold_after_seconds=30 * DAY)
    assert (files, bytes_) == (1, len(content))
    assert not original.exists()

    stub_path = next(vol.rglob("*.minifiles-tiered.json"))
    stub = json.loads(stub_path.read_text())
    assert stub["key"] == "data/report.csv"

    restored = rehydrate(stub_path, target)
    assert restored.read_bytes() == content
    assert not stub_path.exists()


def test_rescan_is_idempotent(tmp_path):
    vol = tmp_path / "vol"
    _make_file(vol, "cold.txt", b"old", age_days=60)
    target = LocalArchiveTarget(tmp_path / "archive")

    assert run_scan(vol, target, cold_after_seconds=30 * DAY)[0] == 1
    # second pass sees only the stub and tiers nothing
    assert run_scan(vol, target, cold_after_seconds=30 * DAY)[0] == 0
