I'll add the two new config fields to the settings class. Let me first locate the existing skill auto-capture config block.Let me read the surrounding context to confirm the exact lines.I'll add the two new fields immediately after line 161.Now let me verify the change by running the verification command.Verification passed. Let me confirm the exact lines added.The two fields were added correctly. Let me log this to memory and health, then notify parent.Task complete. Added the two new config fields to `app/config/settings.py`:

- `skill_verify_enabled: bool = True` (line 162)
- `skill_verify_threshold: int = 3` (line 163)

Verification passed — the import printed `True 3`. Config-only change; no other files were modified.