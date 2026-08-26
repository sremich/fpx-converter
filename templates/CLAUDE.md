# [PROJECT NAME] — working notes

[One paragraph: what this is, stack, where it runs.]

This file and `DECISIONS.md` are committed (keep them public-safe — no real
IPs, hostnames, or credentials). `HANDOVER.md` is the local-only roaming
file: environment map, machine state, session log. If it isn't present in
your checkout (worktree, clone, CI), you're missing only machine-local
context, not project rules.

## Commands

```sh
# TODO(milestone-0): the real commands
# [install]
# [lint]
# [test]
```

## Testing tiers

| Tier | What it is | Gates |
|------|-----------|-------|
| 1. Unit | Fast, no external systems; in-memory fakes of integration surfaces | Every push (CI), every Docker build |
| 2. e2e | Real components locally (containers, loopback) | Core pipeline / protocol changes |
| 3. Live | Against a real [external system] instance | Any integration/communication change, before it ships |
| 4. Hardware / on-site | [the verification only Stevie can do] | 1.0.0; until then all releases are pre-releases |

Verify before claiming: tier 1 always; the matching higher tier when its
trigger applies; run the actual container when Dockerfile/entrypoint change.

## Milestone plan

The approved plan, ticked as milestones ship. This survives context loss;
conversation memory doesn't. Approved changes to the plan get edited here;
mid-project ideas that aren't in the plan go to HANDOVER.md open items.

- [ ] 0.1.0 — milestone 0 (scaffold TODOs) + [first must-wants]
- [ ] 0.2.0 — [...]
- [ ] 1.0.0 — [tier-4 verification passed; see testing tiers]

## Worktrees (parallel or risky work)

- Use a worktree for: risky refactors/spikes, parallel sub-agent build
  work, anything that would leave `main` dirty across sessions. Plain
  single-threaded milestone work doesn't need one.
- For sub-agent work, **prefer the harness's built-in worktree isolation**
  (spawn the agent with worktree isolation) — it creates and cleans up the
  worktree itself, so there's no lifecycle to manage.
- Manual, long-lived worktrees live **outside OneDrive**:
  `C:\worktrees\<repo-name>\<branch>` (OneDrive sync fights `.git` locks
  and thrashes on build output). Never create one inside the OneDrive
  project folder. If one is ever orphaned (crash, deleted folder), run
  `git worktree prune`.
- `CLAUDE.md` and `DECISIONS.md` are committed, so every worktree has the
  project rules. `HANDOVER.md`, `source-files/`, and `.env` do NOT follow —
  copy `.env` in manually only if the work needs it.
- Finish by merging the branch back and `git worktree remove` — a worktree
  is never the long-lived copy, and nothing releases from one (releases are
  tag-driven from `main` via CI).

## Sub-agents and delegation

Defined in `.claude/agents/` (committed): `docs-writer` (fast model) drafts
README/CHANGELOG/wiki, `docs-auditor` (stronger model) adversarially audits
docs before release, `scout` digests large `source-files/` inputs and
third-party API docs into briefs, and `code-auditor` reviews branch diffs
against this project's contract (tier triggers, test fidelity, leakage)
before they merge to `main` — run it on every sub-agent build branch and
before any release with code changes; generic bug-hunting stays with the
built-in `/code-review`. Model choices live in those files only — update
them there when models change, not in prose rules.

Delegation policy: the main agent may spawn as many sub-agents as the task
warrants — parallel searches, isolated worktree builds, independent
reviews — without asking first. Delegate when it protects the main
session's context (large reads → `scout`) or when work parallelizes
cleanly; don't delegate trivially serial work. Model choice for ad-hoc
sub-agents is the main agent's call by task weight: cheap/fast for
mechanical or first-draft work, the strongest available for adversarial
review and anything that gates a release. The only hard pins are the docs
pair above, where the asymmetry (fast drafts, stronger audit) IS the
policy. Milestone checkpoints still apply: delegation never crosses a
milestone boundary Stevie hasn't approved.

## Interruption resilience (usage limits)

Sessions die mid-task: the 5-hour usage window, a crash, a machine switch.
The remaining budget is NOT readable from inside a session (only Stevie
can see `/usage`), so the system is crash-safety, not rationing — work so
that an interruption at any moment costs minutes, not hours:

- Small verifiable increments. Never let more than ~30 minutes of work sit
  unpushed; commit and push after every green step. `wip:` commits with
  red tests are fine on a branch — an unpushed working tree is the only
  unacceptable state.
- Run `/checkpoint` (WIP commit+push + HANDOVER resume note, ~2 min) after
  each meaningful unit of work, before any large sub-agent fan-out or long
  autonomous stretch, and immediately if Stevie mentions limits/credits.
- Announce before starting an unusually large fan-out or long autonomous
  run, so Stevie — who can see the meter — has the chance to defer it to
  after the window resets. If he says the window is nearly spent, switch
  to small serial steps with a checkpoint after each.
- Cold-start resume: HANDOVER.md Current state (`Next action:` line), then
  `git log --oneline -10` + `git status`. Same machine: `claude --continue`
  also restores the conversation, but the files are the contract.
- Economy comes from the delegation policy (cheap models for mechanical
  work, `scout` for big reads) — never from skipping verification tiers or
  leaving checklists unticked.

## Releases

Every release is driven end to end by the `/release` skill, which holds
the canonical release checklist and ends by pasting it into the
conversation with every item ticked. Ambient invariants (these hold even
outside a release): CI owns releases — never `gh release create`, never
push images, never edit tags by hand; if CI fails, no partial release
exists — fix and re-tag. Increments: +0.0.1 bugfix / +0.1.0 minor /
+1.0.0 major, always three-part X.Y.Z.

## House conventions

- Commits end with `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`;
  git identity is repo-local `Stevie <sremich@gmail.com>`.
- The version lives ONLY in `VERSION`; language-level copies are derived,
  never hand-edited. CI refuses tags that disagree.
- Never commit secrets, tokens, runtime logs, or `data/`. Credentials
  arrive via `.env`, not chat.
- [Project-specific binding rules accumulate here as they emerge — schema
  compatibility promises, ownership guards, escaping rules, etc.]
