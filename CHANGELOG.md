# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions are always
three-part X.Y.Z (bugfix +0.0.1, minor +0.1.0, major +1.0.0). On release,
move the Unreleased entries into a new version section, bump `VERSION`,
commit, then tag.

## [Unreleased]

### Added
- Project scaffolding from `project-scaffold`.
- `DECISIONS.md`: milestone-0 inventory findings from a read-only spike over
  the full source corpus — FlashPix tile layout, external JPEG table
  splicing, colour space, viewing-transform orientation, embedded thumbnail
  format, deduplication analysis, and the environment constraints.

### Changed
- `.gitignore` extended with the personal-image, sidecar, and output rules
  this project requires; test fixtures under `tests/fixtures/` exempted.
