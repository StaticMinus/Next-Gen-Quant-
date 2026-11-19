"""
Invo -> cTrader Copy Trader
===========================
Mirrors verified master-trader signals from Invo's social feed onto the same
FundedNext cTrader account that the Telegram copier trades.

Why this is not a straight port of invo-copy-trader:
  * invo-copy-trader executes on Hyperliquid perps with a phantom agent key.
    This machine trades cTrader CFDs, so execution goes through CTraderMCPClient.
  * Invo traders hold SOL/XRP/DOGE/HYPE which the broker does not list. Only
    signals whose coin maps to a broker symbol (BTCUSD/ETHUSD here) are executed.
  * Invo signals carry no stop loss and no take profit - the master exits manually.
    Sizing therefore comes from a synthetic ATR stop plus a fixed % of equity risk,
    and exits are mirrored when the master's close post appears in the feed.

Usage:
    python src/integrations/invo_ctrader_copier.py --self-test   # sizing dry check, no feed
    python src/integrations/invo_ctrader_copier.py --dry-run     # signals logged, no orders
    python src/integrations/invo_ctrader_copier.py --live        # real orders on the cTrader account
    python src/integrations/invo_ctrader_copier.py --discover    # rank Invo traders to follow

Environment:
    INVO_REFRESH_TOKEN   required for feed/discovery (350-day JWT from app.invoapp.com)
    INVO_SYMBOL_MAP      optional JSON override, e.g. {"BTC":"BTCUSD","ETH":"ETHUSD"}
    INVO_RISK_PCT        risk per copy in % of equity (default 0.5)
    INVO_ATR_MULT        ATR multiple used as the synthetic stop distance (default 1.5)
    INVO_MAX_NOTIONAL    max notional per copy as a multiple of equity (default 2.0)
    INVO_POLL_SECONDS    feed poll interval (default 8)
"""

import argparse
import base64
import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests
from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from src.integrations.ctrader_mcp_client import (  # noqa: E402
    CTraderMCPClient,
    RiskViolationError,
)
from src.integrations.risk_guardian import guardian  # noqa: E402
from src.utils.telegram_notifier import send_telegram_alert  # noqa: E402

load_dotenv(ROOT_DIR / ".env")

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)-7s | %(message)s")
logger = logging.getLogger("invo_ctrader_copier")


def notify(message: str) -> None:
    """Fire-and-forget Telegram alert. A messaging failure must never stop trading."""
    try:
        if not send_telegram_alert(message):
            logger.debug("Telegram alert not delivered (bot token / chat id unset?)")
    except Exception as exc:
        logger.debug(f"Telegram alert failed: {exc}")


def account_label() -> str:
    return os.getenv("CTRADER_ACCOUNT_ID", "?")

INVO_BASE = os.getenv("INVO_API_BASE", "https://api.invoapp.com")
INVO_APP_VERSION = "0.0.75"
STATE_FILE = Path(os.getenv("INVO_STATE_FILE", str(ROOT_DIR / "cache" / "invo_copier_state.json")))
REHEARSAL_STATE = ROOT_DIR / "cache" / "invo_copier_rehearsal_state.json"

# Broker listing verified via get_symbols(): BTCUSD, BTCEUR, ETHUSD, ETHEUR only.
DEFAULT_SYMBOL_MAP = {"BTC": "BTCUSD", "ETH": "ETHUSD"}

RISK_PCT = float(os.getenv("INVO_RISK_PCT", "0.5"))
ATR_MULT = float(os.getenv("INVO_ATR_MULT", "1.5"))
MAX_NOTIONAL_MULT = float(os.getenv("INVO_MAX_NOTIONAL", "2.0"))
POLL_SECONDS = float(os.getenv("INVO_POLL_SECONDS", "8"))
# Which Invo feeds to watch. "following" only surfaces traders you follow; "trending"
# is platform-wide and keeps the copier fed when your own masters go quiet.
FEEDS = [name.strip() for name in os.getenv("INVO_FEEDS", "following").split(",")
         if name.strip()]
# Comma-separated Invo owner ids. When set, only these masters are mirrored - the
# wide feed then just supplies coverage, so quality stays a deliberate choice.
ALLOWED_TRADERS = {uid.strip() for uid in os.getenv("INVO_ALLOWED_TRADERS", "").split(",")
                   if uid.strip()}
MAX_POSITIONS = int(os.getenv("INVO_MAX_POSITIONS", "2"))  # engine budget, not account-wide
# How far back to page each feed per poll. One page of 20 is enough only while posts
# trickle; a burst (or a gap between cloud cycles) would otherwise push a master's
# entry past the window and that trade would never be copied.
FEED_PAGES = max(1, int(os.getenv("INVO_FEED_PAGES", "3")))
# Entries older than this are history, not signals. Invo's own `isOpen`/`closedAt`
# fields cannot tell us whether a position is still live, so age is the guard against
# filling a master's trade long after they took it (or after they had already left).
MAX_SIGNAL_AGE_MIN = float(os.getenv("INVO_MAX_SIGNAL_AGE_MIN", "20"))
# The cloud runner chains a fresh process every ~10 minutes. An unconditional startup
# message would hit the operator's phone ~144 times a day, which trains them to ignore
# the alerts that actually matter, so "online" only fires after a real outage.
HEARTBEAT_QUIET_MIN = float(os.getenv("INVO_HEARTBEAT_QUIET_MIN", "60"))
STOP_BOUNDS = (0.0025, 0.02)  # synthetic stop distance clamped to 0.25% .. 2% of price
MIN_LOTS = 0.01              # 0.01 BTC / 0.01 ETH granularity
MAX_SEEN_POSTS = 500
RECONCILE_EVERY = 12         # polls between realized-PnL reconciliations (~96s)
ADOPT_EVERY = 30             # polls between broker-state reconciliations (~4 min)


# --------------------------------------------------------------------------- #
# Invo REST client (Python port of invo-client.ts)
# --------------------------------------------------------------------------- #

class InvoClient:
    def __init__(self, refresh_token: Optional[str] = None):
        self.refresh_token = (refresh_token or os.getenv("INVO_REFRESH_TOKEN", "")).strip()
        self.token = os.getenv("INVO_TOKEN", "").strip()
        self.session = requests.Session()

    @staticmethod
    def _decode_jwt_exp(token: str) -> Optional[int]:
        try:
            payload = token.split(".")[1]
            payload += "=" * (-len(payload) % 4)
            claims = json.loads(base64.urlsafe_b64decode(payload))
            return int(claims.get("expires") or claims.get("exp") or 0)
        except Exception:
            return None

    def ensure_token(self) -> None:
        if self.token:
            exp = self._decode_jwt_exp(self.token.replace("Bearer ", ""))
            if exp and exp - time.time() > 30:
                return
        if not self.refresh_token:
            raise RuntimeError("INVO_REFRESH_TOKEN not set - extract it from app.invoapp.com local storage")
        resp = self.session.get(
            f"{INVO_BASE}/v1_0/auth/refresh_token",
            headers={
                "Authorization": f"Bearer {self.refresh_token}",
                "x-app-version": INVO_APP_VERSION,
                "x-platform": "web",
            },
            timeout=20,
        )
        if resp.status_code != 200:
            raise RuntimeError(f"Invo refresh failed HTTP {resp.status_code}: {resp.text[:200]}")
        self.token = resp.json().get("accessToken", "")
        if not self.token:
            raise RuntimeError("Invo refresh returned no accessToken")

    def _headers(self) -> Dict[str, str]:
        token = self.token if self.token.startswith("Bearer ") else f"Bearer {self.token}"
        return {
            "Authorization": token,
            "Content-Type": "application/json",
            "x-app-version": INVO_APP_VERSION,
            "x-platform": "web",
        }

    @staticmethod
    def _parse_body(resp: requests.Response) -> Any:
        text = resp.text
        try:
            return resp.json()
        except Exception:
            try:
                return json.loads(base64.b64decode(text + "=" * (-len(text) % 4)))
            except Exception:
                return text

    def post(self, path: str, body: Dict[str, Any]) -> Any:
        self.ensure_token()
        resp = self.session.post(f"{INVO_BASE}{path}", headers=self._headers(), json=body, timeout=25)
        if resp.status_code == 401:
            self.token = ""
            self.ensure_token()
            resp = self.session.post(f"{INVO_BASE}{path}", headers=self._headers(), json=body, timeout=25)
        data = self._parse_body(resp)
        if resp.status_code >= 400:
            raise RuntimeError(f"Invo {path} {resp.status_code}: {str(data)[:300]}")
        return data

    def get_feed(self, filter_name: str = "following", item_limit: int = 20,
                 last_post_id: Optional[str] = None) -> List[dict]:
        data = self.post(
            "/v1_0/posts/get_feed",
            {"filter": {"filter": filter_name, "assetTypes": []},
             "params": {"lastPostId": last_post_id, "itemLimit": item_limit}},
        )
        if isinstance(data, dict):
            return data.get("items") or []
        return []

    def discover_traders(self, page: int = 1, size: int = 50,
                         filter_name: str = "trending") -> List[dict]:
        data = self.post(
            "/v1_0/trending/get_portfolios_pl",
            {"filter": filter_name, "params": {"page": page, "size": size}},
        )
        if isinstance(data, dict):
            return data.get("items") or data.get("portfolios") or []
        return []

    def follow_user(self, user_id: str) -> Any:
        return self.post("/v1_0/users/follow", {"objectId": user_id})


# --------------------------------------------------------------------------- #
# Trader discovery
# --------------------------------------------------------------------------- #

def _first_value(row: Dict[str, Any], *paths: str, default: Any = None) -> Any:
    """Walk dotted paths through Invo's loosely-typed payloads.

    The discovery response shape is undocumented and has changed between app
    versions, so every field is probed at several plausible locations rather
    than assuming one layout.
    """
    for path in paths:
        node: Any = row
        for part in path.split("."):
            node = node.get(part) if isinstance(node, dict) else None
            if node is None:
                break
        if node not in (None, "", [], {}):
            return node
    return default


def _as_number(value: Any) -> Optional[float]:
    try:
        return float(str(value).replace("%", "").replace(",", "").strip())
    except (TypeError, ValueError):
        return None


def trader_rows(traders: List[dict], include_liquidated: bool = False) -> List[Dict[str, Any]]:
    """Normalise the discovery payload into something an operator can act on.

    Ranked by whether the trader currently holds a symbol this broker can mirror:
    a 300% record on SOL is worthless here because BTC and ETH are the only crypto
    symbols the account trades.
    """
    rows: List[Dict[str, Any]] = []
    for row in traders:
        if not isinstance(row, dict):
            continue
        if row.get("liquidated") and not include_liquidated:
            continue
        open_trades = row.get("openTrades") or {}
        assets = {str(asset).upper() for asset in (open_trades.get("assets") or [])}
        rows.append({
            "user_id": _first_value(row, "ownerId", "owner.id", "portfolio.ownerId",
                                    "userId", "id"),
            "trader": _first_value(row, "owner.username", "username", "user.username",
                                   "owner.name", "name", default="?"),
            "portfolio": _first_value(row, "title", "portfolio.title", "portfolioTitle",
                                      default=""),
            "win_rate": _as_number(_first_value(row, "winRate", "portfolio.winRate",
                                                "portfolio.winrate")),
            "pnl": _as_number(_first_value(row, "percentChange", "plSnapshot", "pnl",
                                           "portfolio.pnl", "totalPnl", "roi")),
            "open_count": int(_as_number(_first_value(open_trades, "count")) or 0),
            "copyable": sorted(assets & set(DEFAULT_SYMBOL_MAP)),
            "followers": int(_as_number(_first_value(row, "followerCount")) or 0),
            "liquidated": bool(row.get("liquidated")),
        })
    rows.sort(key=lambda r: (not r["copyable"], r["pnl"] is None, -(r["pnl"] or 0.0)))
    return rows


def format_traders(rows: List[Dict[str, Any]], limit: int = 25) -> str:
    if not rows:
        return "no traders returned"
    lines = [f"{'#':>3}  {'trader':<18} {'portfolio':<20} {'win':>7} {'pnl%':>9} "
             f"{'copies':>8} {'fol':>7}  user id"]
    for index, row in enumerate(rows[:limit], start=1):
        rate = row["win_rate"]
        if rate is None:
            win = "-"
        else:
            win = f"{rate * 100:.1f}%" if rate <= 1 else f"{rate:.1f}%"
        pnl = "-" if row["pnl"] is None else f"{row['pnl']:,.1f}"
        copies = ",".join(row["copyable"]) or "-"
        lines.append(f"{index:>3}  {'@' + str(row['trader'])[:17]:<18} "
                     f"{str(row['portfolio'])[:19]:<20} {win:>7} {pnl:>9} "
                     f"{copies:>8} {row['followers']:>7}  {row['user_id'] or '?'}")
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Signal / sizing helpers
# --------------------------------------------------------------------------- #

def write_env_value(env_path: Path, key: str, value: str) -> None:
    """Set or replace a single KEY=value line without touching the rest of the file."""
    lines = env_path.read_text(encoding="utf-8").splitlines() if env_path.exists() else []
    replaced = False
    out: List[str] = []
    for line in lines:
        if line.strip().startswith(f"{key}="):
            out.append(f"{key}={value}")
            replaced = True
        else:
            out.append(line)
    if not replaced:
        out.append(f"{key}={value}")
    env_path.parent.mkdir(parents=True, exist_ok=True)
    env_path.write_text("\n".join(out) + "\n", encoding="utf-8")


def set_refresh_token(token: str, env_path: Optional[Path] = None,
                      client: Optional["InvoClient"] = None) -> int:
    """Validate an Invo refresh token against the live API, then persist it."""
    token = (token or "").strip().removeprefix("Bearer ").strip()
    expires_at = InvoClient._decode_jwt_exp(token)
    if not expires_at:
        print("not a JWT - expected three dot-separated segments")
        return 1
    remaining_days = int((expires_at - time.time()) / 86400)
    if remaining_days <= 0:
        print("that token has already expired - re-extract it from the browser")
        return 1

    probe = client or InvoClient(refresh_token=token)
    probe.refresh_token = token
    probe.token = ""
    try:
        probe.ensure_token()
        posts = probe.get_feed("following", 3)
    except Exception as exc:
        print(f"Invo rejected the token: {exc}")
        return 1

    target = env_path or (ROOT_DIR / ".env")
    write_env_value(target, "INVO_REFRESH_TOKEN", token)
    print(f"saved INVO_REFRESH_TOKEN to {target.name} - valid {remaining_days} day(s), "
          f"{len(posts)} post(s) visible on your following feed")
    return 0


def symbol_map() -> Dict[str, str]:
    mapping = dict(DEFAULT_SYMBOL_MAP)
    raw = os.getenv("INVO_SYMBOL_MAP", "").strip()
    if raw:
        try:
            mapping.update({str(k).upper(): str(v).upper() for k, v in json.loads(raw).items()})
        except Exception:
            logger.warning("INVO_SYMBOL_MAP is not valid JSON - using defaults")
    return mapping


def average_true_range(df, period: int = 14) -> Optional[float]:
    if df is None or len(df) < period + 1:
        return None
    high, low, close = df["high"], df["low"], df["close"]
    prev_close = close.shift(1)
    tr = (high - low).abs()
    tr = tr.combine((high - prev_close).abs(), max)
    tr = tr.combine((low - prev_close).abs(), max)
    value = float(tr.rolling(period).mean().iloc[-1])
    return value if value > 0 else None


def synthetic_stop_distance(price: float, atr: Optional[float]) -> float:
    """ATR-based stop, clamped so a quiet tape cannot produce absurd position sizes."""
    floor = price * STOP_BOUNDS[0]
    ceiling = price * STOP_BOUNDS[1]
    if atr is None:
        return price * 0.0075
    return min(ceiling, max(floor, atr * ATR_MULT))


def compute_units(equity: float, price: float, stop_distance: float, risk_pct: float) -> float:
    """Fixed-fractional sizing: risk_usd / stop_distance, then capped by notional."""
    risk_usd = equity * (risk_pct / 100.0)
    units = risk_usd / max(stop_distance, 1e-9)
    max_units = (equity * MAX_NOTIONAL_MULT) / max(price, 1e-9)
    return round(min(units, max_units), 2)


def parse_min_volume(payload: Any) -> Optional[float]:
    """Broker rejects sub-minimum sizes with 'minimum allowed volume = X' (base units)."""
    text = str(payload)
    marker = "minimum allowed volume"
    if marker not in text.lower():
        return None
    try:
        tail = text.lower().split(marker, 1)[1]
        digits = ""
        for ch in tail:
            if ch.isdigit() or ch == ".":
                digits += ch
            elif digits:
                break
        return float(digits) if digits else None
    except Exception:
        return None


# --------------------------------------------------------------------------- #
# Copier
# --------------------------------------------------------------------------- #

class InvoCtaderCopier:
    def __init__(self, dry_run: bool = True, ctrader: Optional[CTraderMCPClient] = None,
                 state_file: Optional[Path] = None, risk_pct: float = RISK_PCT,
                 max_positions: Optional[int] = None,
                 feeds: Optional[List[str]] = None,
                 allowed_traders: Optional[set] = None):
        self.dry_run = dry_run
        self.ctrader = ctrader or CTraderMCPClient()
        self.state_file = state_file or STATE_FILE
        self.risk_pct = risk_pct
        self.max_positions = max_positions or MAX_POSITIONS
        self.feeds = feeds or FEEDS
        self.allowed = ALLOWED_TRADERS if allowed_traders is None else set(allowed_traders)
        self.symbols = symbol_map()
        self.invo = InvoClient()  # reused so the 10-minute access token survives across polls
        self.state = self._load_state()
        self.seen_posts: set = set(self.state.get("seen_posts", []))
        # Dry-run plans are tracked in memory only: writing them to the shared state
        # file would make a later --live run believe slots are already taken.
        self._dry_planned: set = set()
        self._first_poll = True

    # -- state ------------------------------------------------------------- #

    def _load_state(self) -> Dict[str, Any]:
        if self.state_file.exists():
            try:
                with open(self.state_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                data.setdefault("copies", {})
                data.setdefault("seen_posts", [])
                data.setdefault("pending_closes", [])
                return data
            except Exception as exc:
                logger.warning(f"State file unreadable ({exc}) - starting fresh")
        return {"copies": {}, "seen_posts": [], "pending_closes": [], "updated_at": None}

    def _save_state(self) -> None:
        self.state["seen_posts"] = list(self.seen_posts)[-MAX_SEEN_POSTS:]
        self.state["updated_at"] = datetime.now(timezone.utc).isoformat()
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        with open(self.state_file, "w", encoding="utf-8") as f:
            json.dump(self.state, f, indent=2)

    def _open_copy_for_symbol(self, symbol: str) -> Optional[Dict[str, Any]]:
        for copy in self.state["copies"].values():
            if copy.get("symbol") == symbol and not copy.get("closed"):
                return copy
        return None

    def _symbol_names(self) -> Dict[str, str]:
        try:
            return {str(sid): name.upper()
                    for name, sid in self.ctrader.get_symbol_map().items()}
        except Exception as exc:
            logger.debug(f"Symbol map unavailable: {exc}")
            return {}

    def adopt_broker_positions(self) -> int:
        """Reconcile tracked copies against what the broker actually holds.

        Cloud runners are ephemeral, so the state file can disappear between cycles.
        Without this, a lost state file would re-open a symbol that is already held
        (doubling risk) or keep believing a closed trade still eats a budget slot.
        Adopting untracked positions also means a master's exit still flattens a
        trade this process did not personally open.
        """
        fetch = getattr(self.ctrader, "get_positions_strict", None)
        if fetch is None or self.dry_run:
            return 0
        positions = fetch()
        if positions is None:
            logger.warning("Broker reconciliation skipped: position telemetry offline")
            return 0

        live: Dict[int, Dict[str, Any]] = {}
        for pos in positions:
            try:
                live[int(pos.get("positionId") or 0)] = pos
            except (TypeError, ValueError):
                continue

        changed = 0
        for copy in self.state["copies"].values():
            if copy.get("closed") or not copy.get("positionId"):
                continue
            if int(copy["positionId"]) in live:
                continue
            copy["closed"] = True
            copy["closedAt"] = copy.get("closedAt") or datetime.now(timezone.utc).isoformat()
            copy["closeReason"] = "gone from broker"
            changed += 1
            logger.warning(f"ADOPT {copy.get('symbol')} #{copy['positionId']} is no longer "
                           f"open at the broker - releasing its slot")

        names = self._symbol_names()
        managed = {str(symbol).upper() for symbol in self.symbols.values()}
        tracked = {int(c["positionId"]) for c in self.state["copies"].values()
                   if c.get("positionId") and not c.get("closed")}
        for position_id, pos in live.items():
            if position_id in tracked:
                continue
            symbol = str(pos.get("symbolName")
                         or names.get(str(pos.get("symbolId")), "")).upper()
            if symbol not in managed:
                continue
            self.state["copies"][f"adopted-{position_id}"] = {
                "symbol": symbol,
                "side": pos.get("tradeSide") or "BUY",
                "units": pos.get("volume"),
                "positionId": position_id,
                "stop": pos.get("stopLoss"),
                "closed": False,
                "trader": "adopted",
                "adopted": True,
                "openedAt": datetime.now(timezone.utc).isoformat(),
            }
            changed += 1
            logger.warning(f"ADOPT untracked broker position #{position_id} {symbol} - "
                           f"now managed so its exit is mirrored")
        if changed:
            self._save_state()
        return changed

    # -- market data ------------------------------------------------------- #

    def _account(self) -> Dict[str, float]:
        bal = self.ctrader.get_balance() or {}
        return {
            "balance": float(bal.get("balance") or 0.0),
            "equity": float(bal.get("equity") or bal.get("balance") or 0.0),
            "free_margin": float(bal.get("freeMargin") or 0.0),
        }

    def _atr(self, symbol: str) -> Optional[float]:
        try:
            bars = self.ctrader.get_trendbars_dataframe(symbol, period="M_15", count=30)
            return average_true_range(bars, 14)
        except Exception as exc:
            logger.debug(f"Trendbars unavailable for {symbol}: {exc}")
            return None

    # -- protection -------------------------------------------------------- #

    def _position(self, position_id: int) -> Optional[Dict[str, Any]]:
        fetch = getattr(self.ctrader, "get_positions_strict", None)
        if fetch is None:
            return None
        for pos in fetch() or []:
            try:
                if int(pos.get("positionId") or 0) == position_id:
                    return pos
            except (TypeError, ValueError):
                continue
        return None

    def _ensure_protection(self, position_id: int, stop_price: float, symbol: str) -> bool:
        """Fail closed: a copy without a broker-side stop must not stay open."""
        if not hasattr(self.ctrader, "get_positions_strict"):
            return True  # no telemetry in this harness (unit tests / dry harness)
        for attempt in range(3):
            fetch = getattr(self.ctrader, "get_positions_strict", None)
            positions = fetch() if fetch else None
            if positions is None:
                logger.warning(f"Protection unverified for #{position_id}: position telemetry offline")
                return True
            for pos in positions:
                if int(pos.get("positionId") or 0) != position_id:
                    continue
                if float(pos.get("stopLoss") or 0) > 0:
                    return True
            if attempt == 0:
                try:
                    self.ctrader.amend_position(int(position_id), stop_loss=stop_price, symbol=symbol)
                except Exception as exc:
                    logger.warning(f"SL amend retry failed for #{position_id}: {exc}")
            time.sleep(0.4)
        return False

    # -- entry ------------------------------------------------------------- #

    def handle_open(self, signal: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        shot = signal["mimicMeta"].get("baseShortId", "")
        coin = str(signal["trade"]["coin"]).upper()
        side = "BUY" if signal["trade"]["side"] == "long" else "SELL"
        trader = signal["owner"].get("username") or signal["owner"].get("id")

        if shot and (shot in self.state["copies"] or shot in self._dry_planned):
            return None
        symbol = self.symbols.get(coin)
        if not symbol:
            logger.info(f"SKIP {coin} {side} @{trader}: no broker symbol (broker lists "
                        f"{', '.join(sorted(set(self.symbols.values())))})")
            return None
        if self._open_copy_for_symbol(symbol):
            logger.info(f"SKIP {symbol} {side} @{trader}: already holding a copied {symbol} position")
            return None
        if guardian.state.get("trading_halted"):
            logger.warning(f"SKIP {symbol} {side}: RiskGuardian halted ({guardian.state.get('halt_reason')})")
            notify(f"<b>MISSED {symbol} {side}</b>\n"
                   f"master @{trader} posted a trade but new copies are halted "
                   f"({guardian.state.get('halt_reason')}).")
            return None
        held = [c for c in self.state["copies"].values() if not c.get("closed")]
        in_use = len(held) + (len(self._dry_planned) if self.dry_run else 0)
        if in_use >= self.max_positions:
            logger.info(f"SKIP {symbol} {side}: copy budget used "
                        f"({in_use}/{self.max_positions}) - Telegram/other positions keep their slots")
            notify(f"<b>MISSED {symbol} {side}</b>\n"
                   f"master @{trader} posted, but the copy budget is full "
                   f"({in_use}/{self.max_positions}). Raise INVO_MAX_POSITIONS to take more.")
            return None

        spot = self.ctrader.get_spot_price(symbol)
        if not spot:
            logger.warning(f"SKIP {symbol}: no live quote")
            return None
        price = float(spot["ask"] if side == "BUY" else spot["bid"])

        acct = self._account()
        if acct["equity"] <= 0:
            logger.warning("SKIP: account equity unavailable")
            return None
        risk = guardian.evaluate_risk(acct["equity"], acct["balance"])
        if risk["is_breach"]:
            logger.warning(f"SKIP {symbol}: drawdown breach, buffer left ${risk['buffer_left']:.2f}")
            return None

        stop_distance = synthetic_stop_distance(price, self._atr(symbol))
        units = compute_units(acct["equity"], price, stop_distance, self.risk_pct)
        if units < MIN_LOTS:
            logger.info(f"SKIP {symbol}: computed size {units} below {MIN_LOTS} minimum")
            return None

        stop_price = round(price - stop_distance if side == "BUY" else price + stop_distance,
                           self.ctrader.get_symbol_digits(symbol))
        risk_usd = units * stop_distance
        plan = {
            "symbol": symbol, "side": side, "units": units, "entry": price,
            "stop": stop_price, "risk_usd": round(risk_usd, 2),
            "notional": round(units * price, 2), "trader": trader,
        }
        logger.info(
            f"{'DRY ' if self.dry_run else ''}OPEN {symbol} {side} {units} units "
            f"(~${units * price:,.0f} notional, ${risk_usd:,.2f} risk) SL {stop_price} "
            f"@ equity ${acct['equity']:,.2f} | trader @{trader}"
        )

        if self.dry_run:
            self._dry_planned.add(shot or f"{symbol}-dry")
            return plan

        comment = f"InvoCopy:{coin}:{(shot or 'na')[:40]}"
        result = None
        try:
            result = self.ctrader.place_market_order(
                symbol=symbol, side=side, volume_lots=units,
                stop_loss_price=stop_price, comment=comment,
            )
        except RiskViolationError as exc:
            logger.warning(f"ORDER REJECTED {symbol} {side}: {exc}")
            return None

        min_vol = parse_min_volume(result)
        if min_vol and min_vol > units:
            if min_vol * price > acct["equity"] * MAX_NOTIONAL_MULT:
                logger.warning(f"ORDER ABORTED {symbol}: broker minimum {min_vol} units "
                               f"exceeds notional cap")
                return None
            logger.info(f"Retrying {symbol} at broker minimum volume {min_vol}")
            try:
                result = self.ctrader.place_market_order(
                    symbol=symbol, side=side, volume_lots=min_vol,
                    stop_loss_price=stop_price, comment=comment,
                )
            except RiskViolationError as exc:
                logger.warning(f"ORDER REJECTED on minimum-size retry: {exc}")
                return None
            units, risk_usd = min_vol, min_vol * stop_distance

        position_id = None
        if isinstance(result, dict):
            position_id = result.get("positionId") or (
                result.get("position", {}).get("positionId") if isinstance(result.get("position"), dict) else None
            )
            if not position_id and isinstance(result.get("amended_protection"), dict):
                position_id = result["amended_protection"].get("positionId")

        if not position_id:
            logger.error(f"ORDER FAILED {symbol} {side}: broker payload {str(result)[:300]}")
            return None

        # A naked leveraged position is the one failure mode a prop account cannot survive.
        if not self._ensure_protection(int(position_id), stop_price, symbol):
            logger.error(f"UNPROTECTED position #{position_id} on {symbol} - flattening immediately")
            notify(f"<b>UNPROTECTED {symbol} FLATTENED</b>\n"
                   f"No broker stop could be confirmed on position #{position_id}, "
                   f"so the copy was closed immediately.")
            self.ctrader.close_position(int(position_id))
            return None

        record = {
            **plan, "units": units, "risk_usd": round(risk_usd, 2),
            "positionId": int(position_id), "closed": False,
            "postId": signal.get("postId"), "portfolioId": signal["mimicMeta"].get("portfolioId"),
            "openedAt": datetime.now(timezone.utc).isoformat(),
        }
        self.state["copies"][shot or f"{symbol}-{position_id}"] = record
        self._save_state()
        logger.info(f"COPIED {symbol} {side} -> position #{position_id}")
        notify(f"<b>COPIED {symbol} {side}</b>\n"
               f"master @{trader}\n"
               f"{units} units (~${units * price:,.0f}) | risk ${risk_usd:,.2f}\n"
               f"stop {stop_price} | position #{position_id}\n"
               f"equity ${acct['equity']:,.2f} | account {account_label()}")
        return record

    # -- exit -------------------------------------------------------------- #

    def handle_close(self, signal: Dict[str, Any]) -> None:
        shot = signal["mimicMeta"].get("baseShortId", "")
        copy = self.state["copies"].get(shot)
        if not copy:
            # Close posts do not always echo baseShortId. Only one copy per symbol
            # can be open at a time, so the symbol is a safe fallback key.
            symbol = self.symbols.get(str(signal["trade"].get("coin", "")).upper())
            for key, candidate in self.state["copies"].items():
                if not candidate.get("closed") and candidate.get("symbol") == symbol:
                    copy, shot = candidate, key
                    logger.info(f"Close post had no baseShortId - matched open {symbol} copy")
                    break
        if not copy or copy.get("closed"):
            logger.info(f"CLOSE signal for {shot or 'unknown'} ignored: not a copied trade")
            return
        logger.info(f"{'DRY ' if self.dry_run else ''}CLOSE {copy['symbol']} position "
                    f"#{copy.get('positionId')} (trader @{copy.get('trader')} exited)")
        if self._close_copy(shot, copy, reason="master exit"):
            notify(f"<b>CLOSED {copy['symbol']}</b>\n"
                   f"master @{copy.get('trader')} exited\n"
                   f"position #{copy.get('positionId')} | realized P&amp;L follows on reconcile")

    def _close_copy(self, shot: str, copy: Dict[str, Any], reason: str) -> bool:
        """Close a copied position, queuing a retry when the broker refuses the request."""
        position_id = copy.get("positionId")
        if not position_id:
            return False
        if self.dry_run:
            copy["closed"] = True
            copy["closedAt"] = datetime.now(timezone.utc).isoformat()
            self._save_state()
            return True
        result = self.ctrader.close_position(int(position_id))
        pending = self.state.setdefault("pending_closes", [])
        if result is None:
            # Market closed, weekend, or transient broker error - keep trying, never orphan it.
            logger.error(f"CLOSE REJECTED for #{position_id} ({reason}) - queued for retry")
            if shot not in pending:
                pending.append(shot)
                self._save_state()
            return False
        copy["closed"] = True
        copy["closedAt"] = datetime.now(timezone.utc).isoformat()
        copy["closeResult"] = str(result)[:300]
        if shot in pending:
            pending.remove(shot)
        self._save_state()
        return True

    def retry_pending_closes(self) -> int:
        """Re-attempt every exit the broker refused on a previous attempt."""
        pending = list(self.state.get("pending_closes", []))
        if not pending or self.dry_run:
            return 0
        closed = 0
        for shot in pending:
            copy = self.state["copies"].get(shot)
            if not copy or copy.get("closed"):
                self.state["pending_closes"].remove(shot)
                self._save_state()
                continue
            logger.info(f"Retrying close for {copy.get('symbol')} #{copy.get('positionId')}")
            if self._close_copy(shot, copy, reason="retry"):
                closed += 1
        return closed

    # -- polling ----------------------------------------------------------- #

    @staticmethod
    def _classify(update: Dict[str, Any]) -> Optional[str]:
        """What did this post actually do: open, increase, or close?

        Invo's `changes` object is the post's own diff - the master's action. By
        contrast `isOpen`, `closingPrice` and `closedAt` are the position's live
        snapshot. Reading the snapshot as an event inverts history: a post that
        opened a trade still reads `isOpen=False` once that trade later closed, so
        every entry looked like an exit and no trade was ever copied. Equally, a
        close whose `closingPrice` is missing was dropped as an "increase", leaving
        our copy to ride to its stop after the master had walked away.
        """
        changes = update.get("changes") or {}
        if "isAdded" in changes:
            return "open" if changes.get("isAdded") else "close"
        if changes.get("isOpen") is True:
            return "open"
        if changes.get("isOpen") is False:
            return "close"
        if changes.get("simIncrease"):
            return "increase"
        if update.get("closedAt") or update.get("reasonClosed"):
            return "close"
        if update.get("isOpen") is True:
            return "open"
        # No diff and a shut position: a stale snapshot, not an event worth acting on.
        return None

    @staticmethod
    def _post_age_minutes(post: Dict[str, Any]) -> Optional[float]:
        """Minutes since the master published this post."""
        raw = post.get("createdAt")
        if not raw:
            return None
        try:
            when = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        except ValueError:
            return None
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - when).total_seconds() / 60.0

    def handle_post(self, post: Dict[str, Any]) -> Optional[str]:
        update = post.get("update")
        if not isinstance(update, dict) or not update.get("ticker"):
            return None
        if not update.get("verifiedTrade"):
            return None

        action = self._classify(update)
        if action is None:
            return None
        if action == "increase":
            logger.info(f"Increase signal on {update.get('ticker')} ignored (no pyramiding)")
            return action
        if action == "open":
            # `update.isOpen` and `closedAt` are unreliable: they read False and even a
            # timestamp *earlier* than the post on entries that are minutes old. Age is
            # the one signal we can trust, and a copy trader must anyway act only on
            # fresh entries - filling a 20-minute-old call just pays a worse price.
            age_min = self._post_age_minutes(post)
            if age_min is not None and age_min > MAX_SIGNAL_AGE_MIN:
                logger.info(f"Stale open on {update.get('ticker')} ignored - posted "
                            f"{age_min:.0f} min ago (limit {MAX_SIGNAL_AGE_MIN:.0f})")
                return "stale"

        signal = {
            "postId": post.get("id"),
            "action": action,
            "owner": update.get("owner") or post.get("owner") or {},
            "trade": {
                "coin": update.get("ticker"),
                "side": "long" if update.get("directionLong") else "short",
                "leverage": update.get("leverage"),
                "entryPrice": update.get("entryPrice"),
                "closingPrice": update.get("closingPrice"),
                "entrySize": update.get("entrySize"),
            },
            "mimicMeta": {
                "portfolioId": (update.get("portfolio") or {}).get("id"),
                "baseShortId": update.get("baseShortId"),
            },
        }
        if action == "open":
            self.handle_open(signal)
        else:
            self.handle_close(signal)
        return action

    def _release_stale_daily_halt(self) -> None:
        """Drop yesterday's 2-strike halt so a bad day does not stop copying forever.

        RiskGuardian only auto-resumes a daily halt while its `decommissioned` flag is
        false, and that flag belongs to the retired equity engine - so without this the
        copier would inherit a permanent halt after the first losing day. Only the
        daily 2-strike reason is released; a manual kill switch is left alone.
        """
        if not guardian.state.get("trading_halted"):
            return
        if "Daily 2-Strike" not in str(guardian.state.get("halt_reason") or ""):
            return
        halted_on = str(guardian.state.get("halt_time") or "")[:10]
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if halted_on and halted_on < today:
            guardian.state["trading_halted"] = False
            guardian.state["halt_reason"] = None
            guardian.save_state()
            logger.warning(f"Released stale 2-strike halt from {halted_on} - new trading day")

    def poll_once(self) -> int:
        self._release_stale_daily_halt()
        self.retry_pending_closes()
        handled = 0
        saw_any = False
        for feed_name in self.feeds:
            try:
                posts = self._feed_pages(feed_name)
            except Exception as exc:
                # Invo 500s on filter names it does not know, so one bad filter in
                # INVO_FEEDS must not take the whole poll down with it.
                logger.error(f"Feed '{feed_name}' failed: {str(exc)[:160]}")
                continue
            saw_any = saw_any or bool(posts)
            handled += self._consume_feed(posts)
        if self._first_poll:
            logger.info(f"Indexed {len(self.seen_posts)} existing feed posts "
                        f"from {self.feeds} - waiting for new signals")
            if not saw_any:
                logger.warning("Every watched feed is empty - nothing is being followed yet. "
                               "Run --discover, then --follow <user id>")
            self._first_poll = False
        self._save_state()
        return handled

    def _allowed_post(self, post: Dict[str, Any]) -> bool:
        """Allowlist gate. An exit for a position we already hold always passes."""
        if not self.allowed:
            return True
        update = post.get("update") or {}
        # Trending posts carry the owner at post level rather than under the update,
        # so reading only update.owner silently dropped allowlisted masters.
        owner = update.get("owner") or post.get("owner") or {}
        if owner.get("id") in self.allowed:
            return True
        # Dropping a trader from the allowlist must not strand their open copy.
        tracked = self.state["copies"].get(update.get("baseShortId") or "", {})
        return bool(tracked and not tracked.get("closed"))

    def _feed_pages(self, feed_name: str) -> List[dict]:
        """Page a feed backwards until a page holds nothing we have not seen.

        Stops early so steady-state polling stays cheap, while a restart or a burst
        still reaches every entry posted since the last successful poll.
        """
        posts: List[dict] = []
        cursor: Optional[str] = None
        for _ in range(FEED_PAGES):
            page = self.invo.get_feed(feed_name, 20, last_post_id=cursor)
            if not page:
                break
            posts.extend(page)
            if all(post.get("id") in self.seen_posts for post in page if post.get("id")):
                break  # the whole page is known history - older pages cannot be new
            cursor = page[-1].get("id")
        return posts

    def _consume_feed(self, posts: List[dict]) -> int:
        handled = 0
        for post in posts:
            post_id = post.get("id")
            if not post_id or post_id in self.seen_posts:
                continue
            self.seen_posts.add(post_id)
            if not self._allowed_post(post):
                continue
            if self._first_poll:
                # Index history instead of replaying it - but never ignore an exit for a
                # position we still hold, or a restart would strand the trade open.
                shot = (post.get("update") or {}).get("baseShortId")
                tracked = self.state["copies"].get(shot or "", {})
                if not tracked or tracked.get("closed"):
                    continue
            try:
                if self.handle_post(post):
                    handled += 1
            except Exception as exc:
                logger.error(f"Signal handling failed for post {post_id}: {exc}")
        return handled

    def run(self, max_polls: Optional[int] = None,
            max_minutes: Optional[float] = None) -> None:
        logger.info(f"Invo copier started ({'DRY-RUN' if self.dry_run else 'LIVE'}) "
                    f"account #{account_label()} "
                    f"feeds={self.feeds} symbols={self.symbols} "
                    f"allowlist={len(self.allowed) or 'any'}"
                    f" risk={self.risk_pct}% poll={POLL_SECONDS}s")
        acct = self._account()
        # Logged at every cycle start: the token decides the account, so this line is the
        # only proof in the cloud log that orders land on the intended demo account.
        logger.info(f"Broker account #{account_label()} balance ${acct['balance']:,.2f} "
                    f"equity ${acct['equity']:,.2f} free margin ${acct['free_margin']:,.2f}")
        self.adopt_broker_positions()
        # Reconcile before reporting so the daily digest includes P&L the broker settled
        # while the previous cycle was shutting down.
        self.reconcile_closed_trades()
        self._heartbeat(acct)
        deadline = time.time() + max_minutes * 60 if max_minutes else None
        polls = 0
        while True:
            try:
                self.poll_once()
                if polls and polls % RECONCILE_EVERY == 0:
                    self.reconcile_closed_trades()
                if polls and polls % ADOPT_EVERY == 0:
                    self.adopt_broker_positions()
            except Exception as exc:
                logger.error(f"Poll failed: {exc}")
            polls += 1
            if max_polls and polls >= max_polls:
                return
            if deadline and time.time() >= deadline:
                logger.info(f"Runner budget of {max_minutes} min used up after {polls} poll(s) - "
                            f"handing over to the next scheduled cycle")
                return
            time.sleep(POLL_SECONDS)

    def _heartbeat(self, acct: Dict[str, float]) -> None:
        """Announce a restart after a gap, and send one plain-language report a day."""
        now = datetime.now(timezone.utc)
        previous = self.state.get("last_heartbeat")
        announce = True
        if previous:
            try:
                seen = datetime.fromisoformat(str(previous).replace("Z", "+00:00"))
                announce = (now - seen).total_seconds() > HEARTBEAT_QUIET_MIN * 60
            except ValueError:
                announce = True
        self.state["last_heartbeat"] = now.isoformat()
        if announce:
            notify(f"<b>Invo copier online</b>\n"
                   f"account {account_label()} ({'dry run' if self.dry_run else 'LIVE'})\n"
                   f"equity ${acct['equity']:,.2f} | balance ${acct['balance']:,.2f}\n"
                   f"masters {len(self.allowed) or 'any on feed'} | "
                   f"risk {self.risk_pct}%/copy | max {self.max_positions} open")
        today = now.strftime("%Y-%m-%d")
        if self.state.get("last_digest_date") != today:
            self.state["last_digest_date"] = today
            notify(self._digest(today, acct))

    def _digest(self, today: str, acct: Dict[str, float]) -> str:
        """One message a day: what was copied, what it made, and whether we are halted.

        A quiet copier and a dead copier look identical from the phone, so this also
        doubles as proof of life on days with no signals.
        """
        copies = list(self.state["copies"].values())
        opened = [c for c in copies if str(c.get("openedAt") or "").startswith(today)]
        closed = [c for c in copies if str(c.get("closedAt") or "").startswith(today)]
        realized = sum(float(c.get("realizedPnl") or 0.0)
                       for c in closed if c.get("reconciled"))
        wins = sum(1 for c in closed if float(c.get("realizedPnl") or 0.0) > 0)
        still_open = [c for c in copies if not c.get("closed")]
        lines = [
            f"<b>Daily copy report {today}</b>",
            f"account {account_label()} | equity ${acct['equity']:,.2f}",
            f"copied {len(opened)} | closed {len(closed)} "
            f"({wins} win / {len(closed) - wins} loss) | realized ${realized:,.2f}",
            f"still open {len(still_open)}/{self.max_positions} | "
            f"daily losses {guardian.state.get('daily_losses_count', 0)}/"
            f"{guardian.state.get('max_daily_losses', 2)}",
        ]
        for copy in still_open[:5]:
            lines.append(f"  {copy.get('symbol')} {copy.get('side')} "
                         f"@{copy.get('trader')} SL {copy.get('stop')}")
        if guardian.state.get("trading_halted"):
            lines.append(f"HALTED: {guardian.state.get('halt_reason')}")
        if not opened:
            lines.append("No new master entries in range - still watching.")
        return "\n".join(lines)

    def reconcile_closed_trades(self) -> int:
        """Attribute broker-realized P&L to copies and feed RiskGuardian's 2-strike breaker."""
        pending = {
            int(c["positionId"]): (key, c)
            for key, c in self.state["copies"].items()
            if c.get("positionId") and not c.get("reconciled") and not self.dry_run
        }
        if not pending:
            return 0
        fetch = getattr(self.ctrader, "get_closed_deals", None)
        if not fetch:
            return 0
        applied = 0
        for deal in fetch(days=2) or []:
            position_id = int(deal.get("position_id") or 0)
            if position_id not in pending:
                continue
            key, copy = pending[position_id]
            pnl = float(deal.get("net_pnl") or 0.0)
            # A rehearsal is an operator smoke test, not a master's trade - charging it to
            # the daily breaker would burn a real strike and could halt live copying.
            if copy.get("trader") != "rehearsal":
                guardian.record_trade_result(is_loss=pnl < 0, pnl_usd=abs(pnl))
            copy.update({
                "reconciled": True, "closed": True, "realizedPnl": pnl,
                "closedAt": copy.get("closedAt") or datetime.now(timezone.utc).isoformat(),
            })
            applied += 1
            logger.info(f"RECONCILED {copy.get('symbol')} #{position_id}: ${pnl:,.2f} "
                        f"({'loss' if pnl < 0 else 'win'}) - "
                        f"daily losses {guardian.state['daily_losses_count']}")
            notify(f"<b>{'LOSS' if pnl < 0 else 'WIN'} {copy.get('symbol')} "
                   f"${pnl:,.2f}</b>\n"
                   f"master @{copy.get('trader')} | position #{position_id}\n"
                   f"daily losses {guardian.state['daily_losses_count']}/"
                   f"{guardian.state.get('max_daily_losses', 2)} "
                   f"(${guardian.state.get('daily_loss_total', 0.0):,.2f})\n"
                   f"account {account_label()}")
            if guardian.state.get("trading_halted"):
                notify(f"<b>NEW COPIES HALTED</b>\n{guardian.state.get('halt_reason')}\n"
                       f"Existing positions keep their stops. Entries resume next "
                       f"trading day, or run --status to inspect.")
        if applied:
            self._save_state()
        return applied


    # -- diagnostics ------------------------------------------------------- #

    def status(self) -> None:
        acct = self._account()
        print(f"account    #{account_label()} balance ${acct['balance']:,.2f} "
              f"| equity ${acct['equity']:,.2f} | free margin ${acct['free_margin']:,.2f}")
        halted = guardian.state.get("trading_halted")
        print(f"guardian   {'HALTED - ' + str(guardian.state.get('halt_reason')) if halted else 'active'} "
              f"| daily losses {guardian.state.get('daily_losses_count', 0)}"
              f"/{guardian.state.get('max_daily_losses', 2)}"
              f" (${guardian.state.get('daily_loss_total', 0.0):,.2f})"
              f" | mode {guardian.state.get('active_mode')}")

        copies = self.state["copies"]
        open_copies = {k: c for k, c in copies.items() if not c.get("closed")}
        print(f"watching   feeds={self.feeds} | "
              f"masters={len(self.allowed) if self.allowed else 'any on feed'}")
        print(f"copies     {len(open_copies)} open / {len(copies)} tracked "
              f"(budget {len(open_copies)}/{self.max_positions}) "
              f"| pending closes {len(self.state.get('pending_closes', []))}")
        for key, c in open_copies.items():
            print(f"  {c.get('symbol')} {c.get('side')} {c.get('units')} units "
                  f"#{c.get('positionId')} SL {c.get('stop')} @{c.get('trader')} since {c.get('openedAt')}")

        try:
            positions = self.ctrader.get_positions_strict() or []
            print(f"broker     {len(positions)} open position(s)")
            for p in positions:
                print(f"  #{p.get('positionId')} {p.get('symbolName') or p.get('symbolId')} "
                      f"{p.get('tradeSide')} vol {p.get('volume')} "
                      f"SL {p.get('stopLoss')} TP {p.get('takeProfit')}")
        except Exception as exc:
            print(f"broker     telemetry unavailable: {exc}")

        try:
            deals = self.ctrader.get_closed_deals(days=1) or []
            realized = sum(float(d.get("net_pnl") or 0.0) for d in deals)
            print(f"today      realized ${realized:,.2f} across {len(deals)} closed deal(s)")
            for d in deals[:5]:
                print(f"  #{d.get('position_id')} {d.get('symbol_name')} {d.get('trade_side')} "
                      f"{d.get('lots')} lots ${float(d.get('net_pnl') or 0):,.2f} ({d.get('exit_time')})")
        except Exception as exc:
            print(f"today      deal history unavailable: {exc}")

    def rehearse(self, coin: Optional[str] = None) -> int:
        """Real broker round trip: open with the ATR stop, verify protection, mirror the exit."""
        coin = (coin or next(iter(self.symbols))).upper()
        if coin not in self.symbols:
            print(f"cannot rehearse {coin}: broker symbol map covers {sorted(self.symbols)}")
            return 1
        symbol = self.symbols[coin]
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
        shot = f"REHEARSAL-{stamp}"
        signal = {
            "postId": f"rehearsal-{stamp}",
            "action": "open",
            "owner": {"id": "self", "username": "rehearsal"},
            "trade": {"coin": coin, "side": "long", "leverage": 1},
            "mimicMeta": {"portfolioId": "rehearsal", "baseShortId": shot},
        }
        self.dry_run = False
        logger.info(f"REHEARSAL: placing a live {symbol} order on the configured cTrader account")
        record = None
        try:
            record = self.handle_open(signal)
            if not record:
                logger.error("REHEARSAL FAILED at entry - no position was opened")
                return 1
            pos = self._position(int(record["positionId"]))
            if pos:
                logger.info(
                    f"REHEARSAL protection confirmed: #{record['positionId']} volume {pos.get('volume')} "
                    f"broker SL {pos.get('stopLoss')} (planned {record['stop']})"
                )
            else:
                logger.warning("REHEARSAL: position telemetry did not echo the new position")
        finally:
            if record:
                self.handle_close(signal)
                time.sleep(2.0)
                self.reconcile_closed_trades()
        return 0

    def self_test(self) -> None:
        acct = self._account()
        print(f"account      balance ${acct['balance']:,.2f} | equity ${acct['equity']:,.2f} "
              f"| free margin ${acct['free_margin']:,.2f}")
        symbols = {s.get("symbolName"): s for s in self.ctrader.get_symbols()}
        for coin, symbol in self.symbols.items():
            meta = symbols.get(symbol)
            if not meta:
                print(f"{coin:>4} -> {symbol:<8} MISSING at broker")
                continue
            spot = self.ctrader.get_spot_price(symbol) or {}
            price = float(spot.get("ask") or 0.0)
            atr = self._atr(symbol)
            stop_distance = synthetic_stop_distance(price, atr)
            units = compute_units(acct["equity"], price, stop_distance, self.risk_pct)
            print(f"{coin:>4} -> {symbol:<8} price {price:,.2f} | ATR15 {atr if atr else 'n/a'} "
                  f"| stop {stop_distance:,.2f} ({stop_distance / price * 100:.2f}%) "
                  f"| size {units} units (${units * price:,.0f}) "
                  f"| risk ${units * stop_distance:,.2f}")


def main() -> int:
    # Trader handles and portfolio titles are full of emoji; without this the console
    # renders them as escape garbage on a cp1252 Windows terminal.
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    parser = argparse.ArgumentParser(description="Copy Invo master traders onto cTrader")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--live", action="store_true", help="place real orders on the cTrader account")
    mode.add_argument("--dry-run", action="store_true", help="log signals only (default)")
    mode.add_argument("--self-test", action="store_true", help="print symbol + sizing diagnostics, no feed")
    mode.add_argument("--rehearse", action="store_true", help="real demo round trip: open, verify stop, close")
    mode.add_argument("--discover", action="store_true", help="rank Invo traders to follow")
    mode.add_argument("--status", action="store_true", help="account, copies, guardian and P&L view")
    parser.add_argument("--follow", metavar="USER_ID", help="follow an Invo user id from --discover")
    parser.add_argument("--filter", default="trending",
                        help="--discover ranking: trending (default), top, or any filter Invo accepts")
    parser.add_argument("--limit", type=int, default=25, help="rows shown by --discover")
    parser.add_argument("--feeds", default=",".join(FEEDS),
                        help="comma-separated Invo feeds to watch: following, trending "
                             "(default: $INVO_FEEDS or 'following')")
    parser.add_argument("--allow", default=",".join(sorted(ALLOWED_TRADERS)),
                        help="comma-separated owner ids to mirror; empty copies any feed post "
                             "(default: $INVO_ALLOWED_TRADERS)")
    parser.add_argument("--coin", default=None,
                        help="--rehearse symbol choice, BTC or ETH (default: first mapped)")
    parser.add_argument("--only-copyable", action="store_true",
                        help="--discover: only traders currently holding BTC or ETH")
    parser.add_argument("--include-liquidated", action="store_true",
                        help="--discover: also list blown-up accounts (hidden by default)")
    parser.add_argument("--set-token", metavar="JWT", help="validate an Invo refresh token and save it to .env")
    parser.add_argument("--polls", type=int, default=0, help="stop after N polls (0 = run forever)")
    parser.add_argument("--minutes", type=float, default=0,
                        help="stop after N minutes (0 = run forever) - used by cloud runners")
    args = parser.parse_args()

    dry_run = not args.live

    if args.set_token:
        return set_refresh_token(args.set_token)

    if args.follow:
        result = InvoClient().follow_user(args.follow)
        print(f"following {args.follow} - its posts now enter the 'following' feed "
              f"(response: {str(result)[:120]})")
        print("next: run --live to copy its BTC/ETH entries onto cTrader")
        return 0

    if args.discover:
        traders = InvoClient().discover_traders(filter_name=args.filter)
        rows = trader_rows(traders, include_liquidated=args.include_liquidated)
        if args.only_copyable:
            rows = [row for row in rows if row["copyable"]]
        print(format_traders(rows, limit=args.limit))
        copyable = sum(1 for row in rows if row["copyable"])
        if rows:
            print(f"\n{len(rows)} trader(s), {copyable} holding BTC/ETH right now.")
            print("Follow one, then let the copier mirror it:")
            print("  .\\.venv\\Scripts\\python.exe src\\integrations\\invo_ctrader_copier.py "
                  "--follow <user id from the last column>")
            print("  .\\.venv\\Scripts\\python.exe src\\integrations\\invo_ctrader_copier.py --live")
            print("Only BTC and ETH entries are copyable - the broker lists no other crypto symbol.")
            print("Past P&L is not a forecast; risk is fixed per trade, not per trader.")
        elif traders:
            print("\nunrecognised payload shape - raw sample:")
            print(json.dumps(traders[0])[:800])
        return 0

    copier = InvoCtaderCopier(
        dry_run=dry_run,
        state_file=REHEARSAL_STATE if args.rehearse else None,
        feeds=[name.strip() for name in args.feeds.split(",") if name.strip()],
        allowed_traders={uid.strip() for uid in args.allow.split(",") if uid.strip()},
    )

    if args.rehearse:
        return copier.rehearse(args.coin)

    if args.status:
        copier.status()
        return 0

    if args.self_test:
        copier.self_test()
        return 0

    copier.run(max_polls=args.polls or None, max_minutes=args.minutes or None)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
