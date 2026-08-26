---
name: milestone-0
description: Configure the scaffold for a new project — resolve every milestone-0 TODO marker, put the doc skeletons in place, write the real README. Single-use; run once at project start, and delete this skill as its final step.
---

# Milestone 0 — turn the scaffold into this project

Do this only after the initial-prompt ritual (restate the system, ask
clarifying questions, get the milestone plan approved). Milestone 0 ships
as part of 0.1.0.

The release workflow greps the repo for the marker `TODO(milestone-0)` and
refuses to run while any remain — including the ones in this file, which is
why the final step deletes it. Fix markers, never the check.

## Steps

1. **CI toolchain** — `.github/workflows/ci.yml`: real toolchain setup and
   real test command; mirror both into the verify job of `release.yml`.
2. **Dockerfile** — real build. Keep the `VERSION`/`GIT_SHA` build args and
   surface them in the app (web UI footer, `--version`, or `/api/status`).
3. **docker-compose.yml** — real image name (`ghcr.io/sremich/<repo>`),
   ports, volumes. Leave the pin at `v0.1.0`; it gets bumped after each
   release goes green.
4. **.env.example** — real variables with safe placeholder values. Real
   credentials only ever land in local `.env`.
5. **Doc skeletons** — copy `templates/CLAUDE.md`, `templates/DECISIONS.md`,
   and `templates/HANDOVER.md` to the repo root and fill their
   placeholders. `CLAUDE.md` and `DECISIONS.md` are committed — keep them
   public-safe; `HANDOVER.md` is gitignored (OneDrive-only). Record the
   approved milestone plan in `CLAUDE.md`'s Milestone plan section.
6. **Requirements** — commit a public-safe copy of the filled initial
   prompt as `docs/REQUIREMENTS.md` (strip real IPs/credentials; they stay
   in `source-files/` and `HANDOVER.md`). The requirements should follow
   the repo, not just OneDrive.
7. **Wiki + README** — private repo: create `docs/wiki/Home.md` in-repo
   (never GitHub's wiki section); public repo: ask Stevie to create the
   first wiki page in the web UI (no wiki API exists until then). Then have
   `docs-writer` replace the scaffold README with the project's real one
   and `docs-auditor` audit it.
8. **Commit the configuration** — everything from steps 1–7 goes in as its
   own commit (or several — commit as steps land; interruption resilience
   applies to milestone 0 too) and CI must be green on it BEFORE anything
   is deleted.
9. **Self-delete, as a separate final commit** — remove three consumed
   scaffold pieces: `.claude/skills/milestone-0/` (this directory),
   `templates/` (skeletons now live as the filled root copies), and
   `initial-prompt-template.md` (its content lives on as
   `source-files/initial-prompt.txt` and `docs/REQUIREMENTS.md`). All
   three still carry the marker text and would block releases forever if
   left behind. Then verify no marker remains anywhere:
   `grep -rn "TODO(milestone-0)" --exclude-dir=.git .` must come back
   empty. Commit and push. If anything went wrong earlier, this commit
   never happens and the scaffold stays intact and recoverable.
