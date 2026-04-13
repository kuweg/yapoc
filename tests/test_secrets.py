"""Tests for app.utils.secrets — credential scrubbing."""

from app.utils.secrets import scrub


def test_anthropic_key():
    text = "my key is sk-ant-abc123def456ghi789jkl012mno"
    assert "[REDACTED]" in scrub(text)
    assert "sk-ant-" not in scrub(text)


def test_openai_key():
    text = "openai key: sk-abcdefghijklmnopqrstuv1234567890"
    assert "[REDACTED]" in scrub(text)
    assert "sk-abcdef" not in scrub(text)


def test_openrouter_key():
    text = "key=sk-or-v1-abc123def456ghi789jkl012mno345"
    assert "[REDACTED]" in scrub(text)


def test_google_api_key():
    text = "google: AIzaSyA1234567890abcdefghijklmnopqrs"
    assert "[REDACTED]" in scrub(text)


def test_password_pattern():
    text = "password=mysecretpassword123"
    assert "[REDACTED]" in scrub(text)
    assert "mysecret" not in scrub(text)


def test_api_key_pattern():
    text = "api_key: some_secret_value_here"
    assert "[REDACTED]" in scrub(text)


def test_connection_string():
    text = "postgres://admin:supersecret@db.example.com:5432/mydb"
    assert "[REDACTED]" in scrub(text)


def test_pem_key():
    text = "-----BEGIN RSA PRIVATE KEY-----\nMIIE..."
    assert "[REDACTED]" in scrub(text)


def test_no_false_positive_on_normal_text():
    text = "The agent completed the task successfully. No errors found."
    assert scrub(text) == text


def test_no_false_positive_on_code():
    text = "def calculate_score(items): return sum(i.value for i in items)"
    assert scrub(text) == text


def test_multiple_secrets():
    text = "key1=sk-ant-abc123def456ghi789jkl012mno and password=secret123"
    result = scrub(text)
    assert result.count("[REDACTED]") == 2


def test_empty_string():
    assert scrub("") == ""
