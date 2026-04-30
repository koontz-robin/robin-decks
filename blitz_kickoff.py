#!/usr/bin/env python3
"""Sends a voice memo to Discord at 1:30 PM ET saying IT'S BLITZ TIME"""
import requests, time, json
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")

CHANNEL_ID      = "1486423858318938123"
ELEVENLABS_KEY  = "b3da64bd7c1d62fb2976d9e661d0885541772a9aaa2518680d5a6cbe9ac3db3b"
VOICE_ID        = "OxtnMEpM1AaxPdfQOSkc"
AUDIO_PATH      = "/home/openclaw/.openclaw/workspace/blitz_time.ogg"

with open('/home/openclaw/.openclaw/openclaw.json') as f:
    _cfg = json.load(f)
DISCORD_TOKEN = _cfg['channels']['discord']['token']

# Wait until 1:30 PM ET (DST-aware)
now_et = datetime.now(ET)
target_et = now_et.replace(hour=13, minute=30, second=0, microsecond=0)
target_utc = target_et.astimezone(timezone.utc)
wait = (target_utc - datetime.now(timezone.utc)).total_seconds()
if wait > 0:
    print(f"Waiting {wait:.0f}s until 1:30 PM ET...", flush=True)
    time.sleep(wait)

print("Generating voice...", flush=True)
r = requests.post(
    f"https://api.elevenlabs.io/v1/text-to-speech/{VOICE_ID}?output_format=opus_48000_32",
    headers={"xi-api-key": ELEVENLABS_KEY, "Content-Type": "application/json"},
    json={
        "text": "IT'S BLITZ TIME! LET'S GO!!!",
        "model_id": "eleven_monolingual_v1",
        "voice_settings": {"stability": 0.3, "similarity_boost": 0.8}
    }
)

with open(AUDIO_PATH, "wb") as f:
    f.write(r.content)
print(f"Audio generated: {len(r.content)} bytes", flush=True)

with open(AUDIO_PATH, "rb") as f:
    audio_data = f.read()

hdrs = {"Authorization": "Bot " + DISCORD_TOKEN}
resp = requests.post(
    f"https://discord.com/api/v10/channels/{CHANNEL_ID}/messages",
    headers=hdrs,
    data={"content": "🚨 **IT'S BLITZ TIME** 🚨 1:30-3 PM — phones up, let's GO! 📞🔥"},
    files={"file": ("blitz_time.ogg", audio_data, "audio/ogg")}
)
print(f"Discord: {resp.status_code}", flush=True)
print("DONE", flush=True)
