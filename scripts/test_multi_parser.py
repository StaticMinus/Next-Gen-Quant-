import json
import re
from pathlib import Path
from typing import Dict, Any, Optional

class MultiChannelSignalParser:
    """
    Universal Signal Parser engineered from real message signatures
    across ssfgold, forexgdpfree, learn2tradenews, and XAUUSD_GOLD_TRADING_FOREX.
    """

    KNOWN_SYMBOLS = [
        "XAUUSD", "GOLD", "EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD",
        "USDCHF", "NZDUSD", "EURJPY", "GBPJPY", "AUDNZD", "GBPCHF", "USDNOK"
    ]

    @classmethod
    def clean_text(cls, raw: str) -> str:
        # replace html entities
        t = raw.replace("&#33;", "!").replace("&#036;", "$").replace("&amp;", "&").replace("&#39;", "'").replace("&#092;", "/")
        return t

    @classmethod
    def parse_message(cls, text: str, channel: str) -> Optional[Dict[str, Any]]:
        text_clean = cls.clean_text(text)
        text_lower = text_clean.lower()

        # Hard filters: locked VIP teasers, tournament spam, weekend recaps
        if "locked" in text_lower or "tournament" in text_lower or "weekend market brief" in text_lower or "week ahead" in text_lower:
            return None
        if "to get full trade management" in text_lower and not ("sl:" in text_lower or "tp:" in text_lower):
            return None

        # -------------------------------------------------------------
        # 1. PARSER FOR SSFGOLD:
        # e.g.: "XAUUSD BUY 4179.76  SL:  4169.76 TP:  4199.76 --Trade by William"
        # -------------------------------------------------------------
        m_ssf = re.search(r"\b(XAUUSD|GOLD)\s+(BUY|SELL)\s+([\d\.]+)\s+SL:\s*([\d\.]+)\s+TP:\s*([\d\.]+)", text_clean, re.IGNORECASE)
        if m_ssf:
            sym = "XAUUSD"
            side = m_ssf.group(2).upper()
            entry = float(m_ssf.group(3))
            sl = float(m_ssf.group(4))
            tp = float(m_ssf.group(5))
            return {
                "channel": channel,
                "symbol": sym,
                "side": side,
                "entry_min": entry,
                "entry_max": entry,
                "entry_mid": entry,
                "sl": sl,
                "tps": [tp],
                "type": "DIRECT_EXECUTION"
            }

        # -------------------------------------------------------------
        # 2. PARSER FOR FOREXGDP:
        # e.g.: "Sell AUDNZD at any price between 1.2348 till 1.2375 ... Target 1: 1.2300 ... Stop loss: 1.2436"
        # e.g.: "SELL XAUUSD now at any price between 4173 till 4183 ... Target 1 : 4153 ... Stop loss: 4205"
        # -------------------------------------------------------------
        m_fgdp = re.search(
            r"(?:Forex|Gold)?\s*Signal[\s\S]*?(BUY|SELL)\s+([A-Z]{6}|XAUUSD)[\s\S]*?between\s+([\d\.]+)\s+till\s+([\d\.]+)",
            text_clean, re.IGNORECASE
        )
        if m_fgdp:
            side = m_fgdp.group(1).upper()
            sym = m_fgdp.group(2).upper()
            e1 = float(m_fgdp.group(3))
            e2 = float(m_fgdp.group(4))
            entry_min, entry_max = min(e1, e2), max(e1, e2)
            entry_mid = (e1 + e2) / 2.0

            # Find Targets
            targets = [float(x) for x in re.findall(r"Target\s*\d?\s*:\s*([\d\.]+)", text_clean, re.IGNORECASE)]
            
            # Find Stop Loss
            m_sl = re.search(r"Stop\s*loss\s*:\s*([\d\.]+)", text_clean, re.IGNORECASE)
            sl = float(m_sl.group(1)) if m_sl else None

            if sl:
                return {
                    "channel": channel,
                    "symbol": sym,
                    "side": side,
                    "entry_min": entry_min,
                    "entry_max": entry_max,
                    "entry_mid": entry_mid,
                    "sl": sl,
                    "tps": targets[:3],
                    "type": "ZONE_EXECUTION"
                }

        # -------------------------------------------------------------
        # 3. PARSER FOR LEARN2TRADE:
        # e.g.: "SIGNAL — GOLD (XAU/USD) SHORT ... Entry: $4,210 – $4,230 Target TP1: $4,130 SL: $4,265"
        # e.g.: "FREE SIGNAL — EUR/USD SHORT ... Entry Zone: 1.1360 – 1.1385 TP1: 1.1265 SL: 1.1430"
        # -------------------------------------------------------------
        m_l2t_sym = re.search(r"\b([A-Z]{3}/[A-Z]{3}|XAU/USD|GOLD)\b[\s\S]*?\b(BUY|SELL|LONG|SHORT)\b", text_clean, re.IGNORECASE)
        m_l2t_entry = re.search(r"Entry(?:\s*Zone)?:\s*[\$]?([\d\.,]+)\s*[–\-]\s*[\$]?([\d\.,]+)", text_clean, re.IGNORECASE)
        m_l2t_sl = re.search(r"(?:SL|Stop\s*Loss):\s*[\$]?([\d\.,]+)", text_clean, re.IGNORECASE)

        if m_l2t_sym and m_l2t_entry and m_l2t_sl:
            raw_sym = m_l2t_sym.group(1).upper().replace("/", "")
            if "GOLD" in raw_sym: raw_sym = "XAUUSD"
            raw_side = m_l2t_sym.group(2).upper()
            side = "BUY" if raw_side in ["BUY", "LONG"] else "SELL"
            e1 = float(m_l2t_entry.group(1).replace(",", ""))
            e2 = float(m_l2t_entry.group(2).replace(",", ""))
            entry_min, entry_max = min(e1, e2), max(e1, e2)
            entry_mid = (e1 + e2) / 2.0
            sl = float(m_l2t_sl.group(1).replace(",", ""))

            # Take profits
            tps = [float(x.replace(",", "")) for x in re.findall(r"TP\d?:\s*[\$]?([\d\.,]+)", text_clean, re.IGNORECASE)]

            return {
                "channel": channel,
                "symbol": raw_sym,
                "side": side,
                "entry_min": entry_min,
                "entry_max": entry_max,
                "entry_mid": entry_mid,
                "sl": sl,
                "tps": tps[:3],
                "type": "ZONE_EXECUTION"
            }

        # -------------------------------------------------------------
        # 4. PARSER FOR XAUUSD_GOLD_TRADING_FOREX (Legacy fallback):
        # e.g.: "BUY GOLD 4280 SL 4270 TP 4288"
        # -------------------------------------------------------------
        m_legacy = re.search(r"(BUY|SELL)(?:\s+(?:NOW|MORE|GOLD|XAUUSD|AT|@))*[\s:\-@]*(\d{4}(?:\.\d+)?)", text_clean, re.IGNORECASE)
        if m_legacy:
            side = m_legacy.group(1).upper()
            entry = float(m_legacy.group(2))
            m_sl = re.search(r"(?:STOP\s*LOSS|SL)[\s:\-@]*(\d{4}(?:\.\d+)?)", text_clean, re.IGNORECASE)
            sl = float(m_sl.group(1)) if m_sl else (entry - 10 if side == "BUY" else entry + 10)
            tp_matches = re.findall(r"(?:TAKE\s*PROFIT|TP)\s*(?:[123¹²³]|\d)?[\s:\-@]*(\d{4}(?:\.\d+)?)", text_clean, re.IGNORECASE)
            tps = [float(x) for x in tp_matches][:3]
            return {
                "channel": channel,
                "symbol": "XAUUSD",
                "side": side,
                "entry_min": entry,
                "entry_max": entry,
                "entry_mid": entry,
                "sl": sl,
                "tps": tps,
                "type": "LEGACY_DIRECT"
            }

        return None

def test_parser_on_real_data():
    audit_dir = Path("data/channel_audits")
    target_channels = ["ssfgold", "forexgdpfree", "learn2tradenews", "XAUUSD_GOLD_TRADING_FOREX"]
    
    total_parsed = 0
    results = {}

    for ch in target_channels:
        p = audit_dir / f"{ch}.json"
        if not p.exists(): continue
        with open(p, "r", encoding="utf-8") as f:
            posts = json.load(f)
        
        parsed_in_ch = []
        for post in posts:
            res = MultiChannelSignalParser.parse_message(post["text"], ch)
            if res:
                res["post_id"] = post["id"]
                parsed_in_ch.append(res)
        
        results[ch] = parsed_in_ch
        total_parsed += len(parsed_in_ch)
        print(f"[{ch}] Total messages: {len(posts)} | Successfully Extracted Valid Signals: {len(parsed_in_ch)}")

    print(f"\nTOTAL VALID SIGNALS EXTRACTED ACROSS AUDITED CHANNELS: {total_parsed}")
    out_file = Path("data/channel_audits/parsed_signals_verification.json")
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)
    print(f"Saved full parsed extraction results to {out_file}")

if __name__ == "__main__":
    test_parser_on_real_data()
