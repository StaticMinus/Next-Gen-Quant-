"""
One-command Invo refresh-token capture
======================================
Opens a real Chrome window on app.invoapp.com with a dedicated profile, attaches
over the DevTools Protocol, and watches the network. The Invo web app sends its
long-lived refresh token as `Authorization: Bearer <jwt>` on every
`/v1_0/auth/refresh_token` call, so the token can be read straight off the wire -
no DevTools, no AES decryption, no clicking through Levels.

    python scripts/capture_invo_token.py

Log in (or let the app resume your session). The script picks the JWT with the
furthest-out `expires` claim - that is the 350-day refresh token, not the
10-minute access token - validates it against the live API, and writes it to
.env. The profile lives in cache/chrome_invo_profile, so a second run usually
captures silently without any interaction.

    python scripts/capture_invo_token.py --timeout 600   # wait up to 10 minutes
    python scripts/capture_invo_token.py --port 9222     # attach to an already
                                                         # open debugging Chrome
"""

import argparse
import asyncio
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Dict, Optional
from urllib.parse import urlsplit

import requests
import websockets

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.integrations.invo_ctrader_copier import (  # noqa: E402
    InvoClient,
    set_refresh_token,
)

PROFILE_DIR = ROOT / "cache" / "chrome_invo_profile"
REFRESH_MIN_DAYS = 30
JWT_RE = re.compile(r"eyJ[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]*")
CHROME_CANDIDATES = (
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
)
# Any invoapp subdomain: the app may call the REST API on its own origin rather
# than api.invoapp.com, so match the registrable host instead of one guess.
TRACE_HOST = "invoapp"


def find_chrome() -> str:
    for candidate in CHROME_CANDIDATES:
        if candidate and Path(candidate).is_file():
            return candidate
    found = shutil.which("chrome") or shutil.which("chrome.exe")
    if found:
        return found
    raise SystemExit("Chrome not found. Install Chrome, or use --port to attach to one you "
                     "started with --remote-debugging-port.")


def token_expiry(token: str) -> int:
    """`expires` is Invo's claim; `exp` is the standard one. 0 means unreadable."""
    return int(InvoClient._decode_jwt_exp(token) or 0)


def collect_tokens(text: str) -> None:
    """Pick JWTs out of any blob of headers or JSON and keep them by expiry."""
    if not text:
        return
    for match in JWT_RE.findall(text):
        expiry = token_expiry(match)
        if expiry <= time.time():
            continue
        previous = CANDIDATES.get(match)
        if previous is None or expiry > previous:
            CANDIDATES[match] = expiry


CANDIDATES: Dict[str, int] = {}


def open_page(port: int, timeout: float = 15.0) -> Optional[str]:
    """Wait for the DevTools HTTP endpoint and return a page websocket URL."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            targets = requests.get(f"http://127.0.0.1:{port}/json/list", timeout=2).json()
        except Exception:
            time.sleep(0.3)
            continue
        pages = [t for t in targets if t.get("type") == "page" and t.get("webSocketDebuggerUrl")]
        if pages:
            # Prefer the invoapp tab if it is already there.
            for page in pages:
                if "invoapp" in (page.get("url") or ""):
                    return page["webSocketDebuggerUrl"]
            return pages[0]["webSocketDebuggerUrl"]
        time.sleep(0.3)
    return None


class Session:
    """Minimal CDP client: one reader task, command ids mapped to futures."""

    def __init__(self, ws):
        self.ws = ws
        self.pending: Dict[int, asyncio.Future] = {}
        self.events: asyncio.Queue = asyncio.Queue()
        self.next_id = 0

    async def reader(self) -> None:
        try:
            async for raw in self.ws:
                message = json.loads(raw)
                if "id" in message and message["id"] in self.pending:
                    future = self.pending.pop(message["id"])
                    if not future.done():
                        future.set_result(message)
                else:
                    await self.events.put(message)
        except Exception:
            await self.events.put({"method": "_closed"})

    async def call(self, method: str, params: Optional[dict] = None) -> dict:
        self.next_id += 1
        message_id = self.next_id
        future = asyncio.get_running_loop().create_future()
        self.pending[message_id] = future
        await self.ws.send(json.dumps({"id": message_id, "method": method,
                                       "params": params or {}}))
        return await asyncio.wait_for(future, timeout=10)


async def watch(ws_url: str, timeout: float, verbose: bool,
                url: str) -> list:
    """Attach, reload the app, and collect JWTs. Returns the API paths observed."""
    api_paths: list = []
    async with websockets.connect(ws_url, max_size=None, open_timeout=15) as ws:
        session = Session(ws)
        reader_task = asyncio.create_task(session.reader())
        await session.call("Network.enable")
        await session.call("Runtime.enable")
        # Reload under observation: anything the first paint requested is missed,
        # and the app re-issues its token traffic on every boot.
        await session.call("Page.navigate", {"url": url})
        print(f"[capture] attached - waiting for a token (timeout {int(timeout)}s)")
        if verbose:
            print("[capture] log in to Invo in the Chrome window that just opened")

        urls: Dict[str, str] = {}
        invo_requests: list = []
        auth_hosts: Dict[str, int] = {}
        deadline = time.time() + timeout
        try:
            while time.time() < deadline and not have_long_lived():
                try:
                    event = await asyncio.wait_for(session.events.get(), timeout=2.0)
                except asyncio.TimeoutError:
                    continue

                method = event.get("method")
                params = event.get("params") or {}

                if method == "_closed":
                    break

                if method == "Network.requestWillBeSent":
                    request_id = params.get("requestId")
                    request_url = params.get("request", {}).get("url", "")
                    urls[request_id] = request_url
                    parts = urlsplit(request_url)
                    if TRACE_HOST in (parts.hostname or ""):
                        invo_requests.append(f"{parts.path}"[:90])
                    headers = params.get("request", {}).get("headers", {}) or {}
                    if any(k.lower() == "authorization" for k in headers):
                        host = parts.hostname or "?"
                        auth_hosts[host] = auth_hosts.get(host, 0) + 1
                    collect_tokens(json.dumps(headers))

                elif method == "Network.requestWillBeSentExtraInfo":
                    collect_tokens(json.dumps(params.get("headers", {})))

                elif method in ("Network.responseReceived", "Network.loadingFinished"):
                    request_id = params.get("requestId")
                    if TRACE_HOST in urls.get(request_id, ""):
                        try:
                            body = await session.call("Network.getResponseBody",
                                                      {"requestId": request_id})
                            collect_tokens(body.get("result", {}).get("body", ""))
                        except Exception:
                            pass
        finally:
            reader_task.cancel()
    return {"requests": invo_requests, "auth_hosts": auth_hosts}


def best_token() -> Optional[str]:
    if not CANDIDATES:
        return None
    return max(CANDIDATES.items(), key=lambda item: item[1])[0]


def have_long_lived() -> bool:
    """True once a refresh-length JWT is in hand.

    Stopping at the first JWT seen would abort on an unrelated short-lived token
    (analytics widgets carry their own), long before the Flutter bundle boots and
    the app issues its real API calls.
    """
    cutoff = time.time() + REFRESH_MIN_DAYS * 86400
    return any(expiry > cutoff for expiry in CANDIDATES.values())


def main() -> int:
    parser = argparse.ArgumentParser(description="Capture the Invo refresh token from Chrome")
    parser.add_argument("--port", type=int, default=9222, help="DevTools port (default 9222)")
    parser.add_argument("--timeout", type=float, default=300, help="seconds to wait for login")
    parser.add_argument("--url", default="https://app.invoapp.com", help="page to open")
    parser.add_argument("--keep-open", action="store_true", help="leave Chrome running afterwards")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    chrome = subprocess.Popen(
        [
            find_chrome(),
            f"--remote-debugging-port={args.port}",
            f"--user-data-dir={PROFILE_DIR}",
            "--no-first-run",
            "--no-default-browser-check",
            args.url,
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    print(f"[capture] Chrome started (pid {chrome.pid}), profile {PROFILE_DIR}")

    ws_url = open_page(args.port)
    if not ws_url:
        print("[capture] could not reach the DevTools endpoint on port", args.port)
        print("          another Chrome may already own that port - try --port 9223")
        return 1

    api_paths: list = []
    trace: dict = {"requests": [], "auth_hosts": {}}
    try:
        trace = asyncio.run(watch(ws_url, args.timeout, args.verbose, args.url))
    except KeyboardInterrupt:
        pass
    finally:
        if not args.keep_open:
            chrome.terminate()
    api_paths = trace["requests"]

    token = best_token()
    if not token:
        print(f"\n[capture] no refresh token seen ({len(api_paths)} request(s) to "
              f"{TRACE_HOST}; authorized hosts: {trace['auth_hosts'] or 'none'}).")
        for path in api_paths[:8]:
            print(f"          POST {path}")
        print("          Log in at app.invoapp.com in the Chrome window, then run this again;")
        print("          the saved profile keeps you logged in, so the next run is instant.")
        return 1

    days = int((CANDIDATES[token] - time.time()) / 86400)
    if days < REFRESH_MIN_DAYS:
        # The 10-minute access token is on every request; the 350-day refresh token
        # only appears on /v1_0/auth/refresh_token. Seeing only the former means the
        # app never re-authenticated during the capture window.
        hours = (CANDIDATES[token] - time.time()) / 3600
        print(f"\n[capture] only short-lived token(s) seen: best has {hours:.1f}h left, "
              f"{len(CANDIDATES)} candidate(s), {len(api_paths)} request(s) to {TRACE_HOST}")
        print(f"          authorized hosts: {trace['auth_hosts'] or 'none'}")
        for path in api_paths[:6]:
            print(f"          POST {path}")
        print("          That is the access token, not the 350-day refresh token.")
        print("          Sign out and back in at app.invoapp.com so the refresh call fires,")
        print("          then run this again. The saved profile keeps you signed in.")
        return 1

    print(f"[capture] best token expires in {days} day(s) - validating against Invo")
    return set_refresh_token(token)


if __name__ == "__main__":
    raise SystemExit(main())
