"""Album derivation and filename selection.

Pure functions over path strings — no filesystem access, no I/O. That is
deliberate: this is the logic most likely to be wrong, and it is the logic
tier-1 tests can pin down completely.

The rule that matters here: **filenames are the only human-authored content
in this archive.** No captions, titles, or notes exist in any property set,
and no album database survives. Roughly 17% of files carry a name a person
typed. When several source paths share one SHA-256, the name we keep is the
one a person wrote — losing it loses a caption permanently.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

#: Names a camera or import tool generated. Deliberately narrow: only the
#: prefixes this corpus actually contains. Every distinct filename in the
#: archive was checked, and the only camera-generated forms present are
#: `DCP#####` and `P#######`.
#:
#: Speculative prefixes (IMG, DSC, PICT, MVC, ...) were removed rather than
#: kept "just in case". Each one is a chance to misclassify a human-authored
#: name as camera-generated, and that is the single direction of error that
#: loses a caption permanently — filenames are the only human-authored
#: content in this archive.
_CAMERA_NAME = re.compile(r"^(?:dcp|dc|p)[\s_-]?\d+$", re.IGNORECASE)


def strip_fpx_suffix(filename: str) -> str:
    """Drop exactly one trailing `.fpx`, preserving anything else.

    Doubled extensions are NOT normalised away: `DCP00247.fpx` and
    `DCP00247.fpx.fpx` are genuinely different pixels in this corpus, so the
    stem of the latter is `DCP00247.fpx` and the two never collide.
    """
    if filename.lower().endswith(".fpx"):
        return filename[: -len(".fpx")]
    return filename


def is_camera_generated(filename: str) -> bool:
    """True when the filename carries no human intent."""
    return bool(_CAMERA_NAME.match(strip_fpx_suffix(filename)))


def is_human_authored(filename: str) -> bool:
    return not is_camera_generated(filename)


@dataclass(frozen=True)
class SourceLocation:
    """Where one copy of a file was found, relative to the source root."""

    relpath: str  # POSIX-style, relative to the source root
    name: str  # the filename as it appears on disk, case preserved

    @property
    def parent_posix(self) -> str:
        parent, sep, _ = self.relpath.rpartition("/")
        return parent if sep else ""

    @property
    def tree(self) -> str:
        """The top-level backup folder this copy sits under."""
        head, sep, _ = self.relpath.partition("/")
        return head if sep else ""

    @property
    def album(self) -> str:
        """The immediate parent directory name.

        Album membership is a folder name and nothing else in this corpus, so
        this is the only ground truth available for dating. `album_path`
        (the full relative directory) is recorded alongside it and is
        lossless — this field is just the human-facing label.
        """
        parent = self.parent_posix
        if not parent:
            return ""
        return parent.rpartition("/")[2]


def preferred_location(locations: list[SourceLocation]) -> SourceLocation:
    """Pick the copy whose filename we keep for a group of identical files.

    Ordering, most significant first:
      1. a human-authored name beats a camera-generated one;
      2. then the longer name, which carries more of what was typed;
      3. then the lexicographically smallest relpath, purely so the result is
         deterministic across runs and machines.
    """
    if not locations:
        raise ValueError("cannot choose a preferred location from an empty list")
    return min(
        locations,
        key=lambda loc: (
            is_camera_generated(loc.name),
            -len(strip_fpx_suffix(loc.name)),
            loc.relpath,
        ),
    )


def assign_store_names(groups: list[tuple[str, str]]) -> dict[str, str]:
    """Map sha256 -> unique filename for the ingested copy.

    `groups` is a list of `(sha256, preferred_name)` pairs. Two different
    files really can share a filename in this corpus — Kodak cameras reset
    their numbering, and at least one collision across albums is a genuinely
    different photo — so a name already claimed by a different hash gets a
    short hash suffix rather than silently overwriting.

    The first claimant keeps the bare name, and ordering is by hash so the
    outcome does not depend on directory traversal order.
    """
    assigned: dict[str, str] = {}
    taken: set[str] = set()
    for sha, preferred in sorted(groups):
        stem = strip_fpx_suffix(preferred)
        candidate = f"{stem}.fpx"
        if candidate.lower() in taken:
            # A single fallback is not enough: a source file literally named
            # `<stem>_<8 hex>.fpx` claims the suffixed name first, and the
            # next claimant would then silently overwrite it during ingest.
            # The contract is *never*, so append an ordinal until the name is
            # free. Widening the hash prefix instead would not terminate for
            # hashes that share a long prefix; a counter always does.
            candidate = f"{stem}_{sha[:8]}.fpx"
            ordinal = 2
            while candidate.lower() in taken:
                candidate = f"{stem}_{sha[:8]}-{ordinal}.fpx"
                ordinal += 1
        taken.add(candidate.lower())
        assigned[sha] = candidate
    return assigned


def assign_output_stems(groups: list[tuple[str, str, str]]) -> dict[str, str]:
    """Map sha256 -> unique output stem, scoped per destination folder.

    `groups` is a list of `(sha256, scope, preferred_name)` triples, where
    `scope` comes from `layout.stem_scope` -- the album for a descriptive
    folder, and one shared bucket for every file being filed by year and
    month. The shared bucket is deliberately stricter than it needs to be:
    two such files landing in different months cannot collide, but resolving
    which month they land in needs the import stamp, and that would mean
    reading every file before any name could be assigned.

    Two distinct hashes can land in the same album under the same preferred
    name — Kodak cameras reset their numbering, and this corpus already
    contains cross-album filename collisions between genuinely different
    photos. The output path also folds in a date prefix that two files in
    one album usually share, so the name alone is what keeps them apart.
    Without this, the second file silently overwrites the first and the
    conversion reports success for both.

    Resolved from the manifest alone, with no metadata extraction and no
    filesystem access, so a resumed run assigns exactly the same names as
    the run it resumed: the decision must not depend on which files happen
    to have been converted already.

    Ordering is by hash, so the first claimant of a bare name is stable
    regardless of traversal order — the same reasoning as
    `assign_store_names`, and the same ordinal fallback for the case where a
    source file is itself named `<stem>_<8 hex>`.
    """
    assigned: dict[str, str] = {}
    taken: set[tuple[str, str]] = set()
    for sha, album, preferred in sorted(groups):
        stem = strip_fpx_suffix(preferred)
        scope = album.lower()
        if (scope, stem.lower()) in taken:
            stem = f"{strip_fpx_suffix(preferred)}_{sha[:8]}"
            ordinal = 2
            while (scope, stem.lower()) in taken:
                stem = f"{strip_fpx_suffix(preferred)}_{sha[:8]}-{ordinal}"
                ordinal += 1
        taken.add((scope, stem.lower()))
        assigned[sha] = stem
    return assigned
