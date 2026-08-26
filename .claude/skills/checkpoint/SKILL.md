---
name: checkpoint
description: Fast mid-task save so work survives hitting the usage limit, a crash, or a machine switch — WIP commit + push plus a one-paragraph resume note. Use after each meaningful unit of work, before any large sub-agent fan-out, and immediately if Stevie mentions limits or credits. Much lighter than /wrap-up.
---

# Checkpoint

Assume the session can end mid-sentence. The goal: a fresh session —
possibly on another machine — picks up in minutes without redoing or
re-deriving anything. Speed matters; this should take one to two minutes,
not ten.

## Steps

1. **Commit whatever exists.** `git add -A` and commit with a `wip:`
   message stating the actual state — compiles or not, which tests are
   red, what's half-wired. A red-test WIP commit on a branch is fine; more
   than ~30 minutes of unpushed work is the only unacceptable state.
2. **Push.**
3. **Update `HANDOVER.md` → Current state**, including the
   `Next action:` line: the exact next command or edit, what's failing and
   why (if known), and anything that so far exists only in conversation —
   a decision made, a gotcha discovered, a dead end already ruled out.
   Dead ends matter most: they're what a blind restart wastes credits
   re-exploring.
4. **Stop there.** No changelog, no docs pass, no checklists — that's
   `/wrap-up`, run at real session ends.

## Resume protocol (next session, any machine)

Read `HANDOVER.md` Current state, then `git log --oneline -10` and
`git status`, and continue from `Next action:`. On the same machine,
`claude --continue` additionally restores the conversation itself — but
never depend on it; the files are the contract.
