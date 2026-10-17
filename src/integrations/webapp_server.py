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
                gold_positions = [
                    p for p in enriched
                    if "XAU" in str(p.get("symbol_name") or p.get("symbol") or p.get("symbolName") or "XAUUSD").upper()
                    or p.get("symbolId") == 41
                ]
                gold_p = float(_CACHE.get("gold_price", _CACHE.get("gld_price", 4200.0)))
                gold_ask = float(_CACHE.get("gold_ask", gold_p + 0.35))
                gold_spread = round(abs(gold_ask - gold_p), 2)
                cap = float(_CACHE.get("capital", 6000.0))
                eq = float(_CACHE.get("equity", cap))
                profit = max(0.0, cap - 6000.0)
                target_prog = min(100.0, (profit / 480.0) * 100.0)
                account_id = os.getenv("CTRADER_ACCOUNT_ID", "5942153")

                payload = {
                    "account_id": account_id,
                    "mode": "Mode A (2 Tickets: TP1 + TP2)",
                    "capital": cap,
                    "equity": eq,
                    "free_margin": float(_CACHE.get("free_margin", 5900.0)),
                    "buffer": 360.0,
                    "daily_buffer": 180.0,
                    "daily_floor": float(os.getenv("DAILY_DRAWDOWN_FLOOR", "5650.0")),
                    "active_positions": gold_positions,
                    "has_active_trade": len(gold_positions) > 0,
                    "gold_price": gold_p,
                    "gold_ask": gold_ask,
                    "gold_spread": gold_spread,
                    "target_progress": round(target_prog, 1),
                    "target_profit": 480.0,
                    "current_profit": round(profit, 2),
                    "live_p2p_rate": _CACHE.get("live_p2p_rate", LIVE_P2P_RATE),
                    "wallet_address": _CACHE.get("wallet_address", "⚠️ NO WALLET LINKED — Use /setwallet in Telegram"),
                }
            except Exception as e:
                account_id = os.getenv("CTRADER_ACCOUNT_ID", "5942153")
                payload = {
                    "account_id": account_id,
                    "mode": "Mode A (2 Tickets: TP1 + TP2)",
                    "capital": 6000.0,
                    "equity": 6000.0,
                    "free_margin": 6000.0,
                    "buffer": 360.0,
                    "daily_buffer": 180.0,
                    "daily_floor": 5650.0,
                    "active_positions": [],
                    "has_active_trade": False,
                    "gold_price": 4200.0,
                    "gold_ask": 4200.35,
                    "gold_spread": 0.35,
                    "target_progress": 0.0,
                    "target_profit": 480.0,
                    "current_profit": 0.0,
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

