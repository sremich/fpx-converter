"""The frozen application's entry script.

PyInstaller runs this as a top-level script, so it cannot be
`fpx_gui/__main__.py` itself -- that module uses relative imports and needs a
package. This exists only to hand control over.

The exe wears two hats and this is where they are told apart: launched
normally it opens the window, and launched with `--run-cli` in front of the
arguments it is the command line tool, which is how a conversion started from
the window runs. `fpx_gui.__main__.main` makes that decision before importing
Qt.
"""

from __future__ import annotations

import multiprocessing
import sys

from fpx_gui.__main__ import main

if __name__ == "__main__":
    # Harmless here and cheap insurance: any library that starts a process
    # pool inside a frozen exe re-runs this script in the child, and without
    # this the application would open a second window instead of a worker.
    multiprocessing.freeze_support()
    sys.exit(main())
