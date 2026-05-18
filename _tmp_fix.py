#!/usr/bin/env python3
import pathlib
p = pathlib.Path("app") / "config" / "settings.py"
c = open(p).read()
c = c.replace('tts_engine: str = "offline"', 'tts_engine: str = "openai"')
open(p, "w").write(c)
print("OK")
