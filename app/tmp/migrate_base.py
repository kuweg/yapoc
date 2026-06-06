#!/usr/bin/env python3
"""Migrate app/agents/base/__init__.py to support separate memory directory."""

import re
import subprocess
import sys

FILE = "app/agents/base/__init__.py"
BACKUP = "app/agents/base/__init__.py.bak"

with open(FILE, "r") as f:
    content = f.read()

# Save backup
with open(BACKUP, "w") as f:
    f.write(content)

print(f"Read {len(content)} bytes from {FILE}")
print(f"Backup saved to {BACKUP}")

# ── Step 2: Add _memory_dir after `self._dir =` line ──
init_pattern = re.compile(
    r'(self\._dir = agent_dir\n)'
)
content = init_pattern.sub(
    r'\1'
    r'        self._memory_dir = Path("app/memory/agents") / self._name\n'
    r'        self._memory_dir.mkdir(parents=True, exist_ok=True)\n',
    content
)
print("Step 2 done: Added _memory_dir initialization after self._dir = agent_dir")

# ── Step 3: Refactor _read_file, _write_file, _append_file to accept dir parameter ──

# _read_file: add dir: Path | None = None parameter, use target_dir = dir or self._dir
read_file_pattern = re.compile(
    r'(    async def _read_file\(self, filename: str\) -> str:\n'
    r'        path = self\._dir / filename)'
)
content = read_file_pattern.sub(
    r'    async def _read_file(self, filename: str, dir: Path | None = None) -> str:\n'
    r'        target_dir = dir or self._dir\n'
    r'        path = target_dir / filename',
    content
)
print("Step 3a done: Refactored _read_file")

# _write_file: add dir: Path | None = None parameter, use target_dir = dir or self._dir
write_file_pattern = re.compile(
    r'(    async def _write_file\(self, filename: str, content: str\) -> None:\n'
    r'        async with aiofiles\.open\(self\._dir / filename)'
)
content = write_file_pattern.sub(
    r'    async def _write_file(self, filename: str, content: str, dir: Path | None = None) -> None:\n'
    r'        target_dir = dir or self._dir\n'
    r'        async with aiofiles.open(target_dir / filename',
    content
)
print("Step 3b done: Refactored _write_file")

# _append_file: add dir: Path | None = None parameter, use target_dir = dir or self._dir
append_file_pattern = re.compile(
    r'(    async def _append_file\(self, filename: str, content: str\) -> None:\n'
    r'        async with aiofiles\.open\(self\._dir / filename, "a")'
)
content = append_file_pattern.sub(
    r'    async def _append_file(self, filename: str, content: str, dir: Path | None = None) -> None:\n'
    r'        target_dir = dir or self._dir\n'
    r'        async with aiofiles.open(target_dir / filename, "a"',
    content
)
print("Step 3c done: Refactored _append_file")

# ── Step 4: Add three new memory methods after _append_file ──
# Find the end of _append_file (3 blank lines after it signals next method or comment)
append_end_pattern = re.compile(
    r'(            await f\.write\(content\)\n\n'
    r'    async def _prune_memory)'
)
content = append_end_pattern.sub(
    r'            await f.write(content)\n\n'
    r'    async def _read_memory_file(self, filename: str) -> str:\n'
    r'        """Read a file from the memory directory."""\n'
    r'        return await self._read_file(filename, dir=self._memory_dir)\n'
    r'\n'
    r'    async def _write_memory_file(self, filename: str, content: str) -> None:\n'
    r'        """Write a file to the memory directory."""\n'
    r'        return await self._write_file(filename, content, dir=self._memory_dir)\n'
    r'\n'
    r'    async def _append_memory_file(self, filename: str, content: str) -> None:\n'
    r'        """Append to a file in the memory directory."""\n'
    r'        return await self._append_file(filename, content, dir=self._memory_dir)\n'
    r'\n'
    r'    async def _prune_memory',
    content
)
print("Step 4 done: Added _read_memory_file, _write_memory_file, _append_memory_file")

# ── Step 5: Replace direct memory file references with memory method calls ──

memory_files = ["MEMORY.MD", "HEALTH.MD", "NOTES.MD", "LEARNINGS.MD", "GOALS.MD",
                "LIVE.MD", "RESULT.MD", "ERROR.MD", "OUTPUT.MD", "CRASH.MD"]

replacements = []

for fname in memory_files:
    # _read_file(fname) -> _read_memory_file(fname)
    old = f'self._read_file("{fname}")'
    new = f'self._read_memory_file("{fname}")'
    count = content.count(old)
    if count > 0:
        content = content.replace(old, new)
        replacements.append(f"self._read_file(\"{fname}\"): {count} -> self._read_memory_file")

    # _write_file(fname -> _write_memory_file(fname
    old_write = f'self._write_file("{fname}"'
    new_write = f'self._write_memory_file("{fname}"'
    count = content.count(old_write)
    if count > 0:
        content = content.replace(old_write, new_write)
        replacements.append(f"self._write_file(\"{fname}\"): {count} -> self._write_memory_file")

    # _append_file(fname -> _append_memory_file(fname
    old_append = f'self._append_file("{fname}"'
    new_append = f'self._append_memory_file("{fname}"'
    count = content.count(old_append)
    if count > 0:
        content = content.replace(old_append, new_append)
        replacements.append(f"self._append_file(\"{fname}\"): {count} -> self._append_memory_file")

print(f"Step 5 done: {len(replacements)} replacement patterns applied")
for r in replacements:
    print(f"  - {r}")

# Also check for Path expressions referencing these files via self._dir
# e.g. self._dir / "MEMORY.MD"
for fname in memory_files:
    old_path = f'self._dir / "{fname}"'
    # We only want to replace these in methods that are NOT the memory helper methods
    # and NOT the _prune_memory method (which uses self._dir / "MEMORY.MD")
    # Let's check how many there are
    count = content.count(old_path)
    if count > 0:
        print(f"  NOTE: {count} occurrences of self._dir / \"{fname}\" remain (probably in _prune_memory)")

# Verify _prune_memory still references self._dir / "MEMORY.MD" correctly
# It's fine if it does (it reads the file location, then writes back)
# But _prune_memory should also use the memory dir pattern
# Let's update _prune_memory to use self._memory_dir
prune_pattern = re.compile(
    r'(        path = self\._dir / "MEMORY\.MD"\n'
    r'        if not path\.exists\(\))'
)
if prune_pattern.search(content):
    content = prune_pattern.sub(
        r'        path = self._memory_dir / "MEMORY.MD"\n'
        r'        if not path.exists()',
        content
    )
    print("Step 5b: Updated _prune_memory to use self._memory_dir / MEMORY.MD")
else:
    print("Step 5b: _prune_memory self._dir / MEMORY.MD already handled")

# Step 5c: Also handle the `self._dir / "MEMORY.MD"` in get_status
status_pattern = re.compile(
    r'(        memory = await self\._read_file\("MEMORY\.MD"\))'
)
if status_pattern.search(content):
    print("  NOTE: get_status already uses _read_file(MEMORY.MD) which should have been migrated to _read_memory_file")
else:
    print("  NOTE: get_status memory read pattern not found (may already be migrated)")

# Also handle get_status health:
status_health_pattern = re.compile(
    r'(        health = await self\._read_file\("HEALTH\.MD"\))'
)
if status_health_pattern.search(content):
    print("  NOTE: get_status already uses _read_file(HEALTH.MD) which should have been migrated to _read_memory_file")

# ── Step 6: Write modified file back ──
with open(FILE, "w") as f:
    f.write(content)

print(f"\nStep 6 done: Written {len(content)} bytes back to {FILE}")

# ── Step 7: Syntax check ──
result = subprocess.run(["python3", "-m", "py_compile", FILE], capture_output=True, text=True)
if result.returncode == 0:
    print("Step 7 done: Syntax check PASSED")
else:
    print(f"Step 7: Syntax check FAILED (rc={result.returncode})")
    print("STDERR:", result.stderr)
    print("STDOUT:", result.stdout)
    sys.exit(1)
