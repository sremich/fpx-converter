"""Tier-1: the window's controls, turned into command lines.

Two things are being proved here, and the second is the important one.

**Every combination of the output controls produces the flags the CLI
actually has.** They are checked against `build_parser()` rather than against
a list typed here: a flag renamed in the CLI must break this file, not the
application.

**The destination goes through `config.ensure_outside_source`.** That rule --
nothing may be written under the read-only source archive -- is the one whose
violation cannot be undone, and a front end that grew its own path check
would be a second implementation of it that could drift. The spy test below
fails if the call ever stops happening.

All paths in this file are invented. The archive is not in the repository and
neither are its folder names.
"""

from __future__ import annotations

import itertools
from pathlib import Path

import pytest

from fpx_converter import config, outputs
from fpx_converter.cli import build_parser
from fpx_gui import options as options_mod
from fpx_gui.options import ConvertOptions


@pytest.fixture
def folders(tmp_path: Path) -> tuple[Path, Path]:
    source = tmp_path / "photos"
    source.mkdir()
    return source, tmp_path / "converted"


def _convert_parser():
    for action in build_parser()._actions:
        if action.choices and "convert" in action.choices:
            return action.choices["convert"]
    raise AssertionError("the CLI no longer has a `convert` subcommand")


class TestTheFlagsAreRealFlags:
    def test_every_generated_flag_exists_on_the_cli(self, folders) -> None:
        """The check that makes the rest of this file mean anything."""
        source, dest = folders
        parser = _convert_parser()
        known = {opt for action in parser._actions for opt in action.option_strings}
        assert known, "no options were found; this check would pass vacuously"

        for archive, sharing in ((True, True), (True, False), (False, True)):
            args = options_mod.convert_args(
                ConvertOptions(source=source, dest=dest, archive=archive, sharing=sharing)
            )
            for token in args[1:]:
                if token.startswith("--"):
                    assert token in known, f"{token} is not a flag of `convert`"

    def test_the_generated_command_lines_parse(self, folders) -> None:
        source, dest = folders
        parser = build_parser()
        for _label, args in options_mod.convert_pipeline(
            ConvertOptions(source=source, dest=dest)
        ):
            parser.parse_args(args)
        for _label, args in options_mod.review_pipeline(
            ConvertOptions(source=source, dest=dest)
        ):
            parser.parse_args(args)


class TestOutputCombinations:
    @pytest.mark.parametrize(
        ("archive_format", "archive_framing", "sharing_format", "sharing_framing"),
        list(
            itertools.product(
                outputs.FORMATS, outputs.FRAMINGS, outputs.FORMATS, outputs.FRAMINGS
            )
        ),
    )
    def test_each_pairing_reaches_the_command_line_and_the_specs(
        self, folders, archive_format, archive_framing, sharing_format, sharing_framing
    ) -> None:
        source, dest = folders
        chosen = ConvertOptions(
            source=source,
            dest=dest,
            archive_format=archive_format,
            archive_framing=archive_framing,
            sharing_format=sharing_format,
            sharing_framing=sharing_framing,
        )
        parsed = build_parser().parse_args(options_mod.convert_args(chosen))
        assert parsed.archive_format == archive_format
        assert parsed.archive_framing == archive_framing
        assert parsed.sharing_format == sharing_format
        assert parsed.sharing_framing == sharing_framing
        assert parsed.no_archive is False
        assert parsed.no_sharing is False

        labels = {spec.label for spec in chosen.specs()}
        assert labels == {
            f"archive/{archive_format}/{archive_framing}",
            f"sharing/{sharing_format}/{sharing_framing}",
        }

    def test_turning_off_the_archive_emits_no_archive_and_nothing_else(
        self, folders
    ) -> None:
        source, dest = folders
        args = options_mod.convert_args(
            ConvertOptions(source=source, dest=dest, archive=False)
        )
        assert "--no-archive" in args
        assert "--archive-format" not in args
        assert "--archive-framing" not in args
        parsed = build_parser().parse_args(args)
        assert parsed.no_archive is True
        assert parsed.no_sharing is False

    def test_turning_off_sharing_emits_no_sharing_and_nothing_else(self, folders) -> None:
        source, dest = folders
        args = options_mod.convert_args(
            ConvertOptions(source=source, dest=dest, sharing=False)
        )
        assert "--no-sharing" in args
        assert "--sharing-format" not in args
        parsed = build_parser().parse_args(args)
        assert parsed.no_sharing is True

    def test_asking_for_neither_is_refused_by_the_cli_s_own_error(self, folders) -> None:
        """`OutputSpecError`, with the CLI's wording. Not a message invented here."""
        source, dest = folders
        chosen = ConvertOptions(source=source, dest=dest, archive=False, sharing=False)
        with pytest.raises(outputs.OutputSpecError):
            options_mod.validate(chosen)

    def test_resume_is_on_by_default_and_start_over_is_the_opt_in(self, folders) -> None:
        source, dest = folders
        default = options_mod.convert_args(ConvertOptions(source=source, dest=dest))
        assert "--no-resume" not in default
        started_over = options_mod.convert_args(
            ConvertOptions(source=source, dest=dest, resume=False)
        )
        assert "--no-resume" in started_over
        assert build_parser().parse_args(started_over).no_resume is True

    def test_progress_is_always_asked_for(self, folders) -> None:
        """It is what drives the progress bar; a run without it looks hung."""
        source, dest = folders
        args = options_mod.convert_args(ConvertOptions(source=source, dest=dest))
        assert "--progress" in args
        assert build_parser().parse_args(args).progress is True


class TestTheReadOnlySourceRule:
    def test_a_destination_inside_the_source_is_refused(self, folders) -> None:
        source, _dest = folders
        chosen = ConvertOptions(source=source, dest=source / "converted")
        with pytest.raises(config.SourceWriteRefused):
            options_mod.validate(chosen)

    def test_the_source_folder_itself_is_refused_as_a_destination(self, folders) -> None:
        source, _dest = folders
        with pytest.raises(config.SourceWriteRefused):
            options_mod.validate(ConvertOptions(source=source, dest=source))

    def test_the_refusal_message_is_the_cli_s_own(self, folders) -> None:
        source, _dest = folders
        with pytest.raises(config.SourceWriteRefused) as raised:
            options_mod.validate(ConvertOptions(source=source, dest=source / "out"))
        assert "read-only source archive" in str(raised.value)

    def test_validation_goes_through_ensure_outside_source(
        self, folders, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The guard on the guard.

        If this front end ever starts deciding for itself whether a
        destination is acceptable -- comparing strings, calling
        `Path.is_relative_to`, anything -- this test fails, and it should. The
        rule has one implementation and everything calls it.
        """
        source, dest = folders
        calls: list[tuple[Path, Path, str]] = []
        real = config.ensure_outside_source

        def spy(target: Path, source_root: Path, what: str) -> Path:
            calls.append((Path(target), Path(source_root), what))
            return real(target, source_root, what)

        monkeypatch.setattr(config, "ensure_outside_source", spy)
        options_mod.validate(ConvertOptions(source=source, dest=dest))

        assert calls, "the destination was never passed to config.ensure_outside_source"
        target, root, _what = calls[0]
        assert target == dest
        assert root == source

    def test_a_missing_source_folder_is_refused_before_anything_launches(
        self, tmp_path: Path
    ) -> None:
        chosen = ConvertOptions(source=tmp_path / "nowhere", dest=tmp_path / "out")
        with pytest.raises(config.ConfigError):
            options_mod.validate(chosen)

    def test_an_empty_folder_field_is_refused(self, tmp_path: Path) -> None:
        """`Path("")` is `Path(".")`, which exists.

        Without an explicit check, leaving a field blank passed validation and
        scanned the working directory.
        """
        with pytest.raises(config.ConfigError):
            options_mod.validate(ConvertOptions(source=Path(""), dest=tmp_path / "out"))
        with pytest.raises(config.ConfigError):
            options_mod.validate(ConvertOptions(source=tmp_path, dest=Path("")))


class TestWhereThingsLand:
    def test_the_manifest_and_the_page_live_in_the_destination(self, folders) -> None:
        """Never beside the source -- and a destination is then a whole record."""
        source, dest = folders
        chosen = ConvertOptions(source=source, dest=dest)
        assert chosen.manifest.parent == dest
        assert dest in chosen.report_page.parents
        assert chosen.store.parent == dest

    def test_the_scan_reads_the_source_and_writes_nowhere_near_it(self, folders) -> None:
        source, dest = folders
        args = options_mod.scan_args(ConvertOptions(source=source, dest=dest))
        parsed = build_parser().parse_args(args)
        assert Path(parsed.source) == source
        assert dest in Path(parsed.manifest).parents

    def test_converting_does_not_copy_the_archive_a_second_time(self, folders) -> None:
        """`ingest` belongs to the review page, which is the only step needing it."""
        source, dest = folders
        commands = [
            args[0] for _label, args in options_mod.convert_pipeline(
                ConvertOptions(source=source, dest=dest)
            )
        ]
        assert commands == ["scan", "convert"]
        review = [
            args[0] for _label, args in options_mod.review_pipeline(
                ConvertOptions(source=source, dest=dest)
            )
        ]
        assert review == ["ingest", "gallery"]

    def test_every_step_is_labelled_for_a_person(self, folders) -> None:
        source, dest = folders
        chosen = ConvertOptions(source=source, dest=dest)
        for label, _args in options_mod.convert_pipeline(chosen) + options_mod.review_pipeline(
            chosen
        ):
            assert label and label[0].isupper()
