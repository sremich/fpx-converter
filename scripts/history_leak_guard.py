"""Scan git *history* for personal content, not just the working tree.

`tests/test_environment.py` has two leakage guards and both of them list
`git ls-files --cached --others --exclude-standard`. That is the working tree
and the index: what the repository looks like *now*. It is the right check for
"am I about to commit a photograph", and it is blind to the thing that
actually happened here -- a child's name and two album names sat in five
commits, across five releases, and every one of those guards was green the
whole time, because by then the files had been edited and the names were only
in the history.

Deleting a file does not remove it from a public repository. This is the check
that reads what a clone would still contain.

## Where the needles live, and why not here

A guard whose source code contains the secrets it guards is worthless: it is
itself the leak, and it is committed. So this file contains **no personal
string**, and it never prints one either -- a hit is reported as a commit id
and a short digest of the needle, because CI logs on a public repository are
public.

Two layers, deliberately different in kind:

* **Shapes**, in `FORBIDDEN_PATH_SUFFIXES` and `FORBIDDEN_BASENAMES`. Every
  container a photograph, a derivative or a run's output could arrive in.
  These need no configuration, cannot be forgotten, and are what catches "a
  photo was committed and then deleted". They are structural facts about this
  project, not personal data, so they are safe to commit.
* **Literal needles**, which are personal and therefore supplied from
  outside: `FPX_LEAK_NEEDLES` in the environment (in CI, from a repository
  **secret**, so the list lives in GitHub's secret store and reaches neither
  the repository nor the logs), or `--needles-file` pointing at a file
  **outside the working tree**. Deliberately not a file in the repo: an
  untracked one would still be read by this project's own leakage tests,
  which list untracked files, and a tracked one would be the leak.

The shape layer means the guard is never inert. A fork with no secret
configured still gets the check that matters most, and `--require-needles`
makes the literal layer mandatory where the caller knows it should be there.

## Shallow clones

`actions/checkout` fetches one commit by default. Run against that, this
scans a single commit and passes -- a green tick over history nobody looked
at. `assert_full_history` refuses instead, so the workflow has to say
`fetch-depth: 0`.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

#: Anything ever committed at one of these paths is a photograph, a
#: derivative of one, or the record of a run over the archive. None of them
#: belongs in this repository. Kept in step with `.gitignore`, and long rather
#: than tight: a suffix missing from this list is a hole in the rule.
FORBIDDEN_PATH_SUFFIXES: tuple[str, ...] = (
    ".fpx",
    ".fpx.json",
    ".tif",
    ".tiff",
    ".jpg",
    ".jpeg",
    ".wav",
    ".pez",
)

#: Files a run writes, whatever they are called on disk.
FORBIDDEN_BASENAMES: tuple[str, ...] = (
    "manifest.json",
    "audit_report.json",
    "conversion.log",
    "run-state.json",
    "album-dates.json",
)

#: The one sanctioned exception, and the narrow screenshot rule beside it.
#: Both are also exceptions in `.gitignore`; the reasons are in
#: `tests/fixtures/LICENSE.md`.
ALLOWED_PREFIXES: tuple[str, ...] = (
    "tests/fixtures/",
    "docs/images/",
)


class HistoryLeak(Exception):
    """Raised when something that may not be public is reachable in history."""


@dataclass(frozen=True)
class Finding:
    """One hit, in terms safe to print into a public log."""

    kind: str
    where: str
    detail: str

    def __str__(self) -> str:
        return f"{self.kind}: {self.where} -- {self.detail}"


def redact(needle: str) -> str:
    """A needle named in a way that does not repeat it.

    Enough to identify which entry of the list matched when the person who
    configured it looks, and useless to anybody reading the log.
    """
    digest = hashlib.sha256(needle.strip().lower().encode("utf-8")).hexdigest()
    return f"needle:{digest[:12]} (len {len(needle.strip())})"


def load_needles(
    env: dict[str, str] | None = None, needles_file: Path | None = None
) -> list[str]:
    """The literal needles, from the environment and an out-of-tree file.

    Newline separated, `#` comments and blanks dropped. Lower-cased once here
    so every comparison downstream is case-insensitive without saying so
    again. Short entries are refused rather than accepted: a two-character
    needle matches most of the codebase and would make the guard useless in a
    way that looks like it is working.
    """
    source = os.environ if env is None else env
    raw = list((source.get("FPX_LEAK_NEEDLES") or "").splitlines())
    if needles_file is not None:
        raw += needles_file.read_text(encoding="utf-8").splitlines()

    needles: list[str] = []
    for line in raw:
        entry = line.strip()
        if not entry or entry.startswith("#"):
            continue
        if len(entry) < 3:
            raise HistoryLeak(
                f"a needle of {len(entry)} characters would match almost every "
                "commit; needles must be at least 3 characters"
            )
        needles.append(entry.lower())
    return needles


def _git(repo: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", *args],
        cwd=repo,
        capture_output=True,
        check=True,
        encoding="utf-8",
        errors="replace",
    )
    return proc.stdout


def assert_full_history(repo: Path) -> None:
    """Refuse to scan a shallow clone.

    The failure this prevents is the quiet one: `actions/checkout` without
    `fetch-depth: 0` gives one commit, and one commit passes.
    """
    shallow = _git(repo, "rev-parse", "--is-shallow-repository").strip()
    if shallow == "true":
        raise HistoryLeak(
            "this is a shallow clone, so there is almost no history to scan and "
            "the check would pass by having looked at nothing. Set "
            "`fetch-depth: 0` on actions/checkout."
        )


def _is_forbidden_path(path: str) -> bool:
    lowered = path.strip().lower().replace("\\", "/")
    if not lowered or lowered.startswith(ALLOWED_PREFIXES):
        return False
    if lowered.endswith(FORBIDDEN_PATH_SUFFIXES):
        return True
    return lowered.rsplit("/", 1)[-1] in FORBIDDEN_BASENAMES


def scan_paths(repo: Path) -> list[Finding]:
    """Every path ever recorded in any reachable commit, checked by shape.

    `rev-list --objects --all` names the blob and the path it was stored at,
    in every reachable commit, including ones the file has since been deleted
    in. That is the whole point.
    """
    findings: list[Finding] = []
    seen: set[str] = set()
    for line in _git(repo, "rev-list", "--objects", "--all").splitlines():
        _, _, path = line.partition(" ")
        if not path or path in seen or not _is_forbidden_path(path):
            continue
        seen.add(path)
        findings.append(
            Finding(
                "personal file in history",
                path,
                "a photograph, a derivative or a run's output; deleting it from "
                "the tip does not remove it from a clone",
            )
        )
    return findings


def scan_content(repo: Path, needles: list[str]) -> list[Finding]:
    """Commit messages and diff text, against the literal needles.

    One streamed pass over `git log --all -p` rather than a `git grep` per
    commit: it reads every diff and every message exactly once, and binary
    blobs come back as `Binary files differ` rather than as megabytes.
    """
    if not needles:
        return []

    findings: list[Finding] = []
    reported: set[tuple[str, str]] = set()
    # `%B` so the commit *message* is scanned too -- a name is as public in a
    # subject line as in a file, and the default `--format` header would have
    # been replaced by a custom one that dropped it. The NUL prefix marks the
    # boundary: no diff line and no message line can begin with one, whereas
    # a literal "commit " can.
    proc = subprocess.Popen(
        ["git", "log", "--all", "-p", "--no-color", "--format=%x00%H%n%B"],
        cwd=repo,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        encoding="utf-8",
        errors="replace",
    )
    assert proc.stdout is not None
    commit = "(unknown)"
    try:
        for line in proc.stdout:
            if line.startswith("\x00"):
                commit = line[1:].strip()[:12]
                continue
            lowered = line.lower()
            for needle in needles:
                if needle in lowered and (commit, needle) not in reported:
                    reported.add((commit, needle))
                    findings.append(
                        Finding("configured needle in history", commit, redact(needle))
                    )
    finally:
        proc.stdout.close()
        proc.wait()
    return findings


def check_history(
    repo: Path,
    needles: list[str] | None = None,
    require_needles: bool = False,
) -> list[Finding]:
    """Both layers. Raises `HistoryLeak` on any hit, returns `[]` otherwise."""
    assert_full_history(repo)
    needles = load_needles() if needles is None else needles
    if require_needles and not needles:
        raise HistoryLeak(
            "no needles were configured, and --require-needles says there "
            "should be. Set FPX_LEAK_NEEDLES (a repository secret in CI) or "
            "pass --needles-file."
        )

    findings = scan_paths(repo) + scan_content(repo, needles)
    if findings:
        listing = "\n".join(f"  {f}" for f in findings)
        raise HistoryLeak(
            "git history contains content that must not be published:\n"
            f"{listing}\n\n"
            "History is not fixed by a new commit. Either rewrite it "
            "(filter-repo) and force-push, or do not publish this repository."
        )
    return findings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument(
        "--needles-file",
        type=Path,
        default=None,
        help="a file of literal needles, one per line. Keep it OUTSIDE the "
        "working tree: an untracked one is still read by this project's own "
        "leakage tests, and a tracked one is the leak.",
    )
    parser.add_argument(
        "--require-needles",
        action="store_true",
        help="fail if no literal needles were configured, rather than running "
        "the shape checks alone.",
    )
    args = parser.parse_args(argv)

    try:
        needles = load_needles(needles_file=args.needles_file)
        check_history(args.repo, needles, require_needles=args.require_needles)
    except HistoryLeak as exc:
        print(f"::error::{exc}", file=sys.stderr)
        return 1
    except subprocess.CalledProcessError as exc:
        print(f"::error::git failed: {exc.stderr}", file=sys.stderr)
        return 2

    print(
        f"History clean: {len(needles)} configured needle(s) and "
        f"{len(FORBIDDEN_PATH_SUFFIXES) + len(FORBIDDEN_BASENAMES)} path shapes "
        "checked across all reachable commits."
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
