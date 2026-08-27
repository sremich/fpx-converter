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

from dataclasses import dataclass
from pathlib import Path

from fpx_converter import config, outputs

#: The GUI puts the manifest in the destination, never beside the source.
#: `ensure_outside_source` would refuse the alternative anyway, and this way a
#: destination folder is a complete, self-describing record of one run.
MANIFEST_NAME = "manifest.json"
REPORT_PAGE = Path("report") / "index.html"
#: Where `ingest` puts one `.fpx` per distinct hash. Only the review page
#: needs it, so only the review page pays for it -- see `review_pipeline`.
STORE_DIR = Path("source-files")


@dataclass(frozen=True)
class ConvertOptions:
    """One run, as the window has it configured."""

    source: Path
    dest: Path
    archive: bool = True
    sharing: bool = True
    archive_format: str = "tiff"
    archive_framing: str = "full"
    sharing_format: str = "jpeg"
    sharing_framing: str = "cropped"
    #: Resume is on by default, matching the CLI. The window's checkbox is
    #: phrased the other way round ("start over"), because "resume" is a word
    #: about the tool and "start over" is a word about the job.
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

    def specs(self) -> tuple[outputs.OutputSpec, ...]:
        """The outputs this run would write. Raises `OutputSpecError`."""
        return outputs.build_specs(
            archive=self.archive,
            sharing=self.sharing,
            archive_format=self.archive_format,
            archive_framing=self.archive_framing,
            sharing_format=self.sharing_format,
            sharing_framing=self.sharing_framing,
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
    ]
    if not options.resume:
        args.append("--no-resume")
    if options.archive:
        args += [
            "--archive-format", options.archive_format,
            "--archive-framing", options.archive_framing,
        ]
    else:
        args.append("--no-archive")
    if options.sharing:
        args += [
            "--sharing-format", options.sharing_format,
            "--sharing-framing", options.sharing_framing,
        ]
    else:
        args.append("--no-sharing")
    return args


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
