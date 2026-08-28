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

from PySide6.QtWidgets import QLabel  # noqa: E402

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
    def test_the_format_menu_is_built_from_outputs_formats(self, window) -> None:  # noqa: ANN001
        """Not from strings typed into the window."""
        values = [
            window.custom_format.itemData(i) for i in range(window.custom_format.count())
        ]
        assert values == list(outputs.FORMATS)

    def test_the_framing_menu_is_built_from_outputs_framings(self, window) -> None:  # noqa: ANN001
        values = [
            window.custom_framing.itemData(i)
            for i in range(window.custom_framing.count())
        ]
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
        window.custom_framing.setCurrentIndex(list(outputs.FRAMINGS).index("cropped"))
        window.custom_format.setCurrentIndex(list(outputs.FORMATS).index("jpeg"))
        chosen = window.current_options()
        assert chosen.custom_framing == "cropped"
        assert chosen.custom_format == "jpeg"
        # Cropped goes to `sharing/` whichever route asked for it.
        assert [spec.label for spec in chosen.specs()] == ["sharing/jpeg/cropped"]

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

    def test_convert_needs_both_folders(self, window, folders) -> None:  # noqa: ANN001
        source, dest = folders
        assert not window.convert_button.isEnabled()
        window.source_edit.setText(str(source))
        assert not window.convert_button.isEnabled()
        window.dest_edit.setText(str(dest))
        assert window.convert_button.isEnabled()


class TestCustomAsksTwoQuestions:
    """A format and a framing, and the two extra files. Not a third choice
    between an archive copy and a shareable one -- that is the choice above it,
    and asking again let somebody tick neither and meet a greyed-out button."""

    def test_the_tree_tickboxes_are_gone(self, window) -> None:  # noqa: ANN001
        assert not hasattr(window, "archive_check")
        assert not hasattr(window, "sharing_check")
        assert not hasattr(window, "sharing_format")
        assert not hasattr(window, "sharing_framing")

    def test_convert_stays_available_whatever_custom_is_set_to(
        self, window, folders
    ) -> None:  # noqa: ANN001
        """There is no combination that writes nothing, so none to refuse."""
        source, dest = folders
        _fill(window, source, dest)
        _custom(window)
        for fmt in range(window.custom_format.count()):
            for framing in range(window.custom_framing.count()):
                window.custom_format.setCurrentIndex(fmt)
                window.custom_framing.setCurrentIndex(framing)
                assert window.convert_button.isEnabled()
                assert len(window.current_options().specs()) == 1

    def test_both_menus_are_captioned_and_say_where_the_file_goes(self, window) -> None:  # noqa: ANN001
        """Two bare boxes reading "TIFF" and "Whole photo" name nothing.

        They used to sit under a checkbox naming the tree, which is what said
        what they were for. That checkbox is gone, and this is the release
        whose premise is that the window was unreadable.
        """
        for combo in (window.custom_format, window.custom_framing):
            assert combo.toolTip(), "a menu with no caption and no tooltip"

        captions = {
            label.text()
            for label in window.custom_box.findChildren(QLabel)
        }
        assert {"File type", "Framing"} <= captions

        # And the tree, which Custom no longer has a control for. Read from
        # the options rather than restated here, so the window cannot drift
        # from what the run will do.
        window.custom_framing.setCurrentIndex(list(outputs.FRAMINGS).index("cropped"))
        assert "sharing/" in window.custom_destination.text()
        window.custom_framing.setCurrentIndex(list(outputs.FRAMINGS).index("full"))
        assert "archive/" in window.custom_destination.text()

    def test_the_extra_files_are_still_offered_here(self, window, folders) -> None:  # noqa: ANN001
        source, dest = folders
        _fill(window, source, dest)
        _custom(window)
        window.source_copy_check.setChecked(True)
        window.sidecar_check.setChecked(True)
        args = options_mod.convert_args(window.current_options())
        assert "--source-copy" in args
        assert "--sidecar" in args


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


class TestTheWindowOpensReadable:
    """Stevie opened 1.2.0 and found the cards squashed into slivers: three
    radio buttons collapsed to underscores, the naming card empty, the
    placeholder text in the folder fields sliced in half. Making the window
    bigger fixed it, which is the tell.

    `setMinimumSize(920, 760)` was the cause. It was comfortable for the four
    sections 1.1.0 had, and by 1.2.0 the content's own minimum was past 1000 --
    so Qt was allowed to open the window nearly 300 pixels shorter than its
    contents needed and compress every widget to fit. A number that was right
    when it was typed and silently wrong the moment a card was added.
    """

    def test_nothing_is_ever_compressed_below_what_it_needs(self, window, folders) -> None:  # noqa: ANN001
        """However small the window gets. This is the property the old
        hardcoded minimum did not have, and the reason the contents sit in a
        scroll area rather than being given a taller floor: a floor tall
        enough for this content does not fit a 1366x768 laptop."""
        source, dest = folders
        _fill(window, source, dest)
        window.show()

        inner = window.centralWidget().widget()
        for height in (400, 600, 900):
            window.resize(980, height)
            inner.layout().activate()
            needed = inner.layout().minimumHeightForWidth(inner.width())
            assert inner.height() >= needed, (
                f"at {height}px tall the contents were squeezed to {inner.height()} "
                f"when they need {needed}"
            )

    def test_the_contents_scroll_rather_than_shrink(self, window) -> None:  # noqa: ANN001
        from PySide6.QtWidgets import QScrollArea

        scroller = window.centralWidget()
        assert isinstance(scroller, QScrollArea)
        assert scroller.widgetResizable(), (
            "without this the contents keep their hint width and never fill the window"
        )

    def test_on_a_screen_with_room_it_opens_showing_everything(self, window) -> None:  # noqa: ANN001
        """No scrolling required, because there is space not to.

        The screen is stated rather than inherited: the offscreen platform
        reports 800x800, which the old hardcoded 760 satisfied, so a test that
        took the display as it found it could not fail here or in CI.

        It is stated *large* on purpose. This content is now taller than an
        ordinary 1200-pixel display, so a screen of that size no longer has
        room and the assertion would be measuring the screen rather than the
        sizing. The small-screen case is
        `test_on_a_screen_without_room_it_takes_what_there_is`.
        """
        from PySide6.QtCore import QRect

        window._size_to_contents(QRect(0, 0, 1920, 1600))
        assert window.height() >= window.content_height_at(window.width()), (
            "the window opened shorter than its own contents on a screen with room"
        )

    def test_it_opens_tall_enough_for_custom_not_just_for_the_default(self, window) -> None:  # noqa: ANN001
        """A hidden widget counts as nothing to a layout.

        Custom shows a panel the two named modes do not, so measuring whichever
        mode happens to be selected sizes the window for the smallest of the
        three -- and picking Custom then puts a scrollbar on a window with a
        screen's worth of room around it. Measured, not assumed: the two
        heights really do differ.
        """
        from PySide6.QtCore import QRect

        default_only = window.content_height_at(window.PREFERRED_WIDTH)
        tallest = window.tallest_content_height(window.PREFERRED_WIDTH)
        assert tallest > default_only, (
            "the Custom panel adds no height, so this test proves nothing"
        )

        # Large enough that the screen is not the constraint -- see the note
        # in the test above.
        window._size_to_contents(QRect(0, 0, 1920, 1600))
        assert window.height() >= tallest, (
            "the window opened too short for Custom on a screen with room"
        )

    def test_on_a_screen_without_room_it_takes_what_there_is(self, window) -> None:  # noqa: ANN001
        """And the scroll area covers the rest. A floor tall enough for this
        content does not fit a 1366x768 laptop, so demanding one would make the
        window unusable there rather than merely scrollable."""
        from PySide6.QtCore import QRect

        window._size_to_contents(QRect(0, 0, 1366, 768))
        assert window.height() <= 768
        assert window.minimumHeight() <= 768
        assert window.minimumWidth() <= 1366

    def test_the_minimum_never_demands_more_width_than_the_screen(self, window) -> None:  # noqa: ANN001
        """The floor is a typed literal and is meant to be: it is the width
        below which the explanatory lines wrap away into nothing.

        What must not be typed is the *height the window opens at*, and that
        is `test_on_a_screen_with_room_it_opens_showing_everything` -- this one
        would pass against any hardcoded floor between 520 and the screen
        width, so it is named for the narrower thing it actually checks.
        """
        screen = window.screen()
        if screen is not None:
            assert window.minimumWidth() <= screen.availableGeometry().width()
        assert window.minimumWidth() >= 520


class TestItSaysWhatItIsMadeOf:
    """A downloaded exe travels alone.

    There is no folder of licence files beside it and nowhere else to look, so
    the notice has to be inside the binary and reachable from the window. For
    the Qt libraries, used under LGPLv3, that is section 4 rather than a
    courtesy.
    """

    def test_the_help_menu_offers_the_licences(self, window) -> None:  # noqa: ANN001
        from PySide6.QtWidgets import QMenu

        titles = [menu.title() for menu in window.menuBar().findChildren(QMenu)]
        assert any("Help" in title for title in titles), titles
        actions = [action.text() for action in window.menuBar().actions()]
        assert window.licences_action.text().replace("&", "").startswith("Licences")
        assert actions, "the menu bar is empty"

    def test_choosing_it_opens_the_dialog(
        self, window, monkeypatch: pytest.MonkeyPatch
    ) -> None:  # noqa: ANN001
        """The menu entry is wired to the dialog, not merely present."""
        opened: list[object] = []
        monkeypatch.setattr(
            "fpx_gui.window.LicenceDialog.exec", lambda self: opened.append(self)
        )
        window.licences_action.trigger()
        assert opened, "Help -> Licences opened nothing"

    def test_the_dialog_shows_the_notice_and_the_full_texts(self, window, qtbot) -> None:  # noqa: ANN001
        from fpx_gui import notices
        from fpx_gui.window import LicenceDialog

        dialog = LicenceDialog(window)
        qtbot.addWidget(dialog)

        assert dialog.tabs.count() == 1 + len(notices.LICENCE_FILES)
        notice = dialog.pane_text(0)
        assert "Apache-2.0" in notice
        assert "PySide6-Essentials" in notice
        assert "ExifTool" in notice and "NOT BUNDLED" in notice
        assert notices.ISSUES_URL in notice

        # The texts themselves, not a summary of them: a notice that
        # paraphrases a licence is not a copy of it.
        bodies = [dialog.pane_text(i) for i in range(1, dialog.tabs.count())]
        assert any("GNU LESSER GENERAL PUBLIC LICENSE" in body for body in bodies)
        assert any("GNU GENERAL PUBLIC LICENSE" in body for body in bodies)
        assert any("Apache License" in body for body in bodies)
        assert all(len(body) > 5000 for body in bodies), "a text was truncated"

    def test_every_pane_can_be_scrolled_and_reached_from_the_keyboard(
        self, window, qtbot
    ) -> None:  # noqa: ANN001
        """A notice nobody can page through is not a notice."""
        from PySide6.QtCore import Qt

        from fpx_gui.window import LicenceDialog

        dialog = LicenceDialog(window)
        qtbot.addWidget(dialog)
        for index in range(dialog.tabs.count()):
            pane = dialog.tabs.widget(index)
            assert pane.focusPolicy() != Qt.FocusPolicy.NoFocus
            assert pane.verticalScrollBar() is not None

    def test_opening_it_does_not_need_a_network_or_a_checkout(self, window) -> None:  # noqa: ANN001
        """It reads package data, the way the stylesheet does. That is what
        makes it work inside a frozen exe, where there is no repository."""
        from fpx_gui import notices

        for name in notices.LICENCE_FILES:
            assert notices.read_licence(name)


class TestItDoesNotStateFactsAboutSomebodyElsesPhotographs:
    def test_the_window_and_the_title_agree_with_the_executable(self, window) -> None:  # noqa: ANN001
        from fpx_gui import app as app_mod

        assert window.windowTitle() == "FPX Converter"
        assert window.windowTitle() == app_mod.APP_NAME

    def test_no_control_quotes_a_count_from_a_particular_archive(self, window) -> None:  # noqa: ANN001
        """A tooltip once said "70 photographs were cropped in the Kodak
        software" -- a measurement of the author's own corpus, stated to a
        stranger as a fact about theirs."""
        import re

        tooltips = [
            widget.toolTip()
            for widget in window.findChildren(type(window.custom_framing))
        ] + [
            window.custom_framing.toolTip(),
            window.custom_format.toolTip(),
            window.source_copy_check.toolTip(),
            window.sidecar_check.toolTip(),
            window.review_button.toolTip(),
            window.timezone_combo.toolTip(),
        ]
        for text in tooltips:
            assert not re.search(r"\b\d{2,}\s+photograph", text), text


class TestTheTimezoneControl:
    def test_it_reaches_the_options_the_run_is_built_from(self, window, folders) -> None:  # noqa: ANN001
        source, dest = folders
        _fill(window, source, dest)
        window.timezone_combo.setCurrentText("america/denver")
        assert window.current_options().timezone == "america/denver"

    def test_it_offers_the_zones_the_converter_knows(self, window) -> None:  # noqa: ANN001
        offered = {window.timezone_combo.itemText(i) for i in range(window.timezone_combo.count())}
        assert offered == set(options_mod.known_timezones())

    def test_it_opens_at_this_machine_s_zone_or_at_nothing_at_all(self, window) -> None:  # noqa: ANN001
        """Never at a plausible neighbour. A wrong offset is written exactly as
        confidently as a right one."""
        current = window.timezone_combo.currentText().strip()
        assert current in ("", *options_mod.known_timezones())
        assert current == options_mod.detect_timezone()

    def test_it_is_typed_into_rather_than_fixed(self, window) -> None:  # noqa: ANN001
        """So a zone the converter grows can be used before this list does,
        and is refused by the converter itself if it cannot."""
        assert window.timezone_combo.isEditable()


class TestTheReviewPageAsksBeforeItCopies:
    def test_it_says_what_it_will_copy_and_stops_if_told_to(
        self, window, folders, monkeypatch: pytest.MonkeyPatch
    ) -> None:  # noqa: ANN001
        """`ingest` copies one `.fpx` per distinct photograph into the
        destination. Elsewhere in this window keeping the originals is an
        option a person ticks on purpose; a button that does it quietly is a
        surprise, and the kind that fills a disk."""
        from PySide6.QtWidgets import QMessageBox

        source, dest = folders
        dest.mkdir()
        _write_clean_report(dest, converted=2)
        (source / "one.fpx").write_bytes(b"x" * 2048)
        _fill(window, source, dest)

        asked: list[str] = []
        started: list[object] = []
        monkeypatch.setattr(
            "fpx_gui.window.QMessageBox.question",
            lambda _p, _t, text, *a, **k: (
                asked.append(text) or QMessageBox.StandardButton.Cancel
            ),
        )
        monkeypatch.setattr(MainWindow, "_run", lambda self, steps: started.append(steps))

        window._start_review()

        assert asked, "it copied without asking"
        assert str(dest / "source-files") in asked[0]
        assert not started, "saying no still started the copy"

    def test_saying_yes_runs_it(
        self, window, folders, monkeypatch: pytest.MonkeyPatch
    ) -> None:  # noqa: ANN001
        from PySide6.QtWidgets import QMessageBox

        source, dest = folders
        dest.mkdir()
        _write_clean_report(dest, converted=2)
        _fill(window, source, dest)

        started: list[object] = []
        monkeypatch.setattr(
            "fpx_gui.window.QMessageBox.question",
            lambda *a, **k: QMessageBox.StandardButton.Yes,
        )
        monkeypatch.setattr(MainWindow, "_run", lambda self, steps: started.append(steps))

        window._start_review()

        assert started, "saying yes did nothing"
        assert started[0][0][1][0] == "ingest"
