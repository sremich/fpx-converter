"""Dates a person supplied for an album, after looking at the photographs.

This is the missing half of the dating strategy. `CLAUDE.md` says there is no
capture date anywhere in this corpus, that a folder naming a year or a season
does not date a photograph, and that `DateTimeOriginal` is written only where
a date is independently defensible. That leaves most of the archive with no
capture date at all -- correctly, because nothing in the files knows one.

But somebody does. The owner can look at an album and say "that was the
seventeenth". A date typed by a person who was there is *more* defensible than
anything derived from a filesystem, not less, and this is how it gets in.

The file is JSON, written by the QA gallery and read here:

    {
      "album dates": {"Winterfest 1994": "1994-12-17"},
      "notes": {"Winterfest 1994": "the day of the storm"}
    }

Three properties it has to hold to:

* **A single day or nothing.** EXIF has no way to say "sometime that
  winter", so a partial date is refused rather than rounded to the first of
  the month. The project already paid for that lesson: taking the start of a
  range gave 151 files a fabricated capture moment precise to the second.
* **It is a claim, and it is recorded as one.** `date_source` becomes
  `owner-supplied`, so an audit can always separate what a person asserted
  from what the file said.
* **It never lands anywhere else.** The path is local-only, like every other
  file that names an album, and the loader refuses a date it cannot parse
  rather than dropping it silently.
"""

from __future__ import annotations

import datetime
import json
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_FILENAME = "album-dates.json"


class AlbumDateError(ValueError):
    """The album-date file says something the loader will not act on."""


@dataclass(frozen=True)
class AlbumDates:
    """Album name (lowercased) -> the day somebody says it happened."""

    dates: dict[str, datetime.date] = field(default_factory=dict)
    notes: dict[str, str] = field(default_factory=dict)

    def for_album(self, album: str) -> datetime.date | None:
        return self.dates.get(album.strip().lower())

    def note_for(self, album: str) -> str:
        return self.notes.get(album.strip().lower(), "")

    def __bool__(self) -> bool:
        return bool(self.dates)


def _parse_day(album: str, raw: object) -> datetime.date:
    if not isinstance(raw, str):
        raise AlbumDateError(f"{album!r}: expected a date string, got {type(raw).__name__}")
    text = raw.strip()
    if not text:
        raise AlbumDateError(f"{album!r}: empty date")
    try:
        parsed = datetime.date.fromisoformat(text)
    except ValueError as exc:
        # Deliberately strict. "1994-12" would be a month, and rounding a
        # month to its first day is exactly the fabrication this project
        # exists to avoid -- it once gave 151 files a capture moment precise
        # to the second that no evidence supported.
        raise AlbumDateError(
            f"{album!r}: {text!r} is not a single day in YYYY-MM-DD form. "
            "A month or a year cannot be written as a capture date; leave it out "
            "and the album stays undated."
        ) from exc
    if parsed.year < 1826 or parsed > datetime.date.today():
        # 1826 is the oldest surviving photograph. A date outside that window
        # is a typo, and a typo written into an archive is indistinguishable
        # from evidence later.
        raise AlbumDateError(f"{album!r}: {text} is not a plausible photograph date")
    return parsed


def parse(payload: object) -> AlbumDates:
    """Build `AlbumDates` from already-decoded JSON."""
    if not isinstance(payload, dict):
        raise AlbumDateError(f"expected a JSON object, got {type(payload).__name__}")

    raw_dates = payload.get("album dates", payload.get("album_dates", {}))
    if not isinstance(raw_dates, dict):
        raise AlbumDateError("'album dates' must be an object of album -> YYYY-MM-DD")

    dates: dict[str, datetime.date] = {}
    for album, value in raw_dates.items():
        key = str(album).strip().lower()
        if not key:
            raise AlbumDateError("an album name in the date file is empty")
        dates[key] = _parse_day(str(album), value)

    raw_notes = payload.get("notes", {})
    notes: dict[str, str] = {}
    if isinstance(raw_notes, dict):
        notes = {
            str(k).strip().lower(): str(v)
            for k, v in raw_notes.items()
            if str(k).strip() and str(v).strip()
        }

    return AlbumDates(dates=dates, notes=notes)


def load(path: Path | None) -> AlbumDates:
    """Read the file, or return an empty set when there is none.

    A missing file is the normal state and means nothing. A *malformed* one is
    refused loudly: it was written by somebody deliberately recording what they
    remember, and silently ignoring it would lose exactly the evidence this
    module exists to carry.
    """
    if path is None or not path.is_file():
        return AlbumDates()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise AlbumDateError(f"{path} is not valid JSON: {exc}") from exc
    return parse(payload)


def dump(dates: AlbumDates) -> str:
    """Serialise back out, for the gallery to hand to a person."""
    payload = {
        "album dates": {k: v.isoformat() for k, v in sorted(dates.dates.items())},
        "notes": {k: v for k, v in sorted(dates.notes.items())},
    }
    return json.dumps(payload, indent=2, ensure_ascii=True) + "\n"
