Testing the 3 Features                       
                                                                                                                                                                                                                                                                                                                      
  Feature 1: File Tools                                                                                                                                                                                                                                                                                             
                                                                                                                                                                                                                                                                                                                      
  # Start the server
  poetry run yapoc start                                                                                                                                                                                                                                                                                              
                                                                                                                                                                                                                                                                                                                    
  # Enter REPL
  poetry run yapoc

  # Ask agent to write a file
  > Write "hello world" to a file called test_output.txt in the projects/ directory

  # Should trigger approval prompt → approve → file created
  # Then ask it to edit:
  > Replace "hello world" with "goodbye world" in projects/test_output.txt

  # Then delete:
  > Delete the file projects/test_output.txt

  # Test protection — should refuse:
  > Delete the file .env

  Feature 2: Sessions

  # Start a REPL, send a couple messages, then exit
  poetry run yapoc
  > Hello, remember the number 42
  > What number did I mention?
  > /exit

  # Resume latest session (history should carry over)
  poetry run yapoc chat --continue
  > What number did I mention earlier?

  # List sessions
  > /sessions

  # Or resume by ID from the table
  > /resume 20260313-XXXXXX-abcdef

  # One-shot resume also works:
  poetry run yapoc chat -c
  poetry run yapoc chat -r <session-id>

  Session files live in app/agents/master/sessions/*.jsonl — you can inspect them directly.

  Feature 3: Context Compaction

  This is harder to trigger naturally (needs ~85% of 200K tokens). Two ways:

  Manual /compact:
  poetry run yapoc
  > Tell me a long story about dragons
  > Now tell me about space exploration
  > /compact
  # Should print: "Context compacted: X → Y tokens"
  > Summarize what we discussed
  # Agent should still know the topics from compacted summary

  Optional focus:
  > /compact dragons
  # Compaction will emphasize dragon-related content

  Auto-compact kicks in when _estimate_tokens(messages) >= context_window * 0.85. To test without sending 170K tokens of messages, temporarily lower the threshold:

  # In .env, add:
  CONTEXT_COMPACT_THRESHOLD=0.01

  # Then any conversation with a few messages will auto-compact.
  # You'll see "Context compacted (auto): X → Y tokens" in the output.
  # Remove the override after testing.

  Quick smoke test (all at once)

  poetry run yapoc start
  poetry run yapoc
  > Write "test 123" to projects/smoke.txt       # file_write (approve)
  > Read projects/smoke.txt                       # should show content
  > Replace "123" with "456" in projects/smoke.txt # file_edit (approve)
  > /sessions                                      # should show current session
  > /compact                                       # compact context
  > Delete projects/smoke.txt                      # file_delete (approve)
  > /exit

  poetry run yapoc chat -c                         # resume session
  > What file did we just work with?               # agent should recall from history
