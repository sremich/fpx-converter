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

import os
from pathlib import Path

from PySide6.QtCore import QRect, Qt, QUrl
from PySide6.QtGui import QAction, QDesktopServices
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
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
    QScrollArea,
    QTabWidget,
    QTextBrowser,
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

from . import notices, progress, runner, summary
from . import options as options_mod
from .worker import InstallWorker, PipelineWorker

#: Enough scrollback to review a long run without letting a runaway child
#: grow the pane until the machine notices.
MAX_LOG_LINES = 20000

#: What the application calls itself, everywhere. One string: the window
#: title, the title label and `app.APP_NAME` disagreeing is how a program ends
#: up with three names, and this one is also the name of the executable.
APP_TITLE = "FPX Converter"


class LicenceDialog(QDialog):
    """What this program is made of, and the full text of the terms.

    A downloaded executable travels alone. There is no folder of licence files
    beside it and nowhere else for a person to look, so the notice has to be
    inside the binary and reachable from the window -- which for LGPLv3
    section 4 is not a courtesy.

    Scrollable and reachable from the keyboard: the tabs take arrow keys, each
    pane is a focusable read-only browser that scrolls, and Close is the
    default button. A notice nobody can page through is not a notice.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"{APP_TITLE} — licences")
        self.resize(760, 560)

        self.tabs = QTabWidget()
        self.tabs.addTab(_licence_pane(notices.notice_text()), "This program")
        for name, label in (
            (notices.APACHE_2_0, "Apache-2.0"),
            (notices.LGPL_3_0, "LGPL-3.0"),
            (notices.GPL_3_0, "GPL-3.0"),
        ):
            self.tabs.addTab(_licence_pane(notices.read_licence(name)), label)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)

        layout = QVBoxLayout(self)
        layout.addWidget(self.tabs)
        layout.addWidget(buttons)

    def pane_text(self, index: int) -> str:
        """What one tab is showing. For the tests, which cannot read a screen."""
        return self.tabs.widget(index).toPlainText()


def _licence_pane(text: str) -> QTextBrowser:
    """One scrollable, selectable, keyboard-reachable pane of plain text."""
    pane = QTextBrowser()
    # Plain text, deliberately: these are documents with their own line
    # breaks, and letting a rich-text engine reflow a licence is how a licence
    # stops looking like the document it has to be a copy of.
    pane.setPlainText(text)
    pane.setLineWrapMode(QTextBrowser.LineWrapMode.WidgetWidth)
    pane.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
    return pane


def _card(title: str) -> tuple[QFrame, QVBoxLayout]:
    frame = QFrame()
    frame.setObjectName("Card")
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(20, 14, 20, 16)
    layout.setSpacing(10)
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
        self.setWindowTitle(APP_TITLE)

        self._worker: PipelineWorker | None = None
        self._tracker = progress.ProgressTracker()
        self._last_options: options_mod.ConvertOptions | None = None
        #: `st_mtime_ns` of the audit report as the run started, or None.
        self._report_stamp: int | None = None
        self._reviewing = False
        #: Where ExifTool is, or None if it could not be found. Resolved here
        #: and after an install or a locate, never from `_sync_enabled` --
        #: that runs on every keystroke, and this is a disk search.
        self._exiftool: str | None = None
        self._installer: InstallWorker | None = None

        root = QWidget()
        root.setObjectName("Root")
        outer = QVBoxLayout(root)
        outer.setContentsMargins(28, 22, 28, 22)
        outer.setSpacing(14)

        outer.addLayout(self._build_header())
        outer.addWidget(self._build_folders_card())
        # Before the options, because it is the thing that stops the run, and
        # after the folders, because picking those is what a person came here
        # to do. Hidden outright when ExifTool is present, which is almost
        # always: a card that says "nothing is wrong" on every launch trains
        # people to stop reading the cards.
        outer.addWidget(self._build_exiftool_card())
        outer.addWidget(self._build_outputs_card())
        outer.addWidget(self._build_naming_card())
        outer.addWidget(self._build_timezone_card())
        outer.addLayout(self._build_actions_row())
        outer.addWidget(self._build_progress())
        outer.addLayout(self._build_status())
        outer.addWidget(self._build_log(), stretch=1)

        # In a scroll area, so a window shorter than its contents scrolls
        # rather than squeezing them. The natural height is over a thousand
        # pixels, which does not fit a 1366x768 laptop with a taskbar, and the
        # failure mode without this is silent: every card is still there,
        # every one of them unreadable.
        scroller = QScrollArea()
        scroller.setObjectName("Scroller")
        scroller.setWidget(root)
        scroller.setWidgetResizable(True)
        scroller.setFrameShape(QFrame.Shape.NoFrame)
        scroller.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setCentralWidget(scroller)

        self._build_menus()
        # Before the sizing pass, so a window that has to show the ExifTool
        # card opens tall enough for it.
        self._refresh_exiftool()
        self._size_to_contents()
        self._sync_enabled()

    #: What the window opens at, before the screen gets a say. Wide enough
    #: that the explanatory lines under each control wrap once rather than
    #: three times, which is most of what decides the height.
    PREFERRED_WIDTH = 980

    #: Room for a few lines of log beyond the layout's own minimum, so a run
    #: can be watched without resizing first.
    LOG_ROOM = 90

    def content_height_at(self, width: int) -> int:
        """How tall the contents actually are, given this window width.

        `sizeHint` is the wrong question: half of this window is wrapped text,
        and a wrapped label's hint is measured at the layout's own preferred
        width -- far narrower than the window ever is -- so it reports a third
        more height than the content occupies.
        """
        root = self.centralWidget().widget()
        layout = root.layout()
        # Invalidate first. `activate()` recomputes only what is already
        # marked dirty, and showing or hiding a child does not mark it -- so
        # measuring twice around a visibility change returned the first
        # answer both times, and the window sized itself for a panel it had
        # just been told about.
        layout.invalidate()
        layout.activate()
        margins = root.contentsMargins()
        return layout.minimumHeightForWidth(width - margins.left() - margins.right())

    def tallest_content_height(self, width: int) -> int:
        """The same, for whichever mode needs the most room.

        Custom shows a panel the two named modes do not, and a hidden widget
        counts as nothing to a layout. Measuring the mode that happens to be
        selected therefore sizes the window for the smallest of the three, and
        picking Custom afterwards puts a scrollbar on a window with a screen's
        worth of room around it -- a smaller version of exactly the complaint
        this sizing work exists to answer.

        The ExifTool card is measured the same way and for the same reason.
        It is hidden on almost every machine, so a window sized without it
        would be too short on exactly the machines that have to read it --
        which are the ones whose owner has the least idea what is wrong.

        What is saved and restored is `isHidden`, not `isVisible`. They are
        different questions: `isVisible` is false for every child of a window
        that has not been shown yet, which is precisely the state this runs in
        -- it is called from `__init__`. Restoring from it therefore hid
        whatever it had just been asked to measure. `custom_box` survived that
        because `_sync_enabled` sets its visibility again a line later; the
        ExifTool card had nothing to put it back, so a machine with no
        ExifTool got a window that had measured the card and then hidden it.
        """
        conditional = (self.custom_box, self.exiftool_card)
        was_hidden = [widget.isHidden() for widget in conditional]
        for widget in conditional:
            widget.setVisible(True)
        try:
            return self.content_height_at(width)
        finally:
            for widget, hidden in zip(conditional, was_hidden, strict=True):
                widget.setVisible(not hidden)

    def _size_to_contents(self, available: QRect | None = None) -> None:
        """Open at the size the layout says it needs, within the screen there is.

        Asked of the layout rather than typed. The previous `(920, 760)` was
        right for the window as it stood and silently wrong the moment a card
        was added: it let Qt open the window nearly 300 pixels shorter than its
        own content needed and squeeze every widget to fit, which is what the
        user saw -- three radio buttons collapsed to underscores and an
        empty card.

        `available` defaults to the screen's usable area and is passed by the
        tests, which would otherwise inherit the offscreen platform's 800x800
        display and could not tell a window that fits from one that does not.
        """
        if available is None:
            screen = self.screen()
            available = screen.availableGeometry() if screen is not None else None

        # Leaving room for the title bar and border, which `availableGeometry`
        # does not account for.
        max_w = available.width() - 40 if available is not None else self.PREFERRED_WIDTH
        max_h = available.height() - 60 if available is not None else 1000

        width = min(self.PREFERRED_WIDTH, max_w)

        # The width has to stay honest -- squeeze it and the explanatory lines
        # wrap away into nothing, and they are the point of them. The height
        # does not, because the scroll area handles a window shorter than its
        # contents, and on an ordinary 1080p display this content is taller
        # than the screen whatever is done to it.
        self.setMinimumWidth(min(760, max_w))
        self.setMinimumHeight(min(520, max_h))
        self.resize(width, min(self.tallest_content_height(width) + self.LOG_ROOM, max_h))

    # -- construction ----------------------------------------------------

    def _build_menus(self) -> None:
        """One menu, for the one thing a menu bar is needed for.

        The window is a single screen and wants no menus. It gets one anyway,
        because a standalone executable carries no licence files beside it and
        the notice has to be reachable from inside the program.
        """
        help_menu = self.menuBar().addMenu("&Help")
        self.licences_action = QAction("&Licences…", self)
        self.licences_action.triggered.connect(self._show_licences)
        help_menu.addAction(self.licences_action)

    def _show_licences(self) -> None:
        LicenceDialog(self).exec()

    def _build_header(self) -> QVBoxLayout:
        box = QVBoxLayout()
        box.setSpacing(4)
        title = QLabel(APP_TITLE)
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

    def _build_exiftool_card(self) -> QFrame:
        """The one dependency this app cannot install for itself at build time.

        ExifTool writes every tag this tool produces and is a separate program
        with its own licence, so it is not bundled. Until now the window knew
        nothing about that: a person pressed Convert, the child process
        refused, and the reason arrived in the log pane as a line telling them
        to open PowerShell and type a command. That is a fair thing to ask of
        someone who already uses a terminal and a wall for everybody else --
        and it arrived *after* they had chosen their folders and committed to
        a run, which is the worst moment to discover a missing dependency.

        So the check happens when the window opens, and the two ways out are
        buttons.

        The *diagnosis* is `writer.EXIFTOOL_MISSING_DIAGNOSIS`, shared with the
        command line, because two descriptions of one condition drift. The
        *remedy* is not shared: the CLI's full message ends "Then re-run. If it
        is installed somewhere off PATH, point at it with --exiftool" -- advice
        that is simply wrong in front of somebody who has an Install button, a
        file picker, and no run to re-run.
        """
        frame, layout = _card("ExifTool is needed, and is not installed")
        self.exiftool_card = frame

        self.exiftool_hint = QLabel()
        self.exiftool_hint.setObjectName("Hint")
        self.exiftool_hint.setWordWrap(True)
        layout.addWidget(self.exiftool_hint)

        row = QHBoxLayout()
        self.exiftool_install_button = QPushButton("Install ExifTool")
        self.exiftool_install_button.setObjectName("Primary")
        self.exiftool_install_button.setToolTip(
            "Installs ExifTool using the package manager this platform ships "
            "with. The exact command is shown before anything runs."
        )
        self.exiftool_install_button.clicked.connect(self._install_exiftool)

        self.exiftool_locate_button = QPushButton("Locate exiftool.exe…")
        self.exiftool_locate_button.setObjectName("Secondary")
        self.exiftool_locate_button.setToolTip(
            "Point at a copy you already have. Remembered, so this is asked "
            "once."
        )
        self.exiftool_locate_button.clicked.connect(self._locate_exiftool)

        row.addWidget(self.exiftool_install_button)
        row.addWidget(self.exiftool_locate_button)
        row.addStretch(1)
        layout.addLayout(row)
        return frame

    def _refresh_exiftool(self) -> str | None:
        """Look for ExifTool, update the card, and return what was found.

        The lookup is `writer.resolve_exiftool_path`, which is the same
        function the conversion itself uses -- explicit path, then
        `FPX_EXIFTOOL` from the environment or `.env`, then PATH. A second
        copy of that order living in the window would be a second thing to get
        wrong, and the failure it would cause is a window that says ExifTool
        is missing while the converter finds it, or worse the other way round.
        """
        self._exiftool = writer_mod.resolve_exiftool_path()
        if hasattr(self, "exiftool_card"):
            missing = self._exiftool is None
            self.exiftool_card.setVisible(missing)
            if missing:
                self.exiftool_hint.setText(
                    f"{writer_mod.EXIFTOOL_MISSING_DIAGNOSIS} It is free, it is "
                    "quick to install, and it is the last thing standing between "
                    "you and a conversion."
                )
                self.exiftool_hint.setProperty("severity", "bad")
                self.exiftool_hint.style().polish(self.exiftool_hint)
            # No install button where there is no known way to install: an
            # offer that cannot be honoured is worse than not offering.
            self.exiftool_install_button.setVisible(
                runner.exiftool_install_argv() is not None
            )
        return self._exiftool

    def _install_exiftool(self) -> None:
        """Run the platform's installer, having said exactly what it will do.

        Asked, not assumed -- the same rule the review page's copy notice
        follows. The command accepts a package agreement on the user's behalf,
        because a winget that stops to ask gets no answer from a child with no
        stdin; agreeing to somebody else's licence terms is theirs to do, so
        the terms it accepts are named before the button that accepts them.
        """
        argv = runner.exiftool_install_argv()
        if argv is None:  # pragma: no cover - the button is hidden in this case
            return
        answer = QMessageBox.question(
            self,
            "Install ExifTool",
            "This runs the command below, which downloads and installs "
            "ExifTool from its publisher.\n\n"
            f"    {' '.join(argv)}\n\n"
            "It accepts the package source's terms and ExifTool's own licence "
            "on your behalf — ExifTool is free software, under the Perl "
            "Artistic Licence or the GPL, at your option.\n\n"
            "Nothing else on this computer is changed, and your photographs "
            "are not touched.\n\n"
            "Go ahead?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self._say("Installing ExifTool…", "")
        self.exiftool_install_button.setEnabled(False)
        self.exiftool_locate_button.setEnabled(False)
        worker = InstallWorker(parent=self)
        # `_append`, not `_on_line`: the installer's output goes in the log
        # pane, but it is not conversion output and must not be fed to the
        # progress tracker, whose job is counting photographs.
        worker.line.connect(self._append)
        worker.done.connect(self._on_install_done)
        self._installer = worker
        worker.start()

    def _on_install_done(self, code: int) -> None:
        """Report on what is true now, not on what the installer claimed.

        An installer that exits 0 having put ExifTool somewhere that is not on
        this process's PATH is a real outcome -- a new PATH entry does not
        reach an already-running program -- and it is indistinguishable from
        success unless the question asked afterwards is "can it be found?"
        rather than "did that work?".
        """
        self._installer = None
        self.exiftool_install_button.setEnabled(True)
        self.exiftool_locate_button.setEnabled(True)
        if self._refresh_exiftool() is not None:
            self._say("ExifTool is installed. Ready to convert.", summary.OK)
        elif code == 0:
            self._say(
                "The installer finished, but ExifTool still cannot be found.",
                summary.WARN,
                "It may need this app restarted so it picks up the new PATH, "
                "or you can point at it with Locate.",
            )
        else:
            self._say(
                "That did not install ExifTool.",
                summary.ERROR,
                "The log below has what the installer said. You can install "
                "it yourself and then use Locate.",
            )
        self._sync_enabled()

    def _locate_exiftool(self) -> None:
        """Point at an existing copy, and remember it.

        Remembered by writing `FPX_EXIFTOOL` to the user's `.env`, which is a
        file `config.load_env` already reads and `resolve_exiftool_path`
        already consults -- so the command line picks up the same answer, and
        a person who runs both does not have to tell each of them separately.
        """
        pattern = "ExifTool (exiftool.exe)" if os.name == "nt" else "ExifTool (exiftool)"
        chosen, _filter = QFileDialog.getOpenFileName(
            self, "Where is ExifTool?", "", f"{pattern};;All files (*)"
        )
        if not chosen:
            return
        resolved = writer_mod.resolve_exiftool_path(chosen)
        if resolved is None:
            QMessageBox.warning(
                self,
                "That is not ExifTool",
                f"{chosen}\n\nThat file could not be used as ExifTool. Look "
                "for exiftool.exe inside the folder you unzipped.",
            )
            return
        try:
            written = config.set_env_value("FPX_EXIFTOOL", resolved)
        except config.ConfigError as exc:
            # Finding it still counts for this session even if remembering it
            # failed, so this reports rather than refuses.
            QMessageBox.warning(self, "That could not be remembered", str(exc))
        else:
            self._append(f"Remembered ExifTool in {written}")
        os.environ["FPX_EXIFTOOL"] = resolved
        self._refresh_exiftool()
        self._say("ExifTool found. Ready to convert.", summary.OK)
        self._sync_enabled()

    def _build_outputs_card(self) -> QFrame:
        """Three choices, one at a time, each writing one image per photograph.

        This began as two checkboxes and four menus, which is the shape of the
        CLI's flags rather than of anybody's intention. Somebody converting a
        shoebox of photographs wants one of three things, and the two common
        ones want no further questions at all.

        Custom asks two, and deliberately not a third: choosing between an
        archive copy and a shareable one *is* the choice above it, and offering
        it again in here would let somebody tick neither and then wonder why
        Convert had greyed itself out.
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
        custom.setContentsMargins(26, 2, 0, 0)
        custom.setSpacing(8)

        # Both menus are captioned. They used to sit under a checkbox naming
        # the tree, which said what they were for; without it two bare boxes
        # reading "TIFF" and "Whole photo" control nothing a reader can name --
        # in the release whose premise is that this window was unreadable.
        self.custom_format = QComboBox()
        for name in outputs.FORMATS:
            self.custom_format.addItem(name.upper(), name)
        self.custom_format.setCurrentIndex(list(outputs.FORMATS).index("tiff"))
        self.custom_format.setToolTip(
            "TIFF keeps every pixel and is the archival choice. JPEG is "
            "smaller and opens anywhere."
        )

        self.custom_framing = QComboBox()
        for name in outputs.FRAMINGS:
            self.custom_framing.addItem(
                "Whole photo" if name == "full" else "Cropped as framed", name
            )
        self.custom_framing.setCurrentIndex(list(outputs.FRAMINGS).index("full"))
        self.custom_framing.setToolTip(
            "Some photos carry a crop somebody framed in the Kodak software. "
            "Whole photo ignores that and keeps everything the camera "
            "captured; cropped gives you the picture as it was framed."
        )

        row = QHBoxLayout()
        row.setSpacing(10)
        for caption, combo in (
            ("File type", self.custom_format),
            ("Framing", self.custom_framing),
        ):
            column = QVBoxLayout()
            column.setSpacing(2)
            label = QLabel(caption)
            label.setObjectName("Hint")
            column.addWidget(label)
            column.addWidget(combo)
            row.addLayout(column)
        row.addStretch(1)
        custom.addLayout(row)

        # And where it lands, because Custom no longer has a control that says
        # so. The tree follows the framing, which is this project's rule rather
        # than a preference: archive/ keeps the full frame, sharing/ gets the
        # crop. Written by asking `ConvertOptions`, not by a second copy of
        # that rule living here.
        self.custom_destination = QLabel()
        self.custom_destination.setObjectName("Hint")
        self.custom_destination.setWordWrap(True)
        custom.addWidget(self.custom_destination)
        self.custom_format.currentIndexChanged.connect(self._sync_custom_destination)
        self.custom_framing.currentIndexChanged.connect(self._sync_custom_destination)

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

        self._sync_custom_destination()
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
            "  ".join("{" + n + "}" for n, _ in name_template.FIELDS)
            + " — {name} has to stay. Those names are the only thing in your "
            "archive that a person wrote."
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

    def _build_timezone_card(self) -> QFrame:
        """Which zone the photographs were taken in.

        Every other control in this window is zero-config and this one cannot
        be, because there is no answer a program can work out. The zone decides
        the UTC offset recorded beside each timestamp, and a wrong offset looks
        exactly like a right one for ever afterwards -- so where this machine's
        zone is not one the converter recognises, the box is left empty and the
        question is asked rather than answered on the user's behalf.

        Editable, not a fixed list: the drop-down offers the zones the
        converter knows today, and anything else typed in is refused by the
        converter itself with its own message rather than by a second opinion
        living here.
        """
        frame, layout = _card("Time zone")

        self.timezone_combo = QComboBox()
        self.timezone_combo.setEditable(True)
        self.timezone_combo.addItems(options_mod.known_timezones())
        detected = options_mod.detect_timezone()
        self.timezone_combo.setCurrentText(detected)
        edit = self.timezone_combo.lineEdit()
        if edit is not None:
            edit.setPlaceholderText("Leave empty to let the converter decide")
        self.timezone_combo.setToolTip(
            "The zone these photographs were taken in. It only decides the "
            "UTC offset written beside each timestamp; it never shifts the "
            "time itself."
        )
        layout.addWidget(self.timezone_combo)

        hint = QLabel(
            "Left empty because this computer's zone is not one the converter "
            "knows — a wrong offset is written as confidently as a right one, "
            "so it asks rather than guesses."
            if not detected
            else "Taken from this computer. Change it if these photographs "
            "were taken somewhere else."
        )
        hint.setObjectName("Hint")
        hint.setWordWrap(True)
        layout.addWidget(hint)
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
                    f"Dated by its album:  {dated}",
                    f"Nothing to date it (most of them):  {undated}",
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
            "the dates only you know. It first copies one .fpx per photo into "
            "the destination, and asks before it does."
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
            source_copy=self.source_copy_check.isChecked(),
            sidecar=self.sidecar_check.isChecked(),
            name_template=self.name_template_edit.text(),
            folder_scheme=self._folder_scheme(),
            folder_template=self.folder_template_edit.text(),
            custom_format=self.custom_format.currentData(),
            custom_framing=self.custom_framing.currentData(),
            timezone=self.timezone_combo.currentText().strip(),
        )

    def _running(self) -> bool:
        return self._worker is not None

    def _sync_custom_destination(self) -> None:
        """Say which folder Custom writes into, in the window rather than in
        the docs. `tree_format_framing` is the authority; this reads it."""
        tree, fmt, _ = options_mod.ConvertOptions(
            source=Path(), dest=Path(),
            mode=options_mod.CUSTOM,
            custom_format=self.custom_format.currentData(),
            custom_framing=self.custom_framing.currentData(),
        ).tree_format_framing()
        suffix = "tif" if fmt == "tiff" else "jpg"
        self.custom_destination.setText(f"Writes one .{suffix} per photo into {tree}/")

    def _sync_enabled(self) -> None:
        idle = not self._running()
        has_folders = bool(self.source_edit.text().strip() and self.dest_edit.text().strip())
        # Every mode writes one image, so there is no longer a combination of
        # controls that would produce nothing and have to be refused.
        self.custom_box.setVisible(self._mode() == options_mod.CUSTOM)
        # A pattern that would lose the archive's filenames, or produce one no
        # filesystem will take, stops the run here rather than after it has
        # renamed half a tree.
        # The folder pattern is only a question under 'Custom'.
        self.folder_template_edit.setVisible(
            self._folder_scheme() == layout_mod.CUSTOM
        )
        self.folder_template_edit.setEnabled(idle)
        name_ok = not self._sync_preview()
        # Cached, not re-resolved: this method runs on every keystroke in both
        # folder boxes, and resolving means searching PATH.
        exiftool_ok = self._exiftool is not None
        self.convert_button.setEnabled(idle and has_folders and name_ok and exiftool_ok)
        self.cancel_button.setEnabled(not idle)
        # **Not** gated on ExifTool. The review page runs `ingest` and
        # `gallery`, and neither writes a tag -- disabling it for a dependency
        # it does not use would take away the one thing somebody without
        # ExifTool can still do with their photographs.
        self.review_button.setEnabled(idle and has_folders)
        for widget in (
            self.source_edit, self.dest_edit,
            self.source_copy_check, self.sidecar_check,
            self.custom_format, self.custom_framing,
            self.name_template_edit,
            self.folder_scheme,
            self.timezone_combo,
            *self.mode_buttons.values(),
        ):
            widget.setEnabled(idle)

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
        # Asked, not assumed. Building the page runs `ingest`, which copies one
        # `.fpx` per distinct photograph into the destination -- a substantial
        # amount of disk, and the opposite of what a person is told elsewhere
        # in this window, where keeping the originals is an option they have to
        # tick. A button that quietly does the thing the checkbox is for is a
        # surprise, and this is the kind of surprise that fills a disk.
        answer = QMessageBox.question(
            self,
            "This will copy your photos",
            options_mod.review_copy_notice(options),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if answer != QMessageBox.StandardButton.Yes:
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
