I want to create a bullet-proof back notification system for agent execution.
Need design.
Idea is, agent that calls subagetn or other agent is treated as "parent" and called agent/aubagent is "child".
when parent called child it is marked something like agent1 -> agent2.
when agent2 is finnising it's job it called tool notify_parent(agent1), which invokes parent with previous history + subagent-result
that chaing should support different length like agent1->agent2->agent3->..->agentN,
as a result will be N calling notify_parent(parent_name: str), where last will be notify_parent("User").
Also it should support bulk call, for example agent1 calls agent2 and agent3
agent1 -> agent2
       -> agent3

Here I want you to think how it should behave - wait slowest or do streaming


for this request:
spawn planning with this task:
    spawn builder with task: create a file at /tmp/notify_test.txt containing "hello from builder", then call
  notify_parent with your result
    do NOT call wait_for_agent — just spawn and return
  Watch app/agents/planning/TASK.MD. After builder finishes and calls notify_parent, planning's TASK.MD should get the
   trigger (assigned_by: notification, status: pending) and planning's runner wakes up, processes builder's result.

Backend listening on http://0.0.0.0:8000 — Ctrl+C to stop
INFO:     Started server process [79351]
INFO:     Waiting for application startup.
2026-04-12 12:04:55 [INFO ] [spawn_registry] SpawnRegistry loaded 1 entries from data/spawn_registry.json
2026-04-12 12:04:55 [INFO ] [notification_queue] NotificationQueue loaded 4 items (3 unconsumed) from data/notification_queue.json
2026-04-12 12:04:55 [INFO ] [notification_poller] NotificationPoller: started (interval=30s, agents_dir=/Users/nikita_zaitsev/Projects/yapoc/app/agents)
INFO:     Application startup complete.
INFO:     Uvicorn running on http://0.0.0.0:8000 (Press CTRL+C to quit)
2026-04-12 12:05:00 [INFO ] [master    ] Turn 0 start | model=claude-sonnet-4-5 est_tokens=127
2026-04-12 12:05:05 [INFO ] [master    ] Tool spawn_agent | input={'agent_name': 'planning', 'task': 'spawn builder with task: create a file at /tmp/notify_test.txt containing "hello from builder", then call notify_parent with your result\n\ndo NOT call wait_for_age
2026-04-12 12:05:05 [INFO ] [master    ] Usage turn=0 | in=3 out=252 cache_r=2430 cache_w=2385 tps=53.0 cost=$0.000000
2026-04-12 12:05:05 [INFO ] [master    ] Tool spawn_agent done | elapsed=0.002s ok
2026-04-12 12:05:05 [INFO ] [master    ] Turn 1 start | model=claude-sonnet-4-5 est_tokens=420
2026-04-12 12:05:10 [INFO ] [master    ] Usage turn=1 | in=5 out=155 cache_r=4815 cache_w=283 tps=29.2 cost=$0.000000
2026-04-12 12:05:10 [INFO ] [master    ] Task done | turns=2 response_chars=718
2026-04-12 12:05:55 [INFO ] [notification_poller] NotificationPoller: builder completed (done) → notifying parent planning



So is there no last notifications to plannig -> master and master -> user.

tested via poetry run yapoc backend and UI interfaces


Alling instructiinos. I will provide a correct delegation and taks decompositiion.
Task:
spawn 5 new temp agents, ask them question "What is you name?". Return table with responces

How it should be:
1. Master spawn planner and builder
2. Planner thinks and create task for builder
3. Builder do the thing, return response to master
4. Master spawn those agents and collect's it's outputs
5. Master gives notification to planner to remove the agents
6. Planner gives norification to builder to remove agents
7. Builder to master
8.  Master respoded to user

Adjust promots for agents to follow this behaviour and present me changes after