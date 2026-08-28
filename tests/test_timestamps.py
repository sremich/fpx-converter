"""Tier-1 unit tests for timestamp resolution, timezone mapping, and ground-truth gate.

Album names here are invented and deliberately sit outside the corpus's
2000-2002 window where a holiday-plus-year string would otherwise read as a
real folder name. Six real ones did survive in this file until an audit
compared it against the manifest rather than against a guessed pattern list;
`tests/test_environment.py::test_no_real_album_name_is_tracked_in_git` now
does that comparison automatically, so this docstring is no longer the only
thing standing between the archive and a leak.
"""

from __future__ import annotations

import datetime

import pytest

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
        # Easter 1996 is 1996-04-07; Easter 1997 is 1997-03-30; Easter 1998 is 1998-04-12
        res_1996 = timestamps.parse_folder_date("Easter1996")
        assert res_1996.parsed
        assert res_1996.start_date == datetime.date(1996, 4, 7)

        res_1997 = timestamps.parse_folder_date("Easter 1997")
        assert res_1997.parsed
        assert res_1997.start_date == datetime.date(1997, 3, 30)

        res_1998 = timestamps.parse_folder_date("Easter 1998 Picnic")
        assert res_1998.parsed
        assert res_1998.start_date == datetime.date(1998, 4, 12)

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
        res_winter = timestamps.parse_folder_date("Winter 1995 Skiing")
        assert res_winter.parsed
        assert res_winter.date_kind == "season"
        assert res_winter.start_date == datetime.date(1995, 1, 1)

        res_harvest = timestamps.parse_folder_date("Harvest 1994")
        assert res_harvest.parsed
        assert res_harvest.start_date == datetime.date(1994, 9, 1)

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
        for name in ("Pictures", "FlatTree", "Odds and Ends", "Miscellaneous", "Pets"):
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
        # Overrides are supplied by the caller from `.env`; the module ships
        # none, because the keys are album names (see timestamps.py).
        overrides = {"east coast trip": "America/New_York"}

        matched = timestamps.get_album_timezone("Big East Coast Trip 2002", overrides=overrides)
        assert matched == "America/New_York"

        unmatched = timestamps.get_album_timezone("Back Garden 2001", overrides=overrides)
        assert unmatched == "America/Chicago"

    def test_ships_no_album_overrides(self) -> None:
        # A guard, not a formality: hardcoding these means committing album
        # names, and an override that silently stops applying writes a wrong
        # OffsetTime with no other symptom.
        assert timestamps.DEFAULT_ALBUM_TZ_OVERRIDES == {}
        assert timestamps.get_album_timezone("Any Album At All") == "America/Chicago"

    def test_unknown_timezone_is_refused_not_guessed(self) -> None:
        dt = datetime.datetime(2001, 6, 15, 12, 0, 0)
        with pytest.raises(timestamps.UnknownTimezoneError):
            timestamps.get_timezone_offset(dt, "America/Chicgao")  # typo
        with pytest.raises(timestamps.UnknownTimezoneError):
            timestamps.get_timezone_offset(dt, "Somewhere/Made_Up")

    def test_known_non_default_zones_resolve(self) -> None:
        summer = datetime.datetime(2001, 7, 4, 12, 0, 0)
        winter = datetime.datetime(2001, 1, 4, 12, 0, 0)
        assert timestamps.get_timezone_offset(summer, "America/New_York") == "-04:00"
        assert timestamps.get_timezone_offset(winter, "America/New_York") == "-05:00"
        assert timestamps.get_timezone_offset(summer, "America/Los_Angeles") == "-07:00"
        # Hawaii keeps standard time year round.
        assert timestamps.get_timezone_offset(summer, "Pacific/Honolulu") == "-10:00"
        assert timestamps.get_timezone_offset(winter, "Pacific/Honolulu") == "-10:00"


class TestZonesOutsideTheUnitedStates:
    """The whole world, not seven US zones plus UTC.

    Every zone here raised `UnknownTimezoneError` before 1.3.0, and that
    exception is caught per file by the batch engine -- so a run in London,
    Tokyo or Sydney recorded *every file in the archive* as failed, with the
    real reason repeated once per photograph in the error column. Anyone who
    did not hit that hit the other half of it instead: the default zone was
    `America/Chicago`, so a first run anywhere stamped US Central onto
    everything and said nothing.
    """

    SUMMER = datetime.datetime(2001, 7, 15, 12, 0, 0)
    WINTER = datetime.datetime(2001, 1, 15, 12, 0, 0)

    @pytest.mark.parametrize(
        ("zone", "summer", "winter"),
        [
            ("Europe/London", "+01:00", "+00:00"),   # BST / GMT
            ("Europe/Paris", "+02:00", "+01:00"),    # CEST / CET
            ("Asia/Tokyo", "+09:00", "+09:00"),      # no DST, ever
            ("Australia/Sydney", "+10:00", "+11:00"),  # southern hemisphere
            ("America/Phoenix", "-07:00", "-07:00"),  # Arizona keeps standard
            ("America/Chicago", "-05:00", "-06:00"),
        ],
    )
    def test_a_date_inside_and_outside_dst(
        self, zone: str, summer: str, winter: str
    ) -> None:
        assert timestamps.get_timezone_offset(self.SUMMER, zone) == summer
        assert timestamps.get_timezone_offset(self.WINTER, zone) == winter

    def test_a_half_hour_offset_survives_the_formatting(self) -> None:
        """`±HH:00` was hardcoded. India is +05:30 and Adelaide +09:30."""
        assert timestamps.get_timezone_offset(self.SUMMER, "Asia/Kolkata") == "+05:30"
        assert timestamps.get_timezone_offset(self.WINTER, "Australia/Adelaide") == "+10:30"

    @pytest.mark.parametrize("spelling", ["europe/london", "EUROPE/LONDON", "Europe/London"])
    def test_casing_does_not_decide_whether_a_zone_is_known(self, spelling: str) -> None:
        """`zoneinfo` keys are case-sensitive; the people typing them are not."""
        assert timestamps.get_timezone_offset(self.SUMMER, spelling) == "+01:00"


class TestHistoricalDaylightSaving:
    """1998-2002 dates need 1998-2002 rules, not today's.

    The US moved DST from the first Sunday in April to the second Sunday in
    March in 2007. A table built from today's schedule -- or an OS call that
    extrapolates today's rule backwards, which is what Windows does -- puts
    every US photograph taken between mid-March and early April of these
    years an hour out. `zoneinfo` carries the historical rules, and this is
    the test that says so.
    """

    def test_march_2001_in_chicago_is_still_standard_time(self) -> None:
        # Under the post-2007 rule this would already be CDT (-05:00).
        when = datetime.datetime(2001, 3, 15, 12, 0, 0)
        assert timestamps.get_timezone_offset(when, "America/Chicago") == "-06:00"

    def test_dst_began_on_the_first_sunday_in_april_2001(self) -> None:
        # 2001-04-01 was that Sunday.
        assert (
            timestamps.get_timezone_offset(
                datetime.datetime(2001, 3, 31, 12, 0, 0), "America/Chicago"
            )
            == "-06:00"
        )
        assert (
            timestamps.get_timezone_offset(
                datetime.datetime(2001, 4, 2, 12, 0, 0), "America/Chicago"
            )
            == "-05:00"
        )

    def test_and_ended_on_the_last_sunday_in_october(self) -> None:
        # 2001-10-28. Under the post-2007 rule it would run to 4 November.
        assert (
            timestamps.get_timezone_offset(
                datetime.datetime(2001, 10, 27, 12, 0, 0), "America/Chicago"
            )
            == "-05:00"
        )
        assert (
            timestamps.get_timezone_offset(
                datetime.datetime(2001, 11, 1, 12, 0, 0), "America/Chicago"
            )
            == "-06:00"
        )

    def test_london_kept_the_eu_schedule_throughout(self) -> None:
        # BST ran from the last Sunday in March (2001-03-25) to the last in
        # October, and still does -- which is why London is the wrong zone to
        # test the historical machinery with on its own.
        assert (
            timestamps.get_timezone_offset(
                datetime.datetime(2001, 3, 24, 12, 0, 0), "Europe/London"
            )
            == "+00:00"
        )
        assert (
            timestamps.get_timezone_offset(
                datetime.datetime(2001, 3, 26, 12, 0, 0), "Europe/London"
            )
            == "+01:00"
        )


class TestTheMachinesOwnZone:
    def test_it_is_a_zone_the_converter_can_resolve(self) -> None:
        """Whatever it answers has to be usable, or the default is a trap."""
        detected = timestamps.system_timezone()
        if detected is None:
            pytest.skip("this machine's zone could not be identified")
        assert timestamps.resolve_zone_key(detected) is not None
        timestamps.get_timezone_offset(datetime.datetime(2001, 7, 4, 12, 0, 0), detected)

    def test_the_tz_environment_variable_is_honoured(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("TZ", "Asia/Tokyo")
        assert timestamps.system_timezone() == "Asia/Tokyo"

    def test_a_nonsense_tz_variable_does_not_become_the_answer(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Better no answer than a guessed one -- the caller can ask."""
        monkeypatch.setenv("TZ", "Not/AZone")
        detected = timestamps.system_timezone()
        assert detected != "Not/AZone"

    def test_every_windows_name_it_maps_resolves(self) -> None:
        """A typo in that table is a silently wrong offset, not an error."""
        when = datetime.datetime(2001, 7, 4, 12, 0, 0)
        for windows_name, iana in timestamps._WINDOWS_TO_IANA.items():
            assert timestamps.resolve_zone_key(iana) is not None, (
                f"{windows_name} maps to {iana}, which is not a zone"
            )
            timestamps.get_timezone_offset(when, iana)


class TestTheOfflineFallbackTable:
    """What is left when no tz database is installed at all.

    It answers US zones only, because `_is_us_dst` is a US schedule: applied
    to `Europe/London` it would be wrong twice a year, and wrong twice a year
    is indistinguishable from right once written.
    """

    @staticmethod
    def _without_a_database(monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(timestamps, "_zoneinfo_keys", dict)

    def test_us_zones_still_resolve(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self._without_a_database(monkeypatch)
        summer = datetime.datetime(2001, 7, 15, 12, 0, 0)
        winter = datetime.datetime(2001, 1, 15, 12, 0, 0)
        assert timestamps.get_timezone_offset(summer, "America/Chicago") == "-05:00"
        assert timestamps.get_timezone_offset(winter, "America/Chicago") == "-06:00"
        assert timestamps.get_timezone_offset(summer, "UTC") == "+00:00"

    def test_everything_else_is_refused_rather_than_answered_with_a_us_rule(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._without_a_database(monkeypatch)
        with pytest.raises(timestamps.UnknownTimezoneError):
            timestamps.get_timezone_offset(
                datetime.datetime(2001, 7, 15, 12, 0, 0), "Europe/London"
            )


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

    def test_day_precise_folder_date_populates_datetime_original(self) -> None:
        dt_target = datetime.datetime(2002, 7, 18, 14, 1, 34)
        ft_val = int((dt_target - datetime.datetime(1601, 1, 1)).total_seconds() * 10_000_000)

        resolved = timestamps.resolve_file_timestamps(
            import_ft=ft_val,
            scan_time_dt=None,
            primary_album="Fireworks 4th of July 1999",
        )
        assert resolved.datetime_digitized_exif == "2002:07:18 14:01:34"
        # Midnight, NOT the import batch's 14:01:34. The folder names a day;
        # nothing in the file names an hour, and borrowing one from an
        # unrelated transfer session would read as a capture moment.
        assert resolved.datetime_original_exif == "1999:07:04 00:00:00"
        assert resolved.date_source == "folder"
        assert resolved.date_precision == "day"
        assert resolved.offset_time_original == "-05:00"

    @pytest.mark.parametrize(
        ("album", "kind"),
        [
            ("Camping 2000", "year"),
            ("Vacation Trip 2001-02", "year_span"),
            ("Winter 1995 Skiing", "season"),
            ("Zoo Trip - Aug. 2000", "month"),
        ],
    )
    def test_coarse_folder_dates_never_reach_datetime_original(
        self, album: str, kind: str
    ) -> None:
        # 151 of the corpus's 687 files sit in albums like these. A year, a
        # span, a season or a month does not name the day the shutter fired,
        # and EXIF DateTimeOriginal has no way to say "sometime in 2001".
        dt_target = datetime.datetime(2001, 5, 9, 8, 30, 0)
        ft_val = int((dt_target - datetime.datetime(1601, 1, 1)).total_seconds() * 10_000_000)

        assert timestamps.parse_folder_date(album).date_kind == kind

        resolved = timestamps.resolve_file_timestamps(
            import_ft=ft_val, scan_time_dt=None, primary_album=album
        )
        assert resolved.datetime_original_exif is None
        assert resolved.offset_time_original is None
        assert resolved.date_source == "import-stamp"
        assert resolved.date_precision == "none"
        # ...but the folder range is still kept, so the file can be ordered
        # and the 0.6.0 gallery can offer it for review.
        assert resolved.folder_date is not None
        assert resolved.folder_precision in {"year", "season", "month"}
        assert resolved.sort_datetime is not None

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

        # 2. Fail: a December 1994 album imported in January 1995 (wrong year)
        res_fail_year = timestamps.evaluate_album_ground_truth(
            "Solstice Bonfire Dec 1994",
            [datetime.datetime(1995, 1, 5, 20, 0, 0)],
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
                {"sha256": "h2", "albums": ["Solstice Bonfire Dec 1994"]},
                {"sha256": "h3", "albums": ["Random Album"]},
            ]
        }
        timestamps_by_hash = {
            "h1": datetime.datetime(2001, 7, 5, 10, 0),
            "h2": datetime.datetime(1995, 1, 5, 10, 0),
            "h3": datetime.datetime(2001, 9, 1, 10, 0),
        }
        report = timestamps.check_manifest_ground_truth(manifest, timestamps_by_hash)
        assert report.total_albums == 3
        assert report.dated_albums == 2
        assert report.passed_albums == 1
        assert report.failed_albums == 1
        assert report.undated_albums == 1
        assert not report.ok  # has 1 failed album


class TestCoarseAlbumOverride:
    """`FPX_COARSE_ALBUMS`: a folder name that looks day-precise and is not.

    A holiday name resolves to a calendar day, but a folder named for one may
    hold the season around it -- the eve, the day after, the week either side.
    Nothing in the file says which, and only the person who made the folder
    knows. Where they say it is coarse, the name is demoted to its year.

    Invented album names throughout; `test_environment.py` enforces that.
    """

    @staticmethod
    def _with_coarse(monkeypatch, *albums: str) -> None:
        monkeypatch.setattr(
            timestamps, "_coarse_albums", lambda: frozenset(a.lower() for a in albums)
        )

    def test_a_declared_coarse_holiday_stops_naming_a_day(self, monkeypatch) -> None:
        self._with_coarse(monkeypatch, "christmas 1994")
        result = timestamps.parse_folder_date("Christmas 1994")
        assert result.parsed
        assert result.precision == "year"
        assert result.defensible_date is None, "a declared-coarse album still claimed a day"

    def test_it_still_sorts_and_files_under_its_year(self, monkeypatch) -> None:
        """Demotion takes away the claim, not the album.

        The folder is still evidence of *a* year -- it just is not evidence of
        a day. Losing the year too would move the photos out of the year
        folder they belong in.
        """
        self._with_coarse(monkeypatch, "christmas 1994")
        result = timestamps.parse_folder_date("Christmas 1994")
        assert result.year == 1994
        assert result.range_start == datetime.date(1994, 1, 1)

    def test_matching_ignores_case_and_surrounding_space(self, monkeypatch) -> None:
        self._with_coarse(monkeypatch, "christmas 1994")
        assert timestamps.parse_folder_date("  CHRISTMAS 1994 ").precision == "year"

    def test_an_album_not_listed_is_untouched(self, monkeypatch) -> None:
        self._with_coarse(monkeypatch, "christmas 1994")
        other = timestamps.parse_folder_date("Christmas 1995")
        assert other.precision == "day"
        assert other.defensible_date is not None

    def test_the_demotion_can_only_take_a_claim_away(self, monkeypatch) -> None:
        """One-way, deliberately.

        Listing an album must never make its date *more* precise than the
        parser found it -- that would be the fabrication this whole mechanism
        exists to prevent, arriving through the door meant to stop it.
        """
        self._with_coarse(monkeypatch, "summer 1994", "1994")
        season = timestamps.parse_folder_date("Summer 1994")
        assert season.defensible_date is None
        assert season.precision == "year"

        bare_year = timestamps.parse_folder_date("1994")
        assert bare_year.defensible_date is None

    def test_a_year_span_is_not_narrowed_to_its_first_year(self, monkeypatch) -> None:
        """The one case where demotion could ADD precision.

        `1994-95` covers two years. Rewriting it as "the year 1994" would be
        the fabrication this whole mechanism exists to prevent, arriving
        through the door meant to stop it. The demotion short-circuits on
        anything already at year precision, and a span is.
        """
        self._with_coarse(monkeypatch, "1994-95")
        before = timestamps._parse_folder_name("1994-95")
        after = timestamps.parse_folder_date("1994-95")
        assert after.date_kind == before.date_kind
        assert after.start_date == before.start_date
        assert after.end_date == before.end_date
        assert after.defensible_date is None

    def test_an_unparseable_name_is_not_invented_into_a_year(self, monkeypatch) -> None:
        self._with_coarse(monkeypatch, "no date here")
        result = timestamps.parse_folder_date("No Date Here")
        assert not result.parsed
        assert result.year is None
