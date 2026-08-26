"""The manifest: one record per distinct file, keyed on whole-file SHA-256.

Keying on SHA-256 rather than the pixel hash is a decision taken deliberately
(see DECISIONS.md). It costs roughly 27% more output than the pixel hash
would, and it means about 146 output pairs will be pixel-identical, differing
only by a timestamp buried in a property stream. That is expected. The audit
must never report it as a fault.

Every source path a given file appeared under is recorded, along with every
album — because that list is the only record of where a photo lived once the
duplicates are collapsed.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .naming import SourceLocation, assign_store_names, is_human_authored, preferred_location
from .scan import ScannedFile

MANIFEST_VERSION = 1


def build(
    scanned: list[ScannedFile],
    *,
    source_root: Path,
    tool_version: str,
    generated_at: str | None = None,
) -> dict[str, Any]:
    by_hash: dict[str, list[ScannedFile]] = {}
    for item in scanned:
        by_hash.setdefault(item.sha256, []).append(item)

    preferred: dict[str, ScannedFile] = {}
    for sha, items in by_hash.items():
        locations = [SourceLocation(relpath=i.relpath, name=i.name) for i in items]
        chosen = preferred_location(locations)
        preferred[sha] = next(i for i in items if i.relpath == chosen.relpath)

    store_names = assign_store_names([(sha, item.name) for sha, item in preferred.items()])

    entries: list[dict[str, Any]] = []
    for sha in sorted(by_hash):
        items = sorted(by_hash[sha], key=lambda i: i.relpath)
        chosen = preferred[sha]
        locations = [SourceLocation(relpath=i.relpath, name=i.name) for i in items]
        entries.append(
            {
                "sha256": sha,
                "size": chosen.size,
                "store_name": store_names[sha],
                "preferred_name": chosen.name,
                "preferred_relpath": chosen.relpath,
                "preferred_name_is_human_authored": is_human_authored(chosen.name),
                "albums": sorted({loc.album for loc in locations if loc.album}),
                "trees": sorted({loc.tree for loc in locations if loc.tree}),
                "duplicate_count": len(items),
                "sources": [
                    {
                        "relpath": loc.relpath,
                        "name": loc.name,
                        "album": loc.album,
                        "album_path": loc.parent_posix,
                        "tree": loc.tree,
                        "size": item.size,
                        "mtime": item.mtime,
                    }
                    for loc, item in zip(locations, items, strict=True)
                ],
                "is_ole": chosen.is_ole,
                "ole_error": chosen.ole_error,
                "stream_count": len(chosen.streams),
                "streams": chosen.streams,
            }
        )

    human_named = sum(1 for e in entries if e["preferred_name_is_human_authored"])
    return {
        "manifest_version": MANIFEST_VERSION,
        "tool_version": tool_version,
        "generated_at": generated_at or datetime.now(tz=UTC).isoformat(),
        "source_root": str(source_root),
        "counts": {
            "files_seen": len(scanned),
            "distinct_sha256": len(entries),
            "bytes_seen": sum(i.size for i in scanned),
            "bytes_distinct": sum(int(e["size"]) for e in entries),
            "human_authored_names": human_named,
            "not_ole": sum(1 for e in entries if e["is_ole"] is not True),
        },
        "entries": entries,
    }


def write(path: Path, manifest: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # ensure_ascii keeps the control characters in FlashPix stream names
    # (\x05SummaryInformation and friends) legible as escapes rather than
    # raw bytes that a text editor will mangle.
    path.write_text(json.dumps(manifest, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")


def load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))
