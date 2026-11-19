"""Helper: find your Telegram chat_id.

1) Create a bot with @BotFather and put its token in ai/.env (TELEGRAM_TOKEN).
2) Open your bot in Telegram and send it any message (e.g. "hola").
3) Run:  python get_chat_id.py
   It prints the chat_id — copy it into ai/.env as TELEGRAM_CHAT_ID.
"""

import os
import pathlib
import sys

import requests
from dotenv import load_dotenv

load_dotenv(pathlib.Path(__file__).with_name(".env"))

token = os.environ.get("TELEGRAM_TOKEN") or (sys.argv[1] if len(sys.argv) > 1 else "")
if not token:
    sys.exit("Falta TELEGRAM_TOKEN en .env (o pásalo como argumento).")

data = requests.get(f"https://api.telegram.org/bot{token}/getUpdates", timeout=20).json()
if not data.get("ok"):
    sys.exit(f"Telegram respondió error: {data}")

seen = set()
for upd in data.get("result", []):
    msg = upd.get("message") or upd.get("channel_post") or {}
    chat = msg.get("chat", {})
    cid = chat.get("id")
    if cid and cid not in seen:
        seen.add(cid)
        who = chat.get("first_name") or chat.get("title") or "?"
        print(f"TELEGRAM_CHAT_ID={cid}   ({chat.get('type')}, {who})")

if not seen:
    print("No encontré mensajes. Manda un mensaje a tu bot (ej. 'hola') y vuelve a correr esto.")
