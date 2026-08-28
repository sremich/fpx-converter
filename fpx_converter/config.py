"""Configuration, read from `.env` and the process environment.

Deliberately not using python-dotenv: the format we need is a dozen lines of
`KEY=value`, and every dependency in this project is one more thing that can
change under an archival run.

Precedence: real environment variables beat `.env`, so a one-off run can
override without editing the file.

**Nothing here is required.** `.env` is a convenience for an archive that gets
converted more than once; every setting it carries has a command-line flag or
a sensible runtime answer, and a fresh install with no configuration at all
must be able to run `scan` and `convert`.
"""

from __future__ import annotations

import contextlib
import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

#: Where the package itself lives. Used to find a `.env` shipped beside a
#: source checkout, and to tell a checkout from a `pip install`. It is
#: **not** where anything is written -- see `work_root`.
PACKAGE_ROOT = Path(__file__).resolve().parent.parent

#: Kept for callers that predate `work_root()`. In a source checkout the two
#: are the same directory; in an installed copy `PACKAGE_ROOT` is
#: `site-packages`, which is not a place to put an archive.
REPO_ROOT = PACKAGE_ROOT

#: A file that only a checkout of this project has beside the package.
_CHECKOUT_MARKERS = (".git", "VERSION")

#: Set by `--work-dir`, or by `--env-file` for the `.env` search alone.
_work_dir_override: Path | None = None
_env_file_override: Path | None = None


class ConfigError(RuntimeError):
    """Raised when configuration is missing or points somewhere unusable."""


class SourceWriteRefused(RuntimeError):
    """Raised when something would write inside the read-only source root."""


def is_source_checkout(path: Path) -> bool:
    """Does this directory look like a checkout of this project?"""
    return any((path / marker).exists() for marker in _CHECKOUT_MARKERS)


def set_work_dir(path: str | Path | None) -> None:
    """Point every default working path at `path` (from `--work-dir`)."""
    global _work_dir_override
    _work_dir_override = Path(path).expanduser() if path else None


def set_env_file(path: str | Path | None) -> None:
    """Read configuration from exactly this `.env` (from `--env-file`)."""
    global _env_file_override
    if path is None:
        _env_file_override = None
        return
    resolved = Path(path).expanduser()
    if not resolved.is_file():
        raise ConfigError(f"--env-file {resolved} does not exist.")
    _env_file_override = resolved


def work_root() -> Path:
    """The directory default working paths hang off.

    Three answers, in order:

    1. `--work-dir`, or `FPX_WORK_DIR`.
    2. the directory holding the package, but **only** when it is a checkout
       of this project -- that is the developer's `output/` and
       `source-files/`, and it is where they have always been.
    3. otherwise the current working directory.

    Step 2's guard is the whole point. `Path(__file__).parent.parent` is the
    repository in a checkout and `site-packages` in a `pip install`, and the
    defaults built on it quietly aimed a photo archive, a manifest and two
    output trees at the inside of somebody's virtual environment.
    """
    if _work_dir_override is not None:
        return _work_dir_override
    env_dir = os.environ.get("FPX_WORK_DIR", "").strip()
    if env_dir:
        return Path(env_dir).expanduser()
    if is_source_checkout(PACKAGE_ROOT):
        return PACKAGE_ROOT
    return Path.cwd()


def source_files_dir() -> Path:
    """Where ingested copies of the source `.fpx` files land. Gitignored."""
    return work_root() / "source-files"


def fpx_store_dir() -> Path:
    return source_files_dir() / "fpx"


def manifest_path() -> Path:
    return source_files_dir() / "manifest.json"


def output_root_default() -> Path:
    """Where `convert` and `gallery` write when told nothing.

    `FPX_OUTPUT_ROOT` has been parsed into `Settings` since 0.1.0 and read by
    nothing, so a person who set it watched their run write somewhere else.
    """
    raw = load_env().get("FPX_OUTPUT_ROOT", "").strip()
    if raw:
        return Path(raw).expanduser()
    return work_root() / "output"


def user_config_dir() -> Path:
    """Where a `.env` that is not tied to one archive belongs."""
    if os.name == "nt":
        base = os.environ.get("APPDATA", "").strip()
        if base:
            return Path(base) / "fpx-converter"
        return Path.home() / "AppData" / "Roaming" / "fpx-converter"
    base = os.environ.get("XDG_CONFIG_HOME", "").strip()
    if base:
        return Path(base) / "fpx-converter"
    return Path.home() / ".config" / "fpx-converter"


def env_file_candidates() -> list[Path]:
    """Every `.env` that would be read, in the order the first hit wins.

    The working directory comes first because that is where a person who
    typed `cd my-archive` expects their settings to live. The package root is
    last, and in an installed copy it holds nothing at all.
    """
    if _env_file_override is not None:
        return [_env_file_override]
    return [
        Path.cwd() / ".env",
        user_config_dir() / ".env",
        PACKAGE_ROOT / ".env",
    ]


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
    """Environment overlaid on `.env`; the environment wins.

    With no explicit path the search is `env_file_candidates()` and the first
    file that exists wins -- the working directory, then the user's config
    directory, then the package root. It used to be the package root alone,
    which in an installed copy is a directory the user has never seen.
    """
    candidates = [env_path] if env_path is not None else env_file_candidates()
    values: dict[str, str] = {}
    for candidate in candidates:
        if candidate is not None and candidate.is_file():
            values.update(parse_env_file(candidate.read_text(encoding="utf-8")))
            break
    values.update({k: v for k, v in os.environ.items() if k.startswith("FPX_")})
    return values


def set_env_value(key: str, value: str, env_path: Path | None = None) -> Path:
    """Write one `FPX_*` setting into a `.env` file, leaving everything else alone.

    Exists for the GUI's "locate exiftool.exe" picker: a located path is only
    useful the once unless something writes it down, and the only place this
    codebase reads it back from afterward is `.env` via `load_env()`. Refuses
    any key not prefixed `FPX_` -- `load_env()` only overlays names with that
    prefix, so writing anything else would produce a setting that is silently
    read by nothing.

    The default target is `user_config_dir() / ".env"`, never the working
    directory. A GUI can be launched from a desktop shortcut, a pinned icon,
    or a double-clicked file, so "the working directory" is not a place the
    user chose -- writing there would put the setting somewhere the next
    launch has no particular reason to look, or drop a dotfile into a folder
    the user never asked to have one in.

    Every other line survives untouched -- other keys, comments, blank lines,
    and their order -- because this is also the file a person hand-edits to
    add `FPX_SOURCE_ROOT`, `FPX_TZ_OVERRIDES` or their own notes, and a
    rewrite that only serialized the keys it understood would silently
    discard the rest. If `key` already appears, its **last** occurrence is
    replaced in place and any earlier occurrences of the same key are
    dropped; that matches `parse_env_file`, which assigns each key as it
    reads and so lets a later line quietly win -- leaving the earlier ones in
    place would keep dead lines that look load-bearing but are not. An absent
    key is appended.

    Values are written unquoted. `parse_env_file` only strips a *matching*
    leading/trailing quote pair and never interprets backslashes, so a
    Windows path like `C:\\Program Files\\ExifTool\\exiftool.exe` already
    reads back exactly as written -- quoting it would be solving a problem
    that does not exist here.

    The write is atomic: the new content lands in a temp file beside the
    target and `os.replace` swaps it in, so a process killed mid-write cannot
    leave the user's `.env` truncated.
    """
    if not key.startswith("FPX_"):
        raise ConfigError(
            f"refusing to write {key!r} to .env: load_env() only overlays names "
            "prefixed FPX_, so anything else would be a setting nothing ever reads."
        )

    target = env_path if env_path is not None else user_config_dir() / ".env"
    target.parent.mkdir(parents=True, exist_ok=True)

    lines = target.read_text(encoding="utf-8").splitlines() if target.is_file() else []

    def _is_match(line: str) -> bool:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            return False
        existing_key, sep, _ = stripped.partition("=")
        return bool(sep) and existing_key.strip() == key

    match_indices = [i for i, line in enumerate(lines) if _is_match(line)]
    new_line = f"{key}={value}"

    if match_indices:
        last = match_indices[-1]
        lines[last] = new_line
        for i in reversed(match_indices[:-1]):
            del lines[i]
    else:
        lines.append(new_line)

    text = "\n".join(lines) + "\n"

    fd, tmp_name = tempfile.mkstemp(dir=target.parent, prefix=".env.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
        os.replace(tmp_name, target)
    except BaseException:
        with contextlib.suppress(OSError):
            os.remove(tmp_name)
        raise

    return target


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


def extra_non_descriptive_albums(env_path: Path | None = None) -> frozenset[str]:
    """Archive-specific folder names to treat as saying nothing, from `.env`.

    `layout.NON_DESCRIPTIVE_ALBUMS` carries only names that are generic in any
    archive -- "untitled", "new folder", "misc". A particular archive may have
    its own, and those are album names, which this repository does not carry.
    They go in `.env`:

        FPX_NON_DESCRIPTIVE_ALBUMS=["SomeDumpFolder", "scan batch 3"]

    Refused loudly rather than ignored: a name that silently fails to register
    files a pile of photos under a folder nobody meant to keep.
    """
    return _env_album_list("FPX_NON_DESCRIPTIVE_ALBUMS", env_path)


def _env_album_list(key: str, env_path: Path | None) -> frozenset[str]:
    """A JSON list of album names from `.env`, lowercased. Empty if unset.

    Album names are personal content, so archive-specific lists live in `.env`
    and never in the source tree. Malformed values are refused loudly rather
    than ignored: a name that silently fails to register changes where photos
    are filed or what date they claim, and neither failure announces itself.
    """
    raw = load_env(env_path).get(key, "").strip()
    if not raw:
        return frozenset()
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ConfigError(f"{key} is not valid JSON: {exc}") from exc
    if not isinstance(parsed, list) or not all(isinstance(v, str) for v in parsed):
        raise ConfigError(
            f"{key} must be a JSON list of strings, "
            f'e.g. ["Untitled Folder"] -- got {parsed!r}'
        )
    return frozenset(v.strip().lower() for v in parsed if v.strip())


def coarse_albums(env_path: Path | None = None) -> frozenset[str]:
    """Albums whose folder name must NOT be read as naming a single day.

        FPX_COARSE_ALBUMS=["christmas 1994", "summer trip"]

    A folder name can look day-precise and not be. A holiday name resolves to
    a calendar day, but the folder may hold the whole season around it -- the
    eve, the day after, the week. Only the person who made the folder knows,
    and where they say it is coarse, the name is demoted to its year: the
    album still sorts and files under that year, and nothing is written to
    `DateTimeOriginal`.

    The demotion goes one way. This can take a claim away; it can never add
    one.
    """
    return _env_album_list("FPX_COARSE_ALBUMS", env_path)


def resolve_default_timezone(
    explicit: str | None = None, env_path: Path | None = None
) -> str:
    """The zone this run records offsets for, in order of who said it.

    `--timezone`, then `FPX_DEFAULT_TZ`, then **this machine's own zone**. The
    machine comes before any built-in name because the built-in one is a
    property of whoever wrote the tool: shipping `America/Chicago` as the
    silent default meant a first run in London stamped every photograph with
    US Central, and nothing downstream can tell that from a right answer.

    Raises `ConfigError` where the machine cannot be asked -- one clear
    refusal before the run, rather than a guess repeated 687 times.
    """
    from . import timestamps

    if explicit and explicit.strip():
        return explicit.strip()
    configured = load_env(env_path).get("FPX_DEFAULT_TZ", "").strip()
    if configured:
        return configured
    detected = timestamps.system_timezone()
    if detected:
        return detected
    raise ConfigError(
        "This machine's time zone could not be identified, so there is no zone "
        "to record beside the timestamps. Say which one with --timezone "
        "(an IANA name such as Europe/London), or set FPX_DEFAULT_TZ in .env. "
        "Refused rather than guessed: a wrong OffsetTime is written exactly as "
        "confidently as a right one."
    )


def timezone_settings(
    env_path: Path | None = None, explicit_tz: str | None = None
) -> tuple[str, dict[str, str]]:
    """`(default_tz, album_overrides)` from `.env` and the environment.

    Separate from `Settings.load` because the timezone configuration is
    needed on paths that have no business requiring `FPX_SOURCE_ROOT` --
    converting from an already-ingested store, for one. Reading the whole
    Settings object there would refuse to run without a source archive that
    the operation never touches.
    """
    env = load_env(env_path)
    return (
        resolve_default_timezone(explicit_tz, env_path),
        parse_album_tz_overrides(env.get("FPX_TZ_OVERRIDES", "")),
    )


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
                "No source folder given. Say where the .fpx photos are:\n"
                "    fpx-converter scan /path/to/photos\n"
                "Setting FPX_SOURCE_ROOT in a .env file does the same thing for "
                "every run, and is a convenience rather than a requirement."
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
            default_tz=resolve_default_timezone(env_path=env_path),
            album_tz_overrides=parse_album_tz_overrides(env.get("FPX_TZ_OVERRIDES", "")),
        )
