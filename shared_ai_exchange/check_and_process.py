import os
import json

CHANNEL_FILE = r"c:\doomsday-engine\shared_ai_exchange\channel.json"

def check():
    if not os.path.exists(CHANNEL_FILE):
        return False
    try:
        with open(CHANNEL_FILE, "r") as f:
            data = json.load(f)
        return data.get("turn") == "gemini"
    except Exception:
        return False

if __name__ == "__main__":
    if check():
        print("UPDATE_DETECTED")
    else:
        print("NO_CHANGE")
