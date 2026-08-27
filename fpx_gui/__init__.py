"""fpx-gui — a desktop front end for `fpx_converter`, for people who do not use a terminal.

**It wraps the CLI; it does not reimplement it.** Every conversion this
window starts is `fpx_converter` running as a child process with the same
arguments a person would have typed. The conversion logic has one home and
one set of tests, and nothing in this package decodes a pixel, writes a tag,
or decides where a file lands.

That has a consequence worth stating plainly: **the read-only-source rule is
enforced in exactly one place, `config.ensure_outside_source`, and this
package calls it rather than reasoning about paths itself.** The window
checks the destination before it launches anything so it can show the refusal
in a dialog instead of a stack trace, and the CLI checks it again for real.
Two calls to one function, not two implementations of one rule.

Nothing here imports Qt at package level. `invoke`, `options`, `progress`,
`runner` and `summary` are plain Python and are tested that way; `app`,
`style` and `window` are the Qt half.
"""

from __future__ import annotations

__all__: list[str] = []
