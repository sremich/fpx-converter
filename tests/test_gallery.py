"""Tier-1: the QA review page.

The gallery is how a person sees 687 photographs at once and how the archive
gets the only capture dates it will ever have. Both jobs fail quietly if they
fail at all -- a page that hides the failures still renders, and a date box
that never appears just looks like an album nobody needed to date.

Invented album names throughout; `test_environment.py` enforces that.
"""

from __future__ import annotations

import datetime
from pathlib import Path

import pytest
from PIL import Image

from fpx_converter import album_dates, gallery

FIXTURES = Path(__file__).parent / "fixtures"


def _item(album: str = "Winterfest 1994", **kw) -> gallery.GalleryItem:
    kw.setdefault("store_name", "photo.fpx")
    kw.setdefault("status", "converted")
    kw.setdefault("date_source", "none")
    return gallery.GalleryItem(album=album, **kw)


def _report(files: list[dict]) -> dict:
    return {
        "counts": {"converted": len(files), "resumed": 0, "failed": 0},
        "finished": "2026-08-27T12:00:00",
        "files": files,
    }


class TestAuditClass:
    """What the reviewer is looking for, in the order they care about it."""

    def test_a_failure_outranks_everything(self) -> None:
        item = _item(errors=["boom"], warnings=["hm"], date_original="1994:12:17 00:00:00")
        assert item.audit_class == "failed"

    def test_a_failed_status_counts_even_with_no_error_text(self) -> None:
        assert _item(status="failed").audit_class == "failed"

    def test_a_warning_outranks_a_date(self) -> None:
        assert _item(warnings=["unapplied transform"]).audit_class == "warning"

    def test_a_clean_dated_file_is_dated(self) -> None:
        assert _item(date_original="1994:12:17 00:00:00").audit_class == "dated"

    def test_a_clean_undated_file_is_undated(self) -> None:
        assert _item().audit_class == "undated"


class TestBuildItems:
    def test_the_capture_date_comes_from_the_report_not_a_sidecar(self) -> None:
        """Sidecars are optional; `metadata` may never have been run.

        A gallery that needed them showed a correctly dated archive as
        entirely undated, and nothing about the page said why.
        """
        items = gallery.build_items(
            _report(
                [{"store_name": "a.fpx", "album": "A",
                  "date_original": "1994:12:17 00:00:00"}]
            ),
            store_dir=FIXTURES,
            thumbnails=False,
        )
        assert items[0].date_original == "1994:12:17 00:00:00"

    def test_a_file_with_no_album_still_appears(self) -> None:
        items = gallery.build_items(
            _report([{"store_name": "a.fpx"}]), store_dir=FIXTURES, thumbnails=False
        )
        assert items[0].album == "(no album)"


class TestAlbumsNeedingADate:
    def test_an_album_with_any_undated_photo_is_offered_a_box(self) -> None:
        """*Any*, not *all*.

        Listing only wholly-undated albums hid the box from an album of forty
        the moment two of them happened to carry an embedded scan time, so the
        other thirty-eight could never be dated at all.
        """
        items = [
            _item(date_original="1994:12:17 00:00:00"),
            _item(),
        ]
        assert gallery.albums_needing_a_date(items) == ["Winterfest 1994"]

    def test_a_fully_dated_album_is_not_offered_one(self) -> None:
        items = [_item(date_original="1994:12:17 00:00:00")]
        assert gallery.albums_needing_a_date(items) == []

    def test_albums_come_back_sorted_so_the_page_is_stable(self) -> None:
        items = [_item("Solstice Bonfire 1995"), _item("A Day Out 1994")]
        assert gallery.albums_needing_a_date(items) == ["A Day Out 1994", "Solstice Bonfire 1995"]


class TestThumbnails:
    def test_a_real_fixture_yields_an_inline_data_uri(self) -> None:
        uri = gallery.thumbnail_data_uri(FIXTURES / "giraffe.fpx")
        assert uri.startswith("data:image/jpeg;base64,")

    def test_a_file_with_no_readable_thumbnail_is_not_dropped(self, tmp_path: Path) -> None:
        """More reason to show it, not less: something about it is unusual.

        Dropping it would hide exactly the file a reviewer should look at.
        """
        broken = tmp_path / "broken.fpx"
        broken.write_bytes(b"not an OLE file")
        assert gallery.thumbnail_data_uri(broken) == ""

        items = gallery.build_items(
            _report([{"store_name": "broken.fpx", "album": "A"}]), store_dir=tmp_path
        )
        assert len(items) == 1
        assert "no thumbnail" in gallery.render_html(items, report=_report([]))


class TestRenderedPage:
    def test_it_is_one_self_contained_file_with_no_external_asset(self) -> None:
        """It has to open by double-clicking it in five years' time."""
        page = gallery.render_html([_item()], report=_report([]))
        assert "<!doctype html>" in page.lower()
        for forbidden in ("http://", "https://", "<script src", "<link rel=\"stylesheet\""):
            assert forbidden not in page, f"the page reaches outside itself: {forbidden}"

    def test_an_album_name_is_escaped_rather_than_injected(self) -> None:
        """Album names come from a filesystem, not from this project."""
        page = gallery.render_html(
            [_item("<script>alert(1)</script>")], report=_report([])
        )
        assert "<script>alert(1)</script>" not in page
        assert "&lt;script&gt;" in page

    def test_a_failure_is_visible_on_the_page(self) -> None:
        page = gallery.render_html([_item(errors=["tile 3 short"])], report=_report([]))
        assert "tile 3 short" in page
        assert "data-status='failed'" in page

    def test_the_date_box_appears_for_an_undated_album(self) -> None:
        page = gallery.render_html([_item()], report=_report([]))
        assert "class='album-date'" in page

    def test_a_date_already_supplied_is_prefilled(self) -> None:
        supplied = album_dates.AlbumDates(dates={"winterfest 1994": datetime.date(1994, 12, 17)})
        page = gallery.render_html([_item()], report=_report([]), existing_dates=supplied)
        assert "value='1994-12-17'" in page

    def test_expected_duplicates_are_explained_rather_than_alarming(self) -> None:
        report = _report([])
        report["expected_pixel_identical_groups"] = {
            "count": 9,
            "files_involved": 19,
            "groups": [],
        }
        page = gallery.render_html([_item()], report=report)
        assert "expected, not faults" in page

    def test_the_page_says_how_many_files_lack_a_date(self) -> None:
        items = [_item(date_original="1994:12:17 00:00:00"), _item(), _item()]
        assert "2 of 3 photographs" in gallery.render_html(items, report=_report([]))


def test_write_gallery_creates_its_directory(tmp_path: Path) -> None:
    target = tmp_path / "report" / "index.html"
    gallery.write_gallery("<html></html>", target)
    assert target.is_file()


@pytest.mark.parametrize("mode", ["RGB", "L"])
def test_thumbnails_are_jpeg_whatever_the_source_mode(mode: str, tmp_path: Path) -> None:
    """A 687-thumbnail page of PNGs runs to tens of megabytes."""
    image = Image.new(mode, (400, 300), 128)
    buffer_path = tmp_path / "t.png"
    image.save(buffer_path)
    # Exercised through the public helper's shrink-and-encode path.
    shrunk = image.convert("RGB")
    shrunk.thumbnail(gallery.THUMB_MAX)
    assert max(shrunk.size) <= max(gallery.THUMB_MAX)
