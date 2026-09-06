# YAPOC follow-up audit — 2026-09-05

These findings remain open in the current working tree. This review used temporary databases/files and mocked processes/providers; it did not run real shell commands through YAPOC, contact Telegram, spawn agents, or restart the backend. Runtime source was unchanged by this review.

Two findings expose gaps in the preceding fixes: cancellation of already-queued continuations and stale errors on recovered successful tasks.

## P1: Shell restrictions do not constrain the full command

`app/utils/tools/__init__.py:54` checks only whether the first whitespace-separated token begins with an allowed prefix. `app/utils/tools/shell.py:46` then passes the entire string to `/bin/sh -c`.

A policy permitting `echo` accepts both `echo harmless; unapproved_command` and `echo_not_the_allowed_binary`. Confirmed by calling only the policy predicate; nothing was executed. File-tool forbidden paths do not constrain shell operations.

Correction direction: explicit argument-vector execution for restricted commands, exact executable matching, and an OS-level filesystem/process boundary for agents that can run interpreters or arbitrary shell programs.

## P1, conditional: Telegram authentication defaults to disabled

`app/backend/telegram_bot.py:175` returns false for `Authenticator.enabled` when both PIN and whitelist are empty. The message gate at line 1764 checks authorization only when enabled. If the Telegram bot is enabled with this configuration, unauthenticated private-chat requests can reach task handling. The new HTTP access token does not protect this channel.

Confirmed the empty-configuration predicate in isolation. Actual deployment credentials were not inspected; this is not a claim that the current bot is exposed.

Correction direction: reject task handling until an owner allowlist or authentication mechanism is configured.

## P1: Stop does not cancel the complete execution tree

Two independently confirmed cases:

- `app/utils/tools/shell.py:53` kills the process group on timeout but has no cancellation cleanup. Cancelling a mocked running shell coroutine never called either `killpg` or `proc.kill`; a real subprocess can continue after the master task is cancelled.
- `app/backend/services/notification_delivery.py:49` skips existing delivery rows before checking whether the original request is cancelled. Dispatcher does not recheck parent cancellation. A planning continuation queued before cancellation remained pending and executed successfully afterward in an isolated dispatcher test.

Correction direction: cancellation cleanup for tool subprocess groups, durable root-request cancellation inherited by descendants, and a parent-state check immediately before dispatching continuations.

## P1: A pending child assignment can be overwritten

`app/utils/tools/delegation.py:399` refuses assignment only when process status says `running`. An idle worker can already have a pending TASK.MD awaiting pickup. A second submission is accepted and replaces that assignment. The fixed temporary filename `TASK.md.tmp` also provides no concurrent-writer isolation.

Confirmed with two assignments while the mocked worker stayed idle: both reported successful assignment, and the second replaced the first pending TASK.MD. The Redis runner checks expected task ID against the current file; a mismatch aborts execution rather than restoring the overwritten assignment (`app/agents/base/runner.py`, `_run_task`).

Correction direction: durable per-worker assignment queue or an atomic reservation covering task status, assignment identity, and process startup. Atomic file replacement alone is insufficient.

## P2: Master context mixes active work from different chats

`app/agents/master/agent.py`, `_outstanding_delegations`, filters by assigning agent but does not inspect session or root-request ID. `handle_task_stream` injects that list into every new turn.

Confirmed with a temporary builder assignment owned by chat A and master set to chat B: the injected outstanding-work text included A's task summary. This establishes context contamination; whether the model takes a wrong action depends on its response.

Correction direction: scope actionable delegation context to the current request/session, with explicitly identified global status kept separate.

## P2: A recovered success retains an obsolete error

Startup recovery at `app/backend/main.py:958` requeues interrupted rows without clearing their error. The dispatcher success update at `app/backend/dispatcher.py:279` also leaves it intact. Browser completion rendering treats any nonempty error as failure (`ChatPanel.tsx`, completion effect).

Confirmed by executing a successfully recovered row: status became `done`, while error remained `Backend stopped during execution`. Live success messages omit the error, but reconnect state is read from the database and can present the conflicting state as a failure.

Correction direction: clear obsolete error/terminal fields on valid state transitions while retaining attempt history separately; test the recovered completion through both live delivery and reconnect replay.

## Reproduction artifacts

- `/tmp/yapoc_remaining_audit.py`: shell-policy predicate, Telegram auth predicate, mocked shell cancellation, queued-continuation cancellation, recovered success/error consistency, and pending-assignment overwrite.
- `/tmp/yapoc-remaining-audit.log`: all six reproduction checks completed successfully, meaning the undesirable behaviors were observed.
- Separate temporary-file check confirmed cross-session outstanding-work injection.

Priority: repair the shell boundary and cancellation semantics, prevent assignment overwrite, and verify Telegram is configured to require an authorized owner. Then close context ownership and recovery-state consistency gaps.
