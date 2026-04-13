"""
helpers.py — General-purpose utility helpers for YAPOC.

Provides small, reusable functions used across agents and backend code:

- ``format_timestamp``  — Format a datetime object as ISO 8601, human-readable,
                          or Unix timestamp.
- ``truncate_text``     — Truncate a string to a maximum character length with
                          a configurable suffix.
- ``parse_yaml_block``  — Extract and parse YAML frontmatter from markdown text.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any

import yaml


# ---------------------------------------------------------------------------
# format_timestamp
# ---------------------------------------------------------------------------

def format_timestamp(dt: datetime | None, format: str = "iso") -> str | float:
    """Format a datetime object into a string or float.

    Parameters
    ----------
    dt:
        The datetime object to format.  Must not be ``None``.
    format:
        Output format.  One of:

        - ``'iso'``   — ISO 8601 string via ``dt.isoformat()``
          (e.g. ``"2026-04-13T10:04:09"``).
        - ``'human'`` — Human-readable string
          (e.g. ``"April 13, 2026 10:04:09"``).
        - ``'unix'``  — Unix timestamp as a ``float``
          (e.g. ``1744538649.0``).

    Returns
    -------
    str | float
        Formatted timestamp.  Returns a ``float`` for ``format='unix'``,
        a ``str`` for all other formats.

    Raises
    ------
    ValueError
        If ``dt`` is ``None`` or ``format`` is not one of the supported values.

    Examples
    --------
    >>> from datetime import datetime
    >>> dt = datetime(2026, 4, 13, 10, 4, 9)
    >>> format_timestamp(dt, 'iso')
    '2026-04-13T10:04:09'
    >>> format_timestamp(dt, 'human')
    'April 13, 2026 10:04:09'
    >>> format_timestamp(dt, 'unix')
    1744538649.0
    """
    if dt is None:
        raise ValueError("dt must not be None")

    if format == "iso":
        return dt.isoformat()
    elif format == "human":
        return dt.strftime("%B %d, %Y %H:%M:%S")
    elif format == "unix":
        return dt.timestamp()
    else:
        raise ValueError(
            f"Unknown format {format!r}. Supported formats: 'iso', 'human', 'unix'."
        )


# ---------------------------------------------------------------------------
# truncate_text
# ---------------------------------------------------------------------------

def truncate_text(
    text: str | None,
    max_length: int,
    suffix: str = "...",
) -> str | None:
    """Truncate *text* to at most *max_length* characters.

    If truncation is required the result ends with *suffix* and the total
    length (including the suffix) does not exceed *max_length*.

    Parameters
    ----------
    text:
        The string to truncate.  If ``None``, ``None`` is returned immediately.
    max_length:
        Maximum number of characters in the returned string (including the
        suffix when truncation occurs).  If ``<= 0``, an empty string is
        returned.
    suffix:
        String appended when truncation occurs (default: ``"..."``).

    Returns
    -------
    str | None
        - ``None`` if *text* is ``None``.
        - ``""`` if *max_length* ``<= 0``.
        - *text* unchanged if ``len(text) <= max_length``.
        - Truncated string otherwise.

    Examples
    --------
    >>> truncate_text("Hello, world!", 8)
    'Hello...'
    >>> truncate_text("Hi", 10)
    'Hi'
    >>> truncate_text(None, 10) is None
    True
    """
    if text is None:
        return None

    if max_length <= 0:
        return ""

    if len(text) <= max_length:
        return text

    # Clamp cut point to 0 so a very short max_length never produces a
    # negative slice index (e.g. max_length=1, suffix="...").
    cut = max(0, max_length - len(suffix))
    return text[:cut] + suffix


# ---------------------------------------------------------------------------
# parse_yaml_block
# ---------------------------------------------------------------------------

# Matches standard markdown frontmatter: starts at the very beginning of the
# string with "---\n", ends with "\n---" optionally followed by "\n" or end.
_FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---(?:\n|$)", re.DOTALL)


def parse_yaml_block(text: str | None) -> dict[str, Any] | None:
    """Extract and parse YAML frontmatter from markdown text.

    Frontmatter is the block delimited by ``---`` lines at the very start of
    the document, following the standard Jekyll / Hugo / YAPOC convention::

        ---
        key: value
        other: 123
        ---
        Body text here.

    Parameters
    ----------
    text:
        Markdown text that may contain a YAML frontmatter block.  If ``None``
        or empty, ``None`` is returned.

    Returns
    -------
    dict | None
        Parsed frontmatter as a ``dict`` if found and valid YAML.
        ``None`` if:

        - *text* is ``None`` or empty.
        - No frontmatter block is present.
        - Only an opening ``---`` exists with no closing ``---``.
        - The frontmatter contains invalid YAML.

    Examples
    --------
    >>> parse_yaml_block("---\\nstatus: done\\n---\\nBody")
    {'status': 'done'}
    >>> parse_yaml_block("No frontmatter here") is None
    True
    """
    if not text:
        return None

    match = _FRONTMATTER_RE.match(text)
    if not match:
        return None

    yaml_content = match.group(1)
    try:
        result = yaml.safe_load(yaml_content)
    except yaml.YAMLError:
        return None

    # yaml.safe_load("") returns None; yaml.safe_load("key: val") returns dict
    if not isinstance(result, dict):
        return None

    return result
