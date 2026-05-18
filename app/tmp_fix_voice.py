#!/usr/bin/env python3
"""Temporary script to change openai_tts_voice default from alloy to onyx."""
path = 'app/config/settings.py'
with open(path) as f:
    content = f.read()
content = content.replace(
    'openai_tts_voice: str = "alloy"',
    'openai_tts_voice: str = "onyx"'
)
with open(path, 'w') as f:
    f.write(content)
print("SUCCESS: Changed openai_tts_voice default from alloy to onyx")
