# Agent building

Open the team panel in Conversation and choose **Building** (default) or **List**.
The preference is saved locally. Each floor can collapse. Click a pixel-art person
to open that named agent's flow; on phones the building closes to reveal the flow.

Rooms include pixel-art books, plants, framed art, curtains, warm lamps and rugs.
Smaller residents keep their full clickable area and visible status labels.

The office uses the backend's `runtime_state`, independently of legacy task-based
status. Old pending tasks do not animate an idle process. Failed status requests
show disconnected residents. Reduced-motion preferences disable animation.
Working, waiting, attention, idle and unknown states have visible text labels;
the artwork does not infer research/testing activities from agent names.

By default each named agent has its own floor. To group real, separately named
agents (for example `builder_a` and `builder_b`), set the same top-level value in
each agent's `CONFIG.yaml`:

```yaml
office_role: builder
```

The setting changes presentation only. Each person keeps its own name, process
status and flow. It does not clone processes, create worktrees or implement the
Parallel Universes launch/compare workflow. No simulated workers appear in the
live building. Multiple residents wrap into additional rows on the same floor.

Validation: `poetry run pytest app/backend/tests/test_agent_office.py -q`,
`npm --prefix app/frontend run build`, and
`poetry run python scripts/check_office_browser.py --dist app/frontend/dist`.

## Office atmosphere

Atmosphere can be turned off above the roof; the preference is saved locally.
All animations respect reduced motion. No model calls or extra polling are used.
Cats rest in idle rooms and pace beside working residents. A/B residents have
mint/lavender portals. Envelopes mark changes to observed working-agent/task
summaries, rather than claiming a specific delegation occurred. Initial snapshots
and reconnects do not replay deliveries.

The sky shows night when everyone rests, sun for active/waiting agents, rain for
attention states, and fog for unavailable status. It represents agent runtime
status, not real weather or a separate CI health check. Text status remains visible.

Master has a study, Builder a workshop, Researcher a library, Keeper a greenhouse,
Doctor a clinic, and Evaluator a studio. Custom roles get a stable room theme.
