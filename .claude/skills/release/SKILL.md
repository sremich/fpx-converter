---
name: release
description: Cut a release end to end — docs pass, CHANGELOG, VERSION bump, tag push, CI watch, post-release pin bump and checklist. Use whenever Stevie says to release, ship, cut, or tag a version.
---

# Cut a release

CI owns releases. Your job is everything around the tag push; CI does the
build/push/release itself. Never `gh release create`, never push images,
never edit tags by hand. If CI fails, no partial release exists — fix and
re-tag.

## Steps, in order

1. **Preconditions.** Working tree clean and pushed; tier-1 tests green
   locally (plus any higher tier whose trigger applied this cycle — see the
   testing tiers table in `CLAUDE.md`). If anything fails, stop and report.
2. **Docs pass.** Spawn `docs-writer` to update README + CHANGELOG (and
   wiki, at minimum Release-History), then `docs-auditor` to audit. The
   audit must PASS before continuing.
3. **Version.** Decide the increment (+0.0.1 bugfix, +0.1.0 minor feature,
   +1.0.0 major) and confirm it with Stevie if not already stated. Move
   CHANGELOG `Unreleased` → `vX.Y.Z` dated section; write the same X.Y.Z
   (three-part, no `v`) into `VERSION`. That file is the only source of
   truth — any language-level copy is derived, never hand-edited.
4. **Commit, push, tag.** Commit both changes, push, then push an annotated
   tag: `git tag -a vX.Y.Z -m "vX.Y.Z"` and `git push origin vX.Y.Z`.
5. **Watch CI.** `gh run watch` (or poll `gh run list`) until the Release
   workflow is fully green: verify → build+push → release created, with the
   pre-release flag automatic while 0.x. If it fails, diagnose, fix,
   delete nothing — bump and re-tag per the failure.
6. **Post-release.** Bump the `docker-compose.yml` image pin to the new
   tag; commit and push.
7. **Prove it.** Paste the checklist below into the conversation and tick
   every item explicitly. Checklists survive context loss; memory doesn't.

## The release checklist (canonical copy — lives here only)

CI does the middle steps itself; the checklist proves nothing around them
was skipped.

- [ ] Tier-1 tests green locally; higher tiers if triggered this cycle
- [ ] Code changes reviewed by `code-auditor` (MERGE verdict)
- [ ] `docs-writer` wrote/updated README + CHANGELOG; `docs-auditor` audited them
- [ ] `CHANGELOG.md`: Unreleased → new `vX.Y.Z` section
- [ ] `VERSION` bumped (three-part X.Y.Z, correct increment: +0.0.1 / +0.1.0 / +1.0.0)
- [ ] Commit pushed; annotated tag `vX.Y.Z` pushed
- [ ] CI release workflow fully green (verify → build+push → release created)
- [ ] Pre-release flag correct (automatic while 0.x)
- [ ] `docker-compose.yml` image pin bumped to the new tag; committed
- [ ] Wiki updated (at minimum Release-History); `docs-auditor` audited; public-safe.
      Location: `docs/wiki/` in-repo while the repo is private; GitHub wiki
      section once public
- [ ] `HANDOVER.md` + `DECISIONS.md` updated; milestone ticked in the
      `CLAUDE.md` plan
