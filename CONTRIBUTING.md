# Contributing

Thanks for looking. This project converts a family photo archive that exists
in exactly one copy, and a few of its rules are not guessable from the code.
Please read these before opening a pull request; the rest is ordinary.

## The rules that are not negotiable

**Never commit a photograph.** No image from anyone's archive, no album name,
no human-authored filename, no caption. The repository is for the software;
the photographs are not. Two tier-1 tests enforce this, and they list
`--cached --others --exclude-standard` rather than plain `git ls-files` —
a brand-new file is not in the index, and the narrower listing once read a
leak as clean right up to the commit that added it.

**The one exception is `tests/fixtures/`, and it has its own screening rule.**
A fixture must contain **no people**, confirmed by eye at full resolution and
not on a contact sheet — a body part at the frame edge and text in the picture
are both disqualifying, and both survive a thumbnail check. An adopted fixture
is renamed to a neutral stem before it is committed, because a filename
somebody typed is a caption. See
[`tests/fixtures/README.md`](tests/fixtures/README.md) for the process and
[`tests/fixtures/LICENSE.md`](tests/fixtures/LICENSE.md) for the terms — the
fixtures are **not** under this project's Apache-2.0 licence.

**The source tree is read-only.** Nothing in this project may write, move,
rename, or delete a source `.fpx`. That is enforced in code
(`config.ensure_outside_source`), not left to the caller, and the desktop app
*calls* it rather than reimplementing the check.

**The version lives only in `VERSION`.** `pyproject.toml` reads it
dynamically; no language-level copy is ever hand-edited. A tier-1 test refuses
a second source of truth, and CI refuses a tag that disagrees with the file.

**Releases are CI-driven.** Pushing a `vX.Y.Z` tag is the whole trigger.
Never run `gh release create`, never edit or move a tag by hand. If CI fails
there is no partial release — fix it and re-tag.

**Dependencies are pinned exactly, and stay that way.** This pipeline runs
once over an irreplaceable archive. A silent upstream change in a decoder or
a metadata writer is a correctness risk, not a convenience one, so a range
specifier is not an acceptable substitute for a pin. If you bump a pin, say
in the PR what you ran to check the output is unchanged.

## Testing tiers, and the two you cannot run

| Tier | What it is | Who runs it |
|---|---|---|
| 1. Unit | Parsers, naming, batch engine, resume state, the GUI's Qt-free half. No photographs, no ExifTool. | You and CI, every push |
| 2. e2e | Full pipeline over the 37 committed fixtures, plus the colour oracle in both directions. | You and CI, on any decoder/metadata/output/batch change |
| 3. Sample batch | 50 files from the private archive. | Maintainer only |
| 4. Full dataset | The whole private archive, plus a human looking at the result. | Maintainer only |

**Tiers 3 and 4 need the private photo archive and cannot be run by
contributors or by CI.** They are not skipped in your environment because
something is misconfigured; the data is not public and never will be. CI's
job is tiers 1 and 2, and a PR is judged on those. If your change touches the
decoder, the metadata engine, the output writer, or the batch engine, say so
in the PR — a maintainer runs tier 3 before it merges.

One thing worth knowing if you touch colour:
`fpx_converter.thumbnail.compute_image_correlation` folds both images to
greyscale and says **nothing** about colour, and
per-channel Pearson correlation is invariant under any per-channel affine
map, so a wrong gain or a wrong neutral point scores as well as a correct
decode. Colour is `chroma_agreement` in `fpx_converter/oracles.py`. Both
weaker checks were written, shipped, and caught.

## Setting up

```sh
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements-dev.txt   # Windows
# .venv/bin/python -m pip install -r requirements-dev.txt          # POSIX

# lint and test
python -m ruff check .
python -m pytest
```

Add `-r requirements-gui.txt` instead if you are working on the desktop front
end or building the executable.

**ExifTool** is a separate program, not a Python package, and is not in any
requirements file. Install it with
`winget install --id OliverBetz.ExifTool`. Do not try to fetch it from a URL.

> **Note for Windows users with long-path support disabled:** deep paths
> corrupt installs and writes. If that applies to you, put the virtual
> environment somewhere short — a top-level directory such as `C:\venvs\`
> rather than inside a deeply nested project folder.

## Pull requests

- Small, verifiable increments. A `wip:` commit with red tests is fine on a
  branch; an unpushed working tree is the state to avoid.
- Run tier 1 always, and the matching higher tier when its trigger applies.
  **"It decoded" is not "it decoded correctly"** — colour and orientation need
  eyes at least once per variant.
- Say what you verified and how. "Tests pass" is less useful than naming the
  tier and the trigger that made it apply.
- Licensing: contributions are accepted under the Apache License 2.0, the
  same terms the project ships under.

Questions go to <https://github.com/sremich/fpx-converter/issues>. That is the
only channel; no email address is published for this project.
