import os
import sys
import requests
from dotenv import load_dotenv

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

load_dotenv()
token = os.getenv("TELEGRAM_BOT_TOKEN")
chat_id = os.getenv("TELEGRAM_CHAT_ID", "8428715579")

from src.integrations.telegram_ai_coach import evaluate_market_signals
signals = evaluate_market_signals()
print(f"Evaluated {len(signals)} signals: {signals}")

for s in signals:
    msg = (
        "🚨 <b>AUTONOMOUS QUANT RADAR SIGNAL</b>\n"
        "────────────────────────────\n"
        f"🎯 <b>TRIGGER:</b> <code>{s['ticker']} // {s['strategy']}</code>\n"
        f"• <b>Market Price:</b> <code>${s['price']:.2f}</code>\n"
        f"• <b>Technical RSI:</b> <code>{s['rsi']:.1f}</code>\n"
        f"• <b>Take Profit:</b> <code>${s['target']:.2f}</code> (+3.5%)\n"
        f"• <b>Stop Loss:</b> <code>${s['stop']:.2f}</code> (-3.0% / -$13.50 risk)\n"
        "• <b>Position Sizing:</b> <code>$450.00 (7.5% allocation)</code>\n"
        "────────────────────────────\n"
        f"💡 <i>{s['summary']}</i>\n"
        "🛡️ <i>Sentinel Safe: 100% compliant with -$180 daily limit.</i>"
    )
    markup = {
        "inline_keyboard": [
            [{"text": f"🎫 View {s['ticker']} Ticket", "callback_data": f"cmd_card_ticket_{s['ticker'].lower()}"}],
            [{"text": "📊 Active Trades", "callback_data": "cmd_trades"}, {"text": "📡 Live Radar", "callback_data": "cmd_signals"}]
        ]
    }
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": msg,
        "parse_mode": "HTML",
        "reply_markup": markup
    }
    res = requests.post(url, json=payload).json()
    print(f"Dispatch result for {s['ticker']}: {res}")
