"""
Telegram Notifier Module — AgentQuant Live Alerts
=================================================
Sends instant trade signals, execution confirmations, and daily PnL summaries
directly to the user's Telegram phone app via Telegram Bot API.
"""

import os
import urllib.request
import urllib.parse
import json
from dotenv import load_dotenv

load_dotenv()


def send_telegram_alert(message: str) -> bool:
    """
    Sends a message to Telegram using bot token and chat ID.
    Reads TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID from environment.
    Gracefully logs and returns False if tokens are missing.
    """
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")

    if not token or not chat_id:
        # Not configured yet - silent return or local log
        return False

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": message,
        "parse_mode": "HTML",
    }

    try:
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as response:
            res = json.loads(response.read().decode("utf-8"))
            return res.get("ok", False)
    except Exception as e:
        # Fallback without parse_mode if formatting had an error
        try:
            payload_plain = {"chat_id": chat_id, "text": message}
            data_plain = json.dumps(payload_plain).encode("utf-8")
            req_plain = urllib.request.Request(
                url, data=data_plain, headers={"Content-Type": "application/json"}, method="POST"
            )
            with urllib.request.urlopen(req_plain, timeout=10) as response:
                res = json.loads(response.read().decode("utf-8"))
                return res.get("ok", False)
        except Exception as e2:
            print(f"[!] Telegram Alert failed: {e2}")
            return False


if __name__ == "__main__":
    # Self-test
    test_msg = "🤖 *AgentQuant Test Alert*\nConnection successful! Your automated trading bot is online."
    success = send_telegram_alert(test_msg)
    if success:
        print("Telegram alert delivered successfully!")
    else:
        print("Telegram alert skipped (TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID not set in .env).")
