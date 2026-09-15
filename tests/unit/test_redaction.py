"""Redactor: известные секреты и типовые паттерны никогда не доходят до записи."""

from __future__ import annotations

from release_promotion_agent.core.redaction import MASK, Redactor


def test_known_secret_is_masked_everywhere() -> None:
    redactor = Redactor(known_secrets=("s3cr3t-token-value",))
    out = redactor.redact("подключаюсь с s3cr3t-token-value к API")
    assert "s3cr3t-token-value" not in out
    assert MASK in out


def test_longer_secret_masked_before_shorter_prefix() -> None:
    redactor = Redactor(known_secrets=("abc", "abcdef-long"))
    out = redactor.redact("значение abcdef-long здесь")
    assert "abcdef-long" not in out
    assert "def-long" not in out


def test_key_value_patterns_masked() -> None:
    redactor = Redactor()
    for line in (
        '{"token": "xyz123"}',
        "password=hunter2",
        "Api-Key: verysecret",
    ):
        out = redactor.redact(line)
        assert MASK in out, line
    assert "hunter2" not in redactor.redact("password=hunter2")


def test_bearer_masked() -> None:
    out = Redactor().redact("Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.payload")
    assert "eyJhbGciOiJIUzI1NiJ9" not in out


def test_plain_text_untouched() -> None:
    text = "diff по репозиторию controller-a: ключ retries 3 → 5"
    assert Redactor().redact(text) == text
