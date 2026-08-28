"""What the window collects, turned into the command lines a person would type.

Every checkbox and dropdown in the window maps onto one real flag. Nothing
here invents an option the CLI does not have, and nothing here decides
anything the CLI decides:

* the output set is built by `fpx_converter.outputs.build_specs`, so an
  impossible combination is refused by `OutputSpecError` -- the same error,
  with the same wording, that a terminal user gets;
* the destination is checked by `fpx_converter.config.ensure_outside_source`,
  so a destination inside the read-only archive is refused by the one
  function that enforces that rule anywhere in this project.

The window calls `validate` before it launches anything, purely so the
refusal arrives as a sentence in a dialog rather than a traceback in a log
pane. The CLI then checks both again for real. Two calls to one function is
not a duplicated rule; a second implementation would be.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

from fpx_converter import config, layout, outputs
from fpx_converter import name_template as name_template_mod
from fpx_converter import timestamps as timestamps_mod

#: The GUI puts the manifest in the destination, never beside the source.
#: `ensure_outside_source` would refuse the alternative anyway, and this way a
#: destination folder is a complete, self-describing record of one run.
MANIFEST_NAME = "manifest.json"
REPORT_PAGE = Path("report") / "index.html"
#: Where `ingest` puts one `.fpx` per distinct hash. Only the review page
#: needs it, so only the review page pays for it -- see `review_pipeline`.
STORE_DIR = Path("source-files")
#: The marker the Cancel button creates. See `runner.CliProcess.cancel` for
#: why a file exists alongside a console signal.
STOP_FILENAME = "stop-requested"


#: The three things somebody actually wants, and only one at a time.
ARCHIVE = "archive"
SHARING = "sharing"
CUSTOM = "custom"

#: Label and explanation for each, in the order the window shows them.
MODE_CHOICES: tuple[tuple[str, str, str], ...] = (
    (
        ARCHIVE,
        "Archive copy — TIFF, whole photo",
        "The one to keep. Lossless, every pixel the camera captured.",
    ),
    (
        SHARING,
        "Shareable copy — JPEG, cropped",
        "The one to send people. Opens anywhere, cropped as it was framed.",
    ),
    (
        CUSTOM,
        "Custom — you choose",
        "Any combination of format and framing, and the extra files.",
    ),
)


def known_timezones() -> tuple[str, ...]:
    """The zones the converter can resolve an offset for, asked of it.

    Not a list typed here. The converter resolves offsets from its own table
    and refuses anything outside it -- loudly, because a wrong `OffsetTime*`
    is indistinguishable from a right one once written -- so a second list in
    the front end would eventually offer a zone the converter rejects. The
    public name is preferred where the converter grows one; the table itself
    is the fallback.
    """
    known = getattr(timestamps_mod, "KNOWN_TIMEZONES", None)
    if known is None:
        known = timestamps_mod._TZ_OFFSETS  # noqa: SLF001 -- see the docstring
    return tuple(sorted({*known, "utc"}))


#: Names `time.tzname` can report that the CLDR table has no row for.
#:
#: One entry, and it is a spelling rather than a zone: some runtimes report
#: UTC by its full name. Anything that is genuinely a Windows zone belongs in
#: the converter's table, not here.
_EXTRA_ZONE_NAMES: dict[str, str] = {
    "coordinated universal time": "Etc/UTC",
}


def _build_windows_zone_names() -> dict[str, str]:
    """Windows zone name -> the IANA name this window would put in the box.

    Windows names its time zones its own way and Python reports that name, so
    something has to translate. This front end used to carry its own table of
    eight -- all of them American -- which meant `detect_timezone` returned
    nothing on a machine in London or Tokyo and the combo opened empty for
    everyone outside the United States.

    The converter already has the full CLDR map, all ~140 rows of it, and uses
    it for exactly this. So this is a *view* of that map and not a copy of it:
    the project's rule is that the desktop app calls the converter rather than
    restating it, and two tables of Windows zone names would drift the moment
    one of them was corrected.

    Lower-cased on both sides because `known_timezones` -- which is likewise
    asked of the converter -- offers lower-case keys, and a detected value the
    combo does not list is a box pre-filled with something not in its own menu.
    A row whose zone the converter cannot resolve is dropped rather than
    offered.
    """
    merged = {**timestamps_mod._WINDOWS_TO_IANA, **_EXTRA_ZONE_NAMES}  # noqa: SLF001
    offered = set(known_timezones())
    return {
        windows_name.strip().lower(): iana.lower()
        for windows_name, iana in merged.items()
        if iana.lower() in offered
    }


#: Built once at import. See `_build_windows_zone_names` for why it is derived
#: rather than typed.
_WINDOWS_ZONE_NAMES: dict[str, str] = _build_windows_zone_names()


def detect_timezone(name: str | None = None) -> str:
    """This machine's zone, where the converter would recognise it. Else `""`.

    An empty answer is a real answer and the window shows it as one: the
    control is left blank rather than filled with a plausible neighbour. The
    zone decides the UTC offset recorded beside every timestamp the run
    writes, and nothing downstream can tell a wrong offset from a right one,
    so a guess here is worse than a question.

    What counts as recognised is the converter's own CLDR table, so a machine
    set to London, Tokyo or Kolkata is answered as readily as one set to
    Chicago. A name in no table still yields `""` -- the lookup is exact, and
    there is deliberately no nearest-match step.

    `name` is for the tests, which cannot change the machine's clock.
    """
    reported = name if name is not None else (time.tzname[0] if time.tzname else "")
    return _WINDOWS_ZONE_NAMES.get(reported.strip().lower(), "")


@dataclass(frozen=True)
class ConvertOptions:
    """One run, as the window has it configured."""

    source: Path
    dest: Path
    #: Which of the three the window offers: `ARCHIVE`, `SHARING` or `CUSTOM`.
    #: The first two ignore the format and framing fields entirely and write
    #: exactly one image per photograph; only `CUSTOM` reads them.
    mode: str = ARCHIVE
    #: Read only under `CUSTOM`. The two named modes are one fixed tree each
    #: and ignore these entirely, which is the point of them.
    custom_format: str = "tiff"
    custom_framing: str = "full"
    #: The source `.fpx` copied beside its converted image. Off by default:
    #: the source archive is read-only and still there, so this is a second
    #: copy of something that was never at risk.
    source_copy: bool = False
    #: The `.fpx.json` raw-property dump. Off by default: it can be rebuilt
    #: from the source at any time with `metadata`.
    sidecar: bool = False
    #: What each converted image is called, before its extension. Applies to
    #: all three modes -- naming is about what the files are called, not about
    #: which of them get written.
    name_template: str = name_template_mod.DEFAULT_TEMPLATE
    #: How the output tree is arranged: one of `layout.FOLDER_SCHEMES`.
    folder_scheme: str = layout.BY_ALBUM
    #: Read only under `layout.CUSTOM`, and ignored otherwise.
    folder_template: str = layout.DEFAULT_FOLDER_TEMPLATE
    #: Which zone the photographs were taken in. It selects the `OffsetTime*`
    #: written beside each timestamp and never shifts the time itself.
    #:
    #: Empty means "say nothing", and then no `--timezone` reaches the command
    #: line and the converter's own answer stands. That is the honest default
    #: for a machine whose zone this front end could not recognise: the window
    #: asks rather than filling the box with a neighbouring zone that would be
    #: an hour wrong and would look exactly like a right one.
    timezone: str = ""
    #: Always on. It skips what is already finished and costs a re-read at
    #: worst, and the window no longer offers a way to turn it off -- "ignore
    #: what a previous run did" described a mechanism rather than a job, and
    #: nobody could say what it would do to their photographs.
    resume: bool = True

    @property
    def manifest(self) -> Path:
        return self.dest / MANIFEST_NAME

    @property
    def report_page(self) -> Path:
        return self.dest / REPORT_PAGE

    @property
    def store(self) -> Path:
        return self.dest / STORE_DIR

    @property
    def stop_file(self) -> Path:
        return self.dest / STOP_FILENAME

    def tree_format_framing(self) -> tuple[str, str, str]:
        """Which tree this run writes into, and as what. One image, always.

        The named modes are deliberately not expressed as "the custom
        settings, preset": they ignore the custom fields entirely, so leaving
        Custom cannot carry its last setting into a run whose label says
        something else.

        The tree follows the **framing**, which is the project's rule --
        `archive/` keeps the full frame, `sharing/` gets the crop -- and not
        the mode. Custom lost its archive-vs-shareable choice in 1.2.1, so
        something has to decide, and pinning it to `archive/` would have filed
        a cropped image in the tree whose whole job is the uncropped one. It
        also means the same two answers land in the same place however they
        were reached: Custom set to JPEG and cropped writes exactly what the
        Shareable copy button writes, in the same folder.
        """
        if self.mode == SHARING:
            return "sharing", "jpeg", "cropped"
        if self.mode == ARCHIVE:
            return "archive", "tiff", "full"
        tree = "sharing" if self.custom_framing == "cropped" else "archive"
        return tree, self.custom_format, self.custom_framing

    def specs(self) -> tuple[outputs.OutputSpec, ...]:
        """The outputs this run would write. Raises `OutputSpecError`."""
        tree, fmt, framing = self.tree_format_framing()
        if tree == "sharing":
            return outputs.build_specs(
                archive=False, sharing=True,
                sharing_format=fmt, sharing_framing=framing,
            )
        return outputs.build_specs(
            archive=True, sharing=False,
            archive_format=fmt, archive_framing=framing,
        )

    def checked_dest(self) -> Path:
        """The destination, refused if it is inside the source archive.

        Delegates to `config.ensure_outside_source`. This front end must
        never grow its own version of that check: the rule it enforces is the
        one whose violation cannot be undone.
        """
        return config.ensure_outside_source(
            self.dest, self.source, "conversion destination"
        )


def validate(options: ConvertOptions) -> tuple[outputs.OutputSpec, ...]:
    """Everything that can be refused before a child process starts.

    Raises `ConfigError` for a source that is not there, `SourceWriteRefused`
    for a destination inside it, and `OutputSpecError` for an output set that
    cannot be written. The window shows whichever message comes back.
    """
    # `Path("")` is `Path(".")`, which exists and is a directory. An empty
    # text field would therefore have passed every check below and quietly
    # scanned whatever the working directory happened to be.
    blank = Path("")
    if options.source == blank:
        raise config.ConfigError("Choose the folder holding the .fpx photos.")
    if options.dest == blank:
        raise config.ConfigError("Choose a folder to write the converted photos into.")
    if not options.source.is_dir():
        raise config.ConfigError(
            f"The source folder does not exist: {options.source}"
        )
    options.checked_dest()
    name_template_mod.validate(options.name_template)
    if options.folder_scheme == layout.CUSTOM:
        layout.validate_folder_template(options.folder_template)
    return options.specs()


def scan_args(options: ConvertOptions) -> list[str]:
    """Walk the source read-only and write the manifest into the destination."""
    return [
        "scan",
        "--source", str(options.source),
        "--manifest", str(options.manifest),
    ]


def convert_args(options: ConvertOptions) -> list[str]:
    """The conversion itself, with `--progress` so the run can be watched.

    Format and framing are emitted only for a tree that is actually being
    written. Passing `--archive-format` beside `--no-archive` is harmless but
    it makes the command line in the log pane read as though it meant
    something, and the log pane is the only place a person can see what was
    actually run.
    """
    args = [
        "convert",
        "--manifest", str(options.manifest),
        "--dest", str(options.dest),
        "--progress",
        "--stop-file", str(options.stop_file),
    ]
    if not options.resume:
        args.append("--no-resume")
    if options.source_copy:
        args.append("--source-copy")
    if options.sidecar:
        args.append("--sidecar")
    # Passed whenever the window has an answer, default or not. This one is
    # not omitted for matching the converter's default the way the patterns
    # below are: the converter's default zone is a property of whoever built
    # it, and a run that silently inherits it writes an offset nobody chose.
    if options.timezone.strip():
        args += ["--timezone", options.timezone.strip()]
    # Only when it is not what the CLI would do anyway: the log pane is the
    # one place a person sees what was run, and a line of flags that all
    # restate the defaults is harder to read, not more informative.
    if options.name_template != name_template_mod.DEFAULT_TEMPLATE:
        args += ["--name-template", options.name_template]
    if options.folder_scheme != layout.BY_ALBUM:
        args += ["--folder-scheme", options.folder_scheme]
        # Only where it is read. Beside `--folder-scheme year` it would look
        # like it meant something, and the log pane is the one place a person
        # can see what was actually run.
        if options.folder_scheme == layout.CUSTOM:
            args += ["--folder-template", options.folder_template]

    # Every mode is one image. Derived here rather than in the window, so the
    # command line in the log pane always matches what the option means, and
    # from the same function `specs()` uses so the two cannot disagree.
    tree, fmt, framing = options.tree_format_framing()
    if tree == "sharing":
        return [*args, "--no-archive", "--sharing-format", fmt,
                "--sharing-framing", framing]
    return [*args, "--no-sharing", "--archive-format", fmt, "--archive-framing", framing]


def ingest_args(options: ConvertOptions) -> list[str]:
    """Copy one `.fpx` per distinct hash into a flat store inside the destination.

    Only the review page needs this. `gallery` reads its thumbnails from the
    embedded DIBs and finds each file at `store/<store_name>`, which is a flat
    layout that neither the nested source tree nor the nested output tree
    provides. `ingest` re-hashes and skips what is already there, so running
    it again costs a read rather than a copy.
    """
    return [
        "ingest",
        "--manifest", str(options.manifest),
        "--dest", str(options.store),
    ]


#: How many files the estimate below will look at before it gives up and says
#: "at least". A directory walk in the window's own thread has to be bounded;
#: an archive of a few hundred photographs is instant, and one of a million
#: files must not freeze the window to produce a number nobody needed.
ESTIMATE_FILE_LIMIT = 50_000


def source_size(source: Path, limit: int = ESTIMATE_FILE_LIMIT) -> tuple[int, bool]:
    """`(bytes, was_capped)` for the `.fpx` files under `source`.

    Read-only, like everything this front end does to a source folder.
    """
    total = 0
    seen = 0
    for path in source.rglob("*.fpx"):
        try:
            total += path.stat().st_size
        except OSError:  # pragma: no cover - a file that vanished mid-walk
            continue
        seen += 1
        if seen >= limit:
            return total, True
    return total, False


def describe_bytes(size: int) -> str:
    """A size a person reads, not a number of bytes."""
    for unit, step in (("GB", 1024**3), ("MB", 1024**2), ("KB", 1024)):
        if size >= step:
            return f"{size / step:.1f} {unit}"
    return f"{size} bytes"


def review_copy_notice(options: ConvertOptions) -> str:
    """What the review page is about to copy, said before it copies it.

    The review page needs a flat store of one `.fpx` per distinct photograph
    and `ingest` builds it, which means pressing this button copies a
    substantial part of the source archive into the destination. That is a
    reasonable thing for it to do and an unreasonable thing for it to do
    quietly -- especially in a project whose stated rule is that the `.fpx`
    copy is opt-in.
    """
    size, capped = source_size(options.source)
    about = "at least " if capped else "up to about "
    return (
        "Building the review page first copies your photos.\n\n"
        f"One copy of each distinct .fpx goes into:\n    {options.store}\n\n"
        f"That needs {about}{describe_bytes(size)} of free space — less where "
        "the same photograph appears more than once, because identical files "
        "are stored once.\n\n"
        "Your source folder is only read from and is not changed. The copies "
        "are yours to delete once you are finished with the review page.\n\n"
        "Go ahead?"
    )


def gallery_args(options: ConvertOptions) -> list[str]:
    """Build the review page from the run that just finished."""
    return [
        "gallery",
        "--dest", str(options.dest),
        "--manifest", str(options.manifest),
        "--store", str(options.store),
        "--out", str(options.report_page),
    ]


def convert_pipeline(options: ConvertOptions) -> list[tuple[str, list[str]]]:
    """The steps behind the Convert button, in order, each with its label.

    Two commands, not one: `convert` reads a manifest, and a person who
    picked a folder in a window has not run `scan`. Both are the real
    subcommands with the real flags.

    `ingest` is deliberately **not** here. It would copy the whole archive a
    second time on every conversion, and nothing in the conversion needs it --
    `convert` falls back to the manifest's own source paths. It belongs to the
    review page, which is the only thing that does need it.
    """
    return [
        ("Reading the source folder", scan_args(options)),
        ("Converting", convert_args(options)),
    ]


def review_pipeline(options: ConvertOptions) -> list[tuple[str, list[str]]]:
    """The steps behind the review-page button, in order, each with its label."""
    return [
        ("Collecting thumbnails", ingest_args(options)),
        ("Building the review page", gallery_args(options)),
    ]
