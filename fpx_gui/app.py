"""Starting the application: one window, styled to follow the system theme.

Separate from `window` so importing the window class costs no `QApplication`,
and separate from `__main__` so the sentinel dispatch there stays free of Qt.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from . import style
from .window import APP_TITLE, MainWindow

#: One name, taken from the window rather than typed again. The program, the
#: window and the executable all being called the same thing is the point.
APP_NAME = APP_TITLE


def system_is_dark(app: QApplication) -> bool:
    """Whether the desktop is in dark mode, as far as Qt can tell.

    `colorScheme` is the modern answer and is what Windows actually reports.
    Older Qt builds have no such thing, and rather than guess, an unknown
    answer means light -- the theme the stylesheet defines outright.
    """
    hints = app.styleHints()
    scheme = getattr(hints, "colorScheme", None)
    if scheme is None:  # pragma: no cover - Qt older than 6.5
        return False
    return scheme() == Qt.ColorScheme.Dark


def apply_theme(app: QApplication) -> None:
    app.setStyleSheet(style.build_stylesheet(system_is_dark(app)))


def run(argv: list[str] | None = None) -> int:
    app = QApplication(list(argv or []))
    app.setApplicationName(APP_NAME)
    app.setOrganizationName("fpx-converter")
    apply_theme(app)

    hints = app.styleHints()
    changed = getattr(hints, "colorSchemeChanged", None)
    if changed is not None:  # pragma: no cover - depends on the desktop
        changed.connect(lambda _scheme: apply_theme(app))

    window = MainWindow()
    window.show()
    return app.exec()
