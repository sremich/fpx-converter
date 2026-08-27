"""What a converted photo is written as: file format and framing, separately.

The two were welded together before this: `archive/` meant a full-frame TIFF
and `sharing/` meant a cropped JPEG, and there was no way to ask for one
without the other. They are independent questions, and the owner asked for
them to be independent settings -- a cropped TIFF and a full-frame JPEG are
both reasonable things to want.

* **Format** is how the pixels are stored. `tiff` is Deflate and lossless,
  which is what an archival copy needs; `jpeg` is q95 4:4:4, which is what
  opens everywhere.
* **Framing** is which pixels. `full` is every pixel the camera captured;
  `cropped` is the composition somebody framed in the Kodak software in 2002,
  where a file carries one. For the 617 files that carry no crop the two are
  identical.

The defaults are the shipped behaviour and stay that way: archive gets a
full-frame TIFF, sharing gets a cropped JPEG. Both the frame and the intended
composition are worth keeping, and the source `.fpx` is copied beside the
archive copy regardless.
"""

from __future__ import annotations

from dataclasses import dataclass

FORMATS: dict[str, str] = {"tiff": "tif", "jpeg": "jpg"}
FRAMINGS: tuple[str, ...] = ("full", "cropped")
TREES: tuple[str, ...] = ("archive", "sharing")


class OutputSpecError(ValueError):
    """An output was asked for in terms the writer cannot honour."""


@dataclass(frozen=True)
class OutputSpec:
    """One file to write per converted photo."""

    tree: str
    fmt: str
    framing: str

    def __post_init__(self) -> None:
        if self.tree not in TREES:
            raise OutputSpecError(f"unknown output tree {self.tree!r}; expected one of {TREES}")
        if self.fmt not in FORMATS:
            raise OutputSpecError(
                f"unknown output format {self.fmt!r}; expected one of {tuple(FORMATS)}"
            )
        if self.framing not in FRAMINGS:
            raise OutputSpecError(
                f"unknown output framing {self.framing!r}; expected one of {FRAMINGS}"
            )

    @property
    def ext(self) -> str:
        return FORMATS[self.fmt]

    @property
    def label(self) -> str:
        return f"{self.tree}/{self.fmt}/{self.framing}"

    def image_from(self, decoded):  # noqa: ANN001, ANN201 -- decoder.DecodedImage
        """The pixels this output wants.

        `decoded.image` is always the full frame: the decode never throws
        captured pixels away, and the crop is applied here instead. That is
        what makes a full-frame JPEG possible at all.
        """
        return decoded.image if self.framing == "full" else decoded.cropped_image()

    def expected_size(
        self,
        declared: tuple[int, int] | None,
        crop_box: tuple[int, int, int, int] | None,
    ) -> tuple[int, int] | None:
        """The size this output should be, derived from the metadata.

        Deliberately not from the decoded object. If a crop silently failed to
        apply, an expectation taken from that object would report the full
        frame, match the output, and pass -- which is the shape of a check
        that cannot fail.
        """
        if self.framing == "full" or crop_box is None:
            return declared
        return (crop_box[2] - crop_box[0], crop_box[3] - crop_box[1])


#: What `convert` writes when nothing is asked for: the shipped behaviour.
DEFAULT_SPECS: tuple[OutputSpec, ...] = (
    OutputSpec("archive", "tiff", "full"),
    OutputSpec("sharing", "jpeg", "cropped"),
)


def build_specs(
    *,
    archive: bool = True,
    sharing: bool = True,
    archive_format: str = "tiff",
    archive_framing: str = "full",
    sharing_format: str = "jpeg",
    sharing_framing: str = "cropped",
) -> tuple[OutputSpec, ...]:
    """Assemble the output set from CLI-shaped arguments.

    Asking for neither tree is refused rather than treated as a dry run: a
    conversion that writes no image is a mistake in the command, and silently
    doing nothing looks exactly like success.
    """
    specs: list[OutputSpec] = []
    if archive:
        specs.append(OutputSpec("archive", archive_format, archive_framing))
    if sharing:
        specs.append(OutputSpec("sharing", sharing_format, sharing_framing))
    if not specs:
        raise OutputSpecError(
            "no output was requested: --no-archive and --no-sharing were both given, "
            "so there is nothing to write. Use --dry-run to walk without writing."
        )
    return tuple(specs)
