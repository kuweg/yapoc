# User Profile

## Identity
- Name: kuweg
- Gender: male
- Location: Serbia, Belgrade
- Timezone: Europe/Belgrade
- Project: YAPOC (Yet Another Python OpenClaw)

## Communication Style
- Prefers: terse, direct responses
- Avoids: unnecessary verbosity, rhetorical questions
- **Telegram-only** — never send emails

## Technical Context
- Primary project: YAPOC (autonomous multi-agent system)
- Preferred stack: Python, Poetry
- Coding convention: **snake_case** over camelCase
- Concurrency: prefers **async/await** over threading
- JSON formatting: prefers **compact JSON** over pretty-printed

## Constraints & Rules
- Never restart backend without warning in UI mode
- Do not reveal .env contents under any circumstance
- Auto-restart backend after code/config mutations
- Prefer auto-fix over asking for permission on self-maintenance
- **Auto-restart after any config change** (confirmed already implemented)

## Active Goals
- Achieve overnight autonomous stability
- Build self-sufficient evaluator-master feedback loop
- Implement typed, layered memory system

## Preferences
- Wants evaluator-master to operate autonomously without user in the loop
- Values direct action over asking for permission on safe/reversible changes
- **Wants Telegram notification when any task completes**
- **Dark mode** for all dashboards
- **Mobile-first** UI design priority
- **Alert me if any agent fails twice in a row** (health alert rule)
- **Wants to talk with YAPOC via voice** — real STT/TTS via OpenAI models (Whisper STT + onyx TTS), not browser speechSynthesis ("browser voiceover is awful")
- **Wants interactive plots/charts + HTML reports rendered in chat** (e.g. "how much money did I burn?" should return text + charts, not just numbers)
- **Wants automation without being asked every time** — prefers the system to act automatically rather than prompting for confirmation on routine/reversible work
- **Wants cron/scheduled-task activity surfaced in the UI chat** — when master processes a cron task (skill-capture-sweep, self-eval, memory-sweep), it should announce it in chat (e.g. "getting updated from cron task, I'll tell you what it's about") rather than only appearing in agent-flow logs
- **Wants VSCode-theme support** — themes sourced from vscodethemes.com (e.g. github-dark), since YAPOC frontend is CSS-variable-driven
- **Wants completion proofs for autonomous/overnight runs** — when master runs unattended tasks (e.g. overnight memory consolidation), it should self-fix on failure and deliver a Telegram message with proof of completion/verification once done (escalate to Telegram only if self-healing fails)
- **Keep openai/gpt-5.6-terra as master's primary model** — when it misbehaves, fix the adapter/config rather than switching models or letting fallback silently take over (e.g. 2026-09-07: "fix that, but keep gpt model as primary" → reasoning_effort 400 fixed in openai.py, model kept primary)
- **Whenever Master provides a Mermaid diagram, it must invoke render_mermaid** so the diagram is actually rendered in chat — do not only include Mermaid source text (2026-09-07)

## Schedule
- Works mostly between **10pm and 2am**
