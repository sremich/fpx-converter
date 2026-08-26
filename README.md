# project-scaffold

Template repository for starting new agent-built projects. Encodes the
conventions proven across companion-ppt-helper, closed-caption-generation,
and netbox-monitor so every project starts with them instead of
rediscovering them: CI-owned releases, single-source versioning, doc/audit
workflow, handover discipline, and testing tiers.

> **In a spawned project?** This README gets replaced by the project's real
> README (the `docs-writer` sub-agent drafts it during milestone 0). The
> rules live in `source-files/initial-prompt.txt` (committed public-safe as
> `docs/REQUIREMENTS.md` during milestone 0) and, as they grow, in
> `CLAUDE.md`.

## Starting a new project

1. Create the repo from this template:

   ```bash
   gh repo create sremich/NEW-PROJECT --template sremich/project-scaffold --private --clone
   ```

   (Or clone into the OneDrive projects folder if it should roam:
   `git clone https://github.com/sremich/NEW-PROJECT` there.)

2. Fill in `initial-prompt-template.md` — every `[BRACKETED]` placeholder,
   delete the `TIP:` lines — and save it as
   `source-files/initial-prompt.txt` (gitignored; add any input materials
   to `source-files/` too).

3. Start the agent with:

   > please look at the "initial-prompt.txt" in the source-files folder for
   > the initial prompt

4. The agent restates the system, asks clarifying questions, proposes a
   milestone plan, and then runs the **`/milestone-0`** skill (summary
   below) as part of 0.1.0.

## What's in the scaffold

| Path | Purpose |
|------|---------|
| `initial-prompt-template.md` | The fillable initial prompt (the only file you edit by hand) |
| `.github/workflows/ci.yml` | Tests on every push |
| `.github/workflows/release.yml` | On `v*` tag: verify tag==VERSION → refuse unfinished scaffold → test → build+push GHCR image (version+SHA baked in, smoke-pull with retry) → GitHub release (auto pre-release while 0.x) |
| `VERSION` | The **only** place the version lives (always X.Y.Z) |
| `scripts/check-version.sh` | Enforces tag/VERSION agreement and three-part format |
| `Dockerfile`, `docker-compose.yml`, `.env.example` | Stubs with `TODO(milestone-0)` markers; compose carries the image pin to bump each release |
| `CHANGELOG.md` | Keep-a-Changelog stub |
| `templates/HANDOVER.md` | Roaming agent context skeleton (session-close checklist, cold start, environment map) — stays gitignored/OneDrive-only once copied |
| `templates/CLAUDE.md` | Working-notes skeleton (commands, testing tiers, milestone plan, worktree policy, delegation rules) — **committed** once copied; keep public-safe |
| `templates/DECISIONS.md` | Append-only decisions / hard-won lessons — **committed** once copied; keep public-safe |
| `.claude/agents/` | Sub-agents: `docs-writer` (fast model drafts README/CHANGELOG/wiki), `docs-auditor` (stronger model audits before release), `scout` (read-only digests of large inputs), `code-auditor` (pre-merge diff review against the project's contract) |
| `.claude/skills/` | Skills: `/milestone-0` (configure the scaffold, then self-deletes), `/release` (drives a release end to end), `/wrap-up` (session-close checklist), `/checkpoint` (2-minute mid-task save so hitting the usage limit costs nothing) |
| `.claude/settings.json` | Permission allowlist (git/gh/docker/test-runner commands prompt-free; tag pushes and force pushes still prompt; `.env` reads denied) |
| `.gitignore` | Pre-set: `source-files/`, `HANDOVER.md`, `.env`, `data/`, logs, venvs |

## Milestone 0 (the agent does this — `/milestone-0` skill)

Resolve every `TODO(milestone-0)` marker — the release workflow **refuses to
run while any remain**. The skill walks through all of it:

- [ ] `ci.yml` / `release.yml`: real toolchain setup + test command
- [ ] `Dockerfile`: real build (keep the `VERSION`/`GIT_SHA` build args and
      surface them in the app — web UI footer, `--version`, or `/api/status`)
- [ ] `docker-compose.yml`: real image name, ports, volumes
- [ ] `.env.example`: real variables with safe placeholders
- [ ] Copy `templates/{HANDOVER,CLAUDE,DECISIONS}.md` to the repo root and
      fill their placeholders. `CLAUDE.md` + `DECISIONS.md` get committed
      (public-safe); `HANDOVER.md` stays gitignored/OneDrive-only
- [ ] Commit a public-safe copy of the filled initial prompt as
      `docs/REQUIREMENTS.md` (real IPs/credentials stay in `source-files/`
      and `HANDOVER.md`)
- [ ] Wiki home page: private repo → create `docs/wiki/Home.md` in the repo
      itself (never the wiki section); public repo → ask Stevie to create
      the first wiki page in the web UI (GitHub has no wiki API; `.wiki.git`
      doesn't exist until then)
- [ ] Replace this README with the project's real README (`docs-writer`
      drafts, `docs-auditor` audits)
- [ ] Delete `templates/`, `.claude/skills/milestone-0/`, and
      `initial-prompt-template.md` (all three still carry markers once
      consumed), then verify the marker grep comes back empty

## Release model (memorize this shape)

```
CHANGELOG Unreleased → vX.Y.Z   →  bump VERSION  →  commit + push
→  push annotated tag vX.Y.Z    →  CI does everything else
→  when green: bump compose pin →  tick the /release skill's checklist
```

Never create releases, push images, or edit tags by hand — if CI fails, no
partial release exists; fix and re-tag.
