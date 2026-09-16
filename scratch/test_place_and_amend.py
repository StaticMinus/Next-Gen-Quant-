import os
import sys
import json
from dotenv import load_dotenv

load_dotenv()
from src.integrations.ctrader_mcp_client import CTraderMCPClient

client = CTraderMCPClient()
if client.initialize():
    print("cTrader initialized. Session ID:", client.session_id)
    sym_map = client.get_symbol_map()
    sym_id = sym_map.get("XAUUSD")
    print("XAUUSD Symbol ID:", sym_id)

    # Place market order for 0.01 lot of XAUUSD (100 volume units)
    # volume = lots * lotSize * 100 = 0.01 * 100 * 100 = 100
    order_args = {
        "symbolId": sym_id,
        "orderType": "MARKET",
        "tradeSide": "BUY",
        "volume": 100,
        "label": "AgentQuant",
        "comment": "AgentQuant Gold Dip"
    }
    raw = client.call_tool("create_order", order_args)
    print("create_order raw response:", raw)
    data = client._parse_content_json(raw)
    print("Parsed create_order data:", data)

    # Check positions
    pos = client.get_positions()
    print("Open positions:", pos)
    if pos:
        latest_pos = pos[-1]
        pos_id = latest_pos["positionId"]
        entry_price = latest_pos.get("entryPrice", 4335.0)
        # S&P and metals may be in 100,000 units if raw, or display price
        print("Latest position ID:", pos_id, "Raw position:", latest_pos)
        
        # Calculate SL and TP as display price
        # If entry price is 4335.0:
        sl_price = round(4335.0 * 0.97, 2)
        tp_price = round(4335.0 * 1.025, 2)
        print(f"Amending position {pos_id} with SL: {sl_price} and TP: {tp_price}")
        
        amend_raw = client.call_tool("amend_position", {
            "positionId": pos_id,
            "stopLoss": sl_price,
            "takeProfit": tp_price
        })
        print("amend_position raw response:", amend_raw)
