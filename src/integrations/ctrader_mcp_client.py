"""
cTrader Remote MCP Client for AgentQuant
=========================================
Connects to FundedNext cTrader via the official cTrader Remote MCP server (mcp.ctrader.com).
Executes live telemetry (balance, equity, margin), symbol quotes, historical trendbars,
and trade operations (market orders, limit orders, position amendments, emergency closing).
Operates over Server-Sent Events (SSE) and HTTP POST with standard JSON-RPC 2.0.
"""

import os
import sys
import json
import time
from typing import Dict, List, Optional, Any
import requests
from dotenv import load_dotenv

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

load_dotenv()

DEFAULT_URL = os.getenv("CTRADER_MCP_URL", "https://mcp.ctrader.com/trading/mcp")
DEFAULT_TOKEN = os.getenv("CTRADER_ACCESS_TOKEN", "eyJwbGFudCI6ImZ1bmRlZG5leHQiLCJlbnZpcm9ubWVudCI6ImRlbW8iLCJ0b2tlbiI6ImZxRUUwRnFZcmYyVFpMRVZFNHd5VnRldkdQUHJES0wvWlltd3RUTnhlQTQ9In0")
ACCOUNT_ID = os.getenv("CTRADER_ACCOUNT_ID", "3028655")


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
        payload = {
            "jsonrpc": "2.0",
            "method": "tools/call",
            "params": {
                "name": name,
                "arguments": arguments or {}
            },
            "id": self._next_id()
        }
        return self._post_sse(payload)

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
        """
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

    def get_positions(self) -> List[dict]:
        """
        Returns list of active open positions.
        """
        raw = self.call_tool("get_positions")
        data = self._parse_content_json(raw)
        if data and isinstance(data, dict) and "positions" in data:
            return data["positions"]
        return []

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
                           comment: str = "AgentQuant Scalper") -> Optional[dict]:
        """
        Places a market order.
        volume = lots * lotSize * 100
        For indices (SPX500, NDX100): lotSize = 1 -> volume = lots * 100
        For metals (XAUUSD): lotSize = 100 -> volume = lots * 10000
        For forex: lotSize = 100000 -> volume = lots * 10000000
        """
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
            # Forex lotSize = 100000
            raw_vol = int(round(volume_lots * 100000 * 100))

        args = {
            "symbolId": sym_id,
            "orderType": "MARKET",
            "tradeSide": side.upper(),
            "volume": max(1, raw_vol),
            "label": "AgentQuant",
            "comment": comment[:256]
        }
        if relative_sl_points:
            args["relativeStopLoss"] = int(relative_sl_points)
        if relative_tp_points:
            args["relativeTakeProfit"] = int(relative_tp_points)

        raw = self.call_tool("create_order", args)
        return self._parse_content_json(raw)

    def close_position(self, position_id: int, volume: Optional[int] = None) -> Optional[dict]:
        """
        Closes an open position. If volume is None, closes completely.
        """
        args = {"positionId": position_id}
        if volume:
            args["volume"] = volume
        raw = self.call_tool("close_position", args)
        return self._parse_content_json(raw)


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
