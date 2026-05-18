import asyncio
import json
import re
import time as _time
import traceback
from collections import deque
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, AsyncIterator

import aiofiles
from loguru import logger as _log

from app.config import settings
from app.utils import agent_settings as _agent_settings
from app.utils.adapters import (
    AgentConfig,
    BaseLLMAdapter,
    CompactEvent,
    FallbackAdapter,
    Message,
    StreamEvent,
    TextDelta,
    ThinkingDelta,
    ToolDone,
    ToolResult,
    ToolStart,
    TurnComplete,
    UsageStats,
    get_adapter,
    parse_config_block,
)
from app.utils.tools import BaseTool, build_tools
from app.utils.usage_tracker import UsageTracker
from app.agents.base.context import build_system_context, _parse_runner_config


def _estimate_tokens(messages: list[dict[str, Any]]) -> int:
    """Rough token estimate: ~4 chars per token."""
    return len(json.dumps(messages, default=str)) // 4


def _calc_turn_cost(
    model: str,
    input_tokens: int,
    output_tokens: int,
    cache_creation_tokens: int,
    cache_read_tokens: int,
) -> float:
    """Compute approximate USD cost for one LLM turn. Used only for logging."""
    try:
        from app.utils.adapters.models import ALL_PRICING
        pricing = ALL_PRICING.get(model)
        if not pricing:
            return 0.0
        in_rate, out_rate = pricing
        base_input = max(0, input_tokens - cache_creation_tokens - cache_read_tokens)
        return (
            base_input * in_rate
            + cache_creation_tokens * in_rate * 1.25
            + cache_read_tokens * in_rate * 0.1
            + output_tokens * out_rate
        ) / 1_000_000
    except Exception:
        return 0.0


# Cap on how much of a response we write back into MEMORY.MD. MEMORY.MD
# is injected into every future system prompt as recent history, so
# *anything* verbatim in here becomes a template the model imitates.
# Keeping entries short makes them behave as log lines rather than pattern
# examples the model will continue/imitate.
# Full responses are written to RESULT.MD instead (see _write_result).
_MEMORY_RESPONSE_CHAR_CAP = 500

# Only strip actual raw XML tool-call syntax leaking into text (Anthropic
# XML fallback, etc.). Normal prose descriptions of what an agent did are
# preserved — they are valid episodic log content.
_XML_TOOL_PATTERNS = (
    re.compile(r"<tool_call\b", re.IGNORECASE),
    re.compile(r"<function_call\b", re.IGNORECASE),
    re.compile(r"<invoke\b", re.IGNORECASE),
    re.compile(r"<function_calls>", re.IGNORECASE),
)


def _scrub_secrets(text: str) -> str:
    """Best-effort secret redaction before writing to agent files."""
    try:
        from app.utils.secrets import scrub
        return scrub(text)
    except Exception:
        return text


def _sanitize_for_memory(text: str) -> str:
    """Strip only raw XML tool-call syntax. Preserve normal prose.

    The result is stored as the ``result:`` field in MEMORY.MD entries —
    a brief log line, NOT the raw response text.

    Full response text is written to RESULT.MD via ``_write_result``
    and read back by the runner for TASK.MD result transport.
    """
    if not text:
        return ""
    for pat in _XML_TOOL_PATTERNS:
        if pat.search(text):
            return "[response omitted — contained raw tool-call syntax]"
    # Scrub secrets before persisting
    text = _scrub_secrets(text)
    # Keep first few non-empty lines collapsed into a single log-line.
    # The char cap below keeps the entry short enough that the model
    # treats it as episodic history, not a template to imitate, while
    # preserving enough structure that multi-line responses don't lose
    # everything after their opening sentence.
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    compact = " ".join(lines[:5])
    return compact[:_MEMORY_RESPONSE_CHAR_CAP]


_COMPACT_SYSTEM_PROMPT = """\
You are a conversation compactor. Summarize the conversation below into a concise \
summary that preserves all key facts, decisions, code snippets, file paths, and \
action items. The summary will replace the conversation history, so include everything \
needed to continue the work. Be thorough but concise. Output only the summary text."""


class BaseAgent:
    def __init__(self, agent_dir: Path) -> None:
        self._dir = agent_dir
        self._name = agent_dir.name
        self._last_config: AgentConfig | None = None
        self._usage = UsageTracker(agent_dir)
        self._session_id: str | None = None  # set by dispatcher or caller
        self._task_source: str | None = None  # autonomy gate: "user" | "goal" | "cron" | "doctor" | "webhook" | "notification"
        self._recent_tools: deque[str] = deque(maxlen=15)  # for loop detection
        self._loop_reflected: bool = False  # set after loop reflection injected
        self._no_tool_turns: int = 0  # stuck detector: consecutive no-tool turns

    # ── Session event emission ──────────────────────────────────────────────

    async def _emit_event(self, event_type: str, payload: dict[str, Any]) -> None:
        """Write a structured event to the session event log (append-only JSONL).

        Also pushes to WebSocket subscribers if available.
        Events are used for real-time streaming in the Chat tab.
        """
        if not self._session_id:
            return
        event = {
            "type": event_type,
            "agent": self._name,
            "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
            **payload,
        }
        # Write to session event log (local audit)
        session_dir = settings.project_root / "data" / "sessions" / self._session_id
        session_dir.mkdir(parents=True, exist_ok=True)
        event_file = session_dir / "events.jsonl"
        try:
            async with aiofiles.open(event_file, "a", encoding="utf-8") as f:
                await f.write(json.dumps(event, default=str) + "\n")
        except Exception as _ev_exc:
            _log.bind(agent=self._name).warning(
                "Session event JSONL write failed: {}", _ev_exc
            )
        # Publish to Redis pub/sub for real-time streaming to UI
        try:
            from app.backend.message_bus import bus
            await bus.publish(
                f"session:{self._session_id}:events",
                event,
                agent_name=self._name,
            )
        except Exception as _redis_exc:
            _log.bind(agent=self._name).warning(
                "Session event Redis publish failed: {}", _redis_exc
            )

    # ── File helpers ────────────────────────────────────────────────────────

    async def _read_file(self, filename: str) -> str:
        path = self._dir / filename
        if not path.exists():
            return ""
        async with aiofiles.open(path, encoding="utf-8") as f:
            return await f.read()

    async def _write_file(self, filename: str, content: str) -> None:
        async with aiofiles.open(self._dir / filename, "w", encoding="utf-8") as f:
            await f.write(content)

    async def _append_file(self, filename: str, content: str) -> None:
        async with aiofiles.open(self._dir / filename, "a", encoding="utf-8") as f:
            await f.write(content)

    async def _prune_memory_if_needed(self, max_lines: int = 200, keep: int = 100) -> None:
        """Trim MEMORY.MD by both line-count AND age.

        Two-pronged hygiene:

        - **Line cap**: if file exceeds ``max_lines`` non-empty lines, keep
          only the most recent ``keep``. (Pre-existing behavior.)
        - **Age cap**: drop entries whose ``[YYYY-MM-DD HH:MM]`` prefix is
          older than ``settings.memory_max_age_days``. Even talkative agents
          shouldn't carry month-old prose; the vector indexer already keeps
          the full history searchable via ``search_memory``.

        Both passes apply on every call; either triggering causes a rewrite.
        Lines without a parseable timestamp prefix are kept (defensive — we
        never silently drop unknown content).
        """
        path = self._dir / "MEMORY.MD"
        if not path.exists():
            return
        async with aiofiles.open(path, encoding="utf-8") as f:
            raw = await f.readlines()

        # Age cutoff (UTC-naive — MEMORY.MD timestamps are local-naive too).
        cutoff: datetime | None = None
        try:
            days = int(settings.memory_max_age_days or 0)
        except (TypeError, ValueError):
            days = 0
        if days > 0:
            cutoff = datetime.now() - timedelta(days=days)

        ts_re = re.compile(r"^\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2})\]")
        non_empty = [l for l in raw if l.strip()]

        # Age filter
        age_kept: list[str] = []
        for ln in non_empty:
            if cutoff is None:
                age_kept.append(ln)
                continue
            m = ts_re.match(ln)
            if not m:
                age_kept.append(ln)  # no timestamp → keep
                continue
            try:
                ts = datetime.strptime(m.group(1), "%Y-%m-%d %H:%M")
            except ValueError:
                age_kept.append(ln)
                continue
            if ts >= cutoff:
                age_kept.append(ln)

        # Line cap
        if len(age_kept) > max_lines:
            age_kept = age_kept[-keep:]

        if len(age_kept) == len(non_empty) and len(age_kept) == sum(1 for l in raw if l.strip()):
            return  # nothing changed

        async with aiofiles.open(path, "w", encoding="utf-8") as f:
            await f.writelines(age_kept)

    async def _write_result(self, text: str) -> None:
        """Write the full LLM response to RESULT.MD (overwrite each time).

        RESULT.MD is the authoritative source for task result transport.
        The runner reads it after ``run_stream_with_tools()`` completes
        and writes the content into TASK.MD's ``## Result`` section.

        This decouples result transport from MEMORY.MD, which only stores
        short 1-sentence summaries to avoid the "double message" bug where
        the model imitates/continues truncated previous responses.
        """
        await self._write_file("RESULT.MD", text)

    async def _write_error(self, text: str) -> None:
        """Write an error/exception trace to ERROR.MD (overwrite each time).

        Kept separate from RESULT.MD so consumers (the runner, the
        websocket notification relay, /agents/{name}/file endpoints)
        never surface error text formatted as a success result.
        """
        await self._write_file("ERROR.MD", text)

    # ── Config ───────────────────────────────────────────────────────────────

    async def _load_config(self, config_raw: str | None = None) -> AgentConfig:
        """Return the primary :class:`AgentConfig` for this agent.

        Resolution order:

        1. ``app/config/agent-settings.json`` — cross-provider primary
           for this agent, if present. This is now the authoritative
           source; CONFIG.yaml is the fallback for agents not listed in
           the JSON (mostly temporary agents created at runtime).
        2. ``CONFIG.yaml`` YAML block.
        3. ``NOTES.MD`` ``[config]`` block (legacy).
        4. ``settings`` defaults.

        Only the *primary* is returned here — the full fallback chain is
        applied later in :meth:`_load_adapter`.
        """
        # 1. agent-settings.json (primary binding)
        entry = _agent_settings.resolve_agent(self._name)
        if entry is not None:
            return AgentConfig(
                adapter=entry["adapter"],
                model=entry["model"],
                temperature=entry["temperature"],
                max_tokens=entry["max_tokens"],
            )

        # 2+3. CONFIG.yaml / NOTES.MD legacy
        raw = config_raw if config_raw is not None else await self._read_file("CONFIG.yaml")
        if raw.strip():
            cfg = parse_config_block(raw)
        else:
            notes = await self._read_file("NOTES.MD")
            cfg = parse_config_block(notes)

        adapter = cfg.get("adapter") or settings.default_adapter
        model = cfg.get("model") or settings.default_model
        try:
            temperature = float(cfg.get("temperature", settings.default_temperature))
        except (TypeError, ValueError):
            temperature = settings.default_temperature
        try:
            max_tokens = int(cfg.get("max_tokens", 32768))
        except (TypeError, ValueError):
            max_tokens = 32768
        return AgentConfig(
            adapter=adapter, model=model, temperature=temperature, max_tokens=max_tokens
        )

    async def _load_adapter(self, config: AgentConfig) -> BaseLLMAdapter:
        """Return a ready-to-use adapter for this agent.

        If the agent is listed in ``agent-settings.json`` with one or
        more fallbacks, wrap the primary in a :class:`FallbackAdapter`
        so provider failures (auth, rate limit, 5xx) transparently fall
        through to the next provider. Otherwise return a plain adapter.
        """
        chain = _agent_settings.build_adapter_chain(self._name)
        if chain and len(chain) > 1:
            return FallbackAdapter(chain)
        # Either the agent is not listed, or it has no fallbacks — just
        # use the primary config the caller loaded.
        return get_adapter(config)

    async def _detect_config_change(self, new_config: AgentConfig) -> bool:
        """Compare new config against last known config. Logs changes to HEALTH.MD."""
        old = self._last_config
        self._last_config = new_config
        if old is None:
            return False
        changes: list[str] = []
        if old.adapter != new_config.adapter:
            changes.append(f"adapter: '{old.adapter}' -> '{new_config.adapter}'")
        if old.model != new_config.model:
            changes.append(f"model: '{old.model}' -> '{new_config.model}'")
        if old.temperature != new_config.temperature:
            changes.append(f"temperature: {old.temperature} -> {new_config.temperature}")
        if old.max_tokens != new_config.max_tokens:
            changes.append(f"max_tokens: {old.max_tokens} -> {new_config.max_tokens}")
        if not changes:
            return False
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
        entry = f"[{timestamp}] CONFIG_CHANGE: {', '.join(changes)}\n"
        await self._append_file("HEALTH.MD", entry)
        return True

    # ── Task ─────────────────────────────────────────────────────────────────

    async def set_task(self, task: str) -> None:
        await self._write_file("TASK.MD", task)

    async def get_task(self) -> str:
        return await self._read_file("TASK.MD")

    # ── Frontmatter helpers ──────────────────────────────────────────────

    @staticmethod
    def _parse_frontmatter(content: str) -> dict[str, str]:
        """Extract YAML frontmatter from ``---`` delimited block."""
        from app.utils.frontmatter import parse_frontmatter_fields
        return parse_frontmatter_fields(content)

    @staticmethod
    def _update_frontmatter(content: str, **fields: str) -> str:
        """Rewrite frontmatter fields, preserving body. Creates frontmatter if absent."""
        existing = {}
        body = content
        m = re.match(r"^---\s*\n(.*?)\n---\s*\n?", content, re.DOTALL)
        if m:
            for line in m.group(1).splitlines():
                if ":" in line:
                    key, _, val = line.partition(":")
                    existing[key.strip()] = val.strip()
            body = content[m.end() :]
        existing.update(fields)
        fm_lines = [f"{k}: {v}" for k, v in existing.items()]
        return "---\n" + "\n".join(fm_lines) + "\n---\n" + body

    async def mark_task_consumed(self) -> None:
        """Mark a completed TASK.MD as consumed so it won't be re-injected."""
        content = await self._read_file("TASK.MD")
        if not content.strip():
            return
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        content = self._update_frontmatter(content, consumed_at=now)
        await self._write_file("TASK.MD", content)

    async def get_task_status(self) -> str:
        """Return the ``status`` frontmatter field from TASK.MD, or empty string."""
        content = await self._read_file("TASK.MD")
        return self._parse_frontmatter(content).get("status", "")

    async def set_task_status(
        self, status: str, *, result: str = "", error: str = ""
    ) -> None:
        """Update TASK.MD frontmatter status and optionally fill Result/Error sections."""
        content = await self._read_file("TASK.MD")
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        updates: dict[str, str] = {"status": status}
        if status in ("done", "error"):
            updates["completed_at"] = now
        content = self._update_frontmatter(content, **updates)

        # Pass replacement as a callable so re.sub treats `result`/`error`
        # as LITERAL text, not a substitution template. With an f-string
        # template, any `\u…`, `\g`, or backreference-looking sequence in
        # the user content gets interpreted by the regex engine and raises
        # `re.error: bad escape \u at position N` mid-write — which leaves
        # TASK.MD status stuck at "running" and the runner unable to
        # complete its post-task path (set_task_status -> _notify_parent_via_bus
        # -> _write_status("idle")). Classic root cause of the "agent
        # finished but master keeps waiting" failure mode.
        if result:
            _result = result  # capture for closure
            content = re.sub(
                r"(## Result\n).*?(?=\n## |\Z)",
                lambda m: m.group(1) + _result + "\n",
                content,
                flags=re.DOTALL,
            )
        if error:
            _error = error
            content = re.sub(
                r"(## Error\n).*?(?=\n## |\Z)",
                lambda m: m.group(1) + _error + "\n",
                content,
                flags=re.DOTALL,
            )
        await self._write_file("TASK.MD", content)

    async def get_task_body(self) -> str:
        """Return the ``## Task`` section text from TASK.MD."""
        content = await self._read_file("TASK.MD")
        m = re.search(r"## Task\n(.*?)(?=\n## |\Z)", content, re.DOTALL)
        return m.group(1).strip() if m else content.strip()

    # ── Run ──────────────────────────────────────────────────────────────────

    async def run(self, history: list[Message] | None = None) -> str:
        response: str = ""
        _exc: BaseException | None = None
        _exc_tb: str = ""
        try:
            config = await self._load_config()
            adapter = await self._load_adapter(config)

            system_prompt = await build_system_context(self._dir)
            task = await self._read_file("TASK.MD")

            response = await adapter.complete(
                system_prompt=system_prompt,
                user_message=task,
                history=history,
            )

            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
            entry = f"[{timestamp}] task: {_sanitize_for_memory(task)} | result: {_sanitize_for_memory(response)} | outcome: success\n"
            await self._append_file("MEMORY.MD", entry)

            await self._write_file("TASK.MD", "")
            return response

        except Exception as exc:
            _exc = exc
            _exc_tb = traceback.format_exc()
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
            error_entry = f"[{timestamp}] ERROR: {exc}\n{_exc_tb}\n"
            await self._append_file("HEALTH.MD", error_entry)
            raise

        finally:
            try:
                if _exc is not None:
                    await self._write_error(f"[ERROR] {_exc}\n\n{_exc_tb}")
                    if not response:
                        await self._write_result("")
                else:
                    # Strip raw XML tool call syntax from response before writing to RESULT.MD
                    cleaned = response
                    # Strip <tool_calls> wrapper blocks (entire block including content)
                    cleaned = re.sub(r'<tool_calls>.*?</tool_calls>', '', cleaned, flags=re.DOTALL)
                    # Strip individual <invoke ...> blocks (with attributes, entire block including content)
                    cleaned = re.sub(r'<invoke\b[^>]*>.*?</invoke>', '', cleaned, flags=re.DOTALL)
                    # Strip <parameter ...> tags left inside
                    cleaned = re.sub(r'<parameter\b[^>]*/>', '', cleaned, flags=re.DOTALL)
                    cleaned = re.sub(r'<parameter\b[^>]*>.*?</parameter>', '', cleaned, flags=re.DOTALL)
                    # Strip <function_call> blocks
                    cleaned = re.sub(r'<function_call>.*?</function_call>', '', cleaned, flags=re.DOTALL)
                    # Strip <tool_call> blocks
                    cleaned = re.sub(r'<tool_call>.*?</tool_call>', '', cleaned, flags=re.DOTALL)
                    cleaned = cleaned.strip()
                    await self._write_result(cleaned if cleaned else response)
                    await self._write_error("")
            except Exception as exc:
                _log.bind(agent=self._name).warning(
                    "Failed to persist RESULT/ERROR.MD after run: {}", exc
                )

    async def run_stream(
        self, history: list[Message] | None = None
    ) -> AsyncIterator[str]:
        try:
            config = await self._load_config()
            adapter = await self._load_adapter(config)

            system_prompt = await build_system_context(self._dir)
            task = await self._read_file("TASK.MD")

            full_response: list[str] = []
            async for chunk in adapter.stream(
                system_prompt=system_prompt,
                user_message=task,
                history=history,
            ):
                full_response.append(chunk)
                yield chunk

            response = "".join(full_response)
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
            entry = f"[{timestamp}] task: {_sanitize_for_memory(task)} | result: {_sanitize_for_memory(response)} | outcome: success\n"
            await self._append_file("MEMORY.MD", entry)
            await self._write_result(response)

            await self._write_file("TASK.MD", "")

        except Exception as exc:
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
            tb_str = traceback.format_exc()
            error_entry = f"[{timestamp}] ERROR: {exc}\n{tb_str}\n"
            await self._append_file("HEALTH.MD", error_entry)
            raise

    # ── Tool helpers ────────────────────────────────────────────────────────

    async def _load_tool_names(self, config_raw: str | None = None) -> list[str]:
        """Parse tool names from CONFIG.yaml tools: block, falling back to agent-settings.json.

        Tolerates blank lines and ``#`` comments between list items so
        that agents can annotate their tool lists without breaking the
        parser.
        """
        raw = config_raw if config_raw is not None else await self._read_file("CONFIG.yaml")
        if not raw.strip():
            return []
        # Find lines after "tools:" that start with "  - "
        names: list[str] = []
        in_tools = False
        for line in raw.splitlines():
            stripped = line.strip()
            if stripped == "tools:" or stripped.startswith("tools:"):
                after = stripped[len("tools:"):].strip()
                if after:
                    names.extend(t.strip() for t in after.split(",") if t.strip())
                    break
                in_tools = True
                continue
            if in_tools:
                if not stripped or stripped.startswith("#"):
                    continue
                match = re.match(r"\s+-\s+(.+)", line)
                if match:
                    item = match.group(1).strip()
                    if "#" in item:
                        item = item.split("#", 1)[0].strip()
                    if item:
                        names.append(item)
                else:
                    if not line.startswith(" "):
                        break

        # Fallback: check agent-settings.json when CONFIG.yaml has no tools:
        if not names:
            try:
                from app.utils.agent_settings import load_agent_settings
                settings_json = load_agent_settings()
                agent_cfg = (settings_json.get("agents") or {}).get(self._name, {})
                json_tools = agent_cfg.get("tools", [])
                if json_tools:
                    names = list(json_tools)
            except Exception:
                pass

        return names

    async def _execute_tool(
        self,
        tc: Any,
        tool_map: dict[str, BaseTool],
    ) -> tuple[ToolResult, ToolDone]:
        """Execute a single tool call, return ToolResult + ToolDone event."""
        tool = tool_map.get(tc.name)
        if tool is None:
            result = ToolResult(
                tool_use_id=tc.id,
                content=f"Unknown tool: {tc.name}",
                is_error=True,
            )
            return result, ToolDone(name=tc.name, result=result.content, is_error=True)

        # ── Security gate ──
        # Hardcoded fast-path + LLM classifier for risky tools. Denies are
        # surfaced to the LLM as a tool error so the model can reason about
        # the block rather than re-trying the same forbidden call.
        try:
            from app.utils.tools.security_gate import classify as _sec_classify
            _decision, _sec_reason = await _sec_classify(
                tool=tc.name, params=dict(tc.input or {}), caller=self._name,
            )
        except Exception as _gate_exc:
            _log.bind(agent=self._name, tool=tc.name).warning(
                "security_gate error ({}) — defaulting to allow", _gate_exc,
            )
            _decision, _sec_reason = "allow", "gate-error"
        if _decision == "deny":
            _block_msg = (
                f"BLOCKED by security gate: {_sec_reason}. "
                f"The action was not executed. Choose a different approach "
                f"or use a non-destructive alternative."
            )
            _log.bind(agent=self._name, tool=tc.name).warning(
                "BLOCKED by security gate ({})", _sec_reason,
            )
            result = ToolResult(tool_use_id=tc.id, content=_block_msg, is_error=True)
            return result, ToolDone(name=tc.name, result=_block_msg, is_error=True)

        # Transient errors get one automatic retry before surfacing to the LLM.
        # Note: FileNotFoundError, PermissionError, IsADirectoryError, NotADirectoryError
        # all inherit from OSError but are permanent — exclude them explicitly.
        _PERMANENT_OS_ERRORS = (
            FileNotFoundError, PermissionError, IsADirectoryError,
            NotADirectoryError, FileExistsError,
        )
        _TRANSIENT_ERRORS = (asyncio.TimeoutError, ConnectionError, OSError)
        _max_retries = 1
        last_exc: Exception | None = None

        for _attempt in range(_max_retries + 1):
            try:
                output = await tool.execute(**tc.input)
                result = ToolResult(tool_use_id=tc.id, content=output)
                return result, ToolDone(name=tc.name, result=output)
            except _PERMANENT_OS_ERRORS as exc:
                # OSError subclasses that indicate permanent failures — no retry
                last_exc = exc
                break
            except _TRANSIENT_ERRORS as exc:
                last_exc = exc
                if _attempt < _max_retries:
                    _log.bind(agent=self._name, tool=tc.name).warning(
                        "Transient error (attempt {}), retrying in 2s: {}", _attempt + 1, exc
                    )
                    await asyncio.sleep(2)
                    continue
                # All retries exhausted — fall through to error result
            except Exception as exc:
                # Non-transient error — no retry
                last_exc = exc
                break

        err_msg = f"Tool error: {last_exc}" if last_exc else "Tool error: unknown"
        result = ToolResult(tool_use_id=tc.id, content=err_msg, is_error=True)
        return result, ToolDone(name=tc.name, result=result.content, is_error=True)

    # ── Context compaction ────────────────────────────────────────────────

    async def _compact_messages(
        self,
        messages: list[dict[str, Any]],
        system_prompt: str,
        config: AgentConfig,
        focus: str = "",
    ) -> list[dict[str, Any]]:
        """Compress messages into a single summary message via LLM.

        Bugfix: previously this always used `settings.context_compact_model`
        (defaults to `claude-haiku-4-5-20251001`) regardless of which adapter
        the agent itself was using. Agents on the DeepSeek adapter would hit
        a `DeepSeek API error (400): supported model names are deepseek-...`
        crash mid-compaction, leaving the runner stuck at state=running
        (downstream Bug 3 in `docs/test-findings.md`).

        Use the compact-model override ONLY when the agent's adapter
        natively supports that model. Otherwise compact with the agent's
        own model — slightly more expensive but doesn't fail.
        """
        if config.adapter == "anthropic" and settings.context_compact_model:
            compact_model = settings.context_compact_model
        else:
            compact_model = config.model
        compact_config = AgentConfig(
            adapter=config.adapter,
            model=compact_model,
            temperature=0.2,
        )
        adapter = get_adapter(compact_config)

        # Build the conversation text for summarization
        convo_parts: list[str] = []
        for msg in messages:
            role = msg.get("role", "?")
            content = msg.get("content", "")
            if isinstance(content, list):
                # Tool results or multi-part content
                text_parts = []
                for block in content:
                    if isinstance(block, dict):
                        text_parts.append(
                            block.get("text", block.get("content", str(block)))
                        )
                    else:
                        text_parts.append(str(block))
                content = "\n".join(text_parts)
            convo_parts.append(f"[{role}]: {content}")

        convo_text = "\n\n".join(convo_parts)

        prompt = _COMPACT_SYSTEM_PROMPT
        if focus:
            prompt += f"\n\nFocus especially on: {focus}"

        summary = await adapter.complete(
            system_prompt=prompt,
            user_message=convo_text,
        )

        # Return a single user message with the compacted summary
        return [
            {
                "role": "user",
                "content": (
                    f"[Compacted conversation summary]\n{summary}\n\n"
                    "[System prompt preserved separately — see PROMPT.MD and Notes]"
                )
            }
        ]

    # ── Run with tools (multi-turn) ──────────────────────────────────────

    async def run_stream_with_tools(
        self,
        history: list[Message] | None = None,
        manage_task_file: bool = True,
        notifications_context: str = "",
        blocked_tools: set[str] | None = None,
    ) -> AsyncIterator[StreamEvent]:
        # Read per-agent task_timeout. Priority: agent-settings.json →
        # CONFIG.yaml runner block → settings default. agent-settings.json is
        # the authoritative cross-cutting runtime config; CONFIG.yaml is legacy.
        _cfg_raw = await self._read_file("CONFIG.yaml")
        _runner = _parse_runner_config(_cfg_raw)
        try:
            from app.utils.agent_settings import resolve_runner_settings
            _as_runner = resolve_runner_settings(self._name)
        except Exception as _rs_exc:
            _log.bind(agent=self._name).warning(
                "resolve_runner_settings failed (falling back to CONFIG.yaml/settings): {}",
                _rs_exc,
            )
            _as_runner = {}
        # Resolution priority: agent-settings.json → CONFIG.yaml → settings.
        # `or` chains skip 0, so we explicitly use sentinel checks to preserve
        # an explicit `task_timeout: 0` (which means "no timeout"). See Fix 2.1.
        _task_timeout = _as_runner.get("task_timeout")
        if _task_timeout is None:
            _task_timeout = _runner.get("task_timeout")
        if _task_timeout is None:
            _task_timeout = settings.task_timeout
        # task_timeout <= 0 means unbounded. asyncio.timeout(None) is a
        # documented no-op context — keeps the wrap in place but never fires.
        _timeout_value = _task_timeout if (_task_timeout and _task_timeout > 0) else None
        response: str = ""
        _stream_exc: BaseException | None = None
        _stream_exc_tb: str = ""

        try:
            async with asyncio.timeout(_timeout_value):
                config = await self._load_config(config_raw=_cfg_raw)
                await self._detect_config_change(config)
                adapter = await self._load_adapter(config)

                system_prompt = await build_system_context(self._dir, config_text=_cfg_raw)
                if notifications_context:
                    system_prompt += f"\n\n---\n\n{notifications_context}"
                task = await self._read_file("TASK.MD")

                # Load and build tools
                tool_names = await self._load_tool_names(config_raw=_cfg_raw)
                if blocked_tools:
                    tool_names = [n for n in tool_names if n not in blocked_tools]
                    _log.bind(agent=self._name).info(
                        "Blocked tools: {} ({} tools available after filtering)",
                        blocked_tools, len(tool_names),
                    )
                tools = build_tools(tool_names, self._dir, session_id=self._session_id)
                tool_defs = [t.to_definition() for t in tools]
                tool_map = {t.name: t for t in tools}

                # Build initial messages
                messages: list[dict[str, Any]] = []
                if history:
                    # History already contains the current user message as
                    # the last entry (appended by _send_to_agent before
                    # calling handle_task_stream). Don't re-add from TASK.MD.
                    for msg in history:
                        role = msg.role
                        if role == "system":
                            # Anthropic rejects role="system" in the messages
                            # array — fold as user turn so content is not lost.
                            role = "user"
                        messages.append({"role": role, "content": msg.content})
                else:
                    # Standalone runner mode — no history, use TASK.MD content
                    messages.append({"role": "user", "content": task})

                full_text_parts: list[str] = []
                max_turns = _runner.get("max_turns", settings.max_turns)
                threshold_tokens = int(
                    adapter.context_window_size() * settings.context_compact_threshold
                )
                _tool_start_times: dict[str, float] = {}
                _task_cost_usd: float = 0.0  # accumulator for per-task budget
                _budget_exceeded = False

                for _turn in range(max_turns):
                    # Auto-compact if approaching context limit
                    estimated = _estimate_tokens(messages)
                    if estimated >= threshold_tokens:
                        tokens_before = estimated
                        messages = await self._compact_messages(
                            messages, system_prompt, config
                        )
                        tokens_after = _estimate_tokens(messages)
                        yield CompactEvent(
                            reason="auto",
                            tokens_before=tokens_before,
                            tokens_after=tokens_after,
                        )
                        _pct = round((1 - tokens_after / tokens_before) * 100) if tokens_before else 0
                        _log.bind(
                            agent=self._name, event="compact", turn=_turn,
                            tokens_before=tokens_before, tokens_after=tokens_after,
                        ).info("Compact auto | tokens {}→{} (saved {}%)", tokens_before, tokens_after, _pct)

                    _log.bind(
                        agent=self._name, event="turn_start", turn=_turn,
                        model=config.model, in_tokens=estimated,
                    ).info("Turn {} start | model={} est_tokens={}", _turn, config.model, estimated)

                    # Stream one LLM turn
                    turn_complete: TurnComplete | None = None

                    # Guard: ensure messages always ends with a user-role message.
                    # Claude Opus 4+ rejects requests that end with an assistant
                    # message ("assistant prefill"). Log a warning and strip any
                    # trailing assistant messages so the adapter never sees them.
                    if messages and messages[-1].get("role") == "assistant":
                        _log.bind(agent=self._name).warning(
                            "messages ended with assistant role before turn {} — stripping",
                            _turn,
                        )
                        while messages and messages[-1].get("role") == "assistant":
                            messages.pop()

                    async for event in adapter.stream_with_tools(
                        system_prompt=system_prompt,
                        messages=messages,
                        tools=tool_defs,
                    ):
                        if isinstance(event, ThinkingDelta):
                            yield event
                            await self._emit_event("thinking_delta", {"text": event.text})
                        elif isinstance(event, TextDelta):
                            full_text_parts.append(event.text)
                            yield event
                            await self._emit_event("message_delta", {"text": event.text})
                        elif isinstance(event, ToolStart):
                            _tool_start_times[event.name] = _time.monotonic()
                            _input_repr = repr(event.input)
                            _log.bind(
                                agent=self._name, event="tool_start", turn=_turn,
                                model=config.model, tool=event.name, tool_input=_input_repr,
                            ).info("Tool {} | input={}", event.name, _input_repr)
                            yield event
                            await self._emit_event("tool_call", {"name": event.name, "input": event.input})
                        elif isinstance(event, UsageStats):
                            # Persist this turn's usage to USAGE.json so we
                            # can attribute spend to this agent even when
                            # the CLI renderer is not in the loop (e.g. in
                            # subprocess runners or HTTP streaming).
                            self._usage.record_turn(
                                model=config.model,
                                input_tokens=event.input_tokens,
                                output_tokens=event.output_tokens,
                                cache_creation_tokens=event.cache_creation_tokens,
                                cache_read_tokens=event.cache_read_tokens,
                            )
                            yield event
                            # ── Budget enforcement ──
                            _turn_cost = _calc_turn_cost(
                                config.model, event.input_tokens, event.output_tokens,
                                event.cache_creation_tokens, event.cache_read_tokens,
                            )
                            _task_cost_usd += _turn_cost
                            # Per-agent lifetime budget
                            if settings.budget_per_agent_usd > 0:
                                _usage_snap = self._usage.snapshot()
                                if _usage_snap["total_cost_usd"] >= settings.budget_per_agent_usd:
                                    _budget_msg = (
                                        f"[BUDGET EXCEEDED] Agent '{self._name}' lifetime cost "
                                        f"${_usage_snap['total_cost_usd']:.4f} >= "
                                        f"budget ${settings.budget_per_agent_usd:.4f}. Stopping."
                                    )
                                    await self._append_file("HEALTH.MD", f"[{_time.strftime('%Y-%m-%d %H:%M', _time.localtime())}] {_budget_msg}\n")
                                    yield TextDelta(text=f"\n\n{_budget_msg}")
                                    _budget_exceeded = True
                            # Per-task budget
                            if not _budget_exceeded and settings.budget_per_task_usd > 0:
                                if _task_cost_usd >= settings.budget_per_task_usd:
                                    _budget_msg = (
                                        f"[BUDGET EXCEEDED] Task cost ${_task_cost_usd:.4f} >= "
                                        f"budget ${settings.budget_per_task_usd:.4f}. Stopping."
                                    )
                                    await self._append_file("HEALTH.MD", f"[{_time.strftime('%Y-%m-%d %H:%M', _time.localtime())}] {_budget_msg}\n")
                                    yield TextDelta(text=f"\n\n{_budget_msg}")
                                    _budget_exceeded = True
                            # Daily autonomous budget (only for non-user-initiated runs).
                            # The dispatcher already gates new task spawns against this cap,
                            # but in-flight long-running tasks could overshoot. This halt
                            # ensures overnight runs cannot exceed daily_autonomous_budget_usd.
                            if (
                                not _budget_exceeded
                                and self._task_source
                                and self._task_source.lower() in {"goal", "cron", "doctor", "webhook"}
                            ):
                                try:
                                    from app.utils.cost_governor import (
                                        is_autonomous_budget_exhausted as _is_auto_exh,
                                        get_autonomous_spend_today as _get_auto_spend,
                                    )
                                    if _is_auto_exh():
                                        _spend = _get_auto_spend()
                                        _budget_msg = (
                                            f"[AUTONOMOUS BUDGET EXHAUSTED] Daily autonomous spend "
                                            f"${_spend:.4f} >= cap ${settings.daily_autonomous_budget_usd:.4f}. "
                                            f"Halting {self._task_source!r} task; resumes after midnight UTC."
                                        )
                                        await self._append_file(
                                            "HEALTH.MD",
                                            f"[{_time.strftime('%Y-%m-%d %H:%M', _time.localtime())}] {_budget_msg}\n",
                                        )
                                        yield TextDelta(text=f"\n\n{_budget_msg}")
                                        _budget_exceeded = True
                                        # Emit morning report so a human waking up sees the halt
                                        try:
                                            from app.backend.morning_report import write_morning_report
                                            write_morning_report("budget_halt", {
                                                "agent": self._name,
                                                "source": self._task_source,
                                                "spend_usd": f"{_spend:.4f}",
                                                "cap_usd": f"{settings.daily_autonomous_budget_usd:.2f}",
                                            })
                                        except Exception:
                                            pass
                                except Exception as _auto_exc:
                                    _log.bind(agent=self._name).warning(
                                        "daily-budget check failed ({}) — continuing without halt", _auto_exc,
                                    )
                            _cost = _calc_turn_cost(
                                config.model, event.input_tokens, event.output_tokens,
                                event.cache_creation_tokens, event.cache_read_tokens,
                            )
                            _log.bind(
                                agent=self._name, event="usage_stats", turn=_turn,
                                model=config.model,
                                in_tokens=event.input_tokens,
                                out_tokens=event.output_tokens,
                                cache_r=event.cache_read_tokens,
                                cache_w=event.cache_creation_tokens,
                                tps=round(event.tokens_per_second, 1),
                                cost_usd=round(_cost, 6),
                            ).info(
                                "Usage turn={} | in={} out={} cache_r={} cache_w={} tps={:.1f} cost=${:.6f}",
                                _turn, event.input_tokens, event.output_tokens,
                                event.cache_read_tokens, event.cache_creation_tokens,
                                event.tokens_per_second, _cost,
                            )
                        elif isinstance(event, TurnComplete):
                            turn_complete = event

                    # ── Diagnostic: per-turn loop control state ──
                    # Helps trace the "parallel tools → Turn 1 silent" failure
                    # mode. One line, structured, easy to grep.
                    _log.bind(
                        agent=self._name, event="turn_decision", turn=_turn,
                        model=config.model,
                        tc_is_none=turn_complete is None,
                        stop_reason=getattr(turn_complete, "stop_reason", "?"),
                        n_tool_calls=len(getattr(turn_complete, "tool_calls", []) or []),
                        n_content_blocks=len(getattr(turn_complete, "assistant_content", []) or []),
                        budget_exceeded=_budget_exceeded,
                    ).info(
                        "turn_decision | tc_none={} stop={} tools={} content={} budget_exc={}",
                        turn_complete is None,
                        getattr(turn_complete, "stop_reason", "?"),
                        len(getattr(turn_complete, "tool_calls", []) or []),
                        len(getattr(turn_complete, "assistant_content", []) or []),
                        _budget_exceeded,
                    )

                    if turn_complete is None:
                        _log.bind(agent=self._name, turn=_turn).info("loop break: tc_none")
                        break

                    if _budget_exceeded:
                        _log.bind(agent=self._name, turn=_turn).info("loop break: budget")
                        break

                    # Append assistant message to conversation
                    if turn_complete.assistant_content:
                        messages.append(
                            {
                                "role": "assistant",
                                "content": turn_complete.assistant_content,
                            }
                        )

                    # If no tool calls, we're done
                    if (
                        turn_complete.stop_reason != "tool_use"
                        or not turn_complete.tool_calls
                    ):
                        _log.bind(
                            agent=self._name, turn=_turn,
                            stop=turn_complete.stop_reason,
                            tools=len(turn_complete.tool_calls or []),
                        ).info(
                            "loop break: no-tool-use (stop={}, tools={})",
                            turn_complete.stop_reason,
                            len(turn_complete.tool_calls or []),
                        )
                        break

                    coros = [
                        self._execute_tool(tc, tool_map)
                        for tc in turn_complete.tool_calls
                    ]
                    results = await asyncio.gather(*coros)

                    # Yield ToolDone events, build tool results message
                    tool_results: list[dict[str, Any]] = []
                    for tool_result, tool_done in results:
                        # Count every executed tool call against this agent's
                        # usage, attributed to whichever model decided to call
                        # it. Errors still count — they still cost the model
                        # a tool-use round-trip.
                        self._usage.record_tool_call(config.model)
                        yield tool_done
                        await self._emit_event("tool_result", {
                            "name": tool_done.name,
                            "result": tool_done.result if tool_done.result else "",
                            "is_error": tool_done.is_error,
                        })
                        _elapsed = _time.monotonic() - _tool_start_times.pop(tool_done.name, _time.monotonic())
                        _lvl = "WARNING" if tool_done.is_error else "INFO"
                        _log.bind(
                            agent=self._name, event="tool_done", turn=_turn,
                            model=config.model, tool=tool_done.name,
                            elapsed_s=round(_elapsed, 3), ok=not tool_done.is_error,
                        ).log(
                            _lvl,
                            "Tool {} done | elapsed={:.3f}s {}",
                            tool_done.name, _elapsed, "ERROR" if tool_done.is_error else "ok",
                        )
                        tool_results.append(
                            {
                                "type": "tool_result",
                                "tool_use_id": tool_result.tool_use_id,
                                "content": tool_result.content,
                                "is_error": tool_result.is_error,
                            }
                        )

                    messages.append({"role": "user", "content": tool_results})

                    # ── Loop detection ──
                    # Record both the tool name AND a signature of its input so the
                    # detector catches cases where the same (tool, params) pair gets
                    # called repeatedly with no progress — not just the trivial
                    # "10x same tool" case.
                    import hashlib as _hashlib
                    import json as _json
                    for (tool_result_item, tool_done_item), _tc in zip(
                        results, turn_complete.tool_calls,
                    ):
                        try:
                            _sig_src = _json.dumps(
                                getattr(_tc, "input", None) or {},
                                sort_keys=True, default=str,
                            )
                        except Exception:
                            _sig_src = repr(tool_done_item.name)
                        _sig = _hashlib.sha256(_sig_src.encode("utf-8")).hexdigest()[:8]
                        self._recent_tools.append((tool_done_item.name, _sig))
                    # Check if the last 10 calls are the same tool (existing detector)
                    if len(self._recent_tools) >= 10:
                        last_10 = list(self._recent_tools)[-10:]
                        last_10_names = [item[0] if isinstance(item, tuple) else item for item in last_10]
                        if len(set(last_10_names)) == 1:
                            if self._loop_reflected:
                                # Already reflected once — force-stop
                                _log.bind(agent=self._name).warning(
                                    "Loop detected: {} called 10+ times after reflection. Force-stopping.",
                                    last_10_names[0],
                                )
                                break
                            else:
                                # Inject reflection message
                                self._loop_reflected = True
                                reflection = (
                                    f"[SYSTEM] You have called {last_10_names[0]} {len(last_10_names)} times consecutively. "
                                    f"This suggests a loop. Stop and assess:\n"
                                    f"1. What are you trying to achieve?\n"
                                    f"2. Why isn't it working?\n"
                                    f"3. Is there a fundamentally different approach?\n"
                                    f"If you cannot make progress, call notify_parent with what you've learned."
                                )
                                messages.append({"role": "user", "content": reflection})
                                _log.bind(agent=self._name).warning(
                                    "Loop detected: {} called 10+ times. Injecting reflection.", last_10_names[0],
                                )
                        else:
                            self._loop_reflected = False  # reset when pattern breaks

                        # ── Stuck detector (signature-level) ──
                        # If the SAME (tool, params) signature appears 4+ times in the
                        # last 10 calls, the agent isn't making progress — it's
                        # repeating identical work. Force-stop and surface a stuck
                        # message so the parent (or user) sees what happened. Fires
                        # alongside the same-tool detector above; either is sufficient.
                        last_10_sigs = [item for item in last_10 if isinstance(item, tuple)]
                        if last_10_sigs:
                            from collections import Counter as _Counter
                            _sig_counts = _Counter(last_10_sigs)
                            _top_sig, _top_count = _sig_counts.most_common(1)[0]
                            if _top_count >= settings.stuck_signature_threshold:
                                _stuck_msg = (
                                    f"[STUCK] Tool '{_top_sig[0]}' called with identical "
                                    f"parameters {_top_count} times in the last "
                                    f"{len(last_10_sigs)} calls (sig={_top_sig[1]}). "
                                    f"No progress detected. Force-stopping."
                                )
                                _log.bind(agent=self._name).warning(
                                    "Stuck detected: {} (sig={}) repeated {}x — force-stop.",
                                    _top_sig[0], _top_sig[1], _top_count,
                                )
                                await self._append_file(
                                    "HEALTH.MD",
                                    f"[{_time.strftime('%Y-%m-%d %H:%M', _time.localtime())}] {_stuck_msg}\n",
                                )
                                yield TextDelta(text=f"\n\n{_stuck_msg}")
                                # Emit morning report
                                try:
                                    from app.backend.morning_report import write_morning_report
                                    write_morning_report("stuck", {
                                        "agent": self._name,
                                        "tool": _top_sig[0],
                                        "signature": _top_sig[1],
                                        "repeat_count": str(_top_count),
                                    })
                                except Exception:
                                    pass
                                break

                    # ── Per-turn tool call limit ──
                    _turn_tool_count = sum(1 for _ in results)
                    if _turn_tool_count >= settings.max_tool_calls_per_turn:
                        messages.append({"role": "user", "content": (
                            "[SYSTEM] Tool call limit reached for this turn. "
                            "Summarize your progress and continue in the next turn."
                        )})

                # Log and clean up
                response = "".join(full_text_parts)

                # If the model only used tools and produced no text, include
                # tool outputs so the parent/runner can see actual results.
                if not response.strip():
                    parts: list[str] = []
                    if messages:
                        last_msg = messages[-1]
                        if isinstance(last_msg.get("content"), list):
                            for item in last_msg["content"]:
                                if isinstance(item, dict):
                                    name = item.get("tool_use_id", "")
                                    content = str(item.get("content", ""))
                                    is_err = item.get("is_error", False)
                                    label = "ERROR" if is_err else "OK"
                                    parts.append(f"[{name}] {label}: {content}")
                    if parts:
                        response = "Task completed via tools:\n" + "\n".join(parts)
                    else:
                        response = (
                            "Task completed via tool calls. "
                            "No text response was generated by the model."
                        )

                _log.bind(
                    agent=self._name, event="task_done",
                    turn=_turn, response_chars=len(response),
                ).info("Task done | turns={} response_chars={}", _turn + 1, len(response))

                timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
                entry = f"[{timestamp}] task: {_sanitize_for_memory(task)} | result: {_sanitize_for_memory(response)} | outcome: success\n"
                await self._append_file("MEMORY.MD", entry)
                await self._prune_memory_if_needed()
                if manage_task_file:
                    await self._write_file("TASK.MD", "")

        except TimeoutError:
            _stream_exc = TimeoutError(f"Task timed out after {_task_timeout}s")
            _stream_exc_tb = traceback.format_exc()
            _log.bind(
                agent=self._name, event="exception",
                exc_type="TimeoutError", exc_msg=f"timeout after {_task_timeout}s",
            ).error("Exception TimeoutError | Task timed out after {}s", _task_timeout)
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
            await self._append_file(
                "HEALTH.MD",
                f"[{timestamp}] ERROR: Task timed out after {_task_timeout}s\n{_stream_exc_tb}\n",
            )
            raise
        except Exception as exc:
            _stream_exc = exc
            _stream_exc_tb = traceback.format_exc()
            _log.bind(
                agent=self._name, event="exception",
                exc_type=type(exc).__name__, exc_msg=str(exc),
            ).opt(exception=True).error("Exception {} | {}", type(exc).__name__, exc)
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
            error_entry = f"[{timestamp}] ERROR: {exc}\n{_stream_exc_tb}\n"
            await self._append_file("HEALTH.MD", error_entry)
            raise

        finally:
            try:
                if _stream_exc is not None:
                    await self._write_error(f"[ERROR] {_stream_exc}\n\n{_stream_exc_tb}")
                    if not response:
                        await self._write_result("")
                else:
                    # Strip raw XML tool call syntax from response before writing to RESULT.MD
                    cleaned = response
                    # Strip <tool_calls> wrapper blocks (entire block including content)
                    cleaned = re.sub(r'<tool_calls>.*?</tool_calls>', '', cleaned, flags=re.DOTALL)
                    # Strip individual <invoke ...> blocks (with attributes, entire block including content)
                    cleaned = re.sub(r'<invoke\b[^>]*>.*?</invoke>', '', cleaned, flags=re.DOTALL)
                    # Strip <parameter ...> tags left inside
                    cleaned = re.sub(r'<parameter\b[^>]*/>', '', cleaned, flags=re.DOTALL)
                    cleaned = re.sub(r'<parameter\b[^>]*>.*?</parameter>', '', cleaned, flags=re.DOTALL)
                    # Strip <function_call> blocks
                    cleaned = re.sub(r'<function_call>.*?</function_call>', '', cleaned, flags=re.DOTALL)
                    # Strip <tool_call> blocks
                    cleaned = re.sub(r'<tool_call>.*?</tool_call>', '', cleaned, flags=re.DOTALL)
                    cleaned = cleaned.strip()
                    await self._write_result(cleaned if cleaned else response)
                    await self._write_error("")
            except Exception as exc:
                _log.bind(agent=self._name).warning(
                    "Failed to persist RESULT/ERROR.MD after stream run: {}", exc
                )

    # ── Status ───────────────────────────────────────────────────────────────

    async def get_status(self) -> dict:
        task = await self._read_file("TASK.MD")
        memory = await self._read_file("MEMORY.MD")
        health = await self._read_file("HEALTH.MD")

        memory_entries = len([l for l in memory.splitlines() if l.strip()])
        health_errors = len([l for l in health.splitlines() if l.strip()])

        config = await self._load_config()
        usage = self._usage.snapshot()

        return {
            "name": self._name,
            "model": config.model,
            "has_task": bool(task.strip()),
            "memory_entries": memory_entries,
            "health_errors": health_errors,
            "usage": {
                "input_tokens": usage.get("total_input_tokens", 0),
                "output_tokens": usage.get("total_output_tokens", 0),
                "cache_read_tokens": usage.get("total_cache_read_tokens", 0),
                "tool_calls": usage.get("total_tool_calls", 0),
                "turns": usage.get("total_turns", 0),
                "cost_usd": usage.get("total_cost_usd", 0.0),
            },
        }
