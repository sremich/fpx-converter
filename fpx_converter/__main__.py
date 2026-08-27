from __future__ import annotations

import sys

from .batch import interrupt_on_break
from .cli import main

if __name__ == "__main__":
    # Ctrl+Break has to stop this the same way Ctrl+C does, or a cancelled
    # run dies without writing `audit_report.json`. See `batch.interrupt_on_break`.
    interrupt_on_break()
    sys.exit(main())
