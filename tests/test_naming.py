"""Tier-1: album derivation and filename selection. No filesystem, no photos."""

from __future__ import annotations

import pytest

from fpx_converter.naming import (
    SourceLocation,
    assign_store_names,
    is_camera_generated,
    is_human_authored,
    preferred_location,
    strip_fpx_suffix,
)


@pytest.mark.parametrize(
    ("filename", "expected"),
    [
        ("squirrel.fpx", "squirrel"),
        ("P0000016.FPX", "P0000016"),
        # Exactly one suffix comes off. Doubled extensions are real distinct
        # files in this corpus and must not collapse into their single-suffix
        # twin.
        ("DCP12345.fpx.fpx", "DCP12345.fpx"),
        ("no-extension", "no-extension"),
        ("a.tif", "a.tif"),
    ],
)
def test_strip_fpx_suffix(filename: str, expected: str) -> None:
    assert strip_fpx_suffix(filename) == expected


@pytest.mark.parametrize(
    "filename",
    # Only the forms this corpus actually contains. Every distinct filename
    # in the archive was checked: the camera-generated names are exclusively
    # DCP##### and P#######.
    ["DCP00280.fpx", "dcp00280.fpx", "DC00012.fpx", "P0000016.FPX", "P 42.fpx"],
)
def test_camera_generated_names(filename: str) -> None:
    assert is_camera_generated(filename)
    assert not is_human_authored(filename)


@pytest.mark.parametrize(
    "filename",
    [
        "squirrel.fpx",
        "harbor.fpx",
        "Clouds01.fpx",
        "the dog in a hat.fpx",
        "birthday-cake.fpx",
        # Prefixes from cameras this archive never saw are deliberately NOT
        # matched. Guessing wrong in this direction discards a caption
        # permanently, and guessing wrong the other way only leaves a
        # camera-ish name in place.
        "IMG_0042.fpx",
        "DSC00001.fpx",
        "PICT0003.fpx",
    ],
)
def test_human_authored_names(filename: str) -> None:
    assert is_human_authored(filename)
    assert not is_camera_generated(filename)


def test_doubled_extension_is_not_treated_as_camera_generated() -> None:
    """The stem is `DCP12345.fpx`, which is not bare-prefix-plus-digits."""
    assert not is_camera_generated("DCP12345.fpx.fpx")


class TestSourceLocation:
    def test_album_is_the_immediate_parent_directory(self) -> None:
        loc = SourceLocation(
            relpath="TreeTwo/import-app/Albums/Holiday/party hats.fpx",
            name="party hats.fpx",
        )
        assert loc.album == "Holiday"
        assert loc.tree == "TreeTwo"
        assert loc.parent_posix == "TreeTwo/import-app/Albums/Holiday"

    def test_nested_album_keeps_the_full_path(self) -> None:
        loc = SourceLocation(relpath="T/Albums/Sample/Burst/P0000016.FPX", name="P0000016.FPX")
        assert loc.album == "Burst"
        assert loc.parent_posix == "T/Albums/Sample/Burst"

    def test_file_at_the_root_has_no_album_or_tree(self) -> None:
        loc = SourceLocation(relpath="loose.fpx", name="loose.fpx")
        assert loc.album == ""
        assert loc.tree == ""


class TestPreferredLocation:
    def test_human_name_beats_camera_name(self) -> None:
        chosen = preferred_location(
            [
                SourceLocation(relpath="a/DCP00123.fpx", name="DCP00123.fpx"),
                SourceLocation(relpath="b/the dog in a hat.fpx", name="the dog in a hat.fpx"),
            ]
        )
        assert chosen.name == "the dog in a hat.fpx"

    def test_human_name_wins_regardless_of_ordering(self) -> None:
        """Traversal order must not decide which caption survives."""
        human = SourceLocation(relpath="z/party.fpx", name="party.fpx")
        camera = SourceLocation(relpath="a/DCP00123.fpx", name="DCP00123.fpx")
        assert preferred_location([human, camera]).name == "party.fpx"
        assert preferred_location([camera, human]).name == "party.fpx"

    def test_longer_human_name_wins(self) -> None:
        chosen = preferred_location(
            [
                SourceLocation(relpath="a/cake.fpx", name="cake.fpx"),
                SourceLocation(
                    relpath="b/birthday cake with candles.fpx",
                    name="birthday cake with candles.fpx",
                ),
            ]
        )
        assert chosen.name == "birthday cake with candles.fpx"

    def test_ties_break_on_relpath_for_determinism(self) -> None:
        chosen = preferred_location(
            [
                SourceLocation(relpath="z/same.fpx", name="same.fpx"),
                SourceLocation(relpath="a/same.fpx", name="same.fpx"),
            ]
        )
        assert chosen.relpath == "a/same.fpx"

    def test_empty_input_is_an_error(self) -> None:
        with pytest.raises(ValueError):
            preferred_location([])


class TestAssignStoreNames:
    def test_distinct_names_are_left_alone(self) -> None:
        names = assign_store_names([("aa" * 32, "squirrel.fpx"), ("bb" * 32, "harbor.fpx")])
        assert set(names.values()) == {"squirrel.fpx", "harbor.fpx"}

    def test_same_name_different_hash_gets_a_suffix(self) -> None:
        """Kodak cameras reset their numbering; one such collision in this
        corpus is a genuinely different photo, so neither may overwrite the
        other."""
        sha_a, sha_b = "aa" * 32, "bb" * 32
        names = assign_store_names([(sha_a, "DCP00280.fpx"), (sha_b, "DCP00280.fpx")])
        assert names[sha_a] == "DCP00280.fpx"
        assert names[sha_b] == f"DCP00280_{sha_b[:8]}.fpx"
        assert len(set(names.values())) == 2

    def test_assignment_does_not_depend_on_input_order(self) -> None:
        pairs = [("cc" * 32, "x.fpx"), ("aa" * 32, "x.fpx"), ("bb" * 32, "x.fpx")]
        assert assign_store_names(pairs) == assign_store_names(list(reversed(pairs)))

    def test_collisions_are_case_insensitive(self) -> None:
        """The store lives on Windows, where `X.fpx` and `x.fpx` are one file."""
        sha_a, sha_b = "aa" * 32, "bb" * 32
        names = assign_store_names([(sha_a, "Photo.fpx"), (sha_b, "photo.fpx")])
        assert len({n.lower() for n in names.values()}) == 2

    def test_doubled_extension_keeps_its_inner_suffix(self) -> None:
        names = assign_store_names([("aa" * 32, "DCP12345.fpx.fpx")])
        assert names["aa" * 32] == "DCP12345.fpx.fpx"

    def test_a_suffixed_name_that_is_itself_taken_still_resolves(self) -> None:
        """A single fallback is not enough.

        If a source file is literally named `<stem>_<8 hex>.fpx`, it claims
        the suffixed name first, and a one-shot fallback would hand the same
        name to a second hash -- which ingest would then silently overwrite.
        The contract is *never*, so the suffix widens until it is free.
        """
        taken_name, other, colliding = "aa" + "0" * 62, "aa11" + "0" * 60, "bbbbbbbb" + "0" * 56
        names = assign_store_names(
            [
                (taken_name, "photo_bbbbbbbb.fpx"),
                (other, "photo.fpx"),
                (colliding, "photo.fpx"),
            ]
        )
        assert len(set(names.values())) == 3, names

    def test_store_names_are_globally_unique_under_stress(self) -> None:
        """Whatever the inputs, two distinct hashes never share a name."""
        pairs = []
        for i in range(50):
            pairs.append((f"{i:064x}", "photo.fpx"))
            pairs.append((f"{i + 500:064x}", f"photo_{i:08x}.fpx"))
        names = assign_store_names(pairs)
        assert len(names) == len(pairs)
        lowered = [n.lower() for n in names.values()]
        assert len(set(lowered)) == len(lowered)
