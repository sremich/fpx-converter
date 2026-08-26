"""Copy one `.fpx` per distinct SHA-256 into the repo's local store.

The copy is a convenience, not the archive — the archive is the backup tree,
and it is never touched. Every copy is verified by re-hashing the destination
against the manifest, and an existing correct copy is left alone so an
interrupted run resumes for free.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .scan import sha256_file


@dataclass
class IngestReport:
    copied: int = 0
    skipped: int = 0
    bytes_copied: int = 0
    failures: list[tuple[str, str]] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.failures


def ingest(
    manifest: dict[str, Any],
    *,
    source_root: Path,
    dest_dir: Path,
    dry_run: bool = False,
) -> IngestReport:
    report = IngestReport()
    if not dry_run:
        dest_dir.mkdir(parents=True, exist_ok=True)

    for entry in manifest["entries"]:
        sha = entry["sha256"]
        src = source_root / entry["preferred_relpath"]
        dst = dest_dir / entry["store_name"]

        if dst.is_file() and dst.stat().st_size == entry["size"] and sha256_file(dst) == sha:
            report.skipped += 1
            continue

        if dry_run:
            report.copied += 1
            report.bytes_copied += int(entry["size"])
            continue

        try:
            # copy2 preserves mtime. It reads the source and writes only to
            # the destination; nothing under source_root is opened for write.
            shutil.copy2(src, dst)
        except OSError as exc:
            report.failures.append((entry["store_name"], f"copy failed: {exc}"))
            continue

        actual = sha256_file(dst)
        if actual != sha:
            report.failures.append(
                (entry["store_name"], f"hash mismatch after copy: expected {sha}, got {actual}")
            )
            continue

        report.copied += 1
        report.bytes_copied += dst.stat().st_size

    return report


def verify_store(manifest: dict[str, Any], *, dest_dir: Path) -> list[tuple[str, str]]:
    """Re-hash every ingested copy against the manifest. Returns problems."""
    problems: list[tuple[str, str]] = []
    for entry in manifest["entries"]:
        dst = dest_dir / entry["store_name"]
        if not dst.is_file():
            problems.append((entry["store_name"], "missing from the store"))
            continue
        actual = sha256_file(dst)
        if actual != entry["sha256"]:
            problems.append((entry["store_name"], f"hash mismatch: got {actual}"))
    return problems
