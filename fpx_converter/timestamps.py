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
4. **`DateTimeOriginal` is written only where defensible**: from folder name
   ground truth, embedded film scan date (4 files), or owner review.
5. **The folder-name ground-truth check is an automated gate** that reports
   discrepancies per album and never silently alters date sources.
"""

from __future__ import annotations

import calendar
import datetime
import re
from dataclasses import dataclass, field
from typing import Any

# =============================================================================
# Timezone & Formatting Helpers
# =============================================================================

DEFAULT_TZ = "America/Chicago"

# Normalized album substring -> IANA timezone name
DEFAULT_ALBUM_TZ_OVERRIDES: dict[str, str] = {
    "east coast trip": "America/New_York",
    "east coast": "America/New_York",
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


def get_timezone_offset(dt: datetime.datetime, tz_name: str) -> str:
    """Return formatted UTC offset string (`±HH:MM`) for a naive local datetime.

    Calculates the standard or daylight saving offset without modifying the
    local wall-clock digits. Uses pure Python US DST rules for offline Windows
    resilience where `tzdata` is not installed.
    """
    tz_clean = tz_name.lower().replace(" ", "").replace("_", "")
    is_dst = _is_us_dst(dt)

    # Base UTC offsets for standard US zones:
    # Eastern: -5 (standard) / -4 (DST)
    # Central: -6 (standard) / -5 (DST)
    # Mountain: -7 (standard) / -6 (DST)
    # Pacific: -8 (standard) / -7 (DST)
    if "newyork" in tz_clean or "eastern" in tz_clean:
        h = -4 if is_dst else -5
    elif "denver" in tz_clean or "mountain" in tz_clean:
        h = -6 if is_dst else -7
    elif "losangeles" in tz_clean or "pacific" in tz_clean:
        h = -7 if is_dst else -8
    elif "utc" in tz_clean or "gmt" in tz_clean:
        return "+00:00"
    else:
        # Default: America/Chicago / Central
        h = -5 if is_dst else -6

    sign = "+" if h >= 0 else "-"
    return f"{sign}{abs(h):02d}:00"


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
    def defensible_date(self) -> datetime.date | None:
        """Return a defensible date if one was extracted (exact day, or start of month)."""
        if self.start_date:
            return self.start_date
        if self.year and self.month and self.day:
            return datetime.date(self.year, self.month, self.day)
        if self.year and self.month:
            return datetime.date(self.year, self.month, 1)
        return None


def parse_folder_date(folder_name: str) -> FolderDateResult:
    """Extract dates or date ranges encoded in an album folder name.

    Handles explicit holidays (4th of July, Easter, Christmas, etc.), month+year,
    season+year, 2-year ranges (e.g. `2001-02`), and single years.
    """
    raw = folder_name.strip()
    lower = raw.lower()

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

    # 3. Easter (e.g. "Easter 2002", "Easter2000")
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

    # 6. Season + year (e.g. "Winter 2002", "Harvest 2001", "Spring 2000")
    m_season = re.search(
        r"\b(winter|spring|summer|fall|autumn|harvest)\s+(19\d\d|20\d\d)\b", lower
    )
    if m_season:
        season = m_season.group(1)
        yr = int(m_season.group(2))
        if season == "winter":
            start_d = datetime.date(yr, 1, 1)
            end_d = datetime.date(yr, 2, 28)
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
    m_range = re.search(r"\b(19\d\d|20\d\d)-(?:(\d{2})|(19\d\d|20\d\d))\b", lower)
    if m_range:
        y1 = int(m_range.group(1))
        y2 = int(f"{y1 // 100}{m_range.group(2)}" if m_range.group(2) else m_range.group(3))
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

    # 8. Single standalone year (e.g. "2000", "2001", "2002")
    m_yr = re.search(r"\b(19\d\d|20\d\d)\b", lower)
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
    folder_date: datetime.date | None
    date_source: str  # 'embedded-scan-date' | 'folder' | 'import-stamp' | 'none'
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
) -> ResolvedTimestamps:
    """Resolve timestamps for one file according to project dating rules."""
    from .propset import filetime_to_dt

    import_dt = filetime_to_dt(import_ft) if import_ft else None
    tz_name = get_album_timezone(primary_album, default_tz=default_tz, overrides=tz_overrides)

    offset_digitized = get_timezone_offset(import_dt, tz_name) if import_dt else None
    digitized_exif = format_exif_datetime(import_dt)

    original_dt: datetime.datetime | None = None
    offset_original: str | None = None
    date_src = "none"

    folder_res = parse_folder_date(primary_album) if primary_album else None
    folder_defensible = folder_res.defensible_date if folder_res and folder_res.parsed else None

    if scan_time_dt is not None:
        original_dt = scan_time_dt
        date_src = "embedded-scan-date"
        offset_original = get_timezone_offset(original_dt, tz_name)
    elif folder_defensible is not None:
        if import_dt is not None:
            original_dt = datetime.datetime(
                folder_defensible.year,
                folder_defensible.month,
                folder_defensible.day,
                import_dt.hour,
                import_dt.minute,
                import_dt.second,
            )
        else:
            original_dt = datetime.datetime(
                folder_defensible.year,
                folder_defensible.month,
                folder_defensible.day,
                0,
                0,
                0,
            )
        date_src = "folder"
        offset_original = get_timezone_offset(original_dt, tz_name)
    elif import_dt is not None:
        date_src = "import-stamp"

    original_exif = (
        format_exif_datetime(original_dt)
        if date_src in ("embedded-scan-date", "folder")
        else None
    )

    return ResolvedTimestamps(
        import_timestamp_raw=import_ft,
        import_datetime=import_dt,
        embedded_scan_datetime=scan_time_dt,
        folder_date=folder_defensible,
        date_source=date_src,
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
