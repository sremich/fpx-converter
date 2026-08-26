"""fpx-converter — archival conversion of Kodak FlashPix (.fpx) photos.

The source archive is read-only. Nothing in this package may write, move,
rename, or delete a file underneath the configured source root; the scanner
proves it rather than asserting it (see `scan.verify_unchanged`).
"""

from __future__ import annotations

from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent


def _read_version() -> str:
    """The version lives only in VERSION. Never hardcode a copy here."""
    version_file = _REPO_ROOT / "VERSION"
    if version_file.is_file():
        return version_file.read_text(encoding="utf-8").strip()
    return "0.0.0"


__version__ = _read_version()

__all__ = ["__version__"]
