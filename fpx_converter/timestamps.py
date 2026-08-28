"""Timestamp resolution, timezone offset selection, and folder ground-truth gate.

Core principles (paid for by milestone-0 measurements):
1. **Zero capture dates exist in this corpus.** `0x25000000` and the `0x25xxxxxx`
   group are absent from all files.
2. **The only timestamp is an import-batch stamp** (`PIDSI_CREATE_DTM`),
   replicated into 4 property streams. It goes to `DateTimeDigitized` /
   `xmp:CreateDate` and **never** to `DateTimeOriginal`.
3. **Stored FILETIMEs are LOCAL wall-clock time, not UTC.** No timezone
   conversion is applied to the time digits. The timezone map selects which
   `OffsetTimeOriginal` / `OffsetTimeDigitized` tag is written.
4. **`DateTimeOriginal` is written only where defensible**: a folder name that
   pins a single day, an embedded film scan date, or owner review. A folder
   naming a year, a span, a season or a month does **not** qualify -- see
   `DEFENSIBLE_DATE_KINDS`. Coarser dates survive as `sort_datetime`, which
   orders the output without making a claim.
5. **The folder-name ground-truth check reports per album** and never alters a
   date source. It fails a run only under `check-dates --strict`, because on
   this corpus failing is the expected result: the import stamp misses 7 of 9
   dated albums, which is precisely why it is not trusted as a capture date.
"""

from __future__ import annotations

import calendar
import datetime
import functools
import os
import re
import sys
import time
import zoneinfo
from dataclasses import dataclass, field
from typing import Any

from . import config

# =============================================================================
# Timezone & Formatting Helpers
# =============================================================================

#: The zone used when nothing else says otherwise.
#:
#: A *last resort*, not a preference. `system_timezone()` reads the machine's
#: own zone and `config.resolve_default_timezone` prefers it, so this is
#: reached only where the machine cannot be asked. It stays a US zone because
#: the archive that paid for this tool is a US one; every path that can do
#: better does.
DEFAULT_TZ = "America/Chicago"

#: Album-name -> timezone overrides are **not** hardcoded here.
#:
#: The override keys are album folder names, and album names are personal
#: content this repository does not carry (see ARCHITECTURE.md). They live in
#: `.env` as `FPX_TZ_OVERRIDES`, parsed by `config.parse_album_tz_overrides`,
#: and reach this module as the `overrides` argument. An empty map means every
#: album takes the default zone, which is the correct behaviour for a
#: checkout that has no `.env`.
DEFAULT_ALBUM_TZ_OVERRIDES: dict[str, str] = {}


class UnknownTimezoneError(ValueError):
    """Raised for a timezone name this module cannot resolve an offset for."""


#: Offline fallback: canonical zone name -> (standard hours, daylight hours).
#:
#: `zoneinfo` is the authority now -- it carries the *historical* rules, and
#: this corpus is 1998-2002, where the US switched on the first Sunday in
#: April rather than the second Sunday in March. This table is what remains
#: when `zoneinfo` finds no database at all: a `tzdata` wheel that failed to
#: install, or a stripped runtime. It knows only the zones listed here, and
#: anything else is an error rather than a silent fallback to Central --
#: a wrong `OffsetTime*` is indistinguishable from a right one once written.
#:
#: Its US DST schedule (`_is_us_dst`) is the reason it may only ever be used
#: for US zones: applied to `Europe/London` it would be wrong twice a year.
#:
#: Keyed on the exact zone name, not on substrings: `Pacific/Honolulu`
#: contains "pacific" but is nowhere near US Pacific time, and a substring
#: table quietly gets that wrong by three hours.
_TZ_OFFSETS: dict[str, tuple[int, int]] = {
    "america/new_york": (-5, -4),
    "america/chicago": (-6, -5),
    "america/denver": (-7, -6),
    "america/phoenix": (-7, -7),  # Arizona does not observe DST
    "america/los_angeles": (-8, -7),
    "america/anchorage": (-9, -8),
    "pacific/honolulu": (-10, -10),  # Hawaii does not observe DST
}

#: Informal names accepted for the zones above.
_TZ_ALIASES: dict[str, str] = {
    "eastern": "america/new_york",
    "us/eastern": "america/new_york",
    "central": "america/chicago",
    "us/central": "america/chicago",
    "mountain": "america/denver",
    "us/mountain": "america/denver",
    "arizona": "america/phoenix",
    "pacific": "america/los_angeles",
    "us/pacific": "america/los_angeles",
    "alaska": "america/anchorage",
    "us/alaska": "america/anchorage",
    "hawaii": "pacific/honolulu",
    "us/hawaii": "pacific/honolulu",
}


def _is_us_dst(dt: datetime.datetime) -> bool:
    """Determine whether a naive local datetime falls in US Daylight Saving Time."""
    year = dt.year
    # US Schedule 1987–2006: 1st Sunday in April to last Sunday in October
    if year < 2007:
        # First Sunday in April
        apr1 = datetime.date(year, 4, 1)
        dst_start_day = 1 + (6 - apr1.weekday()) % 7
        dst_start = datetime.datetime(year, 4, dst_start_day, 2, 0, 0)

        # Last Sunday in October
        oct31 = datetime.date(year, 10, 31)
        dst_end_day = 31 - ((oct31.weekday() - 6) % 7)
        dst_end = datetime.datetime(year, 10, dst_end_day, 2, 0, 0)
    else:
        # 2007+ schedule: 2nd Sunday in March to 1st Sunday in November
        mar1 = datetime.date(year, 3, 1)
        dst_start_day = 1 + (6 - mar1.weekday()) % 7 + 7
        dst_start = datetime.datetime(year, 3, dst_start_day, 2, 0, 0)

        nov1 = datetime.date(year, 11, 1)
        dst_end_day = 1 + (6 - nov1.weekday()) % 7
        dst_end = datetime.datetime(year, 11, dst_end_day, 2, 0, 0)

    return dst_start <= dt < dst_end


def get_album_timezone(
    album: str,
    default_tz: str = DEFAULT_TZ,
    overrides: dict[str, str] | None = None,
) -> str:
    """Determine the IANA timezone for an album."""
    tz_overrides = overrides if overrides is not None else DEFAULT_ALBUM_TZ_OVERRIDES
    norm_album = album.lower().strip()
    for pattern, tz_name in tz_overrides.items():
        if pattern.lower() in norm_album:
            return tz_name
    return default_tz


@functools.lru_cache(maxsize=1)
def _zoneinfo_keys() -> dict[str, str]:
    """Lowercased IANA name -> the exact key `zoneinfo` wants.

    `zoneinfo` keys are case-sensitive, and everything that reaches this
    module -- a `.env` line, a `--timezone` argument, a dropdown value -- is
    typed by a person. An empty map means no tz database is installed, which
    is the one case the offline table below still has to cover.
    """
    try:
        return {key.lower(): key for key in zoneinfo.available_timezones()}
    except Exception:  # noqa: BLE001 -- no database at all is a valid state
        return {}


#: Every zone an offset can be resolved for, lowercased.
#:
#: Read by the desktop front end so its menu cannot drift from what the
#: converter accepts. With a tz database present this is the whole IANA set;
#: without one it is the handful of zones the offline table covers.
KNOWN_TIMEZONES: frozenset[str] = frozenset(_zoneinfo_keys()) | frozenset(_TZ_OFFSETS)


def resolve_zone_key(tz_name: str) -> str | None:
    """The exact `zoneinfo` key for a name somebody typed, or `None`.

    Accepts any casing, spaces in place of underscores, and the informal
    aliases in `_TZ_ALIASES`.
    """
    cleaned = tz_name.strip().replace(" ", "_")
    if not cleaned:
        return None
    lowered = cleaned.lower()
    keys = _zoneinfo_keys()
    for candidate in (lowered, _TZ_ALIASES.get(lowered, "")):
        if candidate and candidate in keys:
            return keys[candidate]
    return None


def _format_offset(delta: datetime.timedelta) -> str:
    """A `timedelta` as the `±HH:MM` string EXIF `OffsetTime*` wants."""
    total_minutes = round(delta.total_seconds() / 60)
    sign = "+" if total_minutes >= 0 else "-"
    hours, minutes = divmod(abs(total_minutes), 60)
    return f"{sign}{hours:02d}:{minutes:02d}"


def get_timezone_offset(dt: datetime.datetime, tz_name: str) -> str:
    """Return the UTC offset (`±HH:MM`) to record for a naive local datetime.

    This selects which `OffsetTime*` value is written. It does **not** convert
    the wall-clock digits -- stored FILETIMEs in this corpus are already local
    time, and shifting them would be the bug this project exists to avoid.
    The datetime is attached to the zone, never moved into it.

    Resolved through `zoneinfo`, so the answer uses the rules that were in
    force on that date: a photograph from July 2001 in a US zone gets the
    first-Sunday-in-April schedule and not today's second-Sunday-in-March one.

    Raises `UnknownTimezoneError` for a zone that cannot be resolved, rather
    than guessing -- see `_TZ_OFFSETS`.
    """
    tz_clean = tz_name.strip().lower().replace(" ", "_")
    if tz_clean in ("utc", "gmt", "etc/utc", "etc/gmt"):
        return "+00:00"

    key = resolve_zone_key(tz_name)
    if key is not None:
        offset = dt.replace(tzinfo=zoneinfo.ZoneInfo(key)).utcoffset()
        if offset is not None:
            return _format_offset(offset)

    # No tz database on this machine. The offline table covers US zones only,
    # and `_is_us_dst` is a US schedule, so nothing else may be answered here.
    canonical = _TZ_ALIASES.get(tz_clean, tz_clean)
    offsets = _TZ_OFFSETS.get(canonical)
    if offsets is not None:
        std_h, dst_h = offsets
        h = dst_h if _is_us_dst(dt) else std_h
        sign = "+" if h >= 0 else "-"
        return f"{sign}{abs(h):02d}:00"

    raise UnknownTimezoneError(
        f"no UTC offset known for timezone {tz_name!r}. Give an IANA name such "
        f"as 'Europe/London' or 'America/Chicago' -- with --timezone, or as "
        f"FPX_DEFAULT_TZ. Refused rather than guessed: a wrong OffsetTime is "
        f"indistinguishable from a right one once it is written."
    )


#: Windows zone key name (lowercased) -> IANA zone, from the CLDR
#: `windowsZones` primary-territory mapping.
#:
#: Windows does not use IANA names, and Python reports the Windows one. Only
#: an exact match is used: a near miss would be a wrong `OffsetTime*` written
#: as confidently as a right one, so a name that is not here produces no
#: answer at all and the caller has to be told to say which zone it is.
_WINDOWS_TO_IANA: dict[str, str] = {
    "dateline standard time": "Etc/GMT+12",
    "utc-11": "Etc/GMT+11",
    "aleutian standard time": "America/Adak",
    "hawaiian standard time": "Pacific/Honolulu",
    "marquesas standard time": "Pacific/Marquesas",
    "alaskan standard time": "America/Anchorage",
    "utc-09": "Etc/GMT+9",
    "pacific standard time (mexico)": "America/Tijuana",
    "utc-08": "Etc/GMT+8",
    "pacific standard time": "America/Los_Angeles",
    "us mountain standard time": "America/Phoenix",
    "mountain standard time (mexico)": "America/Chihuahua",
    "mountain standard time": "America/Denver",
    "yukon standard time": "America/Whitehorse",
    "central america standard time": "America/Guatemala",
    "central standard time": "America/Chicago",
    "easter island standard time": "Pacific/Easter",
    "central standard time (mexico)": "America/Mexico_City",
    "canada central standard time": "America/Regina",
    "sa pacific standard time": "America/Bogota",
    "eastern standard time (mexico)": "America/Cancun",
    "eastern standard time": "America/New_York",
    "haiti standard time": "America/Port-au-Prince",
    "cuba standard time": "America/Havana",
    "us eastern standard time": "America/Indiana/Indianapolis",
    "turks and caicos standard time": "America/Grand_Turk",
    "paraguay standard time": "America/Asuncion",
    "atlantic standard time": "America/Halifax",
    "venezuela standard time": "America/Caracas",
    "central brazilian standard time": "America/Cuiaba",
    "sa western standard time": "America/La_Paz",
    "pacific sa standard time": "America/Santiago",
    "newfoundland standard time": "America/St_Johns",
    "tocantins standard time": "America/Araguaina",
    "e. south america standard time": "America/Sao_Paulo",
    "sa eastern standard time": "America/Cayenne",
    "argentina standard time": "America/Argentina/Buenos_Aires",
    "greenland standard time": "America/Nuuk",
    "montevideo standard time": "America/Montevideo",
    "magallanes standard time": "America/Punta_Arenas",
    "saint pierre standard time": "America/Miquelon",
    "bahia standard time": "America/Bahia",
    "utc-02": "Etc/GMT+2",
    "azores standard time": "Atlantic/Azores",
    "cape verde standard time": "Atlantic/Cape_Verde",
    "utc": "Etc/UTC",
    "gmt standard time": "Europe/London",
    "greenwich standard time": "Atlantic/Reykjavik",
    "sao tome standard time": "Africa/Sao_Tome",
    "morocco standard time": "Africa/Casablanca",
    "w. europe standard time": "Europe/Berlin",
    "central europe standard time": "Europe/Budapest",
    "romance standard time": "Europe/Paris",
    "central european standard time": "Europe/Warsaw",
    "w. central africa standard time": "Africa/Lagos",
    "jordan standard time": "Asia/Amman",
    "gtb standard time": "Europe/Bucharest",
    "middle east standard time": "Asia/Beirut",
    "egypt standard time": "Africa/Cairo",
    "e. europe standard time": "Europe/Chisinau",
    "syria standard time": "Asia/Damascus",
    "west bank standard time": "Asia/Hebron",
    "south africa standard time": "Africa/Johannesburg",
    "fle standard time": "Europe/Kyiv",
    "israel standard time": "Asia/Jerusalem",
    "south sudan standard time": "Africa/Juba",
    "kaliningrad standard time": "Europe/Kaliningrad",
    "sudan standard time": "Africa/Khartoum",
    "libya standard time": "Africa/Tripoli",
    "namibia standard time": "Africa/Windhoek",
    "arabic standard time": "Asia/Baghdad",
    "turkey standard time": "Europe/Istanbul",
    "arab standard time": "Asia/Riyadh",
    "belarus standard time": "Europe/Minsk",
    "russian standard time": "Europe/Moscow",
    "e. africa standard time": "Africa/Nairobi",
    "volgograd standard time": "Europe/Volgograd",
    "iran standard time": "Asia/Tehran",
    "arabian standard time": "Asia/Dubai",
    "astrakhan standard time": "Europe/Astrakhan",
    "azerbaijan standard time": "Asia/Baku",
    "russia time zone 3": "Europe/Samara",
    "mauritius standard time": "Indian/Mauritius",
    "saratov standard time": "Europe/Saratov",
    "georgian standard time": "Asia/Tbilisi",
    "caucasus standard time": "Asia/Yerevan",
    "afghanistan standard time": "Asia/Kabul",
    "west asia standard time": "Asia/Tashkent",
    "qyzylorda standard time": "Asia/Qyzylorda",
    "ekaterinburg standard time": "Asia/Yekaterinburg",
    "pakistan standard time": "Asia/Karachi",
    "india standard time": "Asia/Kolkata",
    "sri lanka standard time": "Asia/Colombo",
    "nepal standard time": "Asia/Kathmandu",
    "central asia standard time": "Asia/Almaty",
    "bangladesh standard time": "Asia/Dhaka",
    "omsk standard time": "Asia/Omsk",
    "myanmar standard time": "Asia/Yangon",
    "se asia standard time": "Asia/Bangkok",
    "altai standard time": "Asia/Barnaul",
    "w. mongolia standard time": "Asia/Hovd",
    "north asia standard time": "Asia/Krasnoyarsk",
    "n. central asia standard time": "Asia/Novosibirsk",
    "tomsk standard time": "Asia/Tomsk",
    "china standard time": "Asia/Shanghai",
    "north asia east standard time": "Asia/Irkutsk",
    "singapore standard time": "Asia/Singapore",
    "w. australia standard time": "Australia/Perth",
    "taipei standard time": "Asia/Taipei",
    "ulaanbaatar standard time": "Asia/Ulaanbaatar",
    "aus central w. standard time": "Australia/Eucla",
    "transbaikal standard time": "Asia/Chita",
    "tokyo standard time": "Asia/Tokyo",
    "north korea standard time": "Asia/Pyongyang",
    "korea standard time": "Asia/Seoul",
    "yakutsk standard time": "Asia/Yakutsk",
    "cen. australia standard time": "Australia/Adelaide",
    "aus central standard time": "Australia/Darwin",
    "e. australia standard time": "Australia/Brisbane",
    "aus eastern standard time": "Australia/Sydney",
    "west pacific standard time": "Pacific/Port_Moresby",
    "tasmania standard time": "Australia/Hobart",
    "vladivostok standard time": "Asia/Vladivostok",
    "lord howe standard time": "Australia/Lord_Howe",
    "bougainville standard time": "Pacific/Bougainville",
    "russia time zone 10": "Asia/Srednekolymsk",
    "magadan standard time": "Asia/Magadan",
    "norfolk standard time": "Pacific/Norfolk",
    "sakhalin standard time": "Asia/Sakhalin",
    "central pacific standard time": "Pacific/Guadalcanal",
    "russia time zone 11": "Asia/Kamchatka",
    "new zealand standard time": "Pacific/Auckland",
    "utc+12": "Etc/GMT-12",
    "fiji standard time": "Pacific/Fiji",
    "chatham islands standard time": "Pacific/Chatham",
    "utc+13": "Etc/GMT-13",
    "tonga standard time": "Pacific/Tongatapu",
    "samoa standard time": "Pacific/Apia",
    "line islands standard time": "Pacific/Kiritimati",
}


def _windows_zone_name() -> str | None:
    """The machine's Windows time-zone key name, or `None`.

    The registry is asked first because it holds the canonical English name;
    `time.tzname` is translated on a non-English Windows and would then match
    nothing.
    """
    if os.name != "nt":
        return None
    try:
        import winreg

        with winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r"SYSTEM\CurrentControlSet\Control\TimeZoneInformation",
        ) as handle:
            value, _kind = winreg.QueryValueEx(handle, "TimeZoneKeyName")
        if isinstance(value, str) and value.strip():
            return value.strip().rstrip("\x00")
    except (ImportError, OSError):
        pass
    return time.tzname[0] if time.tzname and time.tzname[0] else None


def system_timezone() -> str | None:
    """The IANA name of this machine's own time zone, or `None`.

    `None` is a real answer and not a failure to try: it means the machine
    could not be asked, and the caller has to make somebody say which zone it
    is rather than stamping every photograph with a guess.
    """
    env_tz = os.environ.get("TZ", "").strip()
    if env_tz and resolve_zone_key(env_tz):
        return resolve_zone_key(env_tz)

    if os.name == "nt" or sys.platform == "win32":
        windows_name = _windows_zone_name()
        if windows_name:
            mapped = _WINDOWS_TO_IANA.get(windows_name.strip().lower())
            if mapped and resolve_zone_key(mapped):
                return resolve_zone_key(mapped)
            direct = resolve_zone_key(windows_name)
            if direct:
                return direct
        return None

    # POSIX: /etc/localtime is normally a symlink into the zoneinfo tree, and
    # Debian-family systems also write the name into /etc/timezone.
    try:
        link = os.readlink("/etc/localtime")
    except OSError:
        link = ""
    if "zoneinfo/" in link:
        candidate = link.split("zoneinfo/", 1)[1]
        if resolve_zone_key(candidate):
            return resolve_zone_key(candidate)
    try:
        with open("/etc/timezone", encoding="utf-8") as handle:
            candidate = handle.read().strip()
    except OSError:
        candidate = ""
    if candidate and resolve_zone_key(candidate):
        return resolve_zone_key(candidate)
    return None


def format_exif_datetime(dt: datetime.datetime | None) -> str | None:
    """Format datetime as standard EXIF string: `YYYY:MM:DD HH:MM:SS`."""
    if dt is None:
        return None
    return dt.strftime("%Y:%m:%d %H:%M:%S")


def format_exif_date_only(d: datetime.date | None) -> str | None:
    """Format date as EXIF date with zeroed time: `YYYY:MM:DD 00:00:00`."""
    if d is None:
        return None
    return d.strftime("%Y:%m:%d 00:00:00")


# =============================================================================
# Folder Name Date Parser
# =============================================================================


def easter_sunday(year: int) -> datetime.date:
    """Compute Gregorian Easter Sunday using Butcher's anonymous algorithm."""
    a = year % 19
    b = year // 100
    c = year % 100
    d = b // 4
    e = b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i = c // 4
    k = c % 4
    el = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * el) // 451
    month = (h + el - 7 * m + 114) // 31
    day = ((h + el - 7 * m + 114) % 31) + 1
    return datetime.date(year, month, day)


def fourth_thursday_november(year: int) -> datetime.date:
    """Compute US Thanksgiving date (4th Thursday in November)."""
    nov1_weekday = datetime.date(year, 11, 1).weekday()
    days_to_first_thursday = (3 - nov1_weekday) % 7
    first_thursday = 1 + days_to_first_thursday
    fourth_thursday = first_thursday + 21
    return datetime.date(year, 11, fourth_thursday)


MONTH_NAMES = {
    "jan": 1,
    "january": 1,
    "feb": 2,
    "february": 2,
    "mar": 3,
    "march": 3,
    "apr": 4,
    "april": 4,
    "may": 5,
    "jun": 6,
    "june": 6,
    "jul": 7,
    "july": 7,
    "aug": 8,
    "august": 8,
    "sep": 9,
    "sept": 9,
    "september": 9,
    "oct": 10,
    "october": 10,
    "nov": 11,
    "november": 11,
    "dec": 12,
    "december": 12,
}


#: How precisely each folder-name date kind pins a photo down.
#: This is the whole point of the type: `Easter 1999` names a day, `Aug. 1999`
#: names a month, `2001` names a year. They are not interchangeable, and the
#: difference decides what may be written to `DateTimeOriginal`.
DATE_KIND_PRECISION: dict[str, str] = {
    "exact_day": "day",
    "month": "month",
    "season": "season",
    "year_span": "year",
    "year": "year",
    "none": "none",
}

#: Only a day-precise folder date may become EXIF `DateTimeOriginal`.
#:
#: EXIF has no month-only or year-only form for a capture date: writing one
#: means naming a specific day. A folder called `2001` does not say the photo
#: was taken on 1 January 2001, and `Summer 2000` does not say 1 June. Picking
#: the first instant of the range would invent a capture date no evidence
#: supports, and would do it for 151 of this corpus's 687 files -- 97 from a
#: bare year, 34 from a year span, 20 from a season. Coarser folder dates are
#: still kept: they order the output and drive the filename prefix, which is a
#: browsing affordance rather than a claim about when the shutter fired.
DEFENSIBLE_DATE_KINDS = frozenset({"exact_day"})


@dataclass
class FolderDateResult:
    parsed: bool
    date_kind: str  # 'exact_day', 'month', 'season', 'year_span', 'year', 'none'
    year: int | None = None
    month: int | None = None
    day: int | None = None
    start_date: datetime.date | None = None
    end_date: datetime.date | None = None
    display_label: str = ""
    description: str = ""

    @property
    def precision(self) -> str:
        """'day' | 'month' | 'season' | 'year' | 'none' -- how tightly this pins a date."""
        return DATE_KIND_PRECISION.get(self.date_kind, "none")

    @property
    def defensible_date(self) -> datetime.date | None:
        """The date this folder name justifies writing to `DateTimeOriginal`.

        `None` for anything coarser than a single day -- see
        `DEFENSIBLE_DATE_KINDS`. Use `range_start` when you want an ordering
        key rather than a truth claim.
        """
        if not self.parsed or self.date_kind not in DEFENSIBLE_DATE_KINDS:
            return None
        return self.start_date

    @property
    def range_start(self) -> datetime.date | None:
        """First day of the range this folder name covers, at any precision.

        Safe for sorting and for the filename prefix; NOT safe for
        `DateTimeOriginal`.
        """
        return self.start_date if self.parsed else None


@functools.lru_cache(maxsize=1)
def _coarse_albums() -> frozenset[str]:
    """Albums the owner has said are coarser than their name looks."""
    try:
        return config.coarse_albums()
    except config.ConfigError:
        raise
    except Exception:  # noqa: BLE001
        # No `.env` at all is the normal case for a fresh checkout.
        return frozenset()


def parse_folder_date(folder_name: str) -> FolderDateResult:
    """Extract dates or date ranges encoded in an album folder name.

    Handles explicit holidays (4th of July, Easter, Christmas, etc.), month+year,
    season+year, 2-year ranges (e.g. `2001-02`), and single years.

    A name listed in `FPX_COARSE_ALBUMS` is demoted to its year afterwards.
    A holiday name resolves to a calendar day, but a folder named for one may
    hold the season around it -- the eve, the day after, the week -- and only
    the person who made the folder knows which. Demotion keeps the album
    filing and sorting under that year while taking away the day-precise
    claim, so nothing reaches `DateTimeOriginal`.
    """
    result = _parse_folder_name(folder_name)
    if not result.parsed or result.year is None:
        return result
    if folder_name.strip().lower() not in _coarse_albums():
        return result
    if result.precision == "year":
        return result
    return FolderDateResult(
        parsed=True,
        date_kind="year",
        year=result.year,
        start_date=datetime.date(result.year, 1, 1),
        end_date=datetime.date(result.year, 12, 31),
        display_label=str(result.year),
        description=f"{result.description} (declared coarse; demoted to the year)".strip(),
    )


def _parse_folder_name(folder_name: str) -> FolderDateResult:
    """The parser itself. `parse_folder_date` is the entry point."""
    raw = folder_name.strip()
    lower = raw.lower()

    # 0. Explicit numeric date (`2001-07-04`, `2001_07_04`, `2001.07.04`).
    #    Must run before the year-range rule below, which would otherwise
    #    read the `2001-07` prefix as the span 2001-2007.
    m_iso = re.search(r"\b(19\d\d|20\d\d)[-_./](\d{1,2})[-_./](\d{1,2})\b", lower)
    if m_iso:
        yr, mon, day = (int(g) for g in m_iso.groups())
        try:
            d = datetime.date(yr, mon, day)
        except ValueError:
            d = None  # e.g. 2001-13-45; fall through to the looser rules
        if d is not None:
            return FolderDateResult(
                parsed=True,
                date_kind="exact_day",
                year=yr,
                month=mon,
                day=day,
                start_date=d,
                end_date=d,
                display_label=d.isoformat(),
                description="Explicit date in folder name",
            )

    # 1. 4th of July / July 4th
    m_july4 = re.search(r"(?:4th\s+of\s+july|july\s+4th?)\s+(19\d\d|20\d\d)", lower)
    if m_july4:
        yr = int(m_july4.group(1))
        d = datetime.date(yr, 7, 4)
        return FolderDateResult(
            parsed=True,
            date_kind="exact_day",
            year=yr,
            month=7,
            day=4,
            start_date=d,
            end_date=d,
            display_label=f"{yr}-07-04",
            description="4th of July",
        )

    # 2. Christmas / Xmas
    m_xmas = re.search(r"\b(?:christmas|xmas)\s+(19\d\d|20\d\d)", lower)
    if m_xmas:
        yr = int(m_xmas.group(1))
        d = datetime.date(yr, 12, 25)
        return FolderDateResult(
            parsed=True,
            date_kind="exact_day",
            year=yr,
            month=12,
            day=25,
            start_date=d,
            end_date=d,
            display_label=f"{yr}-12-25",
            description="Christmas",
        )

    # 3. Easter (e.g. "Easter 1999", "Easter1999")
    m_easter = re.search(r"\beaster\s*(19\d\d|20\d\d)", lower)
    if m_easter:
        yr = int(m_easter.group(1))
        d = easter_sunday(yr)
        return FolderDateResult(
            parsed=True,
            date_kind="exact_day",
            year=yr,
            month=d.month,
            day=d.day,
            start_date=d,
            end_date=d,
            display_label=d.isoformat(),
            description="Easter Sunday",
        )

    # 4. Halloween
    m_halloween = re.search(r"\bhalloween\s+(19\d\d|20\d\d)", lower)
    if m_halloween:
        yr = int(m_halloween.group(1))
        d = datetime.date(yr, 10, 31)
        return FolderDateResult(
            parsed=True,
            date_kind="exact_day",
            year=yr,
            month=10,
            day=31,
            start_date=d,
            end_date=d,
            display_label=f"{yr}-10-31",
            description="Halloween",
        )

    # 5. Month name + year (e.g. "Aug. 2000", "August 2000", "Nov 2001")
    m_month_yr = re.search(
        r"\b(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|"
        r"jul(?:y)?|aug(?:ust)?|sep(?:t|tember)?|oct(?:ober)?|nov(?:ember)?|"
        r"dec(?:ember)?)\.?\s+(19\d\d|20\d\d)\b",
        lower,
    )
    if m_month_yr:
        m_name = m_month_yr.group(1).rstrip(".")
        yr = int(m_month_yr.group(2))
        mon = MONTH_NAMES[m_name]
        last_day = calendar.monthrange(yr, mon)[1]
        start_d = datetime.date(yr, mon, 1)
        end_d = datetime.date(yr, mon, last_day)
        return FolderDateResult(
            parsed=True,
            date_kind="month",
            year=yr,
            month=mon,
            day=1,
            start_date=start_d,
            end_date=end_d,
            display_label=f"{yr}-{mon:02d}",
            description=f"{start_d.strftime('%B')} {yr}",
        )

    # 6. Season + year (e.g. "Winter 1995", "Harvest 1994", "Spring 1996")
    m_season = re.search(
        r"\b(winter|spring|summer|fall|autumn|harvest)\s+(19\d\d|20\d\d)\b", lower
    )
    if m_season:
        season = m_season.group(1)
        yr = int(m_season.group(2))
        if season == "winter":
            start_d = datetime.date(yr, 1, 1)
            end_d = datetime.date(yr, 2, calendar.monthrange(yr, 2)[1])
        elif season == "spring":
            start_d = datetime.date(yr, 3, 1)
            end_d = datetime.date(yr, 5, 31)
        elif season == "summer":
            start_d = datetime.date(yr, 6, 1)
            end_d = datetime.date(yr, 8, 31)
        else:  # fall / autumn / harvest
            start_d = datetime.date(yr, 9, 1)
            end_d = datetime.date(yr, 11, 30)

        return FolderDateResult(
            parsed=True,
            date_kind="season",
            year=yr,
            start_date=start_d,
            end_date=end_d,
            display_label=f"{season.capitalize()} {yr}",
            description=f"{season.capitalize()} {yr}",
        )

    # 7. Year range (e.g. "2001-02" or "2001-2002")
    #
    # `(?<!\d)` rather than `\b`: a year glued straight onto a word has no
    # word boundary in front of it, so a folder named like `holidays2001-02`
    # matched nothing and 24 photos in this corpus lost their year. A digit
    # in front still blocks the match, which is what keeps a camera-generated
    # name like `DCP01999` out.
    m_range = re.search(r"(?<!\d)(19\d\d|20\d\d)-(?:(\d{2})|(19\d\d|20\d\d))(?!\d)", lower)
    y2: int | None = None
    if m_range:
        y1 = int(m_range.group(1))
        if m_range.group(2):
            # Two-digit tail. Only a *consecutive* year reads as a span:
            # `2001-02` means 2001-2002, but `2001-07` is far more likely a
            # numeric month that rule 0 declined than a six-year range.
            # Deriving y2 as y1 + 1 rather than pasting the century onto the
            # tail also sidesteps the rollover that turns `1999-00` into 1900.
            if int(m_range.group(2)) == (y1 + 1) % 100:
                y2 = y1 + 1
        else:
            y2 = int(m_range.group(3))
    if m_range and y2 is not None:
        start_d = datetime.date(y1, 1, 1)
        end_d = datetime.date(y2, 12, 31)
        return FolderDateResult(
            parsed=True,
            date_kind="year_span",
            year=y1,
            start_date=start_d,
            end_date=end_d,
            display_label=f"{y1}-{y2}",
            description=f"{y1} to {y2}",
        )

    # 8. Single year (e.g. "2000", or glued on as in "summer2000")
    m_yr = re.search(r"(?<!\d)(19\d\d|20\d\d)(?!\d)", lower)
    if m_yr:
        yr = int(m_yr.group(1))
        start_d = datetime.date(yr, 1, 1)
        end_d = datetime.date(yr, 12, 31)
        return FolderDateResult(
            parsed=True,
            date_kind="year",
            year=yr,
            start_date=start_d,
            end_date=end_d,
            display_label=f"{yr}",
            description=f"Year {yr}",
        )

    return FolderDateResult(
        parsed=False,
        date_kind="none",
        display_label="",
        description="No date found in folder name",
    )


# =============================================================================
# Per-File Timestamp Resolution
# =============================================================================


@dataclass
class ResolvedTimestamps:
    import_timestamp_raw: int | None
    import_datetime: datetime.datetime | None
    embedded_scan_datetime: datetime.datetime | None
    #: First day of the range the album folder name covers, at whatever
    #: precision it happens to carry. An ordering key, not a capture date --
    #: read `date_precision` before believing the day-of-month.
    folder_date: datetime.date | None
    #: How precise the folder name was: 'day' | 'month' | 'season' | 'year' |
    #: 'none'. `datetime_original_exif` is populated only at 'day' or finer.
    folder_precision: str
    date_source: str  # 'owner-supplied' | 'embedded-scan-date' | 'folder' |
    #                   'import-stamp' | 'none'
    #: Precision of `datetime_original_exif`: 'second' | 'day' | 'none'.
    date_precision: str
    #: Best available ordering key, in descending order of trust: a defensible
    #: capture date, else the folder range start, else the import stamp. Drives
    #: the filename prefix and the filesystem mtime. Never written to EXIF.
    sort_datetime: datetime.datetime | None
    datetime_digitized_exif: str | None
    datetime_original_exif: str | None
    timezone_name: str
    offset_time_digitized: str | None
    offset_time_original: str | None


def resolve_file_timestamps(
    import_ft: int | None,
    scan_time_dt: datetime.datetime | None,
    primary_album: str,
    default_tz: str = DEFAULT_TZ,
    tz_overrides: dict[str, str] | None = None,
    owner_date: datetime.date | None = None,
) -> ResolvedTimestamps:
    """Resolve timestamps for one file according to project dating rules.

    `owner_date` is a day somebody typed after looking at the photographs --
    see `album_dates`. It outranks everything derived from the file, because a
    person who was there is better evidence than a folder name, and far better
    than an import stamp that misses the event by up to 223 days. It is
    recorded as `date_source="owner-supplied"` so an audit can always tell an
    assertion from a derivation.
    """
    from .propset import filetime_to_dt

    import_dt = filetime_to_dt(import_ft) if import_ft else None
    tz_name = get_album_timezone(primary_album, default_tz=default_tz, overrides=tz_overrides)

    offset_digitized = get_timezone_offset(import_dt, tz_name) if import_dt else None
    digitized_exif = format_exif_datetime(import_dt)

    original_dt: datetime.datetime | None = None
    offset_original: str | None = None
    date_src = "none"

    folder_res = parse_folder_date(primary_album) if primary_album else None
    folder_defensible = folder_res.defensible_date if folder_res else None
    folder_range_start = folder_res.range_start if folder_res else None
    folder_precision = folder_res.precision if folder_res else "none"
    precision = "none"

    if owner_date is not None:
        # Midnight, for the same reason the folder branch below uses it: a day
        # is known and an hour is not, and borrowing a clock time from an
        # unrelated transfer session would dress a known day as a precise
        # capture moment in every photo app that shows one.
        original_dt = datetime.datetime(
            owner_date.year, owner_date.month, owner_date.day, 0, 0, 0
        )
        date_src = "owner-supplied"
        precision = "day"
        offset_original = get_timezone_offset(original_dt, tz_name)
    elif scan_time_dt is not None:
        original_dt = scan_time_dt
        date_src = "embedded-scan-date"
        precision = "second"
        offset_original = get_timezone_offset(original_dt, tz_name)
    elif folder_defensible is not None:
        # Midnight, deliberately -- not the import stamp's clock time. The
        # folder names a day; nothing in the file names an hour. Borrowing
        # H:M:S from the import batch would dress a known day in a time
        # belonging to an unrelated transfer session, and the result reads
        # like a precise capture moment to every photo app that shows it.
        original_dt = datetime.datetime(
            folder_defensible.year, folder_defensible.month, folder_defensible.day, 0, 0, 0
        )
        date_src = "folder"
        precision = "day"
        offset_original = get_timezone_offset(original_dt, tz_name)
    elif import_dt is not None:
        date_src = "import-stamp"

    original_exif = (
        format_exif_datetime(original_dt)
        if date_src in ("embedded-scan-date", "folder", "owner-supplied")
        else None
    )

    # Ordering key, in descending order of trust. Coarse folder dates are
    # allowed here precisely because this never reaches EXIF -- it decides
    # where a file sorts, and the filename prefix marks how much of it is
    # actually known.
    if original_dt is not None:
        sort_dt: datetime.datetime | None = original_dt
    elif folder_range_start is not None:
        sort_dt = datetime.datetime(
            folder_range_start.year, folder_range_start.month, folder_range_start.day, 0, 0, 0
        )
    else:
        sort_dt = import_dt

    return ResolvedTimestamps(
        import_timestamp_raw=import_ft,
        import_datetime=import_dt,
        embedded_scan_datetime=scan_time_dt,
        folder_date=folder_range_start,
        folder_precision=folder_precision,
        date_source=date_src,
        date_precision=precision,
        sort_datetime=sort_dt,
        datetime_digitized_exif=digitized_exif,
        datetime_original_exif=original_exif,
        timezone_name=tz_name,
        offset_time_digitized=offset_digitized,
        offset_time_original=offset_original if original_exif else None,
    )


# =============================================================================
# Album Ground-Truth Gate
# =============================================================================


@dataclass
class AlbumGroundTruthResult:
    album: str
    file_count: int
    parsed: bool
    date_kind: str
    expected_display: str
    import_dates_seen: list[str]
    earliest_import: str
    latest_import: str
    verdict: str  # 'PASS' | 'NEAR' | 'FAIL' | 'UNDATED'
    delta_days_min: int | None
    delta_days_max: int | None
    notes: str


@dataclass
class GroundTruthReport:
    total_albums: int
    dated_albums: int
    passed_albums: int
    near_albums: int
    failed_albums: int
    undated_albums: int
    results: list[AlbumGroundTruthResult] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        # Gate passes when all dated albums are accounted for (evaluations reported)
        return self.failed_albums == 0


def evaluate_album_ground_truth(
    album_name: str,
    import_datetimes: list[datetime.datetime],
) -> AlbumGroundTruthResult:
    """Compare an album's parsed date against the import timestamps of its files."""
    count = len(import_datetimes)
    if not import_datetimes:
        return AlbumGroundTruthResult(
            album=album_name,
            file_count=0,
            parsed=False,
            date_kind="none",
            expected_display="None",
            import_dates_seen=[],
            earliest_import="",
            latest_import="",
            verdict="UNDATED",
            delta_days_min=None,
            delta_days_max=None,
            notes="No files with timestamps",
        )

    import_dates = sorted({dt.date() for dt in import_datetimes})
    import_dates_str = [d.isoformat() for d in import_dates]
    min_import = min(import_dates)
    max_import = max(import_dates)

    parsed = parse_folder_date(album_name)
    if not parsed.parsed or parsed.start_date is None:
        return AlbumGroundTruthResult(
            album=album_name,
            file_count=count,
            parsed=False,
            date_kind="none",
            expected_display="Undated",
            import_dates_seen=import_dates_str,
            earliest_import=min_import.isoformat(),
            latest_import=max_import.isoformat(),
            verdict="UNDATED",
            delta_days_min=None,
            delta_days_max=None,
            notes="No date encoded in album name",
        )

    delta_min = (min_import - parsed.start_date).days
    delta_max = (max_import - parsed.start_date).days

    # Evaluation logic
    if parsed.date_kind == "exact_day":
        # Specific event day (e.g. Christmas, 4th of July, Easter)
        if min_import.year != parsed.start_date.year:
            verdict = "FAIL"
            notes = (
                f"Wrong calendar year (expected {parsed.start_date.year}, "
                f"imported {min_import.year})"
            )
        elif 0 <= delta_min <= 3 and 0 <= delta_max <= 3:
            verdict = "PASS"
            notes = f"Imported within {delta_max} days of event"
        elif 0 <= delta_min <= 14:
            verdict = "FAIL" if delta_max > 7 else "NEAR"
            notes = f"+{delta_min} to +{delta_max} days after event"
        else:
            verdict = "FAIL"
            notes = f"+{delta_min} to +{delta_max} days after event (failed ground truth)"

    elif parsed.date_kind == "month":
        assert parsed.end_date is not None
        if min_import.year != parsed.start_date.year:
            verdict = "FAIL"
            notes = (
                f"Wrong calendar year (expected {parsed.start_date.year}, "
                f"imported {min_import.year})"
            )
        elif parsed.start_date <= min_import <= parsed.end_date:
            verdict = "PASS"
            notes = "Imported during the expected month"
        elif 0 <= (min_import - parsed.end_date).days <= 30:
            verdict = "NEAR"
            notes = f"Imported {(min_import - parsed.end_date).days} days after month ended"
        else:
            verdict = "FAIL"
            notes = f"+{delta_min} days delta (imported long after month)"

    elif parsed.date_kind == "season":
        assert parsed.end_date is not None
        if min_import.year != parsed.start_date.year:
            verdict = "FAIL"
            notes = f"Wrong calendar year (expected {parsed.start_date.year})"
        elif parsed.start_date <= min_import <= parsed.end_date:
            verdict = "PASS"
            notes = "Imported during the expected season"
        elif 0 <= (min_import - parsed.end_date).days <= 30:
            verdict = "NEAR"
            notes = "Imported just after season ended"
        else:
            verdict = "FAIL"
            notes = f"Imported outside season window (+{delta_min} days)"

    elif parsed.date_kind in ("year", "year_span"):
        assert parsed.end_date is not None
        if parsed.start_date <= min_import and max_import <= parsed.end_date:
            verdict = "PASS"
            notes = f"Imported within {parsed.display_label}"
        elif min_import.year == parsed.year or max_import.year == (parsed.end_date.year):
            verdict = "NEAR"
            notes = "Spans across year boundary"
        else:
            verdict = "FAIL"
            notes = f"Import year {min_import.year} outside {parsed.display_label}"
    else:
        verdict = "UNDATED"
        notes = "Undated"

    return AlbumGroundTruthResult(
        album=album_name,
        file_count=count,
        parsed=True,
        date_kind=parsed.date_kind,
        expected_display=parsed.display_label,
        import_dates_seen=import_dates_str,
        earliest_import=min_import.isoformat(),
        latest_import=max_import.isoformat(),
        verdict=verdict,
        delta_days_min=delta_min,
        delta_days_max=delta_max,
        notes=notes,
    )


def check_manifest_ground_truth(
    manifest: dict[str, Any],
    timestamps_by_hash: dict[str, datetime.datetime],
) -> GroundTruthReport:
    """Run the ground-truth check across all albums in the manifest."""
    albums_map: dict[str, list[datetime.datetime]] = {}

    for entry in manifest["entries"]:
        sha = entry["sha256"]
        dt = timestamps_by_hash.get(sha)
        if dt is None:
            continue
        for alb in entry["albums"]:
            if alb:
                albums_map.setdefault(alb, []).append(dt)

    results: list[AlbumGroundTruthResult] = []
    dated_count = 0
    passed_count = 0
    near_count = 0
    failed_count = 0
    undated_count = 0

    for alb in sorted(albums_map.keys(), key=lambda s: s.lower()):
        dts = albums_map[alb]
        res = evaluate_album_ground_truth(alb, dts)
        results.append(res)
        if res.parsed:
            dated_count += 1
            if res.verdict == "PASS":
                passed_count += 1
            elif res.verdict == "NEAR":
                near_count += 1
            elif res.verdict == "FAIL":
                failed_count += 1
        else:
            undated_count += 1

    return GroundTruthReport(
        total_albums=len(results),
        dated_albums=dated_count,
        passed_albums=passed_count,
        near_albums=near_count,
        failed_albums=failed_count,
        undated_albums=undated_count,
        results=results,
    )
