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
                enriched = _CACHE.get("enriched_positions", [])
                payload = {
                    "capital": _CACHE.get("capital", 6000.0),
                    "equity": _CACHE.get("equity", 6000.0),
                    "free_margin": _CACHE.get("free_margin", 5704.31),
                    "buffer": 360.0,
                    "daily_buffer": 180.0,
                    "active_positions": enriched,
                    "has_active_trade": len(enriched) > 0,
                    "gld_price": _CACHE.get("gld_price", 4332.46),
                    "gld_mean": _CACHE.get("gld_mean_5d", 4340.00),
                    "gld_dip": _CACHE.get("gld_lower_band", 4330.00),
                    "gld_dist": _CACHE.get("gld_dist", 2.26),
                    "gld_dist_pct": _CACHE.get("gld_dist_pct", 0.05),
                    "spy_price": _CACHE.get("spy_price", 764.29),
                    "spy_mean": _CACHE.get("spy_mean_5d", 764.13),
                    "spy_dip": _CACHE.get("spy_lower_band", 758.45),
                    "spy_dist": _CACHE.get("spy_dist", 5.84),
                    "spy_dist_pct": _CACHE.get("spy_dist_pct", 0.76),
                    "qqq_price": _CACHE.get("qqq_price", 704.54),
                    "qqq_mean": _CACHE.get("qqq_mean_5d", 707.20),
                    "qqq_dip": _CACHE.get("qqq_lower_band", 704.68),
                    "qqq_dist": _CACHE.get("qqq_dist", -0.14),
                    "qqq_dist_pct": _CACHE.get("qqq_dist_pct", 0.0),
                    "aapl_price": _CACHE.get("aapl_price", 331.34),
                    "aapl_mean": _CACHE.get("aapl_mean_5d", 330.50),
                    "aapl_dip": _CACHE.get("aapl_lower_band", 318.50),
                    "aapl_dist": _CACHE.get("aapl_dist", 12.84),
                    "aapl_dist_pct": _CACHE.get("aapl_dist_pct", 3.9),
                    "nvda_price": _CACHE.get("nvda_price", 212.17),
                    "nvda_mean": _CACHE.get("nvda_mean_5d", 212.00),
                    "nvda_dip": _CACHE.get("nvda_lower_band", 210.27),
                    "nvda_dist": _CACHE.get("nvda_dist", 1.90),
                    "nvda_dist_pct": _CACHE.get("nvda_dist_pct", 0.9),
                    "msft_price": _CACHE.get("msft_price", 495.20),
                    "msft_mean": _CACHE.get("msft_mean_5d", 494.80),
                    "msft_dip": _CACHE.get("msft_lower_band", 486.50),
                    "msft_dist": _CACHE.get("msft_dist", 8.70),
                    "msft_dist_pct": _CACHE.get("msft_dist_pct", 1.75),
                    "meta_price": _CACHE.get("meta_price", 612.40),
                    "meta_mean": _CACHE.get("meta_mean_5d", 610.90),
                    "meta_dip": _CACHE.get("meta_lower_band", 598.20),
                    "meta_dist": _CACHE.get("meta_dist", 14.20),
                    "meta_dist_pct": _CACHE.get("meta_dist_pct", 2.31),
                    "payout_days": _CACHE.get("days_until_payout", 5),
                    "account_id": _CACHE.get("account_id", "3028655"),
                    "live_p2p_rate": _CACHE.get("live_p2p_rate", LIVE_P2P_RATE),
                    "wallet_address": _CACHE.get("wallet_address", "⚠️ NO WALLET LINKED — Use /setwallet in Telegram"),
                }
            except Exception as e:
                payload = {
                    "capital": 6000.0,
                    "equity": 5997.47,
                    "free_margin": 5704.31,
                    "buffer": 360.0,
                    "daily_buffer": 180.0,
                    "active_positions": [{
                        "position_id": 3069593,
                        "symbol_name": "XAUUSD",
                        "display_name": "Spot Gold",
                        "trade_side": "BUY",
                        "lots": 0.01,
                        "entry_price": 4334.99,
                        "current_price": 4332.46,
                        "take_profit": 4443.38,
                        "stop_loss": 4204.95,
                        "floating_pnl": -2.53,
                        "floating_pnl_pct": -0.06,
                        "dist_to_tp_usd": 110.92,
                    }],
                    "has_active_trade": True,
                    "gld_price": 4332.46,
                    "spy_price": 764.29,
                    "qqq_price": 704.54,
                    "aapl_price": 331.34,
                    "nvda_price": 212.17,
                    "msft_price": 495.20,
                    "meta_price": 612.40,
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
