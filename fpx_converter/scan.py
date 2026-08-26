"""Read-only walk of the source archive, and the hash cascade behind it.

Every function here opens files in binary read mode and nothing else. The
read-only promise is not left as a comment: a snapshot of **every file** in
the tree is taken before anything is opened and compared afterwards, and a
random sample is re-hashed to catch a change that preserved size and mtime.

Two properties of that check are load-bearing and easy to get wrong:

* The snapshot covers the whole tree, not just the `.fpx` files. A file
  *added* to the archive is a write, and a check that only looks at files it
  already knew about cannot see one.
* The sample is drawn from an unseeded generator. A fixed seed over a sorted
  file list re-hashes the same handful of files on every run forever, which
  leaves the rest of the archive permanently outside the check while looking
  exactly like sampling.
"""

from __future__ import annotations

import hashlib
import random
import stat as stat_module
import sys
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import olefile

#: 1 MiB. Large enough that a 500 MB corpus is a few hundred reads per file,
#: small enough not to hold a whole photo in memory at once.
_CHUNK = 1024 * 1024


def iter_fpx_files(root: Path) -> Iterator[Path]:
    """Yield every `.fpx` under `root`, case-insensitively, sorted.

    Sorted so two runs on the same tree produce the same manifest ordering;
    a manifest that reshuffles on every run is a diff nobody can read.
    """
    yield from sorted(
        (p for p in root.rglob("*") if p.is_file() and p.suffix.lower() == ".fpx"),
        key=lambda p: str(p).lower(),
    )


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(_CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


def tree_snapshot(root: Path) -> dict[str, tuple[int, int]]:
    """size and mtime_ns for every regular file under `root`.

    Deliberately not limited to `.fpx`: creating a file is a write, and the
    binding rule is that this tool writes nothing under the source root at
    all. Restricting the snapshot to the files we care about would make an
    added file invisible to the very check meant to catch it.
    """
    snapshot: dict[str, tuple[int, int]] = {}
    for path in root.rglob("*"):
        try:
            info = path.stat()
        except OSError:
            # A path that cannot be stat'ed cannot be compared; it is
            # reported by the after-pass as vanished if it was there before.
            continue
        if stat_module.S_ISREG(info.st_mode):
            snapshot[str(path)] = (info.st_size, info.st_mtime_ns)
    return snapshot


@dataclass
class UnchangedReport:
    checked: int
    resampled: int
    modified: list[str] = field(default_factory=list)
    vanished: list[str] = field(default_factory=list)
    added: list[str] = field(default_factory=list)
    rehash_mismatches: list[str] = field(default_factory=list)
    #: Which files were actually re-hashed. Recorded so the manifest shows
    #: what the run really verified, and so successive runs can be seen to
    #: cover different files rather than the same ones forever.
    sampled: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not (self.modified or self.vanished or self.added or self.rehash_mismatches)

    def as_dict(self) -> dict[str, object]:
        return {
            "ok": self.ok,
            "files_checked": self.checked,
            "files_rehashed": self.resampled,
            "modified": self.modified,
            "vanished": self.vanished,
            "added": self.added,
            "rehash_mismatches": self.rehash_mismatches,
            "sampled": self.sampled,
        }


def verify_unchanged(
    before: dict[str, tuple[int, int]],
    root: Path,
    hashes: dict[str, str],
    sample_size: int = 25,
    rng: random.Random | None = None,
) -> UnchangedReport:
    """Prove the tree under `root` is unchanged since `before` was taken.

    Size and mtime catch the ordinary accident, and re-walking catches an
    addition. Neither would catch a write that restored size and mtime, so a
    random sample is re-hashed as well — that is the check that would
    actually catch us corrupting the archive.

    `rng` exists so tests can pin the sample. Production runs leave it None
    and get an unseeded generator, so repeated runs cover different files.
    """
    if sample_size < 0:
        raise ValueError(f"sample_size must not be negative, got {sample_size}")

    after = tree_snapshot(root)
    report = UnchangedReport(checked=len(before), resampled=0)

    for path_str, signature in before.items():
        current = after.get(path_str)
        if current is None:
            report.vanished.append(path_str)
        elif current != signature:
            report.modified.append(path_str)
    report.added = sorted(set(after) - set(before))

    candidates = [p for p in before if p in hashes and p in after]
    chooser = rng if rng is not None else random.SystemRandom()
    sample = chooser.sample(candidates, min(sample_size, len(candidates)))
    report.resampled = len(sample)
    report.sampled = sorted(sample)
    for path_str in sample:
        if sha256_file(Path(path_str)) != hashes[path_str]:
            report.rehash_mismatches.append(path_str)
    return report


def ole_inventory(path: Path) -> dict[str, object]:
    """Stream and storage names inside one OLE2 compound document.

    Never raises: a file that cannot be parsed is recorded as such and the
    batch continues. The inventory found zero unparseable files, so anything
    landing in `error` here is news.
    """
    try:
        if not olefile.isOleFile(str(path)):
            return {"is_ole": False, "streams": [], "error": "not an OLE2 compound document"}
        with olefile.OleFileIO(str(path)) as ole:
            entries = ["/".join(parts) for parts in ole.listdir(streams=True, storages=True)]
        return {"is_ole": True, "streams": sorted(entries), "error": None}
    except Exception as exc:  # noqa: BLE001 - one bad file must not stop a batch
        return {"is_ole": None, "streams": [], "error": f"{type(exc).__name__}: {exc}"}


@dataclass
class ScannedFile:
    path: Path
    relpath: str
    name: str
    size: int
    mtime: str
    sha256: str
    streams: list[str]
    is_ole: bool | None
    ole_error: str | None


def scan_tree(
    root: Path,
    *,
    progress_every: int = 100,
    stream: object = sys.stderr,
) -> tuple[list[ScannedFile], dict[str, tuple[int, int]]]:
    """Hash and inventory every `.fpx` under `root`.

    Returns the scanned files and a whole-tree snapshot taken *before* any
    file was opened, for `verify_unchanged` to compare against.
    """
    snapshot = tree_snapshot(root)
    paths = list(iter_fpx_files(root))

    scanned: list[ScannedFile] = []
    for index, path in enumerate(paths, start=1):
        info = path.stat()
        inventory = ole_inventory(path)
        scanned.append(
            ScannedFile(
                path=path,
                relpath=path.relative_to(root).as_posix(),
                name=path.name,
                size=info.st_size,
                mtime=datetime.fromtimestamp(info.st_mtime, tz=UTC).isoformat(),
                sha256=sha256_file(path),
                streams=list(inventory["streams"]),  # type: ignore[arg-type]
                is_ole=inventory["is_ole"],  # type: ignore[arg-type]
                ole_error=inventory["error"],  # type: ignore[arg-type]
            )
        )
        if progress_every and index % progress_every == 0:
            print(f"  scanned {index}/{len(paths)}", file=stream, flush=True)  # type: ignore[arg-type]

    return scanned, snapshot
