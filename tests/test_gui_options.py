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

from fpx_converter import config, layout, name_template, outputs
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
            # The four menus exist only under Custom. The two named modes are
            # one tree each and ignore these fields entirely, which is the
            # whole point of them.
            mode=options_mod.CUSTOM,
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
            ConvertOptions(
                source=source, dest=dest, mode=options_mod.CUSTOM, archive=False
            )
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
            ConvertOptions(
                source=source, dest=dest, mode=options_mod.CUSTOM, sharing=False
            )
        )
        assert "--no-sharing" in args
        assert "--sharing-format" not in args
        parsed = build_parser().parse_args(args)
        assert parsed.no_sharing is True

    def test_asking_for_neither_is_refused_by_the_cli_s_own_error(self, folders) -> None:
        """`OutputSpecError`, with the CLI's wording. Not a message invented here."""
        source, dest = folders
        chosen = ConvertOptions(
            source=source,
            dest=dest,
            mode=options_mod.CUSTOM,
            archive=False,
            sharing=False,
        )
        with pytest.raises(outputs.OutputSpecError):
            options_mod.validate(chosen)

    def test_resume_is_on_and_the_window_offers_no_way_off_it(self, folders) -> None:
        """`Start over` is gone; `--no-resume` stays reachable from the CLI.

        The checkbox meant "ignore what a previous run did", which describes a
        mechanism rather than a job -- nobody could say what it would do to
        their photographs. Resuming skips what is finished and costs a re-read
        at worst, so it is simply on.
        """
        source, dest = folders
        default = options_mod.convert_args(ConvertOptions(source=source, dest=dest))
        assert "--no-resume" not in default
        assert ConvertOptions(source=source, dest=dest).resume is True

        # The field still works for anything that sets it directly, and the
        # flag it emits is still one the CLI has.
        off = options_mod.convert_args(
            ConvertOptions(source=source, dest=dest, resume=False)
        )
        assert build_parser().parse_args(off).no_resume is True

    def test_archive_mode_writes_one_lossless_whole_frame_image(self, folders) -> None:
        """And nothing else. That is what the label promises."""
        source, dest = folders
        chosen = ConvertOptions(source=source, dest=dest, mode=options_mod.ARCHIVE)
        assert [spec.label for spec in chosen.specs()] == ["archive/tiff/full"]
        parsed = build_parser().parse_args(options_mod.convert_args(chosen))
        assert parsed.no_sharing is True
        assert parsed.no_archive is False
        assert parsed.archive_format == "tiff"
        assert parsed.archive_framing == "full"

    def test_sharing_mode_writes_one_cropped_jpeg(self, folders) -> None:
        source, dest = folders
        chosen = ConvertOptions(source=source, dest=dest, mode=options_mod.SHARING)
        assert [spec.label for spec in chosen.specs()] == ["sharing/jpeg/cropped"]
        parsed = build_parser().parse_args(options_mod.convert_args(chosen))
        assert parsed.no_archive is True
        assert parsed.no_sharing is False
        assert parsed.sharing_format == "jpeg"
        assert parsed.sharing_framing == "cropped"

    def test_a_named_mode_ignores_whatever_the_custom_menus_hold(self, folders) -> None:
        """Leaving Custom must not leave its settings switched on behind it.

        The menus keep their values while hidden, so a mode built as "the
        custom settings, preset" would quietly carry the last custom choice
        into a run whose label said something else.
        """
        source, dest = folders
        chosen = ConvertOptions(
            source=source,
            dest=dest,
            mode=options_mod.ARCHIVE,
            archive_format="jpeg",
            archive_framing="cropped",
            sharing=True,
            sharing_format="tiff",
        )
        assert [spec.label for spec in chosen.specs()] == ["archive/tiff/full"]
        assert "--sharing-format" not in options_mod.convert_args(chosen)

    def test_the_extra_files_are_off_unless_asked_for(self, folders) -> None:
        """One photograph, one image. The other two files are each an option."""
        source, dest = folders
        default = build_parser().parse_args(
            options_mod.convert_args(ConvertOptions(source=source, dest=dest))
        )
        assert default.source_copy is False
        assert default.sidecar is False

        for mode in (options_mod.ARCHIVE, options_mod.SHARING, options_mod.CUSTOM):
            asked = build_parser().parse_args(
                options_mod.convert_args(
                    ConvertOptions(
                        source=source,
                        dest=dest,
                        mode=mode,
                        source_copy=True,
                        sidecar=True,
                    )
                )
            )
            assert asked.source_copy is True, mode
            assert asked.sidecar is True, mode

    def test_progress_is_always_asked_for(self, folders) -> None:
        """It is what drives the progress bar; a run without it looks hung."""
        source, dest = folders
        args = options_mod.convert_args(ConvertOptions(source=source, dest=dest))
        assert "--progress" in args
        assert build_parser().parse_args(args).progress is True

    def test_a_stop_file_is_always_offered(self, folders) -> None:
        """Cancel's only guarantee on a machine where a console signal cannot
        be delivered. Without it, cancelling means killing, and killing means
        no audit report."""
        source, dest = folders
        chosen = ConvertOptions(source=source, dest=dest)
        args = options_mod.convert_args(chosen)
        assert "--stop-file" in args
        parsed = build_parser().parse_args(args)
        assert Path(parsed.stop_file) == chosen.stop_file
        assert chosen.stop_file.parent == dest


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


class TestTheNamingAndFolderPatterns:
    """They apply to all three modes: what a file is called and where it goes
    is a different question from which files get written."""

    def test_the_defaults_emit_nothing_because_they_are_the_cli_s_own(
        self, folders
    ) -> None:
        source, dest = folders
        args = options_mod.convert_args(ConvertOptions(source=source, dest=dest))
        assert "--name-template" not in args
        assert "--folder-scheme" not in args
        assert "--folder-template" not in args

    def test_a_changed_filename_pattern_reaches_every_mode(self, folders) -> None:
        source, dest = folders
        for mode in (options_mod.ARCHIVE, options_mod.SHARING, options_mod.CUSTOM):
            parsed = build_parser().parse_args(
                options_mod.convert_args(
                    ConvertOptions(
                        source=source,
                        dest=dest,
                        mode=mode,
                        name_template="{day}-{month}-{year}_{name}",
                    )
                )
            )
            assert parsed.name_template == "{day}-{month}-{year}_{name}", mode

    @pytest.mark.parametrize(
        "scheme", [s for s, _, _ in layout.FOLDER_SCHEMES if s != layout.CUSTOM]
    )
    def test_each_named_scheme_reaches_the_command_line(self, folders, scheme) -> None:
        source, dest = folders
        args = options_mod.convert_args(
            ConvertOptions(source=source, dest=dest, folder_scheme=scheme)
        )
        parsed = build_parser().parse_args(args)
        assert parsed.folder_scheme == scheme
        # Not beside a scheme that does not read it: the log pane is the one
        # place a person sees what was actually run.
        assert "--folder-template" not in args

    def test_the_folder_pattern_is_emitted_only_under_custom(self, folders) -> None:
        source, dest = folders
        args = options_mod.convert_args(
            ConvertOptions(
                source=source,
                dest=dest,
                folder_scheme=layout.CUSTOM,
                folder_template="{year}/{album}",
            )
        )
        parsed = build_parser().parse_args(args)
        assert parsed.folder_scheme == layout.CUSTOM
        assert parsed.folder_template == "{year}/{album}"

    def test_a_pattern_that_would_lose_the_filenames_is_refused_before_launching(
        self, folders
    ) -> None:
        source, dest = folders
        source.mkdir(exist_ok=True)
        with pytest.raises(name_template.TemplateError):
            options_mod.validate(
                ConvertOptions(source=source, dest=dest, name_template="{year}-{month}")
            )

    def test_a_folder_pattern_that_would_walk_upwards_is_refused(self, folders) -> None:
        """It could put converted images anywhere on the disk, the read-only
        source archive included."""
        source, dest = folders
        source.mkdir(exist_ok=True)
        with pytest.raises(name_template.TemplateError):
            options_mod.validate(
                ConvertOptions(
                    source=source,
                    dest=dest,
                    folder_scheme=layout.CUSTOM,
                    folder_template="../{album}",
                )
            )
