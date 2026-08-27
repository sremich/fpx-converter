"""Tier-2: the window itself, offscreen.

Skipped cleanly where PySide6 is absent, because CI's job today is an install
of `requirements-dev.txt` and PySide6 lives in `requirements-gui.txt`. Nothing
here needs a display: `QT_QPA_PLATFORM=offscreen` is set before Qt is
imported.

What is worth testing about a window is not how it looks. It is whether the
controls mean what they say they mean -- whether unticking a box really
reaches the command line, and above all whether a destination inside the
source archive is refused before anything is launched.

Every path here is invented.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

# Before PySide6 is imported by anything, including pytest-qt.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6", reason="the desktop front end needs requirements-gui.txt")
pytest.importorskip("pytestqt", reason="the desktop front end needs requirements-gui.txt")

from fpx_converter import config, layout, name_template, outputs, writer  # noqa: E402
from fpx_gui import options as options_mod  # noqa: E402
from fpx_gui import summary  # noqa: E402
from fpx_gui.window import MainWindow  # noqa: E402


@pytest.fixture
def window(qtbot):  # noqa: ANN001, ANN201
    win = MainWindow()
    qtbot.addWidget(win)
    return win


@pytest.fixture
def folders(tmp_path: Path) -> tuple[Path, Path]:
    source = tmp_path / "photos"
    source.mkdir()
    return source, tmp_path / "converted"


def _fill(window, source: Path, dest: Path) -> None:  # noqa: ANN001
    window.source_edit.setText(str(source))
    window.dest_edit.setText(str(dest))


def _custom(window) -> None:  # noqa: ANN001
    """Select Custom, which is the only mode that reads the tree controls."""
    window.mode_buttons[options_mod.CUSTOM].setChecked(True)


def _stamp(dest: Path) -> int | None:
    """What `_start_convert` records before a run."""
    from fpx_gui.window import _report_stamp

    return _report_stamp(dest / "audit_report.json")


def _write_clean_report(dest: Path, *, converted: int) -> Path:
    """An audit report describing a complete, successful run."""
    import json

    path = dest / "audit_report.json"
    path.write_text(
        json.dumps(
            {
                "complete": True,
                "interrupted": False,
                "unexplained_failures": 0,
                "counts": {
                    "manifest_entries": converted,
                    "selected": converted,
                    "attempted": converted,
                    "not_attempted": 0,
                    "converted": converted,
                    "resumed": 0,
                    "failed": 0,
                    "with_warnings": 0,
                },
            }
        ),
        encoding="utf-8",
    )
    return path


class TestTheControlsComeFromTheCli:
    def test_the_format_menus_are_built_from_outputs_formats(self, window) -> None:  # noqa: ANN001
        """Not from strings typed into the window."""
        for combo in (window.archive_format, window.sharing_format):
            values = [combo.itemData(i) for i in range(combo.count())]
            assert values == list(outputs.FORMATS)

    def test_the_framing_menus_are_built_from_outputs_framings(self, window) -> None:  # noqa: ANN001
        for combo in (window.archive_framing, window.sharing_framing):
            values = [combo.itemData(i) for i in range(combo.count())]
            assert values == list(outputs.FRAMINGS)

    def test_the_window_opens_on_the_archive_copy_and_writes_one_image(
        self, window, folders
    ) -> None:  # noqa: ANN001
        """One photograph in, one file out, and nothing to read first.

        The window used to open with both trees ticked and both extras
        implied, so the plainest possible run produced four files per
        photograph. Whichever of the three somebody picks, the two named ones
        write exactly one image.
        """
        source, dest = folders
        _fill(window, source, dest)
        chosen = window.current_options()
        assert chosen.mode == options_mod.ARCHIVE
        assert [spec.label for spec in chosen.specs()] == ["archive/tiff/full"]
        assert chosen.source_copy is False
        assert chosen.sidecar is False
        assert chosen.resume is True

    def test_the_three_choices_are_exclusive_and_only_custom_asks_questions(
        self, window, folders
    ) -> None:  # noqa: ANN001
        source, dest = folders
        _fill(window, source, dest)
        # `isHidden`, not `isVisible`: the window is never shown in a test, so
        # every child reads as invisible whatever it was asked to be.
        assert window.custom_box.isHidden()

        window.mode_buttons[options_mod.SHARING].setChecked(True)
        assert window.current_options().mode == options_mod.SHARING
        assert not window.mode_buttons[options_mod.ARCHIVE].isChecked()
        assert window.custom_box.isHidden()

        _custom(window)
        assert not window.custom_box.isHidden()
        assert not window.mode_buttons[options_mod.SHARING].isChecked()

    def test_the_extra_files_have_their_own_options(self, window, folders) -> None:  # noqa: ANN001
        """Both off, both reachable, and neither entangled with the images."""
        source, dest = folders
        _fill(window, source, dest)
        _custom(window)
        assert not window.source_copy_check.isChecked()
        assert not window.sidecar_check.isChecked()

        window.source_copy_check.setChecked(True)
        window.sidecar_check.setChecked(True)
        chosen = window.current_options()
        assert chosen.source_copy is True
        assert chosen.sidecar is True
        assert "--source-copy" in options_mod.convert_args(chosen)
        assert "--sidecar" in options_mod.convert_args(chosen)


class TestTheControlsReachTheCommandLine:
    def test_a_changed_dropdown_changes_the_options(self, window, folders) -> None:  # noqa: ANN001
        source, dest = folders
        _fill(window, source, dest)
        _custom(window)
        window.sharing_framing.setCurrentIndex(list(outputs.FRAMINGS).index("full"))
        window.sharing_format.setCurrentIndex(list(outputs.FORMATS).index("tiff"))
        chosen = window.current_options()
        assert chosen.sharing_framing == "full"
        assert chosen.sharing_format == "tiff"

    def test_start_over_is_gone_and_every_run_resumes(self, window, folders) -> None:  # noqa: ANN001
        """The checkbox named a mechanism, not a job, so it is not offered.

        Resuming skips what a previous run finished and costs a re-read at
        worst. `--no-resume` is still on the CLI for whoever needs it.
        """
        source, dest = folders
        _fill(window, source, dest)
        assert not hasattr(window, "start_over")
        assert window.current_options().resume is True
        assert "--no-resume" not in options_mod.convert_args(window.current_options())

    def test_unticking_a_tree_drops_it_and_greys_its_menus(self, window, folders) -> None:  # noqa: ANN001
        source, dest = folders
        _fill(window, source, dest)
        _custom(window)
        window.archive_check.setChecked(False)
        assert window.current_options().archive is False
        assert not window.archive_format.isEnabled()
        assert not window.archive_framing.isEnabled()

    def test_unticking_both_disables_convert_rather_than_writing_nothing(
        self, window, folders
    ) -> None:  # noqa: ANN001
        """`build_specs` would refuse it; the button refuses it first."""
        source, dest = folders
        _fill(window, source, dest)
        _custom(window)
        window.archive_check.setChecked(False)
        window.sharing_check.setChecked(False)
        assert not window.convert_button.isEnabled()

    def test_convert_needs_both_folders(self, window, folders) -> None:  # noqa: ANN001
        source, dest = folders
        assert not window.convert_button.isEnabled()
        window.source_edit.setText(str(source))
        assert not window.convert_button.isEnabled()
        window.dest_edit.setText(str(dest))
        assert window.convert_button.isEnabled()


class TestTheReadOnlySourceRuleAtTheWindow:
    def test_a_destination_inside_the_source_launches_nothing(
        self, window, folders, monkeypatch: pytest.MonkeyPatch
    ) -> None:  # noqa: ANN001
        source, _dest = folders
        _fill(window, source, source / "converted")

        warned: list[tuple[str, str]] = []
        started: list[object] = []
        monkeypatch.setattr(
            "fpx_gui.window.QMessageBox.warning",
            lambda _parent, title, text, *a, **k: warned.append((title, text)),
        )
        monkeypatch.setattr(MainWindow, "_run", lambda self, steps: started.append(steps))

        window._start_convert()

        assert not started, "a conversion was launched into the source archive"
        assert warned, "the refusal was never shown to the person"
        assert "read-only source archive" in warned[0][1]

    def test_the_window_goes_through_ensure_outside_source(
        self, window, folders, monkeypatch: pytest.MonkeyPatch
    ) -> None:  # noqa: ANN001
        """The guard on the guard, at the level a person actually clicks.

        `test_gui_options.py` proves `validate` calls it. This proves the
        button calls `validate`. If the window ever grows its own idea of an
        acceptable path, one of the two fails.
        """
        source, dest = folders
        _fill(window, source, dest)

        calls: list[tuple[Path, Path]] = []
        real = config.ensure_outside_source

        def spy(target, source_root, what):  # noqa: ANN001, ANN202
            calls.append((Path(target), Path(source_root)))
            return real(target, source_root, what)

        monkeypatch.setattr(config, "ensure_outside_source", spy)
        monkeypatch.setattr(MainWindow, "_run", lambda self, steps: None)

        window._start_convert()

        assert calls, "pressing Convert never reached config.ensure_outside_source"
        assert calls[0] == (dest, source)

    def test_a_missing_source_folder_launches_nothing(
        self, window, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:  # noqa: ANN001
        _fill(window, tmp_path / "nowhere", tmp_path / "out")
        warned: list[str] = []
        started: list[object] = []
        monkeypatch.setattr(
            "fpx_gui.window.QMessageBox.warning",
            lambda _p, _t, text, *a, **k: warned.append(text),
        )
        monkeypatch.setattr(MainWindow, "_run", lambda self, steps: started.append(steps))
        window._start_convert()
        assert not started
        assert warned


class TestWhatItSaysWhenItIsOver:
    def test_a_hard_stopped_run_says_no_report_was_written(self, window) -> None:  # noqa: ANN001
        """The one ending that leaves no trustworthy record of itself."""
        from fpx_gui import runner

        window._on_done(1, runner.HARD_STOPPED)
        assert "no audit report" in window._headline.text().lower()
        assert window._headline.property("severity") == summary.ERROR

    def test_a_partial_run_is_not_dressed_up_as_a_finish(
        self, window, folders, tmp_path: Path
    ) -> None:  # noqa: ANN001
        import json

        source, dest = folders
        _fill(window, source, dest)
        dest.mkdir(parents=True, exist_ok=True)
        window._last_options = window.current_options()
        (dest / "audit_report.json").write_text(
            json.dumps(
                {
                    "complete": False,
                    "interrupted": False,
                    "counts": {
                        "manifest_entries": 687,
                        "attempted": 4,
                        "converted": 4,
                        "resumed": 0,
                        "failed": 0,
                        "with_warnings": 0,
                    },
                }
            ),
            encoding="utf-8",
        )
        window._on_done(0, "")
        assert window._headline.property("severity") == summary.ERROR
        assert "not a converted archive" in window._headline.text()

    def test_a_missing_report_is_never_read_as_success(self, window, folders) -> None:  # noqa: ANN001
        source, dest = folders
        _fill(window, source, dest)
        window._last_options = window.current_options()
        window._on_done(0, "")
        assert window._headline.property("severity") == summary.ERROR

    def test_an_earlier_runs_report_is_never_read_as_this_runs_success(
        self, window, folders  # noqa: ANN001
    ) -> None:
        """The finding, and the worst-phrased bug in the window.

        `_on_done` loaded whatever `audit_report.json` was in the destination
        without asking whether this run wrote it. Convert into a folder that
        was converted successfully once before, have any step fail, and the
        window announced "Finished -- all N photos converted" to the one
        audience with no other way to check.
        """
        source, dest = folders
        dest.mkdir(parents=True, exist_ok=True)
        _write_clean_report(dest, converted=687)

        _fill(window, source, dest)
        window._last_options = window.current_options()
        # As `_start_convert` does: stamp the report before the run.
        window._report_stamp = _stamp(dest)

        # The run fails and writes nothing. The old report is untouched.
        window._on_done(1, "")

        assert window._headline.property("severity") == summary.ERROR, (
            "a previous run's report was reported as this run's success"
        )
        assert "687" not in window._headline.text()
        assert "earlier run" in window.log.toPlainText()

    def test_a_report_this_run_wrote_is_read_normally(
        self, window, folders  # noqa: ANN001
    ) -> None:
        """The guard must not refuse the ordinary case."""
        source, dest = folders
        dest.mkdir(parents=True, exist_ok=True)
        _fill(window, source, dest)
        window._last_options = window.current_options()
        window._report_stamp = _stamp(dest)  # nothing there yet

        _write_clean_report(dest, converted=4)
        window._on_done(0, "")

        assert window._headline.property("severity") != summary.ERROR
        assert "4" in window._headline.text()


class TestTheProgressBar:
    def test_it_follows_the_lines_the_child_prints(self, window) -> None:  # noqa: ANN001
        window.progress_bar.setRange(0, 0)
        for index in range(1, 5):
            window._on_line(f"OK   [{index}/4] example-{index:04d}.fpx -> 2 files in 0.1s")
        assert window.progress_bar.maximum() == 100
        assert window.progress_bar.value() == 100

    def test_a_line_it_cannot_read_is_shown_and_does_not_move_it(self, window) -> None:  # noqa: ANN001
        window._on_line("something entirely unexpected")
        assert "something entirely unexpected" in window.log.toPlainText()
        assert window.progress_bar.value() == 0


class TestTheNamingAndFolderControls:
    def test_the_window_opens_on_what_the_cli_would_do_unasked(self, window, folders) -> None:  # noqa: ANN001
        source, dest = folders
        _fill(window, source, dest)
        chosen = window.current_options()
        assert chosen.name_template == name_template.DEFAULT_TEMPLATE
        assert chosen.folder_scheme == layout.BY_ALBUM
        assert "--name-template" not in options_mod.convert_args(chosen)
        assert "--folder-scheme" not in options_mod.convert_args(chosen)

    def test_the_preview_is_the_real_path_and_not_a_second_copy_of_the_rules(
        self, window, folders
    ) -> None:  # noqa: ANN001
        """It is `writer.build_output_relpath`, the same call the conversion
        makes. A front end with its own naming logic would drift, and a preview
        that lied about where six hundred photographs were going would be worse
        than no preview at all."""
        source, dest = folders
        _fill(window, source, dest)
        window.name_template_edit.setText("{day}-{month}-{year}_{name}")

        entry, derived = window._PREVIEW_DATED
        expected = writer.build_output_relpath(
            entry, derived, "jpg", None, "{day}-{month}-{year}_{name}", layout.BY_ALBUM, ""
        ).as_posix()
        assert expected in window.name_preview.text()
        assert "04-07-2002_Backyard" in expected

    def test_the_preview_shows_an_undated_photo_too(self, window, folders) -> None:  # noqa: ANN001
        """Most of this corpus has no date anywhere in it. Somebody needs to
        meet the zeros in the preview, not in six hundred filenames."""
        source, dest = folders
        _fill(window, source, dest)
        assert "0000-00-00_000000_DCP12345" in window.name_preview.text()

    def test_a_pattern_that_drops_the_filename_disables_convert(self, window, folders) -> None:  # noqa: ANN001
        source, dest = folders
        _fill(window, source, dest)
        assert window.convert_button.isEnabled()

        window.name_template_edit.setText("{year}-{month}-{day}")
        assert not window.convert_button.isEnabled()
        assert "{name}" in window.name_preview.text()

        window.name_template_edit.setText(name_template.DEFAULT_TEMPLATE)
        assert window.convert_button.isEnabled()

    def test_the_folder_menu_is_built_from_the_schemes_the_cli_has(self, window) -> None:  # noqa: ANN001
        values = [
            window.folder_scheme.itemData(i) for i in range(window.folder_scheme.count())
        ]
        assert values == [v for v, _, _ in layout.FOLDER_SCHEMES]

    def test_choosing_a_scheme_changes_where_the_preview_says_files_go(
        self, window, folders
    ) -> None:  # noqa: ANN001
        source, dest = folders
        _fill(window, source, dest)
        seen = {}
        for index, (value, _label, _hint) in enumerate(layout.FOLDER_SCHEMES):
            window.folder_scheme.setCurrentIndex(index)
            assert window.current_options().folder_scheme == value
            # The path the preview is built from, rather than the sentence
            # it is shown in, so the assertion is about the folder and not
            # about the wording around it.
            seen[value] = window._preview_path(*window._PREVIEW_DATED)

        stem = "2002-07-04_143210_Backyard.jpg"
        assert seen[layout.BY_ALBUM] == f"2002/Summer 2002/{stem}"
        assert seen[layout.BY_YEAR] == f"2002/{stem}"
        assert seen[layout.BY_YEAR_MONTH] == f"2002/2002 July/{stem}"
        assert seen[layout.FLAT] == stem
        assert seen[layout.CUSTOM] == f"2002/Summer 2002/{stem}"

    def test_the_folder_pattern_box_appears_only_under_custom(self, window, folders) -> None:  # noqa: ANN001
        source, dest = folders
        _fill(window, source, dest)
        assert window.folder_template_edit.isHidden()

        values = [v for v, _, _ in layout.FOLDER_SCHEMES]
        window.folder_scheme.setCurrentIndex(values.index(layout.CUSTOM))
        assert not window.folder_template_edit.isHidden()

        window.folder_scheme.setCurrentIndex(values.index(layout.FLAT))
        assert window.folder_template_edit.isHidden()

    def test_a_folder_pattern_that_walks_upwards_disables_convert(self, window, folders) -> None:  # noqa: ANN001
        source, dest = folders
        _fill(window, source, dest)
        values = [v for v, _, _ in layout.FOLDER_SCHEMES]
        window.folder_scheme.setCurrentIndex(values.index(layout.CUSTOM))
        window.folder_template_edit.setText("../{album}")
        assert not window.convert_button.isEnabled()

    def test_reset_puts_both_patterns_back(self, window, folders) -> None:  # noqa: ANN001
        source, dest = folders
        _fill(window, source, dest)
        values = [v for v, _, _ in layout.FOLDER_SCHEMES]
        window.folder_scheme.setCurrentIndex(values.index(layout.FLAT))
        window.name_template_edit.setText("{name}")

        window._reset_patterns()
        chosen = window.current_options()
        assert chosen.name_template == name_template.DEFAULT_TEMPLATE
        assert chosen.folder_scheme == layout.BY_ALBUM
        assert chosen.folder_template == layout.DEFAULT_FOLDER_TEMPLATE
