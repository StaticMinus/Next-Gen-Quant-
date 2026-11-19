"""
Mock Invo feed server (integration harness)
===========================================
Serves the Invo REST endpoints the copier calls, so the full loop
(feed -> signal parse -> cTrader order -> exit mirror) can be exercised
without credentials.

    python scripts/mock_invo_feed.py --port 8765 --scenario open_close
    $env:INVO_API_BASE="http://127.0.0.1:8765"
    $env:INVO_REFRESH_TOKEN="mock"
    python src/integrations/invo_ctrader_copier.py --live --polls 6

Scenario "open_close": first feed poll is empty, next polls carry a verified
BTC long from @mockmaster, then a close post with a different post id.
"""

import argparse
import base64
import json
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

FEED_CALLS = {"count": 0}


def fake_jwt() -> str:
    def seg(payload: dict) -> str:
        raw = json.dumps(payload).encode()
        return base64.urlsafe_b64encode(raw).decode().rstrip("=")

    return f"{seg({'alg': 'none', 'typ': 'JWT'})}.{seg({'expires': 4102444800})}.sig"


def open_post() -> dict:
    return {
        "id": "mock-post-open-1",
        "update": {
            "ticker": "BTC",
            "name": "Bitcoin",
            "verifiedTrade": True,
            "isOpen": True,
            "baseShortId": "MOCKSHOT1",
            "directionLong": True,
            "leverage": 5,
            "entryPrice": 62000.0,
            "closingPrice": None,
            "changes": {"isAdded": True},
            "portfolio": {"id": "pf-mock", "title": "Mock Master", "winRate": 0.81},
            "owner": {"id": "u-mock", "username": "mockmaster"},
        },
    }


def close_post() -> dict:
    post = open_post()
    post["id"] = "mock-post-close-1"
    post["update"].update({"isOpen": False, "closingPrice": 63000.0})
    return post


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):  # quieter output
        print(f"[mock-invo] {fmt % args}")

    def _send(self, payload: dict, status: int = 200):
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path.endswith("/v1_0/auth/refresh_token"):
            self._send({"accessToken": fake_jwt()})
        else:
            self._send({"error": "not found"}, 404)

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        if length:
            self.rfile.read(length)

        if self.path.endswith("/v1_0/posts/get_feed"):
            FEED_CALLS["count"] += 1
            call = FEED_CALLS["count"]
            if call == 1:
                items = []            # index history
            elif call <= 3:
                items = [open_post()]
            else:
                items = [close_post()]
            print(f"[mock-invo] feed call {call} -> {[i['id'] for i in items]}")
            self._send({"items": items})
        elif self.path.endswith("/v1_0/trending/get_portfolios_pl"):
            self._send({"items": [{"portfolioId": "pf-mock", "title": "Mock Master"}]})
        else:
            self._send({"ok": True})


def main() -> int:
    parser = argparse.ArgumentParser(description="Mock Invo API for copier integration runs")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()

    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print(f"[mock-invo] listening on http://127.0.0.1:{args.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[mock-invo] stopped")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
