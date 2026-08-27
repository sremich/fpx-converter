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
import re
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


#: How the output tree is arranged. `BY_ALBUM` is what the tool has always
#: done and stays the default; the others exist because "keep my folder names"
#: is one reasonable answer and not the only one.
BY_ALBUM = "album"
BY_YEAR = "year"
BY_YEAR_MONTH = "year-month"
FLAT = "flat"
CUSTOM = "custom"

#: Value, label, and the example a person needs to see, in menu order.
FOLDER_SCHEMES: tuple[tuple[str, str, str], ...] = (
    (
        BY_ALBUM,
        "By album — your folder names, kept",
        "2002/Summer 2002/ — a folder somebody named outranks any date "
        "we can work out. Tool-made names, like a zip file's, are replaced by "
        "the year and month.",
    ),
    (BY_YEAR, "By year", "2002/"),
    (BY_YEAR_MONTH, "By year, then month", "2002/2002 July/"),
    (FLAT, "All in one folder", "No subfolders at all."),
    (
        CUSTOM,
        "Custom — you choose",
        "A pattern with / between the levels, using the same fields as the "
        "filename.",
    ),
)

SCHEME_VALUES: frozenset[str] = frozenset(value for value, _, _ in FOLDER_SCHEMES)

#: What a custom folder pattern starts as, and what `CUSTOM` falls back to.
DEFAULT_FOLDER_TEMPLATE = "{year}/{album}"


def filing_year_month(
    entry: dict[str, Any], derived: dict[str, Any]
) -> tuple[int | None, int | None]:
    """The year and month this file is *filed* under -- not ones it is claimed
    to have. Either may be `None`, and `None` means the level is left off.

    An album that names a year is better evidence than the import stamp, so it
    wins: `Summer 2002` files under 2002 even where the stamp says the
    photographs reached a computer in 2003. Where the album gives a year but no
    month, the stamp's month is borrowed only if the stamp agrees about the
    year; otherwise the file sits directly in its year folder.

    A month is never manufactured. Returning a `datetime` meant an unknown
    month had to be *some* month, and every such file landed in January --
    which reads as evidence rather than as the absence of it. This is the same
    rule as the zeroed filename prefix, and the same reasoning as
    `_folder_datetime`: a folder is a browsing affordance, and none of this
    ever reaches `DateTimeOriginal`.
    """
    year: int | None = None
    month: int | None = None

    album = choose_album(entry)
    if is_descriptive(album):
        folder_date = timestamps.parse_folder_date(album)
        if folder_date.parsed and folder_date.year:
            year, month = folder_date.year, folder_date.month

    when = _folder_datetime(derived.get("timestamps", {}))
    if year is None and when is not None:
        year, month = when.year, when.month
    elif month is None and when is not None and when.year == year:
        month = when.month

    return year, month


def output_folder(
    entry: dict[str, Any],
    derived: dict[str, Any],
    scheme: str = BY_ALBUM,
    template: str | None = None,
) -> Path:
    """The folder inside `archive/` or `sharing/` that this file's outputs go in.

    `scheme` is one of `FOLDER_SCHEMES`; `template` is read only under
    `CUSTOM`, and is validated once before a run by `validate_folder_template`.
    """
    if scheme == FLAT:
        return Path(".")

    if scheme in (BY_YEAR, BY_YEAR_MONTH):
        year, month = filing_year_month(entry, derived)
        if year is None:
            return Path(UNDATED_FOLDER)
        if scheme == BY_YEAR or month is None:
            return Path(str(year))
        return Path(str(year)) / f"{year} {_MONTHS[month - 1]}"

    if scheme == CUSTOM:
        return _custom_folder(entry, derived, template or DEFAULT_FOLDER_TEMPLATE)

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


#: What a folder pattern may use. Deliberately smaller than a filename's.
#: `{day}` and `{time}` are not filing concepts -- nothing in this corpus is
#: filed to the second -- and a folder's year and month come from
#: `filing_year_month`, which is allowed to use an album name or an import
#: stamp because a folder is a browsing affordance. A filename's date prefix
#: tracks what is *claimable* and answers a different question, so reusing its
#: fields here would put almost everything under `0000/` while the `By year`
#: scheme said `2002/` -- the same word, two answers.
FOLDER_FIELDS: tuple[str, ...] = ("year", "month", "album")

_FOLDER_FIELD_RE = re.compile(r"\{([^{}]*)\}")


def _folder_values(entry: dict[str, Any], derived: dict[str, Any]) -> dict[str, str]:
    year, month = filing_year_month(entry, derived)
    return {
        "year": f"{year:04d}" if year else "0000",
        "month": f"{month:02d}" if month else "00",
        "album": choose_album(entry),
    }


def _custom_folder(
    entry: dict[str, Any], derived: dict[str, Any], template: str
) -> Path:
    """One level per `/` in the template, with empty levels dropped.

    An unknown year is `0000` and an unknown month `00`, exactly as in a
    filename: there is no capture date anywhere in this corpus, and somebody
    choosing their own pattern should meet that in the preview rather than in
    six hundred folders. The named schemes say `undated` instead, which is why
    they are the ones on offer first.
    """
    from fpx_converter import name_template as name_template_mod

    values = _folder_values(entry, derived)
    parts: list[str] = []
    for level in template.split("/"):
        rendered = _FOLDER_FIELD_RE.sub(
            lambda m: name_template_mod.sanitise(values.get(m.group(1), "")), level
        ).strip()
        if rendered:
            parts.append(rendered)
    return Path(*parts) if parts else Path(UNDATED_FOLDER)


def validate_folder_template(template: str) -> None:
    """Raise `name_template.TemplateError` unless this folder pattern is safe.

    Looser than a filename pattern in one way and stricter in another: `/` is
    the level separator here rather than a forbidden character, and `..` is
    refused outright. A pattern that walked upwards could put converted images
    anywhere on the disk, including inside the read-only source archive, which
    is the one mistake in this project that cannot be undone.
    """
    from fpx_converter import name_template as name_template_mod

    if not template or not template.strip():
        raise name_template_mod.TemplateError(
            "The folder pattern is empty. Choose 'All in one folder' if that is "
            "what you meant."
        )
    if template[0] in "/\\":
        raise name_template_mod.TemplateError(
            "The folder pattern must be relative -- it names folders inside the "
            "destination you chose, not a path of its own."
        )
    for level in template.split("/"):
        if level.strip() in ("..", "."):
            raise name_template_mod.TemplateError(
                "The folder pattern cannot contain '..'. It names folders inside "
                "your destination and nothing outside it."
            )
        for field in _FOLDER_FIELD_RE.findall(level):
            if field in FOLDER_FIELDS:
                continue
            if field in name_template_mod.FIELD_NAMES:
                raise name_template_mod.TemplateError(
                    f"{{{field}}} belongs in the filename pattern, not the folder "
                    "one. Folders can use "
                    + ", ".join("{" + f + "}" for f in FOLDER_FIELDS)
                    + "."
                )
            raise name_template_mod.TemplateError(
                f"Unknown field {{{field}}} in the folder pattern. Folders can use "
                + ", ".join("{" + f + "}" for f in FOLDER_FIELDS)
                + "."
            )
        # `{name}` is required in a *filename*, because losing it loses the only
        # human-authored content in the archive. A folder does not carry it, so
        # the probe supplies one and only the characters and braces are checked.
        name_template_mod.validate(
            _FOLDER_FIELD_RE.sub("", level) + "{name}"
        )


#: The scope every year-and-month file shares when names are assigned.
#: Not a real folder -- the leading NUL keeps it from ever colliding with one.
YEAR_MONTH_SCOPE = "\x00year-month"


def stem_scope(entry: dict[str, Any], scheme: str = BY_ALBUM) -> str:
    """The namespace a file's output name has to be unique within.

    For a descriptive album that is the album itself. For everything else it
    is one shared bucket, because the folder those files land in depends on
    the import stamp, and names are assigned from the manifest alone so that
    a resumed run picks the same ones. Sharing a bucket is stricter than the
    truth -- two files in different months cannot really collide -- and
    stricter is the safe direction: the cost is an occasional unnecessary
    hash suffix, against silently overwriting a photo.
    """
    # Only `BY_ALBUM` puts a file somewhere the manifest alone can predict.
    # Every other scheme files by a date that needs the metadata read, and
    # names are assigned before any of that happens, so they all share one
    # bucket. Stricter than the truth -- two files in different years cannot
    # really collide -- and stricter is the safe direction, exactly as below:
    # the cost is an occasional unnecessary hash suffix, against silently
    # overwriting a photograph.
    if scheme != BY_ALBUM:
        return YEAR_MONTH_SCOPE
    album = choose_album(entry)
    return album if is_descriptive(album) else YEAR_MONTH_SCOPE
