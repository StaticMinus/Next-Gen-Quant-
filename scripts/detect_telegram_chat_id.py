"""
Detect Telegram Chat ID Automatically
=====================================
Checks the bot's incoming updates from Telegram to find your personal Chat ID.
Once detected, it automatically writes TELEGRAM_CHAT_ID into .env and sends a
confirmation test message to your phone.
"""

import os
import sys
import json
import urllib.request
from pathlib import Path
from dotenv import load_dotenv

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

load_dotenv()

token = os.getenv("TELEGRAM_BOT_TOKEN")
if not token:
    print("[!] Error: TELEGRAM_BOT_TOKEN not found in .env")
    sys.exit(1)

print(f"Connecting to Telegram Bot API with token: {token[:12]}...")
url = f"https://api.telegram.org/bot{token}/getUpdates"

try:
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req, timeout=10) as response:
        data = json.loads(response.read().decode("utf-8"))

    results = data.get("result", [])
    if not results:
        print("\n[!] No messages received yet by your bot.")
        print("👉 Action Required:")
        print("   1. Open your Telegram app on your phone.")
        print("   2. Go to: https://t.me/Nextgeneration9_bot")
        print("   3. Tap START (or send any message like 'hello').")
        print("   4. Then run this script again, or let me know!\n")
    else:
        # Get the latest chat_id
        latest_msg = results[-1]
        chat = latest_msg.get("message", {}).get("chat", {}) or latest_msg.get("my_chat_member", {}).get("chat", {})
        chat_id = chat.get("id")
        user_name = chat.get("first_name", "Trader")

        if chat_id:
            print(f"\n🎉 Detected Telegram Chat ID: {chat_id} for user '{user_name}'!")
            
            # Update .env
            env_path = Path(".env")
            content = env_path.read_text(encoding="utf-8")
            if "TELEGRAM_CHAT_ID=" in content:
                import re
                new_content = re.sub(r"TELEGRAM_CHAT_ID=.*", f"TELEGRAM_CHAT_ID={chat_id}", content)
                env_path.write_text(new_content, encoding="utf-8")
                print("✅ Updated .env with your TELEGRAM_CHAT_ID!")

            # Send a test confirmation message to the user's phone
            send_url = f"https://api.telegram.org/bot{token}/sendMessage"
            welcome_text = (
                f"🚀 *AgentQuant Live Connection Successful!*\n\n"
                f"Hello {user_name}! Your automated trading bot is officially connected to this chat.\n\n"
                f"• *Strategy:* Balanced Scalper (SPY)\n"
                f"• *Target Firm:* FundedNext (cTrader)\n"
                f"• *Status:* Online & Ready for 24/7 Cloud Execution\n\n"
                f"You will receive all live trade notifications directly here!"
            )
            payload = json.dumps({
                "chat_id": chat_id,
                "text": welcome_text,
                "parse_mode": "Markdown"
            }).encode("utf-8")

            send_req = urllib.request.Request(send_url, data=payload, headers={"Content-Type": "application/json"}, method="POST")
            with urllib.request.urlopen(send_req, timeout=10) as send_resp:
                res = json.loads(send_resp.read().decode("utf-8"))
                if res.get("ok"):
                    print("📱 Sent a welcome test alert directly to your Telegram app!")
        else:
            print("[!] Found updates but could not parse chat id:", results[-1])

except Exception as e:
    print(f"[!] Error contacting Telegram API: {e}")
