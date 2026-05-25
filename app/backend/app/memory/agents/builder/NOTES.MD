
Starting implementation of 4 Telegram bot features + 1 Master PROMPT.MD update.

Plan:
1. **Feature 1**: Add `_register_commands` method + call from `start()` after lock
2. **Feature 2a**: Change allowed_updates to include "edited_message"
3. **Feature 2b**: Add edited_message handling in polling loop + `is_edit` param in `_handle_message`
4. **Feature 3a**: Remove short-text optimization block in `_stream_editor_loop`
5. **Feature 3b**: Change threshold from 5 to 3
6. **Feature 3c**: Change "Processing your request..." to "Generating..."
7. **Feature 3d**: Add initial "Generating..." edit at start of `_stream_editor_loop`
8. **Feature 4**: Add Image Recognition section to Master PROMPT.MD
