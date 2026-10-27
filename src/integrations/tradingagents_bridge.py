"""
TradingAgents Bridge for AgentQuant
===================================
Bridges Tauric Research's TradingAgents multi-agent framework to AgentQuant's
cTrader execution and FundedNext risk protection engine.

Uses OpenRouter as the primary LLM provider to power:
- Fundamentals Analyst
- Sentiment Analyst
- News & Macro Analyst
- Technical Analyst
- Bull vs. Bear Debate Team
- Portfolio Risk Manager
"""

import logging
import os
import re
from datetime import datetime
from typing import Any, Dict, Optional, Tuple
from dotenv import load_dotenv

try:
    from tradingagents.default_config import DEFAULT_CONFIG
    from tradingagents.graph.trading_graph import TradingAgentsGraph
    from tradingagents.agents.rating import run_rating, parse_rating, RATING_REVIEW
    TRADINGAGENTS_AVAILABLE = True
except ImportError:
    DEFAULT_CONFIG = {}
    TradingAgentsGraph = None
    run_rating = None
    parse_rating = None
    RATING_REVIEW = "REVIEW"
    TRADINGAGENTS_AVAILABLE = False

logger = logging.getLogger("tradingagents_bridge")
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("[%(asctime)s] [%(levelname)s] [TradingAgentsBridge] %(message)s"))
    logger.addHandler(handler)
logger.setLevel(logging.INFO)

load_dotenv()

# Symbol Mapping: cTrader Broker Symbol <-> TradingAgents Analysis Ticker
SYMBOL_MAP = {
    # Crypto
    "BTCUSD": {"ticker": "BTC-USD", "asset_type": "crypto", "name": "Bitcoin Spot"},
    "ETHUSD": {"ticker": "ETH-USD", "asset_type": "crypto", "name": "Ethereum Spot"},
    # Commodities
    "XAUUSD": {"ticker": "GC=F", "asset_type": "commodity", "name": "Gold Spot / Comex"},
    # Forex Majors (Standard 5-decimal & JPY 3-decimal pairs)
    "EURUSD": {"ticker": "EURUSD=X", "asset_type": "forex", "name": "Euro / US Dollar"},
    "GBPUSD": {"ticker": "GBPUSD=X", "asset_type": "forex", "name": "British Pound / US Dollar"},
    "USDJPY": {"ticker": "USDJPY=X", "asset_type": "forex", "name": "US Dollar / Japanese Yen"},
    "AUDUSD": {"ticker": "AUDUSD=X", "asset_type": "forex", "name": "Australian Dollar / US Dollar"},
    "USDCAD": {"ticker": "USDCAD=X", "asset_type": "forex", "name": "US Dollar / Canadian Dollar"},
    "USDCHF": {"ticker": "USDCHF=X", "asset_type": "forex", "name": "US Dollar / Swiss Franc"},
    "NZDUSD": {"ticker": "NZDUSD=X", "asset_type": "forex", "name": "New Zealand Dollar / US Dollar"},
    # Forex Crosses
    "EURJPY": {"ticker": "EURJPY=X", "asset_type": "forex", "name": "Euro / Japanese Yen"},
    "GBPJPY": {"ticker": "GBPJPY=X", "asset_type": "forex", "name": "British Pound / Japanese Yen"},
    # Indices
    "SPX500": {"ticker": "SPY", "asset_type": "stock", "name": "S&P 500 Index"},
    "NDX100": {"ticker": "QQQ", "asset_type": "stock", "name": "Nasdaq 100 Index"},
}


class TradingAgentsBridge:
    def __init__(
        self,
        provider: str = "openrouter",
        model: Optional[str] = None,
        max_debate_rounds: int = 1,
        max_risk_rounds: int = 1,
        debug: bool = False
    ):
        self.provider = provider
        # Default high-performance model on OpenRouter:
        # Use deepseek/deepseek-chat or anthropic/claude-3.5-sonnet
        self.model = model or os.getenv("TRADINGAGENTS_MODEL") or os.getenv("OPENROUTER_MODEL") or "deepseek/deepseek-chat"
        self.max_debate_rounds = max_debate_rounds
        self.max_risk_rounds = max_risk_rounds
        self.debug = debug

        # Prepare configuration
        self.config = self._build_config()

    def _build_config(self) -> Dict[str, Any]:
        cfg = DEFAULT_CONFIG.copy() if DEFAULT_CONFIG else {}
        cfg["llm_provider"] = self.provider
        cfg["deep_think_llm"] = self.model
        cfg["quick_think_llm"] = self.model
        cfg["backend_url"] = "https://openrouter.ai/api/v1"
        cfg["max_debate_rounds"] = self.max_debate_rounds
        cfg["max_risk_discuss_rounds"] = self.max_risk_rounds
        cfg["output_language"] = "English"
        cfg["checkpoint_enabled"] = False
        cfg["max_tokens"] = 4096
        
        # Ensure OPENROUTER_API_KEY is available in env
        if not os.getenv("OPENROUTER_API_KEY") and os.getenv("OPENAI_API_KEY"):
            os.environ["OPENROUTER_API_KEY"] = os.getenv("OPENAI_API_KEY", "")

        return cfg

    def resolve_symbol(self, broker_symbol: str) -> Tuple[str, str, str]:
        """Resolves broker symbol into (analysis_ticker, asset_type, display_name)."""
        sym_clean = broker_symbol.upper().strip()
        info = SYMBOL_MAP.get(sym_clean)
        if info:
            return info["ticker"], info["asset_type"], info["name"]
        return sym_clean, "stock", sym_clean

    def analyze_symbol(
        self,
        broker_symbol: str,
        trade_date: Optional[str] = None,
        analysts: Tuple[str, ...] = ("market", "news", "social", "fundamentals")
    ) -> Dict[str, Any]:
        """
        Executes TradingAgents multi-agent graph propagation for the given symbol.
        Returns a rich structured decision package with signals, debate, and analyst reports.
        """
        ticker, asset_type, display_name = self.resolve_symbol(broker_symbol)
        date_str = trade_date or datetime.now().strftime("%Y-%m-%d")

        if not TRADINGAGENTS_AVAILABLE or TradingAgentsGraph is None:
            logger.error("TradingAgents package is not installed in this environment.")
            return {
                "success": False,
                "error": "TradingAgents package not installed",
                "broker_symbol": broker_symbol,
                "ticker": ticker,
                "trade_date": date_str,
                "rating": "REVIEW",
                "action": "HOLD",
            }

        logger.info(f"Initializing TradingAgents for {broker_symbol} (Ticker: {ticker}, Type: {asset_type}) on {date_str}...")

        # For crypto/commodities/forex, skip SEC company fundamentals for speed & reliability
        active_analysts = analysts
        if asset_type in ("crypto", "commodity", "forex") and "fundamentals" in active_analysts:
            active_analysts = tuple(a for a in active_analysts if a != "fundamentals")

        # Initialize TradingAgentsGraph
        graph = TradingAgentsGraph(
            selected_analysts=active_analysts,
            debug=self.debug,
            config=self.config
        )

        try:
            final_state, rating = graph.propagate(
                company_name=ticker,
                trade_date=date_str,
                asset_type=asset_type
            )
        except Exception as e:
            logger.error(f"TradingAgents propagation failed for {broker_symbol}: {e}", exc_info=True)
            return {
                "success": False,
                "error": str(e),
                "broker_symbol": broker_symbol,
                "ticker": ticker,
                "trade_date": date_str,
                "rating": RATING_REVIEW,
                "action": "HOLD",
            }

        decision_text = final_state.get("final_trade_decision", "")
        extracted_rating = rating or run_rating(final_state) or parse_rating(decision_text)

        # Determine directional action from 5-tier rating
        action = self._rating_to_action(extracted_rating)

        # Extract structured details
        bull_arguments = final_state.get("investment_debate_state", {}).get("bull_history", [])
        bear_arguments = final_state.get("investment_debate_state", {}).get("bear_history", [])
        risk_neutral = final_state.get("risk_debate_state", {}).get("neutral_history", [])
        risk_conservative = final_state.get("risk_debate_state", {}).get("conservative_history", [])

        # Parse potential stop loss / targets mentioned in text
        sl_tp = self._extract_price_targets(decision_text)

        return {
            "success": True,
            "broker_symbol": broker_symbol,
            "ticker": ticker,
            "asset_type": asset_type,
            "display_name": display_name,
            "trade_date": date_str,
            "rating": extracted_rating,
            "action": action,
            "decision_text": decision_text,
            "market_report": final_state.get("market_report", ""),
            "news_report": final_state.get("news_report", ""),
            "sentiment_report": final_state.get("sentiment_report", ""),
            "fundamentals_report": final_state.get("fundamentals_report", ""),
            "bull_summary": bull_arguments[-1] if bull_arguments else "N/A",
            "bear_summary": bear_arguments[-1] if bear_arguments else "N/A",
            "risk_summary": risk_conservative[-1] if risk_conservative else (risk_neutral[-1] if risk_neutral else "N/A"),
            "extracted_targets": sl_tp,
            "timestamp": datetime.now().isoformat()
        }

    def _rating_to_action(self, rating: str) -> str:
        """Translates 5-tier rating to executable Action."""
        r = (rating or "").strip().capitalize()
        if r in ("Buy", "Overweight"):
            return "BUY"
        elif r in ("Sell", "Underweight"):
            return "SELL"
        else:
            return "HOLD"

    def _extract_price_targets(self, text: str) -> Dict[str, Optional[float]]:
        """Heuristic regex parser for stop loss and target profit in text."""
        result = {"stop_loss": None, "take_profit": None}
        if not text:
            return result

        sl_match = re.search(r"(?:stop[\s\-_]*loss|SL)\s*(?:at|of|level|around|[:\-—=])*\s*\$?([0-9]+(?:\.[0-9]+)?)", text, re.IGNORECASE)
        tp_match = re.search(r"(?:take[\s\-_]*profit|target(?:[\s\-_]*price)?|TP)\s*(?:at|of|level|around|[:\-—=])*\s*\$?([0-9]+(?:\.[0-9]+)?)", text, re.IGNORECASE)

        if sl_match:
            try:
                result["stop_loss"] = float(sl_match.group(1))
            except ValueError:
                pass
        if tp_match:
            try:
                result["take_profit"] = float(tp_match.group(1))
            except ValueError:
                pass

        return result
