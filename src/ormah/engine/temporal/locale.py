"""Data model for a temporal locale pack.

A pack is the whole temporal grammar of one language, declared as data: the
static phrases it recognises, its own numeric expression, and the unit aliases
that fold its unit words onto the canonical English keys the parser's
unit->days map is written in. Each pack is a module in
``ormah.engine.temporal.locales`` that exports ``LOCALE``.

Grammar is never user-configurable — a pack is code with tests, not a regex an
operator types into ``.env``.
"""

from __future__ import annotations

import importlib
import re
from dataclasses import dataclass, field


_CODE_RE = re.compile(r"[a-z]{2,3}(?:-[A-Z]{2})?")
_LOCALES_PACKAGE = "ormah.engine.temporal.locales"


@dataclass(frozen=True)
class StaticPhrase:
    """One declared phrase — the single source of truth for both recognition and stripping."""

    pattern: re.Pattern
    """The regex that recognises the phrase, including any leading preposition it removes."""

    window: tuple[int, int | None] | None = None
    """``(days_start, days_end)``, where ``days_end = None`` extends the window to now.

    ``None`` makes the entry **strip-only**: it is removed from the query but
    never selects a window and never makes temporal detection true.
    """

    @property
    def is_strip_only(self) -> bool:
        return self.window is None


@dataclass(frozen=True)
class TemporalLocale:
    """One language's temporal grammar."""

    code: str
    """The pack's identifier as it appears in ``ORMAH_TEMPORAL_LOCALES`` (``en``, ``pt-BR``)."""

    static_phrases: tuple[StaticPhrase, ...] = ()
    """Also the strip order: a phrase that overlaps a shorter one is declared first."""

    numeric_pattern: re.Pattern | None = None
    """This language's numeric expression, matching only its own determiners and units.

    The capture-group contract is fixed and shared across packs, because the
    parser reads the groups: the preposition and determiner prefix is
    non-capturing, **group 1 is the count** and **group 2 is the unit lexeme**.
    """

    unit_aliases: dict[str, str] = field(default_factory=dict)
    """This language's unit words folded onto the canonical English keys. Empty for ``en``."""

    @property
    def windowed_phrases(self) -> tuple[StaticPhrase, ...]:
        """The entries that declare a window — the keyword table, derived."""
        return tuple(p for p in self.static_phrases if not p.is_strip_only)

    @property
    def strip_patterns(self) -> tuple[re.Pattern, ...]:
        """Every entry's pattern plus the numeric one — the strip table, derived.

        There is no second hand-written list, so a phrase can never be
        recognised for the window and forgotten for the strip.
        """
        patterns = [p.pattern for p in self.static_phrases]
        if self.numeric_pattern is not None:
            patterns.append(self.numeric_pattern)
        return tuple(patterns)


def load_locales(codes: tuple[str, ...]) -> tuple[TemporalLocale, ...]:
    """Import the packs named by *codes* from the locale package, in that order.

    ``pt-BR`` loads ``LOCALE`` from ``ormah.engine.temporal.locales.pt_br``.
    A code is checked against a fixed shape before anything is imported, so the
    setting can never name a module outside that package. Codes are
    case-sensitive: ``pt-br`` is a typo, not a match.

    Raises :class:`ValueError` on a malformed code or one with no pack.
    """
    return tuple(_load_locale(code) for code in codes)


def _load_locale(code: str) -> TemporalLocale:
    if not _CODE_RE.fullmatch(code):
        raise ValueError(
            f"invalid temporal locale code {code!r}; expected a form like 'en' or 'pt-BR'"
        )
    name = f"{_LOCALES_PACKAGE}.{code.lower().replace('-', '_')}"
    try:
        module = importlib.import_module(name)
    except ModuleNotFoundError as exc:
        # A broken import inside an existing pack is a bug, not an unknown code.
        if exc.name != name:
            raise
        raise ValueError(f"unknown temporal locale {code!r}; no module {name}") from None
    return module.LOCALE


def parse_locale_codes(value: str) -> tuple[str, ...]:
    """Parse the comma-separated ``ORMAH_TEMPORAL_LOCALES`` form into ordered codes.

    Tokens are split on ``,``, trimmed, and empty tokens dropped; duplicates are
    dropped keeping first-seen order. An empty result, or a code with no pack,
    raises :class:`ValueError` rather than silently disabling temporal parsing.
    """
    codes = tuple(dict.fromkeys(token.strip() for token in value.split(",") if token.strip()))
    if not codes:
        raise ValueError(f"temporal_locales must name at least one locale, got {value!r}")
    load_locales(codes)
    return codes
