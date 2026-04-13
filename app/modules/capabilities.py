"""Capability module definitions for dynamic agent composition.

Each CapabilityModule bundles a set of tools with a prompt fragment and
optional sandbox hints, letting Master compose new agents from pre-built
capabilities instead of crafting prompts and tool lists from scratch.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class CapabilityModule:
    name: str                    # e.g. "file_ops", "web_research"
    description: str             # what this capability does
    tools: list[str]             # tool names to include
    prompt_fragment: str         # prompt section to inject
    sandbox_hints: dict[str, list[str]] = field(default_factory=dict)


# ── Pre-built modules ────────────────────────────────────────────────────────

FILE_OPS = CapabilityModule(
    name="file_ops",
    description="Read, write, edit, delete, and list files within the project sandbox.",
    tools=["file_read", "file_write", "file_edit", "file_delete", "file_list"],
    prompt_fragment=(
        "## File Operations Capability\n"
        "You can read, write, edit, delete, and list files within the project root.\n"
        "Always verify paths before writing. Use file_read to inspect before editing.\n"
        "Prefer file_edit over file_write when modifying existing files.\n"
    ),
)

WEB_RESEARCH = CapabilityModule(
    name="web_research",
    description="Search the web and save findings to files.",
    tools=["web_search", "file_write"],
    prompt_fragment=(
        "## Web Research Capability\n"
        "You can search the web for information and save your findings to files.\n"
        "Always cite sources. Summarize findings concisely. Save raw results to files\n"
        "for later reference when the output is large.\n"
    ),
)

CONFIG_MANAGEMENT = CapabilityModule(
    name="config_management",
    description="Read and edit configuration files and notes safely.",
    tools=["file_read", "file_edit", "notes_read", "notes_write"],
    prompt_fragment=(
        "## Config Management Capability\n"
        "You manage configuration files with care. Always read before editing.\n"
        "Validate changes are syntactically correct. Document changes in NOTES.MD.\n"
        "Never delete config files — only edit them.\n"
    ),
    sandbox_hints={
        "forbidden": [".git", "pyproject.toml"],
    },
)

CODE_ANALYSIS = CapabilityModule(
    name="code_analysis",
    description="Read files, list directories, and run shell commands for code analysis.",
    tools=["file_read", "file_list", "shell_exec"],
    prompt_fragment=(
        "## Code Analysis Capability\n"
        "You analyze codebases by reading files, listing directories, and running\n"
        "safe shell commands (grep, find, wc, etc.). Do NOT modify any files.\n"
        "Produce structured analysis reports with findings and recommendations.\n"
    ),
)

MEMORY_MANAGEMENT = CapabilityModule(
    name="memory_management",
    description="Manage agent memory, notes, health logs, and learnings.",
    tools=["memory_append", "notes_read", "notes_write", "health_log", "learnings_append"],
    prompt_fragment=(
        "## Memory Management Capability\n"
        "You manage persistent memory and knowledge. Use memory_append for task logs,\n"
        "notes for persistent knowledge, health_log for errors/warnings, and\n"
        "learnings_append for rules confirmed by repeated observation.\n"
    ),
)


# ── Registry ─────────────────────────────────────────────────────────────────

CAPABILITY_MODULES: dict[str, CapabilityModule] = {
    m.name: m
    for m in [FILE_OPS, WEB_RESEARCH, CONFIG_MANAGEMENT, CODE_ANALYSIS, MEMORY_MANAGEMENT]
}
