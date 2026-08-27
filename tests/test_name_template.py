"""Tier-1: the filename and folder patterns.

Two rules here are the point, and both come straight from the project's
binding rules rather than from taste.

**A pattern cannot drop `{name}`.** Filenames are the only human-authored
content in this archive. Unlike a wrong date, a lost one cannot be recovered
by re-reading the source.

**A pattern cannot manufacture a date component.** There is no capture date in
this corpus; unknown components stay zeroed, in a custom pattern exactly as in
the shipped one.

Every filename and album in this file is invented.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from fpx_converter import layout, name_template, writer

DATED = {"datetime_original_exif": "2002:07:04 14:32:10"}
YEAR_ONLY = {"folder_date": "2001-01-01", "folder_precision": "year"}
NOTHING: dict[str, str] = {}


def _render(template: str, ts: dict, name: str = "Backyard", album: str = "Album") -> str:
    return name_template.render(template, ts_dict=ts, name=name, album=album)


class TestTheShippedPatternIsWhatItAlwaysWas:
    def test_the_default_reproduces_the_old_prefix_exactly(self) -> None:
        """Not "close enough" -- the same string, so nothing is renamed by
        adding the feature."""
        for ts in (DATED, YEAR_ONLY, NOTHING):
            prefix, _ = writer.format_date_prefix(ts)
            assert _render(name_template.DEFAULT_TEMPLATE, ts) == f"{prefix}_Backyard"

    def test_an_unknown_component_is_zeroed_and_not_guessed(self) -> None:
        assert _render("{year}-{month}-{day}_{name}", YEAR_ONLY) == "2001-00-00_Backyard"
        assert _render("{year}-{month}-{day}_{name}", NOTHING) == "0000-00-00_Backyard"

    def test_the_fields_carry_the_parts_of_the_same_date(self) -> None:
        assert _render("{year}", DATED, name="x") + "!" == "2002!"
        assert _render("{day}-{month}-{year}_{name}", DATED) == "04-07-2002_Backyard"
        assert _render("{date} {time} {name}", DATED) == "2002-07-04 143210 Backyard"

    def test_the_album_is_available_and_the_name_can_repeat(self) -> None:
        assert _render("{album} {name} {name}", NOTHING, album="Trip") == "Trip Backyard Backyard"


class TestWhatAPatternIsRefused:
    def test_a_pattern_without_the_name_is_refused(self) -> None:
        """The one rule that exists to prevent permanent loss."""
        with pytest.raises(name_template.TemplateError) as caught:
            name_template.validate("{year}-{month}-{day}_{time}")
        assert "{name}" in str(caught.value)

    @pytest.mark.parametrize("template", ["", "   ", "{nope}{name}", "{name}{", "}{name}"])
    def test_an_unusable_pattern_is_refused(self, template: str) -> None:
        with pytest.raises(name_template.TemplateError):
            name_template.validate(template)

    @pytest.mark.parametrize("bad", list('<>:"/\\|?*'))
    def test_a_character_no_filename_can_hold_is_refused(self, bad: str) -> None:
        with pytest.raises(name_template.TemplateError):
            name_template.validate("{name}" + bad + "x")

    def test_the_shipped_pattern_passes(self) -> None:
        name_template.validate(name_template.DEFAULT_TEMPLATE)


class TestWhatRenderingProtectsAgainst:
    def test_a_reserved_device_name_does_not_come_out_bare(self) -> None:
        """`CON.tif` cannot be created on Windows, and the shipped pattern
        never produced one because it always began with a date. A pattern of
        just `{name}` can, and the archive is full of names nobody vetted."""
        assert _render("{name}", NOTHING, name="CON") != "CON"
        assert _render("{name}", NOTHING, name="con") != "con"
        assert _render("{name}", NOTHING, name="Contents") == "Contents"

    def test_a_value_from_the_archive_cannot_smuggle_in_a_separator(self) -> None:
        """The pattern is checked; the substituted values are cleaned. An
        album named `Trip 1/2` must not become two folders."""
        assert "/" not in _render("{album}_{name}", NOTHING, album="Trip 1/2")
        assert "\\" not in _render("{album}_{name}", NOTHING, album="a\\b")

    def test_a_trailing_dot_or_space_is_dropped(self) -> None:
        """Windows drops them silently, which would merge two distinct names."""
        assert _render("{name} ", NOTHING, name="a") == "a"
        assert _render("{name}.", NOTHING, name="a") == "a"


class TestTheFolderPattern:
    def test_the_named_schemes_all_produce_something(self) -> None:
        entry = {"albums": ["Summer 2002"], "preferred_name": "Backyard.fpx"}
        derived = {"timestamps": {"sort_datetime": "2002-07-04T14:32:10"}}
        seen = {
            scheme: layout.output_folder(entry, derived, scheme).as_posix()
            for scheme, _, _ in layout.FOLDER_SCHEMES
        }
        assert seen[layout.BY_ALBUM] == "2002/Summer 2002"
        assert seen[layout.BY_YEAR] == "2002"
        assert seen[layout.BY_YEAR_MONTH] == "2002/2002 July"
        assert seen[layout.FLAT] == "."
        assert seen[layout.CUSTOM] == "2002/Summer 2002"

    def test_year_month_never_invents_a_january(self) -> None:
        """An album naming only a year files under the year, with no month
        level at all. Returning a datetime forced a month, and every such file
        landed in January -- which reads as evidence rather than the absence
        of it."""
        entry = {"albums": ["Summer 2002"], "preferred_name": "x.fpx"}
        # An import stamp from a different year cannot lend its month.
        derived = {"timestamps": {"sort_datetime": "2003-01-09T10:00:00"}}
        assert layout.output_folder(entry, derived, layout.BY_YEAR_MONTH) == Path("2002")

    def test_the_stamp_lends_its_month_only_when_it_agrees_about_the_year(self) -> None:
        entry = {"albums": ["Summer 2002"], "preferred_name": "x.fpx"}
        derived = {"timestamps": {"sort_datetime": "2002-09-01T10:00:00"}}
        assert (
            layout.output_folder(entry, derived, layout.BY_YEAR_MONTH).as_posix()
            == "2002/2002 September"
        )

    def test_nothing_datable_lands_in_the_undated_folder(self) -> None:
        entry = {"albums": ["Pictures"], "preferred_name": "x.fpx"}
        for scheme in (layout.BY_YEAR, layout.BY_YEAR_MONTH):
            assert layout.output_folder(entry, {"timestamps": {}}, scheme) == Path(
                layout.UNDATED_FOLDER
            )

    def test_a_custom_pattern_makes_one_level_per_slash(self) -> None:
        entry = {"albums": ["Summer 2002"], "preferred_name": "x.fpx"}
        # `sort_datetime` is set from the best date available, so a file with a
        # defensible capture date always carries one -- see `timestamps`.
        derived = {"timestamps": {"sort_datetime": "2002-07-04T14:32:10"}}
        folder = layout.output_folder(entry, derived, layout.CUSTOM, "{year}/{month}/{album}")
        assert folder.as_posix() == "2002/07/Summer 2002"

    def test_a_folder_pattern_uses_the_filing_date_not_the_claimable_one(self) -> None:
        """`{year}` in a folder must mean what `By year` means.

        The first cut reused the filename's fields, and `{year}/{album}` then
        filed almost everything under `0000/` while the `By year` scheme -- the
        same word -- correctly said `2002/`. A folder is a browsing affordance
        and may use an album name; a filename's date prefix tracks what can be
        claimed.
        """
        entry = {"albums": ["Summer 2002"], "preferred_name": "x.fpx"}
        derived = {"timestamps": {}}
        assert (
            layout.output_folder(entry, derived, layout.CUSTOM, "{year}/{album}").as_posix()
            == "2002/Summer 2002"
        )
        assert layout.output_folder(entry, derived, layout.BY_YEAR).as_posix() == "2002"
        # And the filename, asked the same question, still refuses to claim it.
        assert _render("{year}_{name}", derived["timestamps"]) == "0000_Backyard"

    @pytest.mark.parametrize("field", ["day", "time", "date", "name"])
    def test_a_filename_only_field_is_refused_in_a_folder(self, field: str) -> None:
        """With a message that says where it does belong."""
        with pytest.raises(name_template.TemplateError) as caught:
            layout.validate_folder_template("{" + field + "}/{album}")
        assert "filename pattern" in str(caught.value)

    def test_a_pattern_that_would_walk_upwards_is_refused(self) -> None:
        """It could put converted images anywhere on the disk, the read-only
        source archive included, and that is the one mistake this project
        cannot undo."""
        for bad in ("../{album}", "{year}/../..", "..", "/{album}"):
            with pytest.raises(name_template.TemplateError):
                layout.validate_folder_template(bad)

    def test_an_empty_folder_pattern_is_refused_rather_than_silently_flat(self) -> None:
        with pytest.raises(name_template.TemplateError):
            layout.validate_folder_template("   ")

    def test_a_folder_pattern_does_not_have_to_carry_the_name(self) -> None:
        """That rule is about filenames. Requiring it here would reject every
        sensible folder pattern there is."""
        layout.validate_folder_template("{year}/{album}")
        layout.validate_folder_template(layout.DEFAULT_FOLDER_TEMPLATE)

    def test_every_scheme_but_album_shares_one_naming_bucket(self) -> None:
        """Names are assigned from the manifest alone, before any metadata is
        read, so no other scheme can predict where a file will land. Sharing a
        bucket is stricter than the truth and stricter is the safe direction:
        an unnecessary hash suffix against silently overwriting a photograph.
        """
        a = {"albums": ["Summer 2002"], "preferred_name": "x.fpx"}
        b = {"albums": ["Winter 2003"], "preferred_name": "x.fpx"}
        assert layout.stem_scope(a, layout.BY_ALBUM) != layout.stem_scope(b, layout.BY_ALBUM)
        for scheme in (layout.BY_YEAR, layout.BY_YEAR_MONTH, layout.FLAT, layout.CUSTOM):
            assert layout.stem_scope(a, scheme) == layout.stem_scope(b, scheme)
