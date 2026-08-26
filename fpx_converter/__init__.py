"""fpx-converter — archival conversion of Kodak FlashPix (.fpx) photos.

The source archive is read-only. Nothing in this package may write, move,
rename, or delete a file underneath the configured source root; the scanner
proves it rather than asserting it (see `scan.verify_unchanged`).
"""

from __future__ import annotations

from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent


def _read_version() -> str:
    """The version lives only in VERSION. Never hardcode a copy here.

    Installed copies have no VERSION file beside the package, so the
    installed distribution metadata is consulted first. Falling back to a
    literal would make `--version` lie rather than fail, which is worse than
    raising: a wrong version in an audit trail is undetectable later.
    """
    version_file = _REPO_ROOT / "VERSION"
    if version_file.is_file():
        return version_file.read_text(encoding="utf-8").strip()
    from importlib.metadata import PackageNotFoundError, version

    try:
        return version("fpx-converter")
    except PackageNotFoundError:  # pragma: no cover - neither source tree nor install
        return "unknown"


__version__ = _read_version()

__all__ = ["__version__"]
