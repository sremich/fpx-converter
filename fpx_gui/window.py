"""The window: one screen, no wizard.

Pick two folders, say what to write, press Convert, watch it, read what
happened. Every control maps onto a real flag of `fpx_converter convert`, and
the dropdowns are built from `outputs.FORMATS` and `outputs.FRAMINGS` rather
than from strings typed here, so a format the CLI grows appears in the window
without anybody remembering to add it.

The two things this file is careful about:

* **The destination is checked by `options.validate`**, which calls
  `config.ensure_outside_source`. The window shows the refusal it gets back
  and does not paraphrase it, and it never decides for itself whether a path
  is acceptable.
* **A run that did not finish says so.** The summary comes from
  `audit_report.json` read back off disk, not from the exit code and not from
  the lines that scrolled past, and a cancelled run that had to be killed says
  that too -- because a killed run without a report must not look like one
  that finished.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QRadioButton,
    QVBoxLayout,
    QWidget,
)

from fpx_converter import batch, config, name_template, outputs
from fpx_converter import layout as layout_mod

# The preview is built by calling the same function the conversion calls,
# not by a second copy of the naming rules living in the window. That is
# the read-only-source rule's shape applied to something smaller: a front
# end that reimplemented this would drift, and a preview that lied about
# where six hundred photographs were going would be worse than none.
from fpx_converter import writer as writer_mod

from . import options as options_mod
from . import progress, runner, summary
from .worker import PipelineWorker

#: Enough scrollback to review a long run without letting a runaway child
#: grow the pane until the machine notices.
MAX_LOG_LINES = 20000


def _card(title: str) -> tuple[QFrame, QVBoxLayout]:
    frame = QFrame()
    frame.setObjectName("Card")
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(20, 16, 20, 18)
    layout.setSpacing(12)
    label = QLabel(title)
    label.setObjectName("CardTitle")
    layout.addWidget(label)
    return frame, layout


def _field_label(text: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName("FieldLabel")
    return label


def _report_stamp(path: Path) -> int | None:
    """`st_mtime_ns` of the audit report, or None if there is not one.

    Compared either side of a run to answer one question: did *this* run write
    a report? A file that is missing both times, or untouched, means no.
    """
    try:
        return path.stat().st_mtime_ns
    except OSError:
        return None


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("FlashPix Converter")
        self.setMinimumSize(920, 760)

        self._worker: PipelineWorker | None = None
        self._tracker = progress.ProgressTracker()
        self._last_options: options_mod.ConvertOptions | None = None
        #: `st_mtime_ns` of the audit report as the run started, or None.
        self._report_stamp: int | None = None
        self._reviewing = False

        root = QWidget()
        root.setObjectName("Root")
        outer = QVBoxLayout(root)
        outer.setContentsMargins(28, 24, 28, 24)
        outer.setSpacing(18)

        outer.addLayout(self._build_header())
        outer.addWidget(self._build_folders_card())
        outer.addWidget(self._build_outputs_card())
        outer.addWidget(self._build_naming_card())
        outer.addLayout(self._build_actions_row())
        outer.addWidget(self._build_progress())
        outer.addLayout(self._build_status())
        outer.addWidget(self._build_log(), stretch=1)

        self.setCentralWidget(root)
        self._sync_enabled()

    # -- construction ----------------------------------------------------

    def _build_header(self) -> QVBoxLayout:
        box = QVBoxLayout()
        box.setSpacing(4)
        title = QLabel("FlashPix Converter")
        title.setObjectName("Title")
        subtitle = QLabel(
            "Converts Kodak .fpx photos into archival TIFFs and shareable JPEGs. "
            "The folder you pick is only ever read from."
        )
        subtitle.setObjectName("Subtitle")
        subtitle.setWordWrap(True)
        box.addWidget(title)
        box.addWidget(subtitle)
        return box

    def _build_folders_card(self) -> QFrame:
        frame, layout = _card("Folders")
        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(10)
        grid.setColumnStretch(1, 1)

        self.source_edit = QLineEdit()
        self.source_edit.setPlaceholderText("The folder holding your .fpx photos")
        source_button = QPushButton("Choose…")
        source_button.clicked.connect(self._choose_source)

        self.dest_edit = QLineEdit()
        self.dest_edit.setPlaceholderText("Where the converted photos should go")
        dest_button = QPushButton("Choose…")
        dest_button.clicked.connect(self._choose_dest)

        grid.addWidget(_field_label("Photos"), 0, 0)
        grid.addWidget(self.source_edit, 0, 1)
        grid.addWidget(source_button, 0, 2)
        grid.addWidget(_field_label("Save into"), 1, 0)
        grid.addWidget(self.dest_edit, 1, 1)
        grid.addWidget(dest_button, 1, 2)

        for edit in (self.source_edit, self.dest_edit):
            edit.textChanged.connect(self._sync_enabled)

        layout.addLayout(grid)
        return frame

    def _tree_row(
        self, label: str, note: str, default_format: str, default_framing: str
    ) -> tuple[QCheckBox, QComboBox, QComboBox, QGridLayout]:
        check = QCheckBox(label)
        check.setChecked(True)
        hint = QLabel(note)
        hint.setObjectName("FieldLabel")

        fmt = QComboBox()
        for name in outputs.FORMATS:
            fmt.addItem(name.upper(), name)
        fmt.setCurrentIndex(list(outputs.FORMATS).index(default_format))

        framing = QComboBox()
        for name in outputs.FRAMINGS:
            framing.addItem(
                "Whole photo" if name == "full" else "Cropped as framed", name
            )
        framing.setCurrentIndex(list(outputs.FRAMINGS).index(default_framing))

        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(4)
        grid.addWidget(check, 0, 0)
        grid.addWidget(fmt, 0, 1)
        grid.addWidget(framing, 0, 2)
        grid.addWidget(hint, 1, 0, 1, 3)
        grid.setColumnStretch(0, 1)

        check.toggled.connect(fmt.setEnabled)
        check.toggled.connect(framing.setEnabled)
        check.toggled.connect(self._sync_enabled)
        return check, fmt, framing, grid

    def _build_outputs_card(self) -> QFrame:
        """Three choices, one at a time, and the detail only where it is wanted.

        This began as two checkboxes and four menus, which is the shape of the
        CLI's flags rather than of anybody's intention. Somebody converting a
        shoebox of photographs wants one of three things, and the two common
        ones want no further questions at all.
        """
        frame, layout = _card("What to write")

        self.mode_group = QButtonGroup(self)
        self.mode_buttons: dict[str, QRadioButton] = {}
        for value, label, hint_text in options_mod.MODE_CHOICES:
            button = QRadioButton(label)
            button.setProperty("mode", value)
            self.mode_group.addButton(button)
            self.mode_buttons[value] = button
            layout.addWidget(button)

            hint = QLabel(hint_text)
            hint.setObjectName("Hint")
            hint.setWordWrap(True)
            hint.setIndent(26)
            layout.addWidget(hint)

        self.mode_buttons[options_mod.ARCHIVE].setChecked(True)
        self.mode_group.buttonToggled.connect(lambda *_: self._sync_enabled())

        # Everything below appears only under Custom.
        self.custom_box = QFrame()
        self.custom_box.setObjectName("CustomBox")
        custom = QVBoxLayout(self.custom_box)
        custom.setContentsMargins(26, 4, 0, 0)
        custom.setSpacing(6)

        self.archive_check, self.archive_format, self.archive_framing, archive_row = (
            self._tree_row(
                "Archive copy",
                "Lossless, every pixel the camera captured.",
                "tiff",
                "full",
            )
        )
        self.sharing_check, self.sharing_format, self.sharing_framing, sharing_row = (
            self._tree_row(
                "Shareable copy",
                "Opens anywhere, cropped as it was framed.",
                "jpeg",
                "cropped",
            )
        )
        custom.addLayout(archive_row)
        custom.addLayout(sharing_row)

        # The extra files, each its own option. They used to be written on
        # every conversion, so asking for one photograph produced four files.
        self.source_copy_check = QCheckBox("Also keep a copy of the original .fpx")
        self.source_copy_check.setToolTip(
            "Off by default. Your source folder is only ever read from and is "
            "still there, so this is a second copy of something that was never "
            "at risk."
        )
        self.sidecar_check = QCheckBox("Also write the raw properties as .fpx.json")
        self.sidecar_check.setToolTip(
            "Off by default. Everything the file holds, as JSON. It can be "
            "rebuilt from the original at any time."
        )
        custom.addWidget(self.source_copy_check)
        custom.addWidget(self.sidecar_check)

        layout.addWidget(self.custom_box)
        self.custom_box.setVisible(False)
        return frame

    def _build_naming_card(self) -> QFrame:
        """Where the files go and what they are called.

        Both apply to all three modes above: naming is a separate question
        from choosing an archive copy over a shareable one.

        The preview shows two photographs, not one, and the second is the
        point. There is no capture date anywhere in this kind of archive, so
        most files can only be filed by their album -- a person needs to see
        what that looks like *before* they run six hundred of them.
        """
        frame, layout = _card("Where they go, and what they are called")

        # -- folders ------------------------------------------------------
        layout.addWidget(_field_label("Folders"))
        self.folder_scheme = QComboBox()
        for value, label, _hint in layout_mod.FOLDER_SCHEMES:
            self.folder_scheme.addItem(label, value)
        self.folder_scheme.setCurrentIndex(
            [v for v, _, _ in layout_mod.FOLDER_SCHEMES].index(layout_mod.BY_ALBUM)
        )
        self.folder_scheme.currentIndexChanged.connect(lambda *_: self._sync_enabled())
        layout.addWidget(self.folder_scheme)

        self.folder_hint = QLabel()
        self.folder_hint.setObjectName("Hint")
        self.folder_hint.setWordWrap(True)
        layout.addWidget(self.folder_hint)

        self.folder_template_edit = QLineEdit(layout_mod.DEFAULT_FOLDER_TEMPLATE)
        self.folder_template_edit.setToolTip(
            "One folder level per /. Folders can use "
            + ", ".join("{" + f + "}" for f in layout_mod.FOLDER_FIELDS)
            + " — for example {year}/{album}. The finer fields belong in the "
            "filename, below."
        )
        self.folder_template_edit.textChanged.connect(lambda *_: self._sync_enabled())
        layout.addWidget(self.folder_template_edit)

        # -- filenames ----------------------------------------------------
        layout.addWidget(_field_label("Filenames"))
        self.name_template_edit = QLineEdit(name_template.DEFAULT_TEMPLATE)
        self.name_template_edit.setToolTip(
            "Fields: "
            + " ".join("{" + n + "}" for n, _ in name_template.FIELDS)
            + ". {name} is required."
        )
        self.name_template_edit.textChanged.connect(lambda *_: self._sync_enabled())

        reset = QPushButton("Reset")
        reset.setObjectName("Secondary")
        reset.clicked.connect(self._reset_patterns)

        row = QHBoxLayout()
        row.setSpacing(8)
        row.addWidget(self.name_template_edit, stretch=1)
        row.addWidget(reset)
        layout.addLayout(row)

        fields = QLabel(
            "Fields: "
            + "  ".join("{" + n + "}" for n, _ in name_template.FIELDS)
            + " — {name} is the filename from your archive, and it has to stay: "
            "those names are the only thing here a person wrote."
        )
        fields.setObjectName("Hint")
        fields.setWordWrap(True)
        layout.addWidget(fields)

        self.name_preview = QLabel()
        self.name_preview.setObjectName("Hint")
        self.name_preview.setWordWrap(True)
        layout.addWidget(self.name_preview)

        self._sync_preview()
        return frame

    def _reset_patterns(self) -> None:
        """Both patterns back to what the tool does on its own."""
        self.name_template_edit.setText(name_template.DEFAULT_TEMPLATE)
        self.folder_template_edit.setText(layout_mod.DEFAULT_FOLDER_TEMPLATE)
        self.folder_scheme.setCurrentIndex(
            [v for v, _, _ in layout_mod.FOLDER_SCHEMES].index(layout_mod.BY_ALBUM)
        )

    def _folder_scheme(self) -> str:
        return self.folder_scheme.currentData()

    #: The two photographs the preview is built from. The first is the lucky
    #: case -- an album that named a day. The second is the common one.
    _PREVIEW_DATED = (
        {"albums": ["Summer 2002"], "preferred_name": "Backyard.fpx"},
        {
            "timestamps": {
                "datetime_original_exif": "2002:07:04 14:32:10",
                "sort_datetime": "2002-07-04T14:32:10",
            }
        },
    )
    _PREVIEW_UNDATED = (
        {"albums": ["Pictures"], "preferred_name": "DCP12345.fpx"},
        {"timestamps": {}},
    )

    def _preview_path(self, entry: dict, derived: dict) -> str:
        rel = writer_mod.build_output_relpath(
            entry,
            derived,
            "jpg",
            None,
            self.name_template_edit.text(),
            self._folder_scheme(),
            self.folder_template_edit.text(),
        )
        return rel.as_posix()

    def _sync_preview(self) -> str:
        """Update the preview. Returns the error text, or "" when it is valid."""
        scheme = self._folder_scheme()
        for value, _label, hint in layout_mod.FOLDER_SCHEMES:
            if value == scheme:
                self.folder_hint.setText(hint)
                break

        try:
            name_template.validate(self.name_template_edit.text())
            if scheme == layout_mod.CUSTOM:
                layout_mod.validate_folder_template(self.folder_template_edit.text())
        except name_template.TemplateError as exc:
            self.name_preview.setText(str(exc))
            self.name_preview.setProperty("severity", "bad")
            self.name_preview.style().polish(self.name_preview)
            return str(exc)

        dated = self._preview_path(*self._PREVIEW_DATED)
        undated = self._preview_path(*self._PREVIEW_UNDATED)
        self.name_preview.setText(
            "\n".join(
                [
                    f"A photo whose album named the day:  {dated}",
                    f"One with nothing to date it — most of them:  {undated}",
                ]
            )
        )
        self.name_preview.setProperty("severity", "")
        self.name_preview.style().polish(self.name_preview)
        return ""

    def _build_actions_row(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(12)
        self.convert_button = QPushButton("Convert")
        self.convert_button.setObjectName("Primary")
        self.convert_button.clicked.connect(self._start_convert)

        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.clicked.connect(self._cancel)
        self.cancel_button.setEnabled(False)

        self.review_button = QPushButton("Open review page")
        self.review_button.setToolTip(
            "Builds a page showing every converted photo, and lets you fill in "
            "the dates only you know."
        )
        self.review_button.clicked.connect(self._start_review)

        row.addWidget(self.convert_button)
        row.addWidget(self.cancel_button)
        row.addStretch(1)
        row.addWidget(self.review_button)
        return row

    def _build_progress(self) -> QProgressBar:
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(False)
        return self.progress_bar

    def _build_status(self) -> QVBoxLayout:
        """The line a person reads first when a run ends, and the detail under it."""
        self._headline = QLabel("Pick a folder of photos and a place to put them.")
        self._headline.setObjectName("Headline")
        self._headline.setWordWrap(True)
        self._headline.setProperty("severity", "")

        self._detail = QLabel("")
        self._detail.setObjectName("Detail")
        self._detail.setWordWrap(True)
        self._detail.setTextInteractionFlags(Qt.TextSelectableByMouse)

        box = QVBoxLayout()
        box.setSpacing(4)
        box.addWidget(self._headline)
        box.addWidget(self._detail)
        return box

    def _build_log(self) -> QPlainTextEdit:
        self.log = QPlainTextEdit()
        self.log.setObjectName("Log")
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(MAX_LOG_LINES)
        self.log.setPlaceholderText("What the converter is doing appears here.")
        return self.log

    # -- state -----------------------------------------------------------

    def _mode(self) -> str:
        """Which of the three is selected."""
        for value, button in self.mode_buttons.items():
            if button.isChecked():
                return value
        return options_mod.ARCHIVE

    def current_options(self) -> options_mod.ConvertOptions:
        """Everything the window has configured, as the CLI would receive it."""
        return options_mod.ConvertOptions(
            source=Path(self.source_edit.text().strip()),
            dest=Path(self.dest_edit.text().strip()),
            mode=self._mode(),
            archive=self.archive_check.isChecked(),
            sharing=self.sharing_check.isChecked(),
            source_copy=self.source_copy_check.isChecked(),
            sidecar=self.sidecar_check.isChecked(),
            name_template=self.name_template_edit.text(),
            folder_scheme=self._folder_scheme(),
            folder_template=self.folder_template_edit.text(),
            archive_format=self.archive_format.currentData(),
            archive_framing=self.archive_framing.currentData(),
            sharing_format=self.sharing_format.currentData(),
            sharing_framing=self.sharing_framing.currentData(),
        )

    def _running(self) -> bool:
        return self._worker is not None

    def _sync_enabled(self) -> None:
        idle = not self._running()
        has_folders = bool(self.source_edit.text().strip() and self.dest_edit.text().strip())
        custom = self._mode() == options_mod.CUSTOM
        self.custom_box.setVisible(custom)
        wants_output = (not custom) or (
            self.archive_check.isChecked() or self.sharing_check.isChecked()
        )
        # A pattern that would lose the archive's filenames, or produce one no
        # filesystem will take, stops the run here rather than after it has
        # renamed half a tree.
        # The folder pattern is only a question under 'Custom'.
        self.folder_template_edit.setVisible(
            self._folder_scheme() == layout_mod.CUSTOM
        )
        self.folder_template_edit.setEnabled(idle)
        name_ok = not self._sync_preview()
        self.convert_button.setEnabled(idle and has_folders and wants_output and name_ok)
        self.cancel_button.setEnabled(not idle)
        self.review_button.setEnabled(idle and has_folders)
        for widget in (
            self.source_edit, self.dest_edit,
            self.archive_check, self.sharing_check,
            self.source_copy_check, self.sidecar_check,
            self.name_template_edit,
            self.folder_scheme,
            *self.mode_buttons.values(),
        ):
            widget.setEnabled(idle)
        self.archive_format.setEnabled(idle and self.archive_check.isChecked())
        self.archive_framing.setEnabled(idle and self.archive_check.isChecked())
        self.sharing_format.setEnabled(idle and self.sharing_check.isChecked())
        self.sharing_framing.setEnabled(idle and self.sharing_check.isChecked())

    def _say(self, headline: str, severity: str = "", detail: str = "") -> None:
        self._headline.setText(headline)
        self._headline.setProperty("severity", severity)
        # Qt only re-evaluates a property selector when the style is reapplied.
        self._headline.style().unpolish(self._headline)
        self._headline.style().polish(self._headline)
        self._detail.setText(detail)

    def _append(self, line: str) -> None:
        self.log.appendPlainText(line)

    # -- folder pickers --------------------------------------------------

    def _choose_source(self) -> None:
        chosen = QFileDialog.getExistingDirectory(
            self, "Choose the folder holding your .fpx photos", self.source_edit.text()
        )
        if chosen:
            self.source_edit.setText(chosen)

    def _choose_dest(self) -> None:
        chosen = QFileDialog.getExistingDirectory(
            self, "Choose where the converted photos should go", self.dest_edit.text()
        )
        if chosen:
            self.dest_edit.setText(chosen)

    # -- running ---------------------------------------------------------

    def _start_convert(self) -> None:
        self._reviewing = False
        options = self.current_options()
        try:
            specs = options_mod.validate(options)
        except (config.ConfigError, config.SourceWriteRefused, outputs.OutputSpecError) as exc:
            # The message comes from the CLI's own guard, verbatim. The window
            # is not the authority on any of these and must not sound like it.
            QMessageBox.warning(self, "That cannot be converted", str(exc))
            return

        self.log.clear()
        self._tracker = progress.ProgressTracker()
        self._last_options = options
        # Stamped before the run so that afterwards we can tell a report this
        # run wrote from one that was already lying there. Without this a
        # failed run over a previously-converted destination read the old
        # report and announced a clean finish.
        self._report_stamp = _report_stamp(options.dest / batch.REPORT_FILENAME)
        self.progress_bar.setRange(0, 0)  # indeterminate until the total is known
        self._say("Starting…", "")
        self._append(f"Writing: {', '.join(spec.label for spec in specs)}")
        self._run(options_mod.convert_pipeline(options))

    def _start_review(self) -> None:
        self._reviewing = True
        options = self.current_options()
        try:
            options_mod.validate(options)
        except (config.ConfigError, config.SourceWriteRefused, outputs.OutputSpecError) as exc:
            QMessageBox.warning(self, "That cannot be reviewed", str(exc))
            return
        if not (options.dest / batch.REPORT_FILENAME).is_file():
            QMessageBox.information(
                self,
                "Nothing to review yet",
                "There is no finished run in that folder. Convert some photos first.",
            )
            return
        self._last_options = options
        self.progress_bar.setRange(0, 0)
        self._say("Building the review page…", "")
        self._run(options_mod.review_pipeline(options))

    def _run(self, steps: list[tuple[str, list[str]]]) -> None:
        stop_file = self._last_options.stop_file if self._last_options else None
        worker = PipelineWorker(steps, parent=self, stop_file=stop_file)
        worker.line.connect(self._on_line)
        worker.step.connect(self._on_step)
        worker.done.connect(self._on_done)
        self._worker = worker
        self._sync_enabled()
        worker.start()

    def _on_step(self, label: str, index: int, total: int) -> None:
        self._append(f"--- {label} ({index} of {total})")
        self._say(f"{label}…", "")

    def _on_line(self, line: str) -> None:
        self._append(line)
        if self._reviewing:
            return
        if self._tracker.feed(line):
            fraction = self._tracker.fraction
            if fraction is None:
                return
            if self.progress_bar.maximum() == 0:
                self.progress_bar.setRange(0, 100)
            self.progress_bar.setValue(int(fraction * 100))

    def _on_done(self, code: int, cancel_status: str) -> None:
        self._worker = None
        self.progress_bar.setRange(0, 100)
        self._sync_enabled()

        if cancel_status == runner.HARD_STOPPED:
            # Said out loud, because this is the one ending that leaves no
            # trustworthy record of itself.
            self._append(
                "The converter did not stop when asked and had to be killed. "
                "No audit report was written for this run."
            )
            self._say(
                "Killed — no audit report was written for this run",
                summary.ERROR,
                "The photos already converted are still there and are still good. "
                "Press Convert again to carry on; it will skip what is done.",
            )
            return

        if self._reviewing:
            self._finish_review(code)
            return

        if cancel_status == runner.CANCELLED:
            self._append("Stopped at your request; the report below covers what it did.")

        options = self._last_options
        if options is None:  # pragma: no cover - only reachable before a run
            return
        report_path = options.dest / batch.REPORT_FILENAME
        if _report_stamp(report_path) == self._report_stamp:
            # Nothing was written this run, so anything on disk belongs to a
            # previous one. Reporting it would be the worst kind of wrong: a
            # confident success, phrased for somebody with no other way to
            # check.
            self._append(
                "This run wrote no audit report, so there is nothing to summarise. "
                "Any report already in that folder is from an earlier run."
            )
            result = summary.MISSING_REPORT
        else:
            result = summary.load_summary(report_path)
        self.progress_bar.setValue(100 if result.finished_cleanly else self.progress_bar.value())
        self._say(result.headline, result.severity, "  ".join(result.lines))

    def _finish_review(self, code: int) -> None:
        options = self._last_options
        page = options.report_page if options else None
        if code != 0 or page is None or not page.is_file():
            self._say(
                "The review page could not be built",
                summary.ERROR,
                "The log above says why.",
            )
            return
        self._say("Review page ready", summary.OK, str(page))
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(page)))

    def _cancel(self) -> None:
        worker = self._worker
        if worker is None:
            return
        self.cancel_button.setEnabled(False)
        self._append(
            "Asking the converter to stop after the photo it is on, so it can "
            "finish writing its report…"
        )
        self._say("Stopping…", summary.WARN)
        # Returns at once; the window keeps painting and `_on_done` reports
        # the ending when the child has actually stopped.
        worker.cancel()

    def closeEvent(self, event) -> None:  # noqa: ANN001, N802 -- Qt signature
        """Do not leave a conversion running with nothing watching it."""
        if self._running():
            answer = QMessageBox.question(
                self,
                "A conversion is still running",
                "Stop it and close? It will finish the photo it is on and write "
                "its report first.",
            )
            if answer != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
            self._cancel()
            # Here, and only here, the wait is the right thing: once this
            # window is gone nothing is left watching the converter, so it has
            # to be stopped before the window goes.
            worker = self._worker
            if worker is not None:
                worker.cancel(wait=True)
        event.accept()
