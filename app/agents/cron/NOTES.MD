delegation_targets:
  - builder
  - doctor
  - keeper

schedule:
  - id: health-check
    cron: "*/30 * * * *"
    task: "Run a quick health check: read all agent HEALTH.MD files and report any errors from the last hour."
    assign_to: doctor

  - id: daily-tests
    cron: "0 8 * * *"
    task: "Run the full test suite with `poetry run pytest tests/ -v`. Report failures."
    assign_to: builder

  - id: daily-digest
    cron: "0 9 * * *"
    task: "Generate a daily digest: summarize all agent MEMORY.MD entries from the past 24 hours. Write the digest to app/projects/daily-digest.md."
    assign_to: master