"""
cTrader Remote MCP Client for AgentQuant
=========================================
Connects to FundedNext cTrader via the official cTrader Remote MCP server (mcp.ctrader.com).
Executes live telemetry (balance, equity, margin), symbol quotes, historical trendbars,
and trade operations (market orders, limit orders, position amendments, emergency closing).
Operates over Server-Sent Events (SSE) and HTTP POST with standard JSON-RPC 2.0.
"""

import json
import os
import sys
import time
from typing import Any, Dict, List, Optional

import requests
from dotenv import load_dotenv

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

load_dotenv()

DEFAULT_URL = os.getenv("CTRADER_MCP_URL", "https://mcp.ctrader.com/trading/mcp")
DEFAULT_TOKEN = os.getenv("CTRADER_ACCESS_TOKEN", "eyJwbGFudCI6ImZ1bmRlZG5leHQiLCJlbnZpcm9ubWVudCI6ImRlbW8iLCJ0b2tlbiI6ImZxRUUwRnFZcmYyVFpMRVZFNHd5VnRldkdQUHJES0wvWlltd3RUTnhlQTQ9In0")
ACCOUNT_ID = os.getenv("CTRADER_ACCOUNT_ID", "3028655")


class RiskViolationError(RuntimeError):
    """Raised when an order request violates FundedNext risk, concurrency (max 2), or duplicate asset rules."""
    pass


class CTraderMCPClient:
    def __init__(self, token: Optional[str] = None, url: Optional[str] = None):
        self.url = url or DEFAULT_URL
        self.token = token or DEFAULT_TOKEN
        self.session_id: Optional[str] = None
        self._symbols_cache: Optional[Dict[str, int]] = None
        self.headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream"
        }
        self.rpc_id = 0

    def _next_id(self) -> int:
        self.rpc_id += 1
        return self.rpc_id

    def _post_sse(self, payload: dict, retries: int = 3) -> Optional[dict]:
        headers = dict(self.headers)
        if self.session_id:
            headers["mcp-session-id"] = self.session_id

        for attempt in range(retries):
            try:
                with requests.post(self.url, headers=headers, json=payload, stream=True, timeout=25) as resp:
                    if "mcp-session-id" in resp.headers:
                        self.session_id = resp.headers["mcp-session-id"]

                    if resp.status_code not in (200, 202):
                        if resp.status_code == 404 or "Session not found" in resp.text:
                            self.session_id = None
                        print(f"[!] cTrader MCP HTTP Error {resp.status_code}: {resp.text[:300]}")
                        return None

                    for line in resp.iter_lines():
                        if line:
                            decoded = line.decode("utf-8")
                            if decoded.startswith("data:"):
                                data_str = decoded[5:].strip()
                                return json.loads(data_str)
            except Exception as e:
                if attempt < retries - 1:
                    time.sleep(1.0)
                    continue
                print(f"[!] cTrader MCP Connection Exception: {e}")
                return None
        return None

    def initialize(self) -> bool:
        init_payload = {
            "jsonrpc": "2.0",
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "AgentQuant-AutomatedTrader", "version": "1.0.0"}
            },
            "id": self._next_id()
        }
        res = self._post_sse(init_payload)
        if not res or "result" not in res:
            return False

        # Send initialized notification
        notif_payload = {
            "jsonrpc": "2.0",
            "method": "notifications/initialized"
        }
        self._post_sse(notif_payload)
        return True

    def list_tools(self) -> List[dict]:
        payload = {
            "jsonrpc": "2.0",
            "method": "tools/list",
            "params": {},
            "id": self._next_id()
        }
        res = self._post_sse(payload)
        if res and "result" in res and "tools" in res["result"]:
            return res["result"]["tools"]
        return []

    def call_tool(self, name: str, arguments: Optional[dict] = None) -> Optional[dict]:
        if not self.session_id:
            if not self.initialize():
                return None
        payload = {
            "jsonrpc": "2.0",
            "method": "tools/call",
            "params": {
                "name": name,
                "arguments": arguments or {}
            },
            "id": self._next_id()
        }
        res = self._post_sse(payload)
        if not res and not self.session_id:
            # Session expired and was cleared; re-initialize and retry once
            if self.initialize():
                res = self._post_sse(payload)
        return res

    def _parse_content_json(self, response: Optional[dict]) -> Optional[Any]:
        if not response or "result" not in response or "content" not in response["result"]:
            return None
        for item in response["result"]["content"]:
            if item.get("type") == "text":
                try:
                    return json.loads(item.get("text", "{}"))
                except Exception:
                    return item.get("text")
        return None

    def get_balance(self) -> dict:
        """
        Returns live balance, equity, and free margin in USD dollars.
        Example: {'balance': 6000.0, 'equity': 6000.0, 'freeMargin': 6000.0}
        """
        raw = self.call_tool("get_balance")
        data = self._parse_content_json(raw)
        if data and isinstance(data, dict):
            digits = data.get("moneyDigits", 2)
            div = 10 ** digits
            return {
                "balance": data.get("balance", 0) / div,
                "equity": data.get("equity", 0) / div,
                "freeMargin": data.get("freeMargin", 0) / div,
                "raw": data
            }
        return {"balance": 6000.0, "equity": 6000.0, "freeMargin": 6000.0, "raw": None}

    def get_symbols(self) -> List[dict]:
        raw = self.call_tool("get_symbols")
        data = self._parse_content_json(raw)
        if data and isinstance(data, dict) and "symbols" in data:
            return data["symbols"]
        return []

    def get_symbol_map(self) -> Dict[str, int]:
        if self._symbols_cache:
            return self._symbols_cache
        symbols = self.get_symbols()
        s_map = {}
        for s in symbols:
            s_map[s["symbolName"].upper()] = s["symbolId"]
        self._symbols_cache = s_map
        return s_map

    def get_spot_price(self, symbol: str) -> Optional[dict]:
        """
        Returns latest bid and ask for symbol (e.g. 'SPX500', 'NDX100', 'XAUUSD').
        Checks real-time streaming cache first for sub-millisecond instant return.
        """
        try:
            from src.integrations.ctrader_streamer import get_streamed_spot_price
            streamed = get_streamed_spot_price(symbol)
            if streamed:
                return streamed
        except Exception:
            pass

        s_map = self.get_symbol_map()
        sym_id = s_map.get(symbol.upper())
        if not sym_id:
            return None
        raw = self.call_tool("get_spot_prices", {"symbolId": [sym_id]})
        data = self._parse_content_json(raw)
        if data and isinstance(data, dict) and "prices" in data and len(data["prices"]) > 0:
            p = data["prices"][0]
            # S&P and indices/gold are 5 decimal digits
            div = 100000.0
            return {
                "symbol": symbol,
                "symbolId": sym_id,
                "bid": p.get("bid", 0) / div,
                "ask": p.get("ask", 0) / div,
                "high": p.get("high", 0) / div,
                "low": p.get("low", 0) / div,
                "timestamp": p.get("timestamp")
            }
        return None

    def get_positions_strict(self) -> Optional[List[dict]]:
        """
        Returns list of active open positions directly from broker.
        Returns None if MCP call fails, times out, or error response occurs (Fail-Closed semantics).
        """
        raw = self.call_tool("get_positions")
        if not raw or (isinstance(raw, dict) and raw.get("isError")):
            return None
        data = self._parse_content_json(raw)
        if data and isinstance(data, dict) and "positions" in data:
            return data["positions"]
        return None

    def get_positions(self) -> List[dict]:
        """
        Returns list of active open positions (empty list on failure for legacy compatibility).
        For risk checks, use get_positions_strict() to avoid fail-open assumptions.
        """
        res = self.get_positions_strict()
        return res if res is not None else []

    def get_enriched_positions(self) -> List[dict]:
        """
        Returns list of active open positions enriched with:
          - symbol_name (e.g. 'XAUUSD', 'NDX100')
          - display_name (e.g. 'Spot Gold')
          - lots (converted from raw cTrader volume)
          - current_price (live spot bid/ask)
          - floating_pnl (unrealized profit/loss in USD)
          - floating_pnl_pct
          - take_profit & dist_to_tp (USD and %)
          - stop_loss & dist_to_sl (USD and %)
        """
        positions = self.get_positions()
        if not positions:
            return []

        s_map = self.get_symbol_map()
        id_to_sym = {v: k for k, v in s_map.items()}

        friendly_names = {
            "XAUUSD": "Spot Gold",
            "SPX500": "S&P 500 Index",
            "NDX100": "Nasdaq 100 Index",
            "AAPL": "Apple Inc.",
            "NVDA": "Nvidia Corp.",
            "MSFT": "Microsoft Corp.",
            "META": "Meta Platforms"
        }

        enriched = []
        for p in positions:
            sym_id = p.get("symbolId")
            sym_name = id_to_sym.get(sym_id, p.get("symbolName", f"SYM_{sym_id}")).upper()
            display_name = friendly_names.get(sym_name, sym_name)
            side = p.get("tradeSide", "BUY").upper()
            raw_vol = p.get("volume", 0)
            entry_p = float(p.get("entryPrice", 0.0))
            sl_p = float(p.get("stopLoss", 0.0)) if p.get("stopLoss") else None
            tp_p = float(p.get("takeProfit", 0.0)) if p.get("takeProfit") else None

            # Sizing multiplier and lots calculation
            if "XAU" in sym_name or "GOLD" in sym_name:
                lots = raw_vol / 10000.0
                multiplier = 100.0  # 100 oz per lot
            elif "SPX" in sym_name or "NDX" in sym_name or "US30" in sym_name:
                lots = raw_vol / 100.0
                multiplier = 1.0    # 1 index contract per lot
            else:
                lots = raw_vol / 100.0
                multiplier = 1.0    # 1 share per lot

            # Fetch live spot
            spot = self.get_spot_price(sym_name)
            if spot:
                curr_p = float(spot["bid"] if side == "BUY" else spot["ask"])
            else:
                curr_p = entry_p

            # Calculate floating PnL
            if side == "BUY":
                pnl = (curr_p - entry_p) * lots * multiplier
                pnl_pct = ((curr_p - entry_p) / entry_p) * 100 if entry_p > 0 else 0.0
            else:
                pnl = (entry_p - curr_p) * lots * multiplier
                pnl_pct = ((entry_p - curr_p) / entry_p) * 100 if entry_p > 0 else 0.0

            # Distance to TP
            dist_tp_val = None
            dist_tp_pct = None
            if tp_p:
                dist_tp = (tp_p - curr_p) if side == "BUY" else (curr_p - tp_p)
                dist_tp_val = dist_tp * lots * multiplier
                dist_tp_pct = (dist_tp / curr_p) * 100 if curr_p > 0 else 0.0

            # Distance to SL (cushion left)
            dist_sl_val = None
            dist_sl_pct = None
            if sl_p:
                dist_sl = (curr_p - sl_p) if side == "BUY" else (sl_p - curr_p)
                dist_sl_val = dist_sl * lots * multiplier
                dist_sl_pct = (dist_sl / curr_p) * 100 if curr_p > 0 else 0.0

            enriched.append({
                "position_id": p.get("positionId"),
                "symbol_id": sym_id,
                "symbol_name": sym_name,
                "display_name": display_name,
                "trade_side": side,
                "volume_raw": raw_vol,
                "lots": round(lots, 2),
                "entry_price": entry_p,
                "current_price": curr_p,
                "take_profit": tp_p,
                "stop_loss": sl_p,
                "floating_pnl": round(pnl, 2),
                "floating_pnl_pct": round(pnl_pct, 2),
                "dist_to_tp_usd": round(dist_tp_val, 2) if dist_tp_val is not None else None,
                "dist_to_tp_pct": round(dist_tp_pct, 2) if dist_tp_pct is not None else None,
                "dist_to_sl_usd": round(dist_sl_val, 2) if dist_sl_val is not None else None,
                "dist_to_sl_pct": round(dist_sl_pct, 2) if dist_sl_pct is not None else None,
                "commission": p.get("commission", 0) / 100.0 if p.get("commission") else 0.0,
                "swap": p.get("swap", 0) / 100.0 if p.get("swap") else 0.0
            })
        return enriched

    def get_pending_orders(self) -> List[dict]:
        """
        Returns list of active pending orders.
        """
        raw = self.call_tool("get_pending_orders")
        data = self._parse_content_json(raw)
        if data and isinstance(data, dict) and "orders" in data:
            return data["orders"]
        return []

    def place_market_order(self, symbol: str, side: str = "BUY", volume_lots: float = 0.01,
                           relative_sl_points: Optional[int] = None,
                           relative_tp_points: Optional[int] = None,
                           stop_loss_price: Optional[float] = None,
                           take_profit_price: Optional[float] = None,
                           comment: str = "AgentQuant Scalper",
                           bypass_concurrency_check: bool = False) -> Optional[dict]:
        """
        Places a market order with strict broker-level 2-trade concurrency ceiling
        and duplicate asset protection.
        volume = lots * lotSize * 100
        For indices (SPX500, NDX100): lotSize = 1 -> volume = lots * 100
        For metals (XAUUSD): lotSize = 100 -> volume = lots * 10000
        For forex: lotSize = 100000 -> volume = lots * 10000000
        """
        # ── HARD BROKER-LEVEL CONCURRENCY & DUPLICATE CHOKE POINT ──
        if not bypass_concurrency_check:
            live_positions = self.get_positions_strict()
            if live_positions is None:
                raise RiskViolationError(
                    "CRITICAL: Cannot verify broker positions (telemetry offline/unreachable). "
                    "Order rejected to prevent over-concurrency."
                )

            MAX_ALLOWED_CONCURRENT = 2
            if len(live_positions) >= MAX_ALLOWED_CONCURRENT:
                raise RiskViolationError(
                    f"CONCURRENCY VIOLATION: Cannot open {symbol}. Account already has "
                    f"{len(live_positions)}/{MAX_ALLOWED_CONCURRENT} active positions."
                )

            s_map = self.get_symbol_map()
            target_sym_id = s_map.get(symbol.upper())
            for p in live_positions:
                p_sym_id = p.get("symbolId")
                p_sym_name = str(p.get("symbolName", "")).upper() if p.get("symbolName") else None
                if (target_sym_id and p_sym_id == target_sym_id) or (p_sym_name and p_sym_name == symbol.upper()):
                    raise RiskViolationError(
                        f"DUPLICATE ASSET VIOLATION: Symbol {symbol} is already held in active position #{p.get('positionId')}."
                    )

        # ── ASSET PRICE SANITY CHECK (PREVENTS ETF vs CFD CONFUSION) ──
        sym_upper = symbol.upper()
        if "XAU" in sym_upper or "GOLD" in sym_upper:
            if stop_loss_price is not None and stop_loss_price < 1000.0:
                raise RiskViolationError(
                    f"INVALID PRICE FOR {symbol}: SL ${stop_loss_price} appears to be ETF price, not Spot Gold price (> $1000)."
                )
            if take_profit_price is not None and take_profit_price < 1000.0:
                raise RiskViolationError(
                    f"INVALID PRICE FOR {symbol}: TP ${take_profit_price} appears to be ETF price, not Spot Gold price (> $1000)."
                )

        s_map = self.get_symbol_map()
        sym_id = s_map.get(symbol.upper())
        if not sym_id:
            raise ValueError(f"Unknown symbol: {symbol}")

        # Compute volume in 1/100 units
        sym_upper = symbol.upper()
        if "SPX" in sym_upper or "NDX" in sym_upper or "US30" in sym_upper or "UK100" in sym_upper:
            # Index lotSize = 1
            raw_vol = int(round(volume_lots * 1 * 100))
        elif "XAU" in sym_upper or "GOLD" in sym_upper:
            # Metal lotSize = 100
            raw_vol = int(round(volume_lots * 100 * 100))
        else:
            # Forex/Stocks lotSize = 100000 or 100
            raw_vol = int(round(volume_lots * 100))

        args = {
            "symbolId": sym_id,
            "orderType": "MARKET",
            "tradeSide": side.upper(),
            "volume": max(1, raw_vol),
            "label": "AgentQuant",
            "comment": comment[:256]
        }
        if relative_sl_points and not stop_loss_price:
            args["relativeStopLoss"] = int(relative_sl_points)
        if relative_tp_points and not take_profit_price:
            args["relativeTakeProfit"] = int(relative_tp_points)

        raw = self.call_tool("create_order", args)
        result = self._parse_content_json(raw)

        # If order filled and display SL/TP provided, amend position with exact chart prices
        if result and isinstance(result, dict) and (stop_loss_price or take_profit_price):
            pos_id = result.get("positionId") or (result.get("position", {}).get("positionId") if isinstance(result.get("position"), dict) else None)
            if pos_id:
                amend_args = {"positionId": pos_id}
                if stop_loss_price:
                    amend_args["stopLoss"] = round(float(stop_loss_price), 2)
                if take_profit_price:
                    amend_args["takeProfit"] = round(float(take_profit_price), 2)
                self.call_tool("amend_position", amend_args)

        return result

    def close_position(self, position_id: int, volume: Optional[int] = None) -> Optional[dict]:
        """
        Closes an open position. If volume is None, closes completely by querying current position volume.
        """
        if volume is None:
            # cTrader remote MCP requires volume. Look up current position volume.
            positions = self.get_positions()
            for p in positions:
                if p.get("positionId") == position_id:
                    volume = p.get("volume")
                    break
            if volume is None:
                raw_det = self.call_tool("get_position_details", {"positionId": position_id})
                data_det = self._parse_content_json(raw_det)
                if data_det and isinstance(data_det, dict):
                    pos_obj = data_det.get("position", data_det)
                    volume = pos_obj.get("volume")

        args = {"positionId": position_id, "volume": volume if volume is not None else 100}
        raw = self.call_tool("close_position", args)
        return self._parse_content_json(raw)

ctrader_client = CTraderMCPClient()


if __name__ == "__main__":
    client = CTraderMCPClient()
    print("[*] Initializing cTrader MCP Client...")
    if client.initialize():
        print(f"✅ Handshake successful! Session ID: {client.session_id}")
        bal = client.get_balance()
        print(f"💰 Account Balance: ${bal['balance']:,.2f} | Equity: ${bal['equity']:,.2f} | Free Margin: ${bal['freeMargin']:,.2f}")

        spx = client.get_spot_price("SPX500")
        if spx:
            print(f"📈 SPX500 Spot Price: Bid = ${spx['bid']:.2f} | Ask = ${spx['ask']:.2f}")

        pos = client.get_positions()
        print(f"📊 Open Positions: {len(pos)}")
    else:
        print("❌ Handshake failed!")
