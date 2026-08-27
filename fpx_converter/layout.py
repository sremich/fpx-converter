"""Where a converted photo goes in the output tree.

The owner's rule, in his words: a descriptive source folder keeps its name as
the album, whatever date the photo carries. A folder whose name says nothing
is replaced by year-and-month. Descriptive albums that name a year are filed
under it; descriptive albums that name no date sit at the top, beside the
year folders.

    archive/
      1994/
        Winterfest 1994/         <- descriptive, and it names a year
        1994 December/           <- from a folder whose name said nothing
      1995/
        Solstice Bonfire 1995/
      Rosalind/                  <- descriptive, no date in the name
      undated/                   <- no usable date at all

The point is that a folder name somebody typed is evidence and a folder name
a tool generated is not. `CLAUDE.md` already says filenames are the only
human-authored content in this archive; folder names are the same thing one
level up, and they outrank any date we could derive.
"""

from __future__ import annotations

import datetime
import functools
from pathlib import Path
from typing import Any

from . import config, timestamps

#: Folder names that carry no information about their contents, lowercased.
#:
#: Deliberately a short, explicit list rather than a heuristic. Everything
#: else is treated as descriptive, because the cost of the two mistakes is
#: not symmetric: wrongly calling a folder non-descriptive discards something
#: a person wrote and cannot be recovered from the file, while wrongly
#: calling one descriptive just leaves a slightly odd album name.
NON_DESCRIPTIVE_ALBUMS = frozenset(
    {
        "",
        "root",
        "newzip",
        "new zip",
        "stuff",
        "misc",
        "miscellaneous",
        "untitled",
        "unsorted",
        "new folder",
        "images",
        "image",
        "photos",
        "pictures",
        "temp",
        "tmp",
        "output",
        "scans",
    }
)

UNDATED_FOLDER = "undated"

_MONTHS = (
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
)


@functools.lru_cache(maxsize=1)
def _extra_non_descriptive() -> frozenset[str]:
    """Archive-specific names from `.env`, read once per run."""
    try:
        return config.extra_non_descriptive_albums()
    except config.ConfigError:
        raise
    except Exception:  # noqa: BLE001
        # No `.env` at all is the normal case for a fresh checkout.
        return frozenset()


def is_descriptive(album: str) -> bool:
    """Does this folder name say anything about what is in it?"""
    name = album.strip().lower()
    if name in NON_DESCRIPTIVE_ALBUMS or name in _extra_non_descriptive():
        return False
    # A folder called nothing but a number ("001", "2") is a sequence, not a
    # description. A bare *year* is excluded from that -- it does describe
    # something, and it lands as its own year folder anyway.
    return not (name.isdigit() and not (1900 <= int(name) <= 2100))


def choose_album(entry: dict[str, Any]) -> str:
    """The album a file is filed under: the most descriptive one it belongs to.

    A file usually belongs to several -- an event folder and the flat dump it
    was also copied into. Taking the first listed put 52 photos of one
    Christmas under a folder named after a zip file, and cost them the date
    their real album gave for free.

    Preference order: descriptive and dated, then descriptive, then anything.
    Ties keep manifest order, so the choice is stable across runs.
    """
    albums = [str(a) for a in entry.get("albums", []) if a]
    if not albums:
        return "Root"

    def rank(album: str) -> int:
        if not is_descriptive(album):
            return 0
        return 2 if timestamps.parse_folder_date(album).parsed else 1

    return max(albums, key=rank)


def _folder_datetime(ts_dict: dict[str, Any]) -> datetime.datetime | None:
    """The best date available for *filing* -- not for claiming.

    A year-and-month folder for a photo with no datable album can only come
    from the import stamp, which this project does not trust as a capture
    date: on this corpus it misses the event by up to 223 days. That is fine
    here and nowhere else. A folder is a browsing affordance, exactly like the
    filename prefix; `DateTimeOriginal` is a claim, and this value never
    reaches it.
    """
    for key in ("sort_datetime", "import_datetime"):
        raw = ts_dict.get(key)
        if raw:
            try:
                return datetime.datetime.fromisoformat(str(raw))
            except ValueError:
                continue
    return None


def output_folder(entry: dict[str, Any], derived: dict[str, Any]) -> Path:
    """The folder inside `archive/` or `sharing/` that this file's outputs go in."""
    album = choose_album(entry)

    if is_descriptive(album):
        folder_date = timestamps.parse_folder_date(album)
        if folder_date.parsed and folder_date.year:
            return Path(str(folder_date.year)) / album
        return Path(album)

    when = _folder_datetime(derived.get("timestamps", {}))
    if when is None:
        return Path(UNDATED_FOLDER)
    return Path(str(when.year)) / f"{when.year} {_MONTHS[when.month - 1]}"


#: The scope every year-and-month file shares when names are assigned.
#: Not a real folder -- the leading NUL keeps it from ever colliding with one.
YEAR_MONTH_SCOPE = "\x00year-month"


def stem_scope(entry: dict[str, Any]) -> str:
    """The namespace a file's output name has to be unique within.

    For a descriptive album that is the album itself. For everything else it
    is one shared bucket, because the folder those files land in depends on
    the import stamp, and names are assigned from the manifest alone so that
    a resumed run picks the same ones. Sharing a bucket is stricter than the
    truth -- two files in different months cannot really collide -- and
    stricter is the safe direction: the cost is an occasional unnecessary
    hash suffix, against silently overwriting a photo.
    """
    album = choose_album(entry)
    return album if is_descriptive(album) else YEAR_MONTH_SCOPE
