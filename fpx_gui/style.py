"""The two palettes, and the substitution that turns `style.qss` into a sheet.

Qt stylesheets have no variables, so a light and a dark theme are normally two
files that drift apart. Here there is one file of rules and two dictionaries
of colours: a rule can only ever be written once.

Deliberately importable without Qt, so the palettes and the substitution are
testable with no display and no `QApplication`.
"""

from __future__ import annotations

from importlib import resources

STYLESHEET_RESOURCE = "style.qss"

LIGHT: dict[str, str] = {
    "bg": "#f4f6f9",
    "surface": "#ffffff",
    "field": "#ffffff",
    "border": "#d9dee7",
    "text": "#141922",
    "muted": "#5c6675",
    "accent": "#2f6feb",
    "accentHover": "#2158c4",
    "accentText": "#ffffff",
    "ok": "#146c43",
    "warn": "#8a5a00",
    "error": "#b32318",
    "logBg": "#ffffff",
    "logText": "#2b323d",
}

DARK: dict[str, str] = {
    "bg": "#12151b",
    "surface": "#1a1f27",
    "field": "#222833",
    "border": "#2f3743",
    "text": "#e7ecf3",
    "muted": "#9aa4b2",
    "accent": "#4c8dff",
    "accentHover": "#6ba0ff",
    "accentText": "#0a1120",
    "ok": "#5cd38a",
    "warn": "#f0b849",
    "error": "#ff8a80",
    "logBg": "#0d1017",
    "logText": "#c3ccd9",
}


def palette(dark: bool) -> dict[str, str]:
    return DARK if dark else LIGHT


def read_template() -> str:
    """The raw `.qss`, read as package data so it survives being frozen."""
    return resources.files(__package__).joinpath(STYLESHEET_RESOURCE).read_text(
        encoding="utf-8"
    )


def substitute(template: str, colours: dict[str, str]) -> str:
    """Replace every `@name` with its colour.

    Longest name first. `@accent` is a prefix of `@accentText`, and replacing
    the short one first would leave `#2f6febText` in the sheet -- which Qt
    would silently drop along with the rest of that rule.
    """
    result = template
    for name in sorted(colours, key=len, reverse=True):
        result = result.replace(f"@{name}", colours[name])
    return result


def build_stylesheet(dark: bool) -> str:
    """The finished sheet for one theme."""
    return substitute(read_template(), palette(dark))
