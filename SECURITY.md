# Security

FPX Converter has no network path and uses no credentials. It reads local
files and writes local files; it never modifies, moves, or deletes a source
`.fpx`, and both the manifest and destination paths are refused if they fall
inside the source tree.

Report anything you think is a vulnerability by opening an issue at
<https://github.com/sremich/fpx-converter/issues>. That is the only channel;
no email address is published for this project. If you believe a report
should not be public, say so in the issue without the details and a private
advisory will be opened.

The published `.exe` is **unsigned**, so Windows SmartScreen will warn about
it. Check the download against the SHA-256 published on that version's
release page — `certutil -hashfile fpx-converter-<version>.exe SHA256` must
match it exactly. Download the executable only from
<https://github.com/sremich/fpx-converter/releases>; every release there is
built by CI from a tagged commit, and nothing is ever uploaded by hand.
