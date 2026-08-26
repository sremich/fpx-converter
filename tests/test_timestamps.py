"""Tier-1 unit tests for timestamp resolution, timezone mapping, and ground-truth gate.

Uses invented album names only (e.g. 'Holiday in France 2001', 'Zoo Trip - Aug 2000').
No personal data, no real corpus folder names.
"""

from __future__ import annotations

import datetime

from fpx_converter import timestamps


class TestFolderDateParsing:
    def test_parses_fourth_of_july(self) -> None:
        res = timestamps.parse_folder_date("4th of July 2001")
        assert res.parsed
        assert res.date_kind == "exact_day"
        assert res.start_date == datetime.date(2001, 7, 4)
        assert res.display_label == "2001-07-04"

    def test_parses_christmas(self) -> None:
        res = timestamps.parse_folder_date("Holiday Christmas 2000")
        assert res.parsed
        assert res.date_kind == "exact_day"
        assert res.start_date == datetime.date(2000, 12, 25)

    def test_parses_easter_with_butcher_algorithm(self) -> None:
        # Easter 2000 is 2000-04-23; Easter 2002 is 2002-03-31; Easter 2001 is 2001-04-15
        res_2000 = timestamps.parse_folder_date("Easter2000")
        assert res_2000.parsed
        assert res_2000.start_date == datetime.date(2000, 4, 23)

        res_2002 = timestamps.parse_folder_date("Easter 2002")
        assert res_2002.parsed
        assert res_2002.start_date == datetime.date(2002, 3, 31)

        res_2001 = timestamps.parse_folder_date("Easter 2001 Picnic")
        assert res_2001.parsed
        assert res_2001.start_date == datetime.date(2001, 4, 15)

    def test_parses_halloween(self) -> None:
        res = timestamps.parse_folder_date("Halloween 1999 Party")
        assert res.parsed
        assert res.start_date == datetime.date(1999, 10, 31)

    def test_parses_month_and_year(self) -> None:
        res1 = timestamps.parse_folder_date("Zoo Trip - Aug. 2000")
        assert res1.parsed
        assert res1.date_kind == "month"
        assert res1.start_date == datetime.date(2000, 8, 1)
        assert res1.end_date == datetime.date(2000, 8, 31)
        assert res1.display_label == "2000-08"

        res2 = timestamps.parse_folder_date("Family Event - November 2001")
        assert res2.parsed
        assert res2.start_date == datetime.date(2001, 11, 1)

    def test_parses_season_and_year(self) -> None:
        res_winter = timestamps.parse_folder_date("Winter 2002 Skiing")
        assert res_winter.parsed
        assert res_winter.date_kind == "season"
        assert res_winter.start_date == datetime.date(2002, 1, 1)

        res_harvest = timestamps.parse_folder_date("Harvest 2001")
        assert res_harvest.parsed
        assert res_harvest.start_date == datetime.date(2001, 9, 1)

    def test_parses_year_ranges_and_standalone_years(self) -> None:
        res_range = timestamps.parse_folder_date("Vacation Trip 2001-02")
        assert res_range.parsed
        assert res_range.date_kind == "year_span"
        assert res_range.display_label == "2001-2002"

        res_yr = timestamps.parse_folder_date("Camping 2000")
        assert res_yr.parsed
        assert res_yr.date_kind == "year"
        assert res_yr.display_label == "2000"

    def test_returns_unparsed_for_undated_folder_names(self) -> None:
        for name in ("Pictures", "FlatTree", "Top Drawer", "Miscellaneous", "Pets"):
            res = timestamps.parse_folder_date(name)
            assert not res.parsed
            assert res.date_kind == "none"
            assert res.defensible_date is None


class TestTimezoneOffsets:
    def test_calculates_dst_and_standard_offsets_without_modifying_time(self) -> None:
        # America/Chicago: CDT (UTC-5) in summer, CST (UTC-6) in winter
        summer_dt = datetime.datetime(2001, 7, 18, 14, 0, 0)
        winter_dt = datetime.datetime(2001, 12, 5, 14, 0, 0)

        offset_summer = timestamps.get_timezone_offset(summer_dt, "America/Chicago")
        offset_winter = timestamps.get_timezone_offset(winter_dt, "America/Chicago")

        assert offset_summer == "-05:00"
        assert offset_winter == "-06:00"

    def test_applies_album_timezone_overrides(self) -> None:
        tz_eastport = timestamps.get_album_timezone("Theme Park Big East Coast Trip 2002")
        assert tz_eastport == "America/New_York"

        tz_dc = timestamps.get_album_timezone("East coast trips")
        assert tz_dc == "America/New_York"

        tz_default = timestamps.get_album_timezone("Camping in Back Garden 2001")
        assert tz_default == "America/Chicago"


class TestTimestampResolution:
    def test_import_stamp_maps_to_digitized_never_original(self) -> None:
        # Convert 2002-07-18 14:01:34 to FILETIME
        dt_target = datetime.datetime(2002, 7, 18, 14, 1, 34)
        ft_val = int((dt_target - datetime.datetime(1601, 1, 1)).total_seconds() * 10_000_000)

        # File in an undated album
        resolved = timestamps.resolve_file_timestamps(
            import_ft=ft_val,
            scan_time_dt=None,
            primary_album="General Pictures",
        )
        assert resolved.datetime_digitized_exif == "2002:07:18 14:01:34"
        assert resolved.datetime_original_exif is None
        assert resolved.date_source == "import-stamp"
        assert resolved.offset_time_digitized == "-05:00"
        assert resolved.offset_time_original is None

    def test_folder_derived_date_populates_datetime_original(self) -> None:
        dt_target = datetime.datetime(2002, 7, 18, 14, 1, 34)
        ft_val = int((dt_target - datetime.datetime(1601, 1, 1)).total_seconds() * 10_000_000)

        resolved = timestamps.resolve_file_timestamps(
            import_ft=ft_val,
            scan_time_dt=None,
            primary_album="4th of July 2002",
        )
        assert resolved.datetime_digitized_exif == "2002:07:18 14:01:34"
        # Preserves time-of-day with folder calendar day
        assert resolved.datetime_original_exif == "2002:07:04 14:01:34"
        assert resolved.date_source == "folder"
        assert resolved.offset_time_original == "-05:00"

    def test_embedded_scan_date_takes_precedence_for_original(self) -> None:
        dt_import = datetime.datetime(2002, 7, 18, 14, 1, 34)
        ft_import = int((dt_import - datetime.datetime(1601, 1, 1)).total_seconds() * 10_000_000)
        dt_scan = datetime.datetime(1998, 1, 7, 13, 17, 21)

        resolved = timestamps.resolve_file_timestamps(
            import_ft=ft_import,
            scan_time_dt=dt_scan,
            primary_album="Sample Photos",
        )
        assert resolved.datetime_digitized_exif == "2002:07:18 14:01:34"
        assert resolved.datetime_original_exif == "1998:01:07 13:17:21"
        assert resolved.date_source == "embedded-scan-date"


class TestGroundTruthGate:
    def test_detects_pass_near_and_fail_ground_truth(self) -> None:
        # 1. Pass: July 4th event imported July 5th (+1 day)
        res_pass = timestamps.evaluate_album_ground_truth(
            "4th of July 2001",
            [datetime.datetime(2001, 7, 5, 12, 0, 0)],
        )
        assert res_pass.verdict == "PASS"
        assert res_pass.delta_days_min == 1

        # 2. Fail: Winterfest 1994 imported in January 2002 (wrong year)
        res_fail_year = timestamps.evaluate_album_ground_truth(
            "Holiday Winterfest 1994",
            [datetime.datetime(2002, 1, 5, 20, 0, 0)],
        )
        assert res_fail_year.verdict == "FAIL"
        assert "Wrong calendar year" in res_fail_year.notes

        # 3. Fail: Event in Aug 2000 imported Nov 2000 (+3 months)
        res_fail_months = timestamps.evaluate_album_ground_truth(
            "Trip - Aug. 2000",
            [datetime.datetime(2000, 11, 19, 15, 0, 0)],
        )
        assert res_fail_months.verdict == "FAIL"
        assert res_fail_months.delta_days_min is not None and res_fail_months.delta_days_min > 60

        # 4. Undated folder
        res_undated = timestamps.evaluate_album_ground_truth(
            "General Flat Photos",
            [datetime.datetime(2001, 5, 1, 10, 0, 0)],
        )
        assert res_undated.verdict == "UNDATED"

    def test_runs_manifest_ground_truth_report(self) -> None:
        manifest = {
            "entries": [
                {"sha256": "h1", "albums": ["4th of July 2001"]},
                {"sha256": "h2", "albums": ["Holiday Winterfest 1994"]},
                {"sha256": "h3", "albums": ["Random Album"]},
            ]
        }
        timestamps_by_hash = {
            "h1": datetime.datetime(2001, 7, 5, 10, 0),
            "h2": datetime.datetime(2002, 1, 5, 10, 0),
            "h3": datetime.datetime(2001, 9, 1, 10, 0),
        }
        report = timestamps.check_manifest_ground_truth(manifest, timestamps_by_hash)
        assert report.total_albums == 3
        assert report.dated_albums == 2
        assert report.passed_albums == 1
        assert report.failed_albums == 1
        assert report.undated_albums == 1
        assert not report.ok  # has 1 failed album
