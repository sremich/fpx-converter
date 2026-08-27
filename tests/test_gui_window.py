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

from fpx_converter import config, outputs  # noqa: E402
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

    def test_the_defaults_are_the_shipped_behaviour(self, window, folders) -> None:  # noqa: ANN001
        source, dest = folders
        _fill(window, source, dest)
        chosen = window.current_options()
        assert {spec.label for spec in chosen.specs()} == {
            "archive/tiff/full",
            "sharing/jpeg/cropped",
        }
        assert chosen.resume is True


class TestTheControlsReachTheCommandLine:
    def test_a_changed_dropdown_changes_the_options(self, window, folders) -> None:  # noqa: ANN001
        source, dest = folders
        _fill(window, source, dest)
        window.sharing_framing.setCurrentIndex(list(outputs.FRAMINGS).index("full"))
        window.sharing_format.setCurrentIndex(list(outputs.FORMATS).index("tiff"))
        chosen = window.current_options()
        assert chosen.sharing_framing == "full"
        assert chosen.sharing_format == "tiff"

    def test_start_over_turns_resume_off(self, window, folders) -> None:  # noqa: ANN001
        source, dest = folders
        _fill(window, source, dest)
        window.start_over.setChecked(True)
        assert window.current_options().resume is False

    def test_unticking_a_tree_drops_it_and_greys_its_menus(self, window, folders) -> None:  # noqa: ANN001
        source, dest = folders
        _fill(window, source, dest)
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
