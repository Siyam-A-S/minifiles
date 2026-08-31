"""Cold-data scanner.

Walks a volume mount and yields files whose access time is older than the
cold threshold. Invariants (same discipline as production tiering/GC
scanners):

- Idempotent: stub files (already-tiered markers) are skipped, so re-running
  over a half-tiered volume is safe.
- No surprises mid-flight: candidates are re-stat'ed at tiering time by the
  tierer, since atime may have changed between scan and tier.
- Resumable by construction: the scan is a generator; interrupting it loses
  nothing but position.
"""

import os
import time
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

STUB_SUFFIX = ".minifiles-tiered.json"


@dataclass(frozen=True)
class ColdFile:
    path: Path
    size_bytes: int
    atime: float


def find_cold_files(root: Path, cold_after_seconds: float, now: float | None = None) -> Iterator[ColdFile]:
    """Yield regular files under root not accessed within cold_after_seconds."""
    now = time.time() if now is None else now
    for dirpath, _dirnames, filenames in os.walk(root):
        for name in filenames:
            if name.endswith(STUB_SUFFIX):
                continue
            path = Path(dirpath) / name
            try:
                st = path.stat()
            except FileNotFoundError:
                continue  # raced with a delete; fine
            if not os.path.isfile(path) or os.path.islink(path):
                continue
            if now - st.st_atime > cold_after_seconds:
                yield ColdFile(path=path, size_bytes=st.st_size, atime=st.st_atime)
