"""Model Manager Agent — model availability, purpose-model matching, cross-agent config management.

Runs periodic audits (pure Python, no LLM) to scan agent configs and verify
catalog coverage. Also handles on-demand tasks via TASK.MD for interactive
requests like "optimize all agents" or "check if gpt-4o is available".
"""

import re
from datetime import datetime
from pathlib import Path

from app.agents.base import BaseAgent
from app.config import settings
from app.utils.adapters.models import MODEL_REGISTRY, PROVIDER_MODELS


class ModelManagerAgent(BaseAgent):
    def __init__(self) -> None:
        super().__init__(settings.agents_dir / "model_manager")

    async def run_model_audit(self) -> str:
        """Scan all agent CONFIG.md files, check catalog coverage, write findings to NOTES.MD.

        Pure Python — no LLM calls. Informational only — never applies changes autonomously.
        """
        agents_dir = settings.agents_dir
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        sections: list[str] = [f"# Model Audit Report\n\nGenerated: {now}\n"]

        agent_dirs = sorted(
            p for p in agents_dir.iterdir()
            if p.is_dir() and not p.name.startswith("_") and p.name != "base"
        )

        issues: list[str] = []
        agent_configs: list[dict[str, str]] = []

        for agent_dir in agent_dirs:
            name = agent_dir.name
            config_path = agent_dir / "CONFIG.md"

            if not config_path.exists():
                issues.append(f"- **{name}**: No CONFIG.md found")
                continue

            raw = config_path.read_text(encoding="utf-8", errors="replace")
            adapter = self._extract_yaml_value(raw, "adapter") or "unknown"
            model = self._extract_yaml_value(raw, "model") or "unknown"

            agent_configs.append({"name": name, "adapter": adapter, "model": model})

            # Check if model is in catalog
            in_catalog = model in MODEL_REGISTRY
            # Check if adapter has the model in its provider list
            provider_models = PROVIDER_MODELS.get(adapter, [])
            in_provider = model in provider_models

            status_parts: list[str] = []
            if not in_catalog:
                status_parts.append("NOT IN CATALOG")
                issues.append(f"- **{name}**: model `{model}` not found in catalog")
            if in_catalog and not in_provider:
                status_parts.append(f"WRONG PROVIDER (catalog has it, but not under '{adapter}')")
                issues.append(
                    f"- **{name}**: model `{model}` is in catalog but not listed under provider '{adapter}'"
                )

            status = ", ".join(status_parts) if status_parts else "OK"
            info = MODEL_REGISTRY.get(model)
            pricing = ""
            if info:
                pricing = f" | ${info.input_price}/${info.output_price} per MTok"

            sections.append(f"## {name}\n- adapter: `{adapter}`, model: `{model}`\n- Status: {status}{pricing}")

        # Summary
        total = len(agent_configs)
        issue_count = len(issues)
        summary = f"**Agents scanned:** {total} | **Issues:** {issue_count}"
        sections.insert(1, summary + "\n")

        if issues:
            sections.append("## Issues\n" + "\n".join(issues))

        report = "\n\n".join(sections) + "\n"

        # Write to own NOTES.MD
        notes_path = self._dir / "NOTES.MD"
        notes_path.write_text(report, encoding="utf-8")

        # Log to own memory
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
        await self._append_file(
            "MEMORY.MD",
            f"[{timestamp}] model_audit: {total} agents scanned, {issue_count} issue(s)\n",
        )

        return report

    @staticmethod
    def _extract_yaml_value(content: str, key: str) -> str | None:
        """Extract a simple YAML key value from CONFIG.md content."""
        m = re.search(rf"^{re.escape(key)}\s*:\s*(.+)$", content, re.MULTILINE)
        return m.group(1).strip() if m else None


model_manager_agent = ModelManagerAgent()
