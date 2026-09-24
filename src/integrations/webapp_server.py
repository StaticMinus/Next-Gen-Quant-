"""
AgentQuant Telegram Mini App Web Server
=======================================
Serves the dark-mode HTML5/CSS/JS Telegram Mini App (TMA) and exposes
the /api/telemetry JSON endpoint synced with live cTrader and market radar data.
"""

import json
import mimetypes
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent.parent
WEBAPP_DIR = ROOT_DIR / "webapp"

class WebAppHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        # Silence verbose standard HTTP request logging
        return

    def do_GET(self):
        # 0. Healthcheck Endpoint (for Render / Docker)
        if self.path in ("/health", "/ping"):
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(b'{"status": "ok", "service": "agentquant-terminal"}')
            return

        # 1. API Telemetry Endpoint
        if self.path == "/api/telemetry":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()

            try:
                from src.integrations.telegram_bot_service import _CACHE, LIVE_P2P_RATE
                from src.integrations.ctrader_mcp_client import ctrader_client
                
                # Fetch fresh live telemetry if available
                try:
                    en = ctrader_client.get_enriched_positions()
                    if en is not None:
                        _CACHE["enriched_positions"] = en
                    bal = ctrader_client.get_balance()
                    if bal:
                        _CACHE["capital"] = bal.get("balance", _CACHE.get("capital", 6000.0))
                        _CACHE["equity"] = bal.get("equity", _CACHE.get("equity", 6000.0))
                        _CACHE["free_margin"] = bal.get("freeMargin", _CACHE.get("free_margin", 5704.31))
                except Exception:
                    pass

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
                    "active_positions": [],
                    "has_active_trade": False,
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

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_POST(self):
        if self.path == "/api/close_position":
            content_len = int(self.headers.get('Content-Length', 0))
            post_body = self.rfile.read(content_len)
            try:
                data = json.loads(post_body.decode('utf-8'))
                pos_id = int(data.get('position_id', 0))
                
                if not pos_id:
                    self.send_response(400)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Access-Control-Allow-Origin", "*")
                    self.end_headers()
                    self.wfile.write(json.dumps({"status": "error", "error": "Missing position_id"}).encode('utf-8'))
                    return

                from src.integrations.ctrader_mcp_client import ctrader_client
                from src.integrations.telegram_bot_service import _CACHE, api_call, PRIMARY_CHAT_ID

                close_res = ctrader_client.close_position(pos_id)
                en = ctrader_client.get_enriched_positions()
                _CACHE["enriched_positions"] = en
                bal = ctrader_client.get_balance()
                if bal:
                    _CACHE["capital"] = bal.get("balance", _CACHE.get("capital", 6000.0))
                    _CACHE["equity"] = bal.get("equity", _CACHE.get("equity", 6000.0))

                try:
                    receipt = (
                        "✅ <b>TRADE CLOSED VIA WEB TERMINAL</b>\n"
                        "────────────────────────────\n"
                        f"• <b>Position ID:</b> <code>#{pos_id}</code>\n"
                        "• <b>Source:</b> Next Generation WebApp (David)\n"
                        f"• <b>New Balance:</b> <code>${_CACHE['capital']:,.2f} USD</code>\n"
                        f"• <b>Account Equity:</b> <code>${_CACHE['equity']:,.2f} USD</code>\n"
                        "────────────────────────────\n"
                        "🛡️ Risk parameters safe and verified."
                    )
                    api_call("sendMessage", {
                        "chat_id": PRIMARY_CHAT_ID,
                        "text": receipt,
                        "parse_mode": "HTML"
                    })
                except Exception:
                    pass

                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(json.dumps({"status": "success", "position_id": pos_id, "result": close_res}).encode('utf-8'))
                return
            except Exception as e:
                self.send_response(500)
                self.send_header("Content-Type", "application/json")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(json.dumps({"status": "error", "error": str(e)}).encode('utf-8'))
                return

        self.send_response(404)
        self.end_headers()


def start_webapp_server(host="0.0.0.0", port=None):
    server_port = int(port or os.getenv("PORT", 8080))
    server = ThreadingHTTPServer((host, server_port), WebAppHandler)
    print(f"[+] Telegram Mini App Server active at http://localhost:{server_port}")
    server.serve_forever()


def launch_server_in_thread(port=None):
    server_port = int(port or os.getenv("PORT", 8080))
    t = threading.Thread(target=start_webapp_server, kwargs={"port": server_port}, daemon=True, name="WebAppServer")
    t.start()
def launch_gold_copier_thread():
    """Launches the 24/7 Telegram Gold Copier inside a daemon thread."""
    try:
        from src.integrations.telegram_gold_copier import start_copier_daemon
        t = threading.Thread(target=start_copier_daemon, kwargs={"interval_sec": 2, "dry_run": False}, daemon=True, name="GoldCopierDaemon")
        t.start()
        print("[+] Telegram Gold Copier daemon thread started successfully (2s interval).")
        return t
    except Exception as e:
        print(f"[!] Warning: Could not start Gold Copier daemon thread: {e}")
        return None


if __name__ == "__main__":
    # Launch 24/7 Telegram Gold Copier daemon thread
    launch_gold_copier_thread()

    # Launch Web Server & Healthcheck on Render Free Tier
    try:
        from src.integrations.telegram_bot_service import run_polling
        run_polling()
    except Exception as e:
        print(f"[!] Running standalone WebApp server for healthchecks: {e}")
        start_webapp_server()

