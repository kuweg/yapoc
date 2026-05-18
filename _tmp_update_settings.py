#!/usr/bin/env python3
"""Update tts_engine default in settings.py"""
path = "app/config/settings.py"
with open(path) as f:
    content = f.read()

content = content.replace('tts_engine: str = "offline"', 'tts_engine: str = "openai"')

with open(path, "w") as f:
    f.write(content)

print("settings.py updated successfully")
