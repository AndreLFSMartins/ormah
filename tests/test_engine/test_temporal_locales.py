"""Tests for the temporal locale data model and the loader."""

from __future__ import annotations

import re

import pytest

from ormah.config import Settings
from ormah.engine.temporal import StaticPhrase, TemporalLocale, load_locales


class TestStaticPhrase:
    def test_windowed_entry_carries_its_window(self):
        phrase = StaticPhrase(pattern=re.compile(r"\byesterday\b"), window=(2, 1))
        assert phrase.window == (2, 1)
        assert phrase.is_strip_only is False

    def test_open_ended_window_uses_none_as_its_end(self):
        phrase = StaticPhrase(pattern=re.compile(r"\btoday\b"), window=(1, None))
        assert phrase.window == (1, None)
        assert phrase.is_strip_only is False

    def test_entry_without_a_window_is_strip_only(self):
        phrase = StaticPhrase(pattern=re.compile(r"\brecent\b"))
        assert phrase.window is None
        assert phrase.is_strip_only is True


class TestLoadLocales:
    def test_returns_packs_in_the_order_the_codes_name_them(self):
        assert [loc.code for loc in load_locales(("pt-BR", "en"))] == ["pt-BR", "en"]
        assert [loc.code for loc in load_locales(("en", "pt-BR"))] == ["en", "pt-BR"]

    def test_a_single_code_returns_only_that_pack(self):
        assert [loc.code for loc in load_locales(("en",))] == ["en"]

    def test_raises_on_a_well_formed_code_with_no_pack(self):
        with pytest.raises(ValueError, match="unknown temporal locale"):
            load_locales(("fr",))

    @pytest.mark.parametrize(
        "code", ["pt-br", "pt_br", "PT-BR", "en.x", "..en", "locale", "__init__", "os.path", ""]
    )
    def test_rejects_a_code_outside_the_fixed_shape_before_importing(self, code):
        # The shape check is what keeps the setting from naming an arbitrary
        # module: "os.path" is importable, but never from the locale package.
        with pytest.raises(ValueError, match="invalid temporal locale code"):
            load_locales((code,))

    def test_loads_the_packs_the_setting_names(self, monkeypatch):
        monkeypatch.setenv("ORMAH_TEMPORAL_LOCALES", "pt-BR,en")
        settings = Settings(_env_file=None, memory_dir="/tmp/ormah_test")
        loaded = load_locales(settings.temporal_locale_codes)
        assert [loc.code for loc in loaded] == ["pt-BR", "en"]


def _pack(code: str) -> TemporalLocale:
    return load_locales((code,))[0]


class TestBuiltInPackDeclarations:
    def test_recent_is_the_only_strip_only_entry_and_lives_in_the_en_pack(self):
        strip_only = [
            (locale.code, phrase)
            for locale in load_locales(("en", "pt-BR"))
            for phrase in locale.static_phrases
            if phrase.is_strip_only
        ]
        assert [code for code, _ in strip_only] == ["en"]
        phrase = strip_only[0][1]
        assert phrase.pattern.search("show me recent changes") is not None
        assert phrase.pattern.search("what changed recently") is None


class TestBuiltInNumericPatterns:
    def test_capture_groups_are_count_then_unit_in_en(self):
        match = _pack("en").numeric_pattern.search("changes to the API in the last 3 days")
        assert match is not None
        assert match.groups() == ("3", "days")

    def test_capture_groups_are_count_then_unit_in_pt_br(self):
        match = _pack("pt-BR").numeric_pattern.search("resumo das últimas 2 semanas")
        assert match is not None
        # A capturing determiner or preposition shifts every group and would
        # make the parser read "últimas" as the count.
        assert match.groups() == ("2", "semanas")

    @pytest.mark.parametrize(
        "prompt",
        ["resumo das últimas 2 semanas", "last 2 semanas", "últimas 2 weeks"],
    )
    def test_en_numeric_pattern_ignores_pt_br_forms(self, prompt):
        assert _pack("en").numeric_pattern.search(prompt) is None

    @pytest.mark.parametrize(
        "prompt",
        ["changes in the last 3 days", "past 2 weeks", "last 2 semanas", "últimas 2 weeks"],
    )
    def test_pt_br_numeric_pattern_ignores_en_forms(self, prompt):
        assert _pack("pt-BR").numeric_pattern.search(prompt) is None


class TestBuiltInUnitAliases:
    def test_en_pack_needs_no_aliases(self):
        assert _pack("en").unit_aliases == {}

    @pytest.mark.parametrize(
        "prompt, canonical",
        [
            ("últimas 3 horas", "hour"),
            ("última 1 hora", "hour"),
            ("últimos 5 dias", "day"),
            ("último 1 dia", "day"),
            ("últimas 2 semanas", "week"),
            ("última 1 semana", "week"),
            ("últimos 3 meses", "month"),
            ("último 1 mês", "month"),
            ("último 1 mes", "month"),
        ],
    )
    def test_pt_br_units_fold_onto_the_canonical_english_keys(self, prompt, canonical):
        pack = _pack("pt-BR")
        match = pack.numeric_pattern.search(prompt)
        assert match is not None, prompt
        # The normalisation the parser applies: lowercase, drop the plural "s",
        # then fold onto the canonical key.
        unit = match.group(2).lower().rstrip("s")
        assert pack.unit_aliases.get(unit, unit) == canonical
