#!/usr/bin/env python3
"""Patch tts_engine default"""
import re
p = "app/config/settings.py"
with open(p) as f:
    c = f.read()
c = c.replace('tts_engine: str = "offline"', 'tts_engine: str = "openai"')
with open(p, "w") as f:
    f.write(c)
print("done")
