"""The path check has to leave room for the file ExifTool actually writes.

ExifTool does not edit in place. It writes `<path>_exiftool_tmp` beside the
target and renames it over the original, so a destination that fits the
259-character ceiling by twelve characters does not fit once ExifTool is the
one asking. That window -- final paths of 247 to 259 characters -- passed the
guard and then failed inside ExifTool with `Error creating file`, a message
naming neither the path nor the length, and arriving *after* the TIFF and the
JPEG had already been written and tagged as far as the save.

So the tests here are about the thirteen characters, and about the guard
firing early enough that nothing has been written when it does.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from fpx_converter import writer

FIXTURES = Path(__file__).parent / "fixtures"
FIXTURE = FIXTURES / "Clouds01.fpx"


def _entry() -> dict[str, object]:
    return {
        "store_name": FIXTURE.name,
        "preferred_name": FIXTURE.name,
        "sha256": "0" * 64,
        "albums": ["Sample"],
        "preferred_relpath": FIXTURE.name,
    }


def _write(output_root: Path, **kwargs: object):
    return writer.write_single_entry_dual_output(
        fpx_path=FIXTURE,
        entry=_entry(),
        output_root=output_root,
        source_root=FIXTURES.parent,
        stem="x",
        claimed=set(),
        **kwargs,
    )


def _root_producing_length(tmp_path: Path, wanted: int) -> Path:
    """A destination whose longest output path is exactly `wanted` characters.

    Measured rather than guessed: one no-limit dry run says how long the tree
    comes out for a known root, and the difference is padding on a single
    directory name. Computing it by hand would encode today's folder scheme
    into a test that is not about the folder scheme.
    """
    probe_root = tmp_path / "probe"
    probe = _write(probe_root, max_path=writer.NO_PATH_LIMIT, dry_run=True)
    natural = max(len(str(probe.tif_path)), len(str(probe.jpg_path)))
    padding = wanted - natural + len(probe_root.name)
    assert padding > 0, f"tmp_path is already {natural} characters; no room to aim at {wanted}"
    return tmp_path / ("p" * padding)


class TestTheReserveIsDerivedFromTheSuffix:
    """A typed 13 and a renamed suffix drift apart silently."""

    def test_the_reserve_is_the_length_of_the_suffix(self) -> None:
        assert writer.EXIFTOOL_TMP_SUFFIX == "_exiftool_tmp"
        assert writer.EXIFTOOL_TMP_RESERVE == len(writer.EXIFTOOL_TMP_SUFFIX) == 13

    def test_the_windows_ceiling_loses_exactly_the_reserve(self) -> None:
        assert writer.path_budget(writer.WINDOWS_MAX_PATH) == writer.WINDOWS_MAX_PATH - 13
        assert writer.path_budget(writer.WINDOWS_MAX_PATH) == 246

    def test_no_ceiling_reserves_nothing(self) -> None:
        """`--max-path 0` turns the check off; it does not turn it into -13."""
        assert writer.path_budget(writer.NO_PATH_LIMIT) == writer.NO_PATH_LIMIT

    def test_an_explicit_ceiling_still_pays_the_reserve(self) -> None:
        """`--max-path` sets the ceiling. ExifTool's temp file is not negotiable."""
        assert writer.path_budget(400) == 387


@pytest.mark.parametrize("length", [247, 253, 259])
def test_a_path_inside_the_exiftool_window_is_refused_before_exiftool_runs(
    tmp_path: Path, length: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    """247 to 259: under the ceiling, over it once the suffix is added."""

    def _no_exiftool(*_a: object, **_k: object):
        raise AssertionError("ExifTool was invoked; the path guard let the write start")

    def _no_saving(*_a: object, **_k: object):
        raise AssertionError("images were saved; the path guard fired too late")

    output_root = _root_producing_length(tmp_path, length)
    monkeypatch.setattr(writer.subprocess, "run", _no_exiftool)
    monkeypatch.setattr(writer, "save_output_images", _no_saving)

    result = _write(output_root, max_path=writer.WINDOWS_MAX_PATH)

    assert not result.validation_ok
    assert result.errors
    message = " ".join(result.errors)
    assert str(length) in message, message
    # It has to name the real cause. "over the 259 Windows allows" was true of
    # the ceiling and false of this file, which is under it.
    assert "exiftool" in message.lower(), message
    assert writer.EXIFTOOL_TMP_SUFFIX in message, message
    assert str(writer.path_budget(writer.WINDOWS_MAX_PATH)) in message, message
    assert "--dest" in message, message
    assert not any(output_root.rglob("*.tif")), "an image was written despite the refusal"


def test_a_path_that_fits_with_the_suffix_is_still_allowed(tmp_path: Path) -> None:
    """The reserve tightens the ceiling; it must not close it.

    Without this the previous test passes just as well against a guard that
    refuses everything.
    """
    budget = writer.path_budget(writer.WINDOWS_MAX_PATH)
    output_root = _root_producing_length(tmp_path, budget)
    result = _write(output_root, max_path=writer.WINDOWS_MAX_PATH, dry_run=True)
    assert not any("characters" in e for e in result.errors), result.errors
