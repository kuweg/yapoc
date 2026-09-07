"""
Tests for app/utils/helpers.py

Covers:
- format_timestamp: iso / human / unix formats, default format, None input,
  unknown format, timezone-aware datetime.
- truncate_text: verifies it is a pass-through no-op (truncation caps were
  removed in 1b02284); None / empty input still round-trip correctly.
- parse_yaml_block: valid frontmatter, multiple fields, None / empty / no
  frontmatter, malformed YAML, only opening delimiter.
"""

from __future__ import annotations

from datetime import datetime, timezone, timedelta

import pytest

from app.utils.helpers import format_timestamp, truncate_text, parse_yaml_block


# ===========================================================================
# format_timestamp
# ===========================================================================

class TestFormatTimestamp:
    """Tests for format_timestamp()."""

    # -----------------------------------------------------------------------
    # Fixtures
    # -----------------------------------------------------------------------

    @pytest.fixture()
    def dt(self) -> datetime:
        """A fixed naive datetime for deterministic assertions."""
        return datetime(2026, 4, 13, 10, 4, 9)

    # -----------------------------------------------------------------------
    # Normal cases
    # -----------------------------------------------------------------------

    def test_iso_format_returns_iso_string(self, dt):
        result = format_timestamp(dt, "iso")
        assert result == "2026-04-13T10:04:09"

    def test_human_format_returns_readable_string(self, dt):
        result = format_timestamp(dt, "human")
        assert result == "April 13, 2026 10:04:09"

    def test_unix_format_returns_float(self, dt):
        result = format_timestamp(dt, "unix")
        assert isinstance(result, float)
        # Round-trip: converting back should give the same datetime
        assert datetime.fromtimestamp(result) == dt

    def test_default_format_is_iso(self, dt):
        """Calling without a format argument should default to 'iso'."""
        assert format_timestamp(dt) == format_timestamp(dt, "iso")

    # -----------------------------------------------------------------------
    # Edge cases
    # -----------------------------------------------------------------------

    def test_none_dt_raises_value_error(self):
        with pytest.raises(ValueError, match="None"):
            format_timestamp(None)

    def test_unknown_format_raises_value_error(self, dt):
        with pytest.raises(ValueError, match="Unknown format"):
            format_timestamp(dt, "rfc2822")

    def test_timezone_aware_iso(self):
        """Timezone-aware datetime should include offset in ISO output."""
        tz = timezone(timedelta(hours=2))
        dt_aware = datetime(2026, 4, 13, 10, 4, 9, tzinfo=tz)
        result = format_timestamp(dt_aware, "iso")
        assert "+02:00" in result

    def test_timezone_aware_unix_matches_utc(self):
        """Unix timestamp of a tz-aware datetime should equal its UTC epoch."""
        dt_utc = datetime(2026, 4, 13, 10, 4, 9, tzinfo=timezone.utc)
        result = format_timestamp(dt_utc, "unix")
        assert isinstance(result, float)
        assert result == dt_utc.timestamp()

    def test_human_format_zero_padded_day(self):
        """Day < 10 should be zero-padded in human format (strftime %d)."""
        dt = datetime(2026, 4, 5, 8, 3, 1)
        result = format_timestamp(dt, "human")
        assert result == "April 05, 2026 08:03:01"


# ===========================================================================
# truncate_text
# ===========================================================================

class TestTruncateText:
    """Tests for truncate_text().

    NOTE: `truncate_text` has been an intentional no-op pass-through since
    1b02284 (2026-05-16) — "All truncation caps have been removed" — and has no
    callers anywhere in the app. This class previously asserted the old
    truncating behaviour and so failed on every run; it now pins the contract
    the function actually documents. If truncation is ever reintroduced, these
    are the tests to rewrite first.
    """

    def test_shorter_than_max_returned_unchanged(self):
        assert truncate_text("Hello", 10) == "Hello"

    def test_exactly_max_length_returned_unchanged(self):
        assert truncate_text("Hello", 5) == "Hello"

    def test_longer_than_max_is_returned_unchanged(self):
        """The whole point of the no-op: long text is NOT cut."""
        assert truncate_text("Hello, world!", 8) == "Hello, world!"

    def test_suffix_is_never_appended(self):
        assert truncate_text("Hello, world!", 7, suffix="--") == "Hello, world!"

    def test_max_length_is_ignored_entirely(self):
        text = "A" * 100
        for max_len in (0, -5, 3, 50, 1000):
            assert truncate_text(text, max_len) == text

    # -----------------------------------------------------------------------
    # Edge cases
    # -----------------------------------------------------------------------

    def test_none_text_returns_none(self):
        assert truncate_text(None, 10) is None

    def test_empty_string_returns_empty_string(self):
        assert truncate_text("", 10) == ""

    def test_none_text_with_zero_max_length_returns_none(self):
        assert truncate_text(None, 0) is None

    def test_empty_suffix_changes_nothing(self):
        assert truncate_text("Hello, world!", 5, suffix="") == "Hello, world!"


# ===========================================================================
# parse_yaml_block
# ===========================================================================

class TestParseYamlBlock:
    """Tests for parse_yaml_block()."""

    # -----------------------------------------------------------------------
    # Normal cases
    # -----------------------------------------------------------------------

    def test_valid_single_field_frontmatter(self):
        text = "---\nstatus: done\n---\nBody text here."
        result = parse_yaml_block(text)
        assert result == {"status": "done"}

    def test_valid_multiple_fields(self):
        text = (
            "---\n"
            "status: running\n"
            "assigned_by: planning\n"
            "priority: high\n"
            "---\n"
            "## Task\nDo something.\n"
        )
        result = parse_yaml_block(text)
        assert result == {
            "status": "running",
            "assigned_by": "planning",
            "priority": "high",
        }

    def test_frontmatter_with_integer_value(self):
        text = "---\ncount: 42\n---\n"
        result = parse_yaml_block(text)
        assert result == {"count": 42}

    def test_frontmatter_with_boolean_value(self):
        text = "---\nenabled: true\n---\n"
        result = parse_yaml_block(text)
        assert result == {"enabled": True}

    def test_frontmatter_with_null_value(self):
        text = "---\ncompleted_at: \n---\n"
        result = parse_yaml_block(text)
        assert result is not None
        assert "completed_at" in result
        assert result["completed_at"] is None

    def test_frontmatter_without_trailing_body(self):
        """Frontmatter at end of string (no body after closing ---)."""
        text = "---\nkey: value\n---"
        result = parse_yaml_block(text)
        assert result == {"key": "value"}

    # -----------------------------------------------------------------------
    # Edge cases
    # -----------------------------------------------------------------------

    def test_none_returns_none(self):
        assert parse_yaml_block(None) is None

    def test_empty_string_returns_none(self):
        assert parse_yaml_block("") is None

    def test_text_without_frontmatter_returns_none(self):
        assert parse_yaml_block("No frontmatter here.\nJust plain text.") is None

    def test_text_starting_with_content_not_dashes_returns_none(self):
        assert parse_yaml_block("# Heading\n---\nstatus: done\n---\n") is None

    def test_malformed_yaml_returns_none(self):
        """Invalid YAML (e.g. unbalanced brackets) should return None, not raise."""
        text = "---\nkey: [unclosed\n---\n"
        result = parse_yaml_block(text)
        assert result is None

    def test_only_opening_delimiter_returns_none(self):
        """Only an opening --- with no closing --- should return None."""
        text = "---\nstatus: done\nNo closing delimiter here."
        assert parse_yaml_block(text) is None

    def test_empty_frontmatter_returns_none(self):
        """An empty frontmatter block (--- followed immediately by ---) returns None."""
        text = "---\n---\nBody."
        # yaml.safe_load("") → None → not a dict → return None
        assert parse_yaml_block(text) is None

    def test_frontmatter_with_list_value_returns_dict(self):
        """YAML list values inside a dict frontmatter are valid."""
        text = "---\ntags:\n  - python\n  - yaml\n---\n"
        result = parse_yaml_block(text)
        assert result == {"tags": ["python", "yaml"]}

    def test_real_yapoc_task_md_frontmatter(self):
        """Simulate a real YAPOC TASK.MD frontmatter block."""
        text = (
            "---\n"
            "status: running\n"
            "assigned_by: planning\n"
            "assigned_at: 2026-04-13T10:04:30Z\n"
            "completed_at: \n"
            "---\n"
            "## Task\nDo something useful.\n"
            "## Result\n\n"
            "## Error\n\n"
        )
        result = parse_yaml_block(text)
        assert result is not None
        assert result["status"] == "running"
        assert result["assigned_by"] == "planning"
        assert "assigned_at" in result
        assert "completed_at" in result
