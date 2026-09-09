# User Profile

Copy this file to `PROFILE.md` in the same directory and fill it in. The real
`PROFILE.md` is git-ignored — it holds personal data and is local to your
install.

It is injected verbatim into every agent's system prompt
(`app/agents/base/context.py`) and indexed section-by-section for semantic
recall (`app/utils/indexer.py`, `agent="user"`, `source="PROFILE.md"`), so
`##` headers are the unit of retrieval. Keep entries short and factual;
everything here costs tokens on every single agent turn.

Every section below is optional — delete what does not apply.

## Identity
- Name:
- Timezone:
- Project:

## Communication Style
- Prefers:
- Avoids:

## Technical Context
- Preferred stack:
- Coding conventions:

## Constraints & Rules
- Hard rules the agents must never break.

## Active Goals
- What you are currently trying to achieve.

## Preferences
- Softer defaults the agents should assume when you have not said otherwise.
