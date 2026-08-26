"""Configuration, read from `.env` and the process environment.

Deliberately not using python-dotenv: the format we need is a dozen lines of
`KEY=value`, and every dependency in this project is one more thing that can
change under an archival run.

Precedence: real environment variables beat `.env`, so a one-off run can
override without editing the file.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

#: Where ingested copies of the source .fpx files land. Gitignored.
SOURCE_FILES_DIR = REPO_ROOT / "source-files"
FPX_STORE_DIR = SOURCE_FILES_DIR / "fpx"
MANIFEST_PATH = SOURCE_FILES_DIR / "manifest.json"


class ConfigError(RuntimeError):
    """Raised when configuration is missing or points somewhere unusable."""


class SourceWriteRefused(RuntimeError):
    """Raised when something would write inside the read-only source root."""


def ensure_outside_source(target: Path, source_root: Path, what: str) -> Path:
    """Refuse a write target that lies inside the source archive.

    Without this, a mistyped `--dest` or `--manifest` is enough to write into
    the archive: `ingest` would `mkdir` there and then `shutil.copy2` would
    truncate any source file whose name matched a store name. The read-only
    rule has to be an invariant the code enforces, not a convention the
    caller is trusted to observe.

    Returns the resolved target so callers can use the checked value.
    """
    resolved = target.expanduser().resolve()
    root = source_root.expanduser().resolve()
    if resolved == root or root in resolved.parents:
        raise SourceWriteRefused(
            f"refusing to use {resolved} as the {what}: it is inside the read-only "
            f"source archive at {root}. Nothing may be written under the source root."
        )
    return resolved


def parse_env_file(text: str) -> dict[str, str]:
    """Parse `KEY=value` lines. Blank lines and `#` comments are ignored.

    Surrounding single or double quotes are stripped; nothing else is
    interpreted, so a Windows path with backslashes survives intact.
    """
    values: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        key, sep, value = line.partition("=")
        if not sep:
            continue
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        if key:
            values[key] = value
    return values


def load_env(env_path: Path | None = None) -> dict[str, str]:
    """Environment overlaid on `.env`; the environment wins."""
    path = env_path if env_path is not None else REPO_ROOT / ".env"
    values: dict[str, str] = {}
    if path.is_file():
        values.update(parse_env_file(path.read_text(encoding="utf-8")))
    values.update({k: v for k, v in os.environ.items() if k.startswith("FPX_")})
    return values


def parse_album_tz_overrides(raw: str) -> dict[str, str]:
    """Parse `FPX_TZ_OVERRIDES` into a {album substring: IANA zone} map.

    The format is the JSON object `.env.example` documents, matched
    case-insensitively against the album folder name:

        FPX_TZ_OVERRIDES={"Some Trip":"America/New_York"}

    Album names are personal content, so this map lives in `.env` and never
    in the repository -- see the note in `timestamps.py`. Anything that is
    not a JSON object of strings is refused loudly: a silently ignored
    override writes a wrong `OffsetTime*` that nothing downstream can detect.
    """
    text = raw.strip()
    if not text:
        return {}
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ConfigError(f"FPX_TZ_OVERRIDES is not valid JSON: {exc}") from exc
    if not isinstance(parsed, dict):
        raise ConfigError(
            f"FPX_TZ_OVERRIDES must be a JSON object mapping album name to time "
            f"zone, got {type(parsed).__name__}"
        )
    overrides: dict[str, str] = {}
    for key, value in parsed.items():
        if not isinstance(key, str) or not isinstance(value, str):
            raise ConfigError(
                f"FPX_TZ_OVERRIDES entries must be string pairs, got {key!r}: {value!r}"
            )
        if key.strip():
            overrides[key.strip().lower()] = value.strip()
    return overrides


@dataclass(frozen=True)
class Settings:
    source_root: Path
    output_root: Path | None
    exiftool: str | None
    default_tz: str
    album_tz_overrides: dict[str, str]

    @classmethod
    def load(cls, env_path: Path | None = None) -> Settings:
        env = load_env(env_path)

        raw_source = env.get("FPX_SOURCE_ROOT", "").strip()
        if not raw_source:
            raise ConfigError(
                "FPX_SOURCE_ROOT is not set. Copy .env.example to .env and point "
                "it at the read-only backup tree holding the .fpx files."
            )
        source_root = Path(raw_source).expanduser()
        if not source_root.is_dir():
            raise ConfigError(
                f"FPX_SOURCE_ROOT does not exist or is not a directory: {source_root}"
            )

        raw_output = env.get("FPX_OUTPUT_ROOT", "").strip()
        output_root = Path(raw_output).expanduser() if raw_output else None

        return cls(
            source_root=source_root.resolve(),
            output_root=output_root,
            exiftool=env.get("FPX_EXIFTOOL") or None,
            default_tz=env.get("FPX_DEFAULT_TZ", "America/Chicago"),
            album_tz_overrides=parse_album_tz_overrides(env.get("FPX_TZ_OVERRIDES", "")),
        )
