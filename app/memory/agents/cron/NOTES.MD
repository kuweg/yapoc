schedule:
  - id: memory-sweep
    cron: "0 */20 * * *"
    task: "Perform a memory sweep to extract durable facts from recent dialogues."
    assign_to: librarian

turn_counter: 0
