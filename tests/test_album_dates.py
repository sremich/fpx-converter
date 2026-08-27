"""Tier-1: dates a person supplied after looking at the photographs.

This is the only route by which a capture date enters this archive from
outside the files, so it is also the only route by which a *wrong* one can.
Most of these tests are about refusing things.

Invented album names throughout; `test_environment.py` enforces that.
"""

from __future__ import annotations

import datetime
import json
from pathlib import Path

import pytest

from fpx_converter import album_dates


class TestParsing:
    def test_a_single_day_is_accepted(self) -> None:
        parsed = album_dates.parse({"album dates": {"Winterfest 1994": "1994-12-17"}})
        assert parsed.for_album("Winterfest 1994") == datetime.date(1994, 12, 17)

    def test_album_lookup_ignores_case_and_space(self) -> None:
        parsed = album_dates.parse({"album dates": {"Winterfest 1994": "1994-12-17"}})
        assert parsed.for_album("  WINTERFEST 1994 ") == datetime.date(1994, 12, 17)

    def test_an_unlisted_album_has_no_date(self) -> None:
        parsed = album_dates.parse({"album dates": {"Winterfest 1994": "1994-12-17"}})
        assert parsed.for_album("Solstice Bonfire 1995") is None

    def test_the_underscore_spelling_is_also_read(self) -> None:
        """The gallery writes `album dates`; a person editing by hand may not."""
        parsed = album_dates.parse({"album_dates": {"Winterfest 1994": "1994-12-17"}})
        assert parsed.for_album("Winterfest 1994") == datetime.date(1994, 12, 17)

    def test_notes_are_carried_but_are_not_dates(self) -> None:
        parsed = album_dates.parse(
            {
                "album dates": {"Winterfest 1994": "1994-12-17"},
                "notes": {"Winterfest 1994": "the day of the storm"},
            }
        )
        assert parsed.note_for("Winterfest 1994") == "the day of the storm"

    def test_an_empty_file_is_falsy_and_harmless(self) -> None:
        assert not album_dates.parse({"album dates": {}})


class TestRefusals:
    """A partial date is worse than no date, and both are worse than a typo
    that gets written into an archive and later read as evidence."""

    @pytest.mark.parametrize("value", ["1994-12", "1994", "December 1994", "winter 1994"])
    def test_anything_coarser_than_a_day_is_refused(self, value: str) -> None:
        """EXIF has no month-only or year-only capture date.

        Rounding a month to its first day is exactly the fabrication this
        project exists to avoid: it once gave 151 files a capture moment
        precise to the second that no evidence supported.
        """
        with pytest.raises(album_dates.AlbumDateError, match="single day"):
            album_dates.parse({"album dates": {"Winterfest 1994": value}})

    @pytest.mark.parametrize("value", ["1994-13-01", "1994-02-30", "not a date", ""])
    def test_an_impossible_date_is_refused(self, value: str) -> None:
        with pytest.raises(album_dates.AlbumDateError):
            album_dates.parse({"album dates": {"Winterfest 1994": value}})

    def test_a_date_before_photography_is_refused(self) -> None:
        """A typo written into an archive is indistinguishable from evidence."""
        with pytest.raises(album_dates.AlbumDateError, match="plausible"):
            album_dates.parse({"album dates": {"Winterfest 1994": "0194-12-17"}})

    def test_a_date_in_the_future_is_refused(self) -> None:
        future = datetime.date.today() + datetime.timedelta(days=2)
        with pytest.raises(album_dates.AlbumDateError, match="plausible"):
            album_dates.parse({"album dates": {"Winterfest 1994": future.isoformat()}})

    def test_a_non_string_date_is_refused(self) -> None:
        with pytest.raises(album_dates.AlbumDateError):
            album_dates.parse({"album dates": {"Winterfest 1994": 19941217}})

    def test_the_wrong_shape_of_document_is_refused(self) -> None:
        with pytest.raises(album_dates.AlbumDateError):
            album_dates.parse(["1994-12-17"])
        with pytest.raises(album_dates.AlbumDateError):
            album_dates.parse({"album dates": ["1994-12-17"]})


class TestLoading:
    def test_a_missing_file_is_the_normal_state(self, tmp_path: Path) -> None:
        assert not album_dates.load(tmp_path / "nope.json")
        assert not album_dates.load(None)

    def test_a_malformed_file_is_refused_loudly_not_ignored(self, tmp_path: Path) -> None:
        """Somebody wrote this file down deliberately.

        Skipping it silently would lose exactly the evidence it carries, and
        the run would report success with every album still undated.
        """
        path = tmp_path / album_dates.DEFAULT_FILENAME
        path.write_text('{"album dates": {', encoding="utf-8")
        with pytest.raises(album_dates.AlbumDateError, match="not valid JSON"):
            album_dates.load(path)

    def test_it_round_trips_through_the_file(self, tmp_path: Path) -> None:
        original = album_dates.parse(
            {
                "album dates": {"Winterfest 1994": "1994-12-17"},
                "notes": {"Winterfest 1994": "the day of the storm"},
            }
        )
        path = tmp_path / album_dates.DEFAULT_FILENAME
        path.write_text(album_dates.dump(original), encoding="utf-8")
        assert album_dates.load(path) == original

    def test_the_dump_is_what_the_gallery_produces(self, tmp_path: Path) -> None:
        """Same key spelling, so a page's output can be saved straight to disk."""
        payload = json.loads(
            album_dates.dump(album_dates.parse({"album dates": {"A Day Out 1994": "1994-06-01"}}))
        )
        assert "album dates" in payload
        assert payload["album dates"]["a day out 1994"] == "1994-06-01"
