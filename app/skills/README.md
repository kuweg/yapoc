# Agent Skills

Place `.yaml` skill files here to teach agents reusable procedures.

Each skill has three disclosure levels:
- **Level 1**: One-line summary — injected into every agent's system prompt
- **Level 2**: Parameters and inputs — loaded when an agent decides to use the skill
- **Level 3**: Full step-by-step procedure — loaded when execution details are needed

## Example: `git_commit.yaml`

```yaml
name: git_commit
summary: Commit changes using conventional commit format
description: |
  Creates a git commit with a properly formatted message.
level_1: "Commit changes with conventional commits"
level_2: |
  Parameters:
  - message: The commit message (required)
level_3: |
  Procedure:
  1. Run `git status` to see changed files
  2. Stage files with `git add .`
  3. Run `git commit -m "<message>"`
```

Skills are auto-discovered — no code changes needed. Drop a file here
and all agents can load it via the `load_skills` tool.
