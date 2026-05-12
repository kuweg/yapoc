# Hierarchy Development

## Why Hierarchy Exists

The original reason for hierarchy in YAPOC is valid:

> Split one powerful but overloaded agent into smaller, narrower agents so the
> system becomes more stable, more predictable, and higher quality.

That means hierarchy is **not** the goal by itself. The goal is:

- lower cognitive load per agent
- fewer tools per agent
- less role confusion
- better routing of work
- safer execution boundaries
- easier recovery when one part fails
- higher quality through specialization and verification

If the hierarchy does not produce those outcomes, then it is only extra hops.

---

## Current Truth

Today, YAPOC already has process-level separation and a real delegation runtime:

- `Master` receives work and can stream results
- `Planning` can delegate
- `Builder` can edit files and create agents
- `Keeper`, `Cron`, `Doctor`, `Model Manager` exist in some form
- agents run as separate processes with `TASK.MD` and `STATUS.json`
- delegation caps and waiting primitives exist in code

What is still weak is the **quality of the hierarchy itself**:

- `Master` still carries too many tools and can bypass the hierarchy
- `Planning` is mostly prompt-driven orchestration, not strong structured routing
- some roles are underused or stub-like (`Keeper`, `Cron`)
- verification loops are not consistently built into delegation
- specialization is not enforced hard enough by tools and contracts
- success is not measured, so hierarchy can feel sophisticated without proving value

This means YAPOC currently has **agent separation**, but only a **partially successful hierarchy**.

---

## The Missing Pieces

For a multi-agent hierarchy to actually outperform one strong agent, YAPOC still needs the following.

### 1. Stronger Role Boundaries

Right now the biggest practical weakness is overlap:

- `Master` can do too much directly
- `Planning` and `Builder` partially overlap in execution decisions
- `Keeper` is conceptually important but not central in the real flow

Hierarchy only works when each layer has a narrow job:

- `Master` should route, supervise, and communicate
- `Planner` should decompose and coordinate
- `Builder` should build
- `Keeper` should own config and environment
- `Cron` should own schedules
- `Doctor` should monitor and eventually trigger recovery

Missing:

- a hard rule for when `Master` must delegate
- a hard rule for when `Planning` may delegate vs escalate
- a rule that prevents execution agents from taking work outside their domain
- fewer default tools on `Master`

Without this, hierarchy collapses back into "one big smart agent plus helpers".

### 2. Domain Isolation, Not Just Process Isolation

YAPOC already has process isolation. That is good, but it is not enough.

What is still missing is **domain isolation**:

- code-editing knowledge should live with dev-facing agents
- config/runtime knowledge should live with ops-facing agents
- monitoring/recovery knowledge should live with health agents

This suggests a future structure closer to:

```text
Master
├── Dev Planner
│   ├── Builder
│   └── Tester
├── Ops Planner
│   ├── Keeper
│   └── Cron
└── Monitor
    ├── Doctor
    └── Model Manager
```

Missing:

- separation between development and operations planning
- planner-local notes/memory scoped by domain
- tighter tool sets per family

If all planners still read the whole world and all important agents can still do broad work, specialization will remain shallow.

### 3. Verification Between Layers

This is one of the most important missing pieces.

Right now delegation mostly looks like:

```text
route -> do task -> return result
```

But a quality hierarchy should look more like:

```text
route -> execute -> verify -> retry or accept -> summarize
```

Examples:

- builder changes code -> tester or planning verifies tests
- keeper changes config -> validation step confirms config still parses
- cron writes schedule -> schedule parser confirms it is valid
- doctor detects issue -> recovery task verifies the system actually recovered

Missing:

- explicit verifier role or testing lane
- "done means verified" contract
- retry loop before escalation to the user
- result schema that distinguishes `executed` from `verified`

Without verification, hierarchy improves decomposition but not quality.

### 4. Better Routing Logic

Hierarchy only helps if work goes to the right place early.

Today, some of the routing logic is still too soft:

- `Master` can still choose to directly execute work that should be delegated
- there is not enough structured classification of task type
- mixed tasks are not first-class

Missing:

- first-turn routing classifier
- task classes such as `code`, `config`, `schedule`, `health`, `mixed`
- rules for parallel fan-out on mixed tasks
- fail-fast behavior when the wrong agent receives a task

Good hierarchy requires better routing than "agent decides in prompt space."

### 5. Hard Safety Boundaries in Tools

Part of the value of smaller agents is safety:

- smaller scope
- fewer destructive options
- easier auditing

Some of this exists, but not enough is tool-enforced.

Missing:

- stronger sandbox restrictions for every execution agent
- shell allowlists for `Keeper` and similar agents
- protected-path enforcement for `Builder`
- fewer risky tools available to `Master`
- explicit "cannot touch outside domain" enforcement

If a specialized agent can still operate broadly, specialization is cosmetic.

### 6. Recovery and Fallback at the Hierarchy Level

A hierarchy should degrade gracefully:

- if one agent fails, the whole task should not become opaque
- supervisors should be able to inspect, retry, reroute, or escalate

Some runtime primitives exist already, but the hierarchy still lacks a strong recovery model.

Missing:

- planner reads `read_agent_logs` to diagnose failed sub-agents
- standard retry policy per subtask type
- alternate route when one agent is unavailable
- structured escalation message when retries are exhausted
- clearer handoff from `Doctor` to `Master` or planners for remediation

The hierarchy becomes valuable when failures stay local and understandable.

### 7. Objective Measurement

This is the biggest strategic gap.

The hierarchy was introduced to improve stability and quality, but YAPOC does not yet clearly measure whether it does.

Missing:

- success rate by task type
- retry count by agent
- average task completion time by route
- token/cost overhead of delegation
- percent of tasks solved by direct execution vs hierarchy
- verified-success rate after builder changes

Without these metrics, hierarchy can only be defended aesthetically.

---

## What Hierarchy Must Prove

The hierarchy should justify itself with concrete wins over a single strong agent.

It should prove at least four things:

1. **Lower error rate**
   Narrow agents make fewer wrong moves because they have less scope and fewer tools.

2. **Better recovery**
   When an execution step fails, the supervisor can retry or reroute without losing the whole task.

3. **Better quality**
   Specialized agents plus verification produce more correct final outputs.

4. **Acceptable overhead**
   The extra routing cost is small enough relative to the quality/stability gain.

If YAPOC cannot show these four things, then the hierarchy should be simplified.

---

## Implementation Update (2026-04-18)

This document is now partially implemented in runtime code (not just prompts).

### Implemented Now

1. **Harder delegation boundaries**
- `planning` is no longer an unrestricted spawner in code.
- Only `master` bypasses `delegation_targets`; all other agents must declare allowed targets.
- `planning` now explicitly declares:
  - `delegation_targets: [builder, keeper]`

2. **Structured routing classifier + fail-fast mismatches**
- `spawn_agent` now classifies each spawned task into:
  - `code | config | schedule | health | mixed | general`
- If an agent is a bad domain match for that class, spawn is rejected with a routing error and suggested target.
- This enforces "wrong agent receives task" fail-fast behavior.

3. **Verification contract metadata**
- Delegated tasks now carry frontmatter fields:
  - `task_id`, `task_class`, `route_target`, `route_reason`
  - `verification_required`, `verification_status`, `verified_by`, `verified_at`
- Done tasks that require verification default to `verification_status: pending` unless the result clearly includes a verification section.
- New tool: `verify_task_result` lets parent agents explicitly mark a child task as `verified` or `rejected`.
- `check_task_status`, `wait_for_agent`, `wait_for_agents`, and `read_task_result` now surface verification status.

4. **Routing hint injected into master execution context**
- Master now receives a deterministic routing block per task (class, suggested agent, confidence, verification requirement) before LLM planning.

5. **Hierarchy metrics endpoint**
- New endpoint: `GET /metrics/hierarchy`
- Reports:
  - task counts by parent and by task class
  - success rate by task class
  - verification required/verified/pending counts
  - average completion time by parent

### Files Changed for This Update

- `app/utils/hierarchy.py`
- `app/utils/tools/delegation.py`
- `app/utils/tools/__init__.py`
- `app/agents/base/__init__.py`
- `app/agents/base/runner.py`
- `app/backend/routers/metrics.py`
- `app/agents/planning/CONFIG.md`
- `app/agents/planning/PROMPT.MD`
- `app/agents/master/CONFIG.md`
- `app/agents/master/agent.py`

---

## Next High-Value Steps

1. Add explicit **Verifier** agent lane (or planning verifier mode) so verification is always separate from execution.
2. Track retries using stable subtask IDs (current `task_id` is per-spawn).
3. Add route-level KPI split for direct master handling vs delegated handling in task queue analytics.

---

## Proposed Target Hierarchy

This is the simplest version that still preserves the original intention.

### Layer 1: Router

`Master`

Responsibilities:

- receive tasks from UI, CLI, webhook, cron, and goals
- classify task type
- decide direct execution vs delegation
- supervise long-running work
- communicate results to the user

Should have:

- minimal tool set
- little or no direct file mutation by default
- strong routing rules

### Layer 2: Coordinators

`Dev Planner`

- owns code-task decomposition
- coordinates builder and tester
- aggregates verified results

`Ops Planner`

- owns config, dependency, schedule, and environment changes
- coordinates keeper and cron
- validates operational changes

### Layer 3: Executors

`Builder`

- edits code and files
- can propose changes
- does not own final acceptance

`Tester` (future)

- runs tests, checks outputs, validates changed paths
- feeds failures back into planner/builder loop

`Keeper`

- edits config and environment only

`Cron`

- owns schedule definitions and due-job execution

### Layer 4: Monitors

`Doctor`

- detects stuck agents, repeated failures, crash loops, runaway costs
- opens recovery tasks or asks for remediation

`Model Manager`

- audits model choices, cost posture, provider fallback health

---

## Concrete Development Priorities

These are the highest-leverage steps to make the hierarchy actually earn its complexity.

### Priority 1: Shrink Master

Goal:

- make `Master` a router/supervisor, not a second builder

Actions:

- remove file mutation and shell tools from Master's default tool list
- keep delegation, waiting, logs, memory, web, and messaging tools
- add an explicit direct-exec mode only for narrow/simple tasks
- write a strict delegation policy in prompt + docs

Expected win:

- lower tool bloat
- better routing discipline
- clearer hierarchy

### Priority 2: Split Planning by Domain

Goal:

- isolate dev work from ops work

Actions:

- rename current `Planning` to `Dev Planner`
- create `Ops Planner`
- route config/schedule/environment work to ops
- route code/product work to dev
- allow parallel fan-out on mixed tasks

Expected win:

- less role overlap
- more coherent notes/memory
- easier prompt design

### Priority 3: Add Verification Lane

Goal:

- "done" should mean "checked", not just "executed"

Actions:

- introduce `Tester` agent or planner-owned verify loop
- make code tasks require validation before acceptance
- record `executed`, `verified`, or `failed` separately
- retry builder with test output before escalating

Expected win:

- much better output quality
- hierarchy begins improving correctness, not only structure

### Priority 4: Enforce Boundaries in Tools

Goal:

- make specialization real in code, not just prompts

Actions:

- add stronger sandbox rules for builder and keeper
- add shell allowlists
- forbid protected paths for non-owner agents
- reduce cross-domain tool leakage

Expected win:

- safer agents
- more trustworthy role separation

### Priority 5: Add Hierarchy Metrics

Goal:

- prove the architecture is helping

Actions:

- track route taken per task
- track retries, failures, verification rate, cost, latency
- build a dashboard slice for route effectiveness
- compare direct-exec tasks vs delegated tasks

Expected win:

- real evidence for future design choices

---

## Definition of Success

The hierarchy is working when all of the following are true:

- `Master` rarely edits files directly
- most tasks are routed correctly on the first attempt
- code tasks are verified before being marked done
- failures are contained within one layer and recovered locally
- operational tasks do not pollute development task context
- average quality is better than a single generalist agent
- the extra latency/cost of delegation is measurable and acceptable

---

## Definition of Failure

The hierarchy is failing if:

- `Master` still acts like the main executor
- agents repeatedly overlap or fight over the same task class
- most quality still depends on one model "being smart enough"
- delegation adds cost/latency without better outputs
- verification is missing or optional
- role boundaries exist mainly in prompts, not in tools and policies

If these remain true, YAPOC should simplify the hierarchy rather than deepen it.

---

## Recommended Next Build Sequence

1. Trim Master's tool surface and make routing explicit.
2. Rename Planning to Dev Planner and introduce Ops Planner.
3. Add verification as a first-class stage for code/config tasks.
4. Harden tool-enforced boundaries and sandboxes.
5. Add route-quality metrics and compare against direct execution.

Only after these steps should YAPOC add more agents.

---

## Core Principle

The hierarchy should exist to reduce complexity **for each agent** while improving reliability **for the whole system**.

If adding an agent does not:

- narrow responsibility,
- reduce tool surface,
- improve verification,
- or improve recovery,

then it should not be added.
