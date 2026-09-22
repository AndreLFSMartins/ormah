"""Tests for the language-agnostic TemporalParser.

Every parser here is constructed with an explicit set of packs — no test in
this module reads global configuration or the module-level classifier
functions. Assertions are only ever on the two externally observable outputs:
the window dict for a prompt, and the residue string for a prompt.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone

import pytest

from ormah.engine.temporal import StaticPhrase, TemporalLocale, TemporalParser
from ormah.engine.temporal.locales import en, pt_br

EN = en.LOCALE
PT = pt_br.LOCALE


def _parser(*locales):
    return TemporalParser(locales)


BOTH_ORDERS = pytest.mark.parametrize(
    "locales",
    [pytest.param((EN, PT), id="en,pt-BR"), pytest.param((PT, EN), id="pt-BR,en")],
)


def _days_ago(iso: str) -> float:
    return (datetime.now(timezone.utc) - datetime.fromisoformat(iso)).total_seconds() / 86400


class TestStripRemovesThePhrase:
    def test_english_phrase_is_removed(self):
        assert _parser(EN).strip_temporal_phrases("what did we do last week") == "what did we do"

    def test_portuguese_phrase_is_removed(self):
        assert _parser(PT).strip_temporal_phrases("o que fizemos ontem") == "o que fizemos"


class TestStripConsumesItsOwnLeadingPreposition:
    def test_the_reported_bug(self):
        assert (
            _parser(EN, PT).strip_temporal_phrases("o que fizemos na semana passada")
            == "o que fizemos"
        )

    @pytest.mark.parametrize(
        "prompt",
        [
            "o que fizemos no mês passado",
            "o que fizemos nos últimos 3 dias",
            "o que fizemos nas últimas 2 semanas",
            "o que fizemos em semana passada",
        ],
    )
    def test_every_sibling_contraction_goes_with_the_phrase(self, prompt):
        assert _parser(EN, PT).strip_temporal_phrases(prompt) == "o que fizemos"

    def test_an_interior_contraction_survives_while_the_leading_one_goes(self):
        assert (
            _parser(EN, PT).strip_temporal_phrases("mudanças na API nos últimos 3 dias")
            == "mudanças na API"
        )

    def test_english_preposition_goes_with_an_end_positioned_phrase(self):
        assert (
            _parser(EN, PT).strip_temporal_phrases("changes to the API in the last 3 days")
            == "changes to the API"
        )

    @pytest.mark.parametrize(
        "prompt, residue",
        [
            ("what did we do in the last 3 days on auth", "what did we do on auth"),
            ("what changed in the last 3 days in auth", "what changed in auth"),
        ],
    )
    def test_a_mid_sentence_phrase_takes_its_preposition_too(self, prompt, residue):
        # The old end-of-residue cleanup left "in the" behind here.
        assert _parser(EN, PT).strip_temporal_phrases(prompt) == residue

    def test_a_preposition_not_leading_a_phrase_survives(self):
        assert (
            _parser(EN, PT).strip_temporal_phrases("notes from the meeting last week")
            == "notes from the meeting"
        )

    @BOTH_ORDERS
    def test_a_pack_consumes_only_its_own_prepositions(self, locales):
        # `no` is a PT-BR contraction, but "last 3 days" is English, so it stays.
        parser = TemporalParser(locales)
        assert parser.strip_temporal_phrases("please say no last 3 days") == "please say no"
        assert parser.strip_temporal_phrases("work from ontem") == "work from"
        assert parser.strip_temporal_phrases("work from yesterday") == "work"

    @BOTH_ORDERS
    def test_nothing_removed_means_nothing_cleaned(self, locales):
        assert TemporalParser(locales).strip_temporal_phrases("say no") == "say no"

    def test_a_strip_only_phrase_leaves_its_preposition(self):
        assert (
            _parser(EN, PT).strip_temporal_phrases("look in the recent logs")
            == "look in the logs"
        )


class TestRemovalsAreSequentialReSearches:
    def test_two_disjoint_phrases_are_both_removed(self):
        assert (
            _parser(EN, PT).strip_temporal_phrases("what did we do yesterday and last week")
            == "what did we do and"
        )

    def test_the_combined_phrase_is_removed_whole(self):
        # Declared before "semana passada"; the other way round leaves "nesta".
        assert (
            _parser(EN, PT).strip_temporal_phrases(
                "nesta semana passada discutimos autenticação"
            )
            == "discutimos autenticação"
        )

    def test_overlapping_phrases_do_not_eat_the_topic(self):
        # Collecting spans on the original prompt and deleting them afterwards
        # right-to-left cuts into "discutimos".
        assert (
            _parser(EN, PT).strip_temporal_phrases("esta semana passada discutimos autenticação")
            == "esta discutimos autenticação"
        )


def _locale(code, *phrases):
    return TemporalLocale(
        code=code,
        static_phrases=tuple(
            StaticPhrase(pattern=re.compile(p), window=w) for p, w in phrases
        ),
    )


class TestTheLeftmostPhraseSelectsTheWindow:
    @BOTH_ORDERS
    def test_the_leftmost_numeric_match_wins_across_packs(self, locales):
        params = TemporalParser(locales).extract_time_params(
            "compare últimas 2 semanas with last 3 days"
        )
        # The rolling two-week window: 28d ago -> 14d ago.
        assert 27.9 < _days_ago(params["created_after"]) < 28.1
        assert 13.9 < _days_ago(params["created_before"]) < 14.1

    @BOTH_ORDERS
    def test_the_reversed_prompt_selects_the_other_numeric(self, locales):
        params = TemporalParser(locales).extract_time_params(
            "compare last 3 days with últimas 2 semanas"
        )
        assert 2.9 < _days_ago(params["created_after"]) < 3.1
        assert _days_ago(params["created_before"]) < 0.1

    @BOTH_ORDERS
    @pytest.mark.parametrize(
        "prompt, after, before",
        [
            ("compare ontem with last month", 2, 1),
            ("compare last month with ontem", 60, 30),
        ],
    )
    def test_the_leftmost_static_phrase_wins_across_packs(self, locales, prompt, after, before):
        params = TemporalParser(locales).extract_time_params(prompt)
        assert after - 0.1 < _days_ago(params["created_after"]) < after + 0.1
        assert before - 0.1 < _days_ago(params["created_before"]) < before + 0.1

    @BOTH_ORDERS
    @pytest.mark.parametrize(
        "prompt, after, before",
        [
            ("today: resumo das últimas 2 semanas", 1, 0),
            ("last week and last 2 weeks", 14, 7),
        ],
    )
    def test_numeric_no_longer_outranks_an_earlier_static_phrase(
        self, locales, prompt, after, before
    ):
        params = TemporalParser(locales).extract_time_params(prompt)
        assert after - 0.1 < _days_ago(params["created_after"]) < after + 0.1
        assert before - 0.1 < _days_ago(params["created_before"]) < before + 0.1

    @BOTH_ORDERS
    def test_nesta_semana_passada_is_last_week_and_strips_whole(self, locales):
        parser = TemporalParser(locales)
        params = parser.extract_time_params("nesta semana passada")
        assert 13.9 < _days_ago(params["created_after"]) < 14.1
        assert 6.9 < _days_ago(params["created_before"]) < 7.1
        assert parser.strip_temporal_phrases("nesta semana passada") == ""

    def test_the_longest_match_wins_a_tie_at_the_same_offset(self):
        # Declared shorter-first, so declaration order alone would pick 1d.
        pack = _locale("xx", (r"\blast\b", (1, None)), (r"\blast\s+week\b", (14, 7)))
        params = TemporalParser((pack,)).extract_time_params("last week")
        assert 13.9 < _days_ago(params["created_after"]) < 14.1

    def test_pack_order_breaks_a_tie_of_offset_and_length(self):
        first = _locale("aa", (r"\bfoo\b", (2, 1)))
        second = _locale("bb", (r"\bfoo\b", (60, 30)))
        forward = TemporalParser((first, second)).extract_time_params("foo")
        reverse = TemporalParser((second, first)).extract_time_params("foo")
        assert 1.9 < _days_ago(forward["created_after"]) < 2.1
        assert 59.9 < _days_ago(reverse["created_after"]) < 60.1


class TestWindowArithmetic:
    @pytest.mark.parametrize(
        "prompt,after,before",
        [
            ("show me the past 2 weeks", 28, 14),
            ("mostra as últimas 2 semanas", 28, 14),
            ("last 3 months summary", 180, 90),
            ("resumo dos últimos 3 meses", 180, 90),
        ],
    )
    def test_rolling_previous_period_for_weeks_and_months_above_one(self, prompt, after, before):
        params = _parser(EN, PT).extract_time_params(prompt)
        assert after - 0.1 < _days_ago(params["created_after"]) < after + 0.1
        assert before - 0.1 < _days_ago(params["created_before"]) < before + 0.1

    @pytest.mark.parametrize(
        "prompt,days",
        [
            ("show me the past 1 week", 7),
            ("mostra a última 1 semana", 7),
            ("what did we do in the last 4 days", 4),
            ("o que fizemos nos últimos 4 dias", 4),
            ("what happened in the last 6 hours", 0.25),
            ("o que aconteceu nas últimas 6 horas", 0.25),
            ("last 1 month recap", 30),
            ("resumo do último 1 mês", 30),
        ],
    )
    def test_unit_to_days_and_the_open_ended_branch(self, prompt, days):
        params = _parser(EN, PT).extract_time_params(prompt)
        assert days - 0.1 < _days_ago(params["created_after"]) < days + 0.1
        assert _days_ago(params["created_before"]) < 0.1

    @pytest.mark.parametrize(
        "prompt,after,before",
        [
            ("what did we do today", 1, 0),
            ("o que fizemos hoje", 1, 0),
            ("what did we do yesterday", 2, 1),
            ("o que fizemos ontem", 2, 1),
            ("what happened last week", 14, 7),
            ("o que aconteceu na semana passada", 14, 7),
            ("what happened this week", 7, 0),
            ("o que fizemos nesta semana", 7, 0),
            ("what happened last month", 60, 30),
            ("o que fizemos no mês passado", 60, 30),
            ("what changed recently", 3, 0),
            ("o que mudou recentemente", 3, 0),
        ],
    )
    def test_static_windows(self, prompt, after, before):
        params = _parser(EN, PT).extract_time_params(prompt)
        assert after - 0.1 < _days_ago(params["created_after"]) < after + 0.1
        assert before - 0.1 < _days_ago(params["created_before"]) < before + 0.1

    @pytest.mark.parametrize(
        "prompt", ["what were we working on", "no que estávamos trabalhando", "any recent changes"]
    )
    def test_a_prompt_with_no_window_falls_back_to_three_days(self, prompt):
        params = _parser(EN, PT).extract_time_params(prompt)
        assert 2.9 < _days_ago(params["created_after"]) < 3.1
        assert _days_ago(params["created_before"]) < 0.1


class TestTemporalDetection:
    @pytest.mark.parametrize(
        "prompt",
        [
            "what did we do yesterday",
            "o que fizemos ontem",
            "what did we do in the last 4 days",
            "o que fizemos nos últimos 4 dias",
        ],
    )
    def test_windowed_and_numeric_phrases_are_temporal(self, prompt):
        assert _parser(EN, PT).has_temporal_phrases(prompt) is True

    def test_a_strip_only_phrase_is_not_temporal_but_is_still_stripped(self):
        parser = _parser(EN, PT)
        assert parser.has_temporal_phrases("show me recent changes") is False
        assert parser.strip_temporal_phrases("show me recent changes") == "show me changes"

    def test_a_prompt_with_no_phrase_is_not_temporal(self):
        assert _parser(EN, PT).has_temporal_phrases("what were we working on") is False


class TestThePackSetGatesBehaviour:
    def test_an_english_only_parser_does_not_see_portuguese(self):
        parser = _parser(EN)
        assert parser.has_temporal_phrases("o que fizemos na semana passada") is False
        assert (
            parser.strip_temporal_phrases("o que fizemos na semana passada")
            == "o que fizemos na semana passada"
        )
        params = parser.extract_time_params("o que fizemos ontem")
        assert 2.9 < _days_ago(params["created_after"]) < 3.1

    def test_a_portuguese_only_parser_does_not_see_english(self):
        parser = _parser(PT)
        assert parser.has_temporal_phrases("what did we do last week") is False
        assert (
            parser.strip_temporal_phrases("what did we do last week") == "what did we do last week"
        )
