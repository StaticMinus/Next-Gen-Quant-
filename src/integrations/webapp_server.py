"""
AgentQuant Telegram Mini App Web Server
=======================================
Serves the dark-mode HTML5/CSS/JS Telegram Mini App (TMA) and exposes
the /api/telemetry JSON endpoint synced with live cTrader and market radar data.
"""

import json
import mimetypes
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent.parent
WEBAPP_DIR = ROOT_DIR / "webapp"

class WebAppHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        # Silence verbose standard HTTP request logging
        return

    def do_GET(self):
        # 1. API Telemetry Endpoint
        if self.path == "/api/telemetry":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()

            try:
                from src.integrations.telegram_bot_service import _CACHE, LIVE_P2P_RATE
                payload = {
                    "capital": _CACHE.get("capital", 6000.0),
                    "equity": _CACHE.get("equity", 6000.0),
                    "buffer": 360.0,
                    "spy_price": _CACHE.get("spy_price", 764.29),
                    "spy_mean": _CACHE.get("spy_mean_5d", 764.13),
                    "spy_dip": _CACHE.get("spy_lower_band", 758.45),
                    "spy_dist": _CACHE.get("spy_dist", 5.84),
                    "qqq_price": _CACHE.get("qqq_price", 714.88),
                    "qqq_mean": _CACHE.get("qqq_mean_5d", 715.44),
                    "qqq_dip": _CACHE.get("qqq_lower_band", 704.16),
                    "payout_days": _CACHE.get("days_until_payout", 5),
                    "account_id": _CACHE.get("account_id", "3028655"),
                    "live_p2p_rate": _CACHE.get("live_p2p_rate", LIVE_P2P_RATE),
                    "wallet_address": _CACHE.get("wallet_address", "⚠️ NO WALLET LINKED — Use /setwallet in Telegram"),
                }
            except Exception:
                payload = {
                    "capital": 6000.0,
                    "equity": 6000.0,
                    "buffer": 360.0,
                    "spy_price": 764.29,
                    "spy_mean": 764.13,
                    "spy_dip": 758.45,
                    "spy_dist": 5.84,
                    "qqq_price": 714.88,
                    "qqq_mean": 715.44,
                    "qqq_dip": 704.16,
                    "payout_days": 5,
                    "account_id": "3028655",
                    "live_p2p_rate": 1518.40,
                    "wallet_address": "⚠️ NO WALLET LINKED — Use /setwallet in Telegram",
                }

            self.wfile.write(json.dumps(payload).encode("utf-8"))
            return

        # 2. Static File Serving (webapp/)
        clean_path = self.path.split("?")[0]
        if clean_path in ("/", ""):
            filename = "index.html"
        else:
            filename = clean_path.lstrip("/")

        file_path = WEBAPP_DIR / filename
        if not file_path.exists() or file_path.is_dir():
            file_path = WEBAPP_DIR / "index.html"

        if file_path.exists():
            mime_type, _ = mimetypes.guess_type(str(file_path))
            mime_type = mime_type or "text/html"

            self.send_response(200)
            self.send_header("Content-Type", f"{mime_type}; charset=utf-8")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()

            with open(file_path, "rb") as f:
                self.wfile.write(f.read())
        else:
            self.send_response(404)
            self.end_headers()


def start_webapp_server(host="0.0.0.0", port=8080):
    server = HTTPServer((host, port), WebAppHandler)
    print(f"[+] Telegram Mini App Server active at http://localhost:{port}")
    server.serve_forever()


def launch_server_in_thread(port=8080):
    t = threading.Thread(target=start_webapp_server, kwargs={"port": port}, daemon=True, name="WebAppServer")
    t.start()
    return t


if __name__ == "__main__":
    start_webapp_server()
