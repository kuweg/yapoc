"""Hierarchy routing helpers.

Provides lightweight task classification and domain checks so delegation
boundaries are enforced in code (not only in prompts).
"""

from __future__ import annotations

from dataclasses import dataclass


TASK_CLASSES = ("code", "config", "schedule", "health", "mixed", "general")


_KEYWORDS: dict[str, tuple[str, ...]] = {
    "code": (
        "code",
        "file",
        "function",
        "class",
        "refactor",
        "implement",
        "bug",
        "test",
        "endpoint",
        "ui",
        "frontend",
        "backend",
        "module",
        "script",
        "rename",
        "patch",
    ),
    "config": (
        ".env",
        "environment variable",
        "settings.py",
        "pyproject.toml",
        "dependency",
        "poetry add",
        "config",
        "configuration",
        "api key",
        "secret",
        "model binding",
    ),
    "schedule": (
        "cron",
        "schedule",
        "recurring",
        "periodic",
        "interval",
        "run every",
        "daily",
        "hourly",
        "weekly",
    ),
    "health": (
        "health",
        "crash",
        "recover",
        "stuck",
        "zombie",
        "timeout",
        "monitor",
        "diagnose",
        "doctor",
        "stability",
    ),
}


_SUGGESTED_AGENT_BY_CLASS = {
    "code": "builder",
    "config": "keeper",
    "schedule": "cron",
    "health": "doctor",
    "mixed": "planning",
    "general": "planning",
}


_SUPPORTED_CLASSES_BY_AGENT = {
    "builder": {"code"},
    "keeper": {"config"},
    "cron": {"schedule"},
    "doctor": {"health"},
    "model_manager": {"config", "health"},
}


@dataclass(frozen=True)
class RoutingHint:
    task_class: str
    suggested_agent: str
    reason: str
    confidence: str
    verification_required: bool


def normalize_task_class(value: str | None) -> str | None:
    """Normalize user-provided task class values."""
    if value is None:
        return None
    normalized = value.strip().lower()
    if not normalized:
        return None
    if normalized not in TASK_CLASSES:
        return None
    return normalized


def _score(text: str, task_class: str) -> int:
    return sum(1 for kw in _KEYWORDS[task_class] if kw in text)


def classify_task(task: str, context: str = "", forced_task_class: str | None = None) -> RoutingHint:
    """Classify task text into a hierarchy task class."""
    if forced_task_class:
        suggested = _SUGGESTED_AGENT_BY_CLASS[forced_task_class]
        return RoutingHint(
            task_class=forced_task_class,
            suggested_agent=suggested,
            reason="task_class explicitly provided by caller",
            confidence="high",
            verification_required=forced_task_class != "general",
        )

    text = f"{task}\n{context}".lower()
    scores = {k: _score(text, k) for k in ("code", "config", "schedule", "health")}
    ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)

    if ranked[0][1] <= 0:
        task_class = "general"
        reason = "no strong domain keywords detected"
        confidence = "low"
    else:
        top_class, top_score = ranked[0]
        second_score = ranked[1][1]
        if second_score > 0 and top_score <= second_score + 1:
            task_class = "mixed"
            reason = (
                f"multiple domains matched similarly (top={top_class}:{top_score}, "
                f"second={ranked[1][0]}:{second_score})"
            )
            confidence = "medium"
        else:
            task_class = top_class
            reason = f"dominant domain keywords matched: {top_class} ({top_score})"
            confidence = "high" if top_score >= 2 else "medium"

    return RoutingHint(
        task_class=task_class,
        suggested_agent=_SUGGESTED_AGENT_BY_CLASS[task_class],
        reason=reason,
        confidence=confidence,
        verification_required=task_class != "general",
    )


def agent_supports_task(agent_name: str, task_class: str) -> bool:
    """Return whether agent_name is allowed to execute task_class."""
    if agent_name in {"master", "planning"}:
        return True
    allowed = _SUPPORTED_CLASSES_BY_AGENT.get(agent_name)
    if allowed is None:
        # Unknown or dynamic agents are treated as flexible to preserve
        # backwards compatibility.
        return True
    return task_class in allowed


def should_require_verification(agent_name: str, task_class: str) -> bool:
    """Return whether the spawned task should carry verification metadata."""
    if task_class == "general":
        return False
    return agent_name in {"builder", "keeper", "cron", "doctor", "model_manager"}

