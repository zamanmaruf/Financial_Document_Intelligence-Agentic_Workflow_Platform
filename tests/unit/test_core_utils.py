from __future__ import annotations

import time

import pytest

from app.core.errors import ProviderError, ProviderTimeoutError
from app.core.hashing import sha256_text, stable_hash, stable_json
from app.core.resilience import RetriesExhaustedError, RetryPolicy, call_with_timeout, retry_call
from app.core.text import (
    clean_line,
    content_tokens,
    extract_numbers,
    normalize_number,
    parse_amount,
    split_sentences,
)


class TestHashing:
    def test_stable_json_is_key_order_independent(self) -> None:
        assert stable_json({"b": 1, "a": [2, {"d": 1, "c": 2}]}) == stable_json(
            {"a": [2, {"c": 2, "d": 1}], "b": 1}
        )
        assert stable_hash({"x": 1, "y": 2}) == stable_hash({"y": 2, "x": 1})

    def test_sha256_known_vector(self) -> None:
        assert sha256_text("abc") == (
            "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
        )


class TestNumberNormalization:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("1,234.50", "1234.5"),
            ("$ 4,850.00", "4850"),
            ("(12,000)", "-12000"),
            ("-3.5", "-3.5"),
            ("0.40", "0.4"),
            ("0.75%", "0.75"),
            ("1,000", "1000"),
            ("abc", None),
            # European separators
            ("12.435,50", "12435.5"),
            ("€ 1.985,50", "1985.5"),
            ("2.340.500", "2340500"),
            ("2,1%", "2.1"),
            ("1 234,56", "1234.56"),
            ("(1.204.000)", "-1204000"),
            # a lone dot group stays a decimal (English reading)
            ("1.234", "1.234"),
            ("31.12.2024", None),
        ],
    )
    def test_normalize_number(self, raw: str, expected: str | None) -> None:
        assert normalize_number(raw) == expected

    def test_european_and_english_forms_compare_equal(self) -> None:
        source = "Amount due: 12.435,50 EUR"
        answer = "The amount due is EUR 12,435.50."
        assert extract_numbers(source) == extract_numbers(answer) == ["12435.5"]
        parsed = parse_amount("Subtotal: 10.450,00 EUR")
        assert parsed is not None
        assert parsed[0] == pytest.approx(10450.0)

    def test_sentence_final_period_is_not_part_of_a_number(self) -> None:
        assert extract_numbers("Net income was 1,532,600.") == ["1532600"]

    def test_extract_numbers_drops_sign_and_single_digits(self) -> None:
        nums = extract_numbers("Revenue 4,350,000 fell (120,000) on page 3 of 12.")
        assert "4350000" in nums
        assert "120000" in nums
        assert "3" not in nums

    def test_parse_amount(self) -> None:
        parsed = parse_amount("Amount Due: $5,238.00")
        assert parsed is not None
        assert parsed[0] == pytest.approx(5238.0)
        assert parse_amount("no figures here") is None

    def test_clean_line_collapses_dot_leaders(self) -> None:
        assert clean_line("Total assets ........ 1,000") == "Total assets 1,000"

    def test_sentences_and_tokens(self) -> None:
        assert split_sentences("First one. Second one.") == ["First one.", "Second one."]
        tokens = content_tokens("What is the total amount due?")
        assert "the" not in tokens
        assert "amount" in tokens
        # stopwords are dropped before stemming, so "this" doesn't survive as "thi"
        assert content_tokens("Who sent this invoice? Does it say?") == ["sent", "invoice", "say"]


class TestResilience:
    def test_retry_succeeds_after_transient_failures(self) -> None:
        calls = {"n": 0}

        def flaky() -> str:
            calls["n"] += 1
            if calls["n"] < 3:
                raise ProviderError("transient")
            return "ok"

        outcome = retry_call(flaky, RetryPolicy(max_retries=2, backoff_s=0), (ProviderError,))
        assert outcome.value == "ok"
        assert outcome.retry_count == 2

    def test_retry_exhausted_wraps_last_error(self) -> None:
        def always_fail() -> None:
            raise ProviderError("down")

        with pytest.raises(RetriesExhaustedError) as info:
            retry_call(always_fail, RetryPolicy(max_retries=1, backoff_s=0), (ProviderError,))
        assert info.value.attempts == 2
        assert isinstance(info.value.last_error, ProviderError)

    def test_non_retryable_error_propagates_immediately(self) -> None:
        calls = {"n": 0}

        def bad() -> None:
            calls["n"] += 1
            raise ValueError("bug")

        with pytest.raises(ValueError, match="bug"):
            retry_call(bad, RetryPolicy(max_retries=3, backoff_s=0), (ProviderError,))
        assert calls["n"] == 1

    def test_backoff_is_exponential_and_capped(self) -> None:
        policy = RetryPolicy(max_retries=5, backoff_s=1.0, backoff_multiplier=2.0, max_backoff_s=3)
        assert [policy.delay_for(i) for i in (1, 2, 3)] == [1.0, 2.0, 3.0]

    def test_sleep_is_injected(self) -> None:
        slept: list[float] = []
        calls = {"n": 0}

        def flaky() -> int:
            calls["n"] += 1
            if calls["n"] == 1:
                raise ProviderError("x")
            return 1

        retry_call(
            flaky, RetryPolicy(max_retries=1, backoff_s=0.25), (ProviderError,), sleep=slept.append
        )
        assert slept == [0.25]

    def test_timeout(self) -> None:
        with pytest.raises(ProviderTimeoutError):
            call_with_timeout(lambda: time.sleep(0.5), timeout_s=0.05)
        assert call_with_timeout(lambda: 42, timeout_s=1.0) == 42
