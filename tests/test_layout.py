"""Tier-1 tests for the output tree layout.

The owner's rule: a descriptive source folder keeps its name whatever date the
photo carries, nested under the year if the name gives one and sitting at the
top if it does not; a folder whose name says nothing is replaced by
year-and-month. Invented album names throughout -- no real one may appear in a
committed file, and `test_environment.py` enforces that against the manifest.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from fpx_converter import layout


def _entry(*albums: str) -> dict:
    return {"albums": list(albums), "preferred_name": "photo.fpx"}


def _derived(import_iso: str | None = None, sort_iso: str | None = None) -> dict:
    ts: dict = {}
    if import_iso:
        ts["import_datetime"] = import_iso
    if sort_iso:
        ts["sort_datetime"] = sort_iso
    return {"timestamps": ts}


class TestDescriptiveness:
    @pytest.mark.parametrize(
        "name", ["Solstice Bonfire 1994", "Rosalind", "kestrel", "Left Shelf", "Thicket", "1998"]
    )
    def test_a_name_somebody_typed_is_descriptive(self, name: str) -> None:
        assert layout.is_descriptive(name)

    @pytest.mark.parametrize(
        "name", ["NewZIP", "newzip", "  Stuff  ", "Untitled", "New Folder", ""]
    )
    def test_a_tool_generated_name_is_not(self, name: str) -> None:
        assert not layout.is_descriptive(name)

    def test_a_bare_sequence_number_is_not_descriptive_but_a_year_is(self) -> None:
        assert not layout.is_descriptive("001")
        assert not layout.is_descriptive("42")
        # A year describes something, and it lands as its own year folder.
        assert layout.is_descriptive("1998")
        assert layout.is_descriptive("2002")


class TestAlbumChoice:
    def test_the_descriptive_album_beats_the_dump_it_was_also_copied_into(self) -> None:
        """The 52-photo defect, in miniature.

        Taking the first listed album filed 52 photos of one Christmas under a
        folder named after a zip file -- and because the date comes from the
        album, it cost them a day-precise capture date too.
        """
        entry = _entry("NewZIP", "Solstice Bonfire Dec 1994")
        assert layout.choose_album(entry) == "Solstice Bonfire Dec 1994"

    def test_a_dated_album_beats_an_undated_one(self) -> None:
        assert layout.choose_album(_entry("Rosalind", "Winterfest 1994")) == "Winterfest 1994"

    def test_order_does_not_matter(self) -> None:
        albums = ["NewZIP", "Rosalind", "Winterfest 1994"]
        assert layout.choose_album(_entry(*albums)) == layout.choose_album(_entry(*albums[::-1]))

    def test_a_file_with_no_album_is_not_a_crash(self) -> None:
        assert layout.choose_album({"albums": []}) == "Root"
        assert layout.choose_album({}) == "Root"

    def test_all_non_descriptive_still_returns_one(self) -> None:
        assert layout.choose_album(_entry("NewZIP", "stuff")) in {"NewZIP", "stuff"}


class TestOutputFolder:
    def test_a_dated_album_is_nested_under_its_year(self) -> None:
        folder = layout.output_folder(_entry("Winterfest 1994"), _derived())
        assert folder == Path("1994") / "Winterfest 1994"

    def test_an_undated_album_sits_beside_the_year_folders(self) -> None:
        assert layout.output_folder(_entry("Rosalind"), _derived()) == Path("Rosalind")

    def test_a_dated_album_keeps_its_name_regardless_of_the_photo_date(self) -> None:
        """The owner's rule, stated exactly: the folder wins over the date.

        A photo imported in 1998 that sits in a folder naming 1994 goes under
        1994, because somebody wrote that folder name and nobody wrote the
        import stamp.
        """
        folder = layout.output_folder(
            _entry("Winterfest 1994"), _derived(import_iso="1998-03-02T11:00:00")
        )
        assert folder == Path("1994") / "Winterfest 1994"

    def test_a_meaningless_folder_becomes_year_and_month(self) -> None:
        folder = layout.output_folder(_entry("NewZIP"), _derived(import_iso="2001-12-24T18:30:00"))
        assert folder == Path("2001") / "2001 December"

    def test_year_and_month_prefers_a_folder_date_over_the_import_stamp(self) -> None:
        # `sort_datetime` carries a coarse folder date where one exists. It is
        # weak evidence, but it beats the import stamp, which on this corpus
        # misses the event by up to 223 days.
        folder = layout.output_folder(
            _entry("NewZIP"),
            _derived(import_iso="2002-01-05T20:07:03", sort_iso="2001-12-25T00:00:00"),
        )
        assert folder == Path("2001") / "2001 December"

    def test_no_date_at_all_is_named_as_such(self) -> None:
        folder = layout.output_folder(_entry("NewZIP"), _derived())
        assert folder == Path(layout.UNDATED_FOLDER)

    def test_an_unparseable_stored_date_does_not_crash_the_run(self) -> None:
        folder = layout.output_folder(_entry("NewZIP"), {"timestamps": {"import_datetime": "n/a"}})
        assert folder == Path(layout.UNDATED_FOLDER)

    @pytest.mark.parametrize(
        ("month", "name"),
        [(1, "1999 January"), (6, "1999 June"), (12, "1999 December")],
    )
    def test_month_names_are_spelled_out(self, month: int, name: str) -> None:
        folder = layout.output_folder(
            _entry("NewZIP"), _derived(import_iso=f"1999-{month:02d}-15T00:00:00")
        )
        assert folder == Path("1999") / name


class TestStemScope:
    def test_descriptive_albums_get_their_own_namespace(self) -> None:
        assert layout.stem_scope(_entry("Rosalind")) == "Rosalind"

    def test_year_month_files_share_one_namespace(self) -> None:
        """Stricter than the truth, and deliberately so.

        Which month these land in depends on the import stamp, and names are
        assigned from the manifest alone so a resumed run picks the same ones.
        Sharing a bucket can only cost an unnecessary hash suffix; not sharing
        one could let two photos resolve to the same path.
        """
        assert layout.stem_scope(_entry("NewZIP")) == layout.stem_scope(_entry("stuff"))
        assert layout.stem_scope(_entry("NewZIP")) != "NewZIP"

    def test_the_shared_scope_cannot_collide_with_a_real_album(self) -> None:
        # A NUL cannot occur in a Windows or POSIX path component.
        assert "\x00" in layout.YEAR_MONTH_SCOPE
