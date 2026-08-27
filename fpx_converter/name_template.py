"""The output filename pattern, as something a person can change.

The shipped name is `2002-07-04_143210_Backyard.tif`: a date prefix that
sorts chronologically, then the filename somebody typed. That is a good
default and it is not everybody's default -- plenty of people want the day
first, or the year in a folder and not in the name, or no date at all.

So the pattern is a template with named fields:

    {year}   2002   the four-digit year, or 0000
    {month}  07     the month, or 00
    {day}    04     the day, or 00
    {date}   2002-07-04   shorthand for {year}-{month}-{day}
    {time}   143210 hours, minutes and seconds, or 000000
    {name}   Backyard     the filename from the archive, without `.fpx`
    {album}  Summer 2002  the album this file is filed under

Two rules are enforced rather than advised, and both come from the project's
binding rules:

**`{name}` is required.** Filenames are the only human-authored content in
this archive -- no captions, titles or notes survive anywhere else. A
template without `{name}` throws that away for every file it renames, and
unlike a wrong date it cannot be recovered by re-reading the source, because
the person who typed it is who knows what it meant.

**A component the evidence does not support stays zeroed.** There is no
capture date in this corpus; what the date fields carry is a folder date or
an import stamp, resolved by `writer.format_date_prefix` and reproduced here
from the same values. `{month}` for a file dated only to its year is `00`,
never `01`, because `01` names a month nobody established.

Pure string handling: no filesystem access, no I/O, no clock.
"""

from __future__ import annotations

import re
from typing import Any

#: What the tool has always produced. Anything else is somebody's choice.
DEFAULT_TEMPLATE = "{year}-{month}-{day}_{time}_{name}"

#: Every field, with the example text the window shows beside it.
FIELDS: tuple[tuple[str, str], ...] = (
    ("year", "2002"),
    ("month", "07"),
    ("day", "04"),
    ("date", "2002-07-04"),
    ("time", "143210"),
    ("name", "Backyard"),
    ("album", "Summer 2002"),
)

FIELD_NAMES: frozenset[str] = frozenset(name for name, _ in FIELDS)

#: The field that cannot be left out. See the module docstring.
REQUIRED_FIELD = "name"

_FIELD_RE = re.compile(r"\{([^{}]*)\}")

#: Illegal in a Windows filename, and `/` would silently invent a folder.
_FORBIDDEN = set(r'<>:"/\|?*') | {chr(c) for c in range(32)}

#: Windows refuses these as filenames whatever extension follows. The shipped
#: template can never produce one -- it starts with a date -- but a template
#: of just `{name}` can, and the archive is full of names nobody vetted.
_RESERVED = frozenset(
    ["con", "prn", "aux", "nul"]
    + [f"com{d}" for d in "123456789"]
    + [f"lpt{d}" for d in "123456789"]
)


class TemplateError(ValueError):
    """A template that would lose data or produce an unusable filename."""


def used_fields(template: str) -> list[str]:
    """The field names the template mentions, in order, duplicates included."""
    return _FIELD_RE.findall(template)


def validate(template: str) -> None:
    """Raise `TemplateError` unless this template is safe to convert with.

    Checked before a run starts rather than per file, so a mistake costs a
    message and not a half-renamed output tree.
    """
    if not template or not template.strip():
        raise TemplateError("The filename pattern is empty. It must contain {name}.")

    fields = used_fields(template)
    unknown = [f for f in fields if f not in FIELD_NAMES]
    if unknown:
        known = ", ".join("{" + n + "}" for n, _ in FIELDS)
        raise TemplateError(
            f"Unknown field {{{unknown[0]}}} in the filename pattern. "
            f"The fields are: {known}."
        )

    # A brace that opened and never closed, or a stray `}`. `str.format` would
    # raise deep inside the first conversion instead of here.
    if template.count("{") != len(fields) or template.count("}") != len(fields):
        raise TemplateError(
            "Unbalanced { } in the filename pattern. Every field looks like {year}."
        )

    if REQUIRED_FIELD not in fields:
        raise TemplateError(
            "The filename pattern must contain {name}. The filenames are the only "
            "thing in this archive a person wrote -- there are no captions or titles "
            "anywhere else -- so a pattern that drops them loses them for good."
        )

    literal = _FIELD_RE.sub("", template)
    bad = sorted(set(literal) & _FORBIDDEN)
    if bad:
        shown = " ".join(repr(c) for c in bad)
        raise TemplateError(
            f"The filename pattern cannot contain {shown}. "
            "It names a file, not a folder."
        )


def date_fields(ts_dict: dict[str, Any]) -> dict[str, str]:
    """The date fields for one file, as `writer.format_date_prefix` resolves them.

    Derived from that function rather than beside it, so the template can
    never disagree with the shipped name about what is known.
    """
    from fpx_converter import writer

    prefix, _is_undated = writer.format_date_prefix(ts_dict)
    date, _, time = prefix.partition("_")
    year, month, day = date.split("-")
    return {
        "year": year,
        "month": month,
        "day": day,
        "date": date,
        "time": time,
    }


def sanitise(text: str) -> str:
    """Make one substituted value safe to sit in a filename or folder name.

    The pattern is checked once by `validate`; the values are cleaned every
    time, because those come from the archive rather than from the person
    typing the pattern. An album named `Trip 1/2` must not become two folders.
    """
    return "".join("-" if ch in _FORBIDDEN else ch for ch in text)


def render(
    template: str,
    *,
    ts_dict: dict[str, Any],
    name: str,
    album: str = "",
) -> str:
    """The filename stem this template produces for one file.

    Assumes `validate` has already passed on the template; the substituted
    values are still sanitised, because those come from the archive rather
    than from the person typing the template.
    """
    values = date_fields(ts_dict)
    values["name"] = sanitise(name)
    values["album"] = sanitise(album)

    stem = _FIELD_RE.sub(lambda m: values.get(m.group(1), ""), template)

    # Deliberately not stripped. Windows trims a trailing dot or space from the
    # end of a path component, and a stem is never the end of one -- the
    # extension always follows -- so `Beach .tif` and `X..tif` are creatable
    # and distinct. Normalising them would rename files relative to 1.1.0 and
    # would collapse two source names that differ only there, which is the same
    # mistake as normalising a doubled `.fpx` extension.
    if stem.split(".")[0].lower() in _RESERVED:
        stem = f"{stem}_"
    return stem or sanitise(name) or "image"
