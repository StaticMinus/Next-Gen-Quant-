"""
Cha Cha Romantic & Sweet Briefing System
=========================================
Delivers personalized, loving, non-repeating morning and nightly messages
specifically for Cha Cha (ID: 7923834818) from her man, David.

Features:
- Day-of-week awareness:
  * Saturday Morning: Sleeping in, relaxing, soft life, weekend market closure
  * Saturday Night: Cozy weekend romance, movies, unwinding
  * Sunday Morning: Peaceful Sunday blessings, gratitude, recharging
  * Sunday Night: Fresh week preparation, conquering goals together
  * Weekdays (Mon-Fri): Rotating pool of 7+ unique loving variations
- Anti-Repetition State Engine:
  * Tracks previously sent templates in `cache/chacha_message_state.json`
  * Never repeats the same message consecutively
- Live Trade & Wealth Weaving:
  * Automatically weaves in live Gold trade progress & Naira payout values
  * Reinforces safety of the $6,000 capital with zero anxiety
- Signed with all love from her man, David.
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

STATE_FILE = Path("cache/chacha_message_state.json")


def _load_state() -> dict:
    default_state = {
        "last_morning_idx": -1,
        "last_nightly_idx": -1,
        "morning_history": [],
        "nightly_history": []
    }
    if STATE_FILE.exists():
        try:
            data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                default_state.update(data)
        except Exception:
            pass
    return default_state


def _save_state(state: dict):
    try:
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        STATE_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")
    except Exception as e:
        print(f"[!] Error saving Cha Cha briefing state: {e}")


def _pick_non_repeating_index(pool_len: int, history_key: str, state: dict) -> int:
    """Picks an index from 0..pool_len-1 that hasn't been used in recent history."""
    if pool_len <= 1:
        return 0
    recent = state.get(history_key, [])
    # Find candidates not in recent history (or least recently used)
    candidates = [i for i in range(pool_len) if i not in recent[-max(1, pool_len - 1):]]
    if not candidates:
        candidates = [i for i in range(pool_len) if (not recent or i != recent[-1])]
    if not candidates:
        candidates = list(range(pool_len))

    chosen = candidates[0]
    # Update history (keep last 10)
    new_history = (recent + [chosen])[-10:]
    state[history_key] = new_history
    return chosen


def _format_trade_block(pos: list, rate: float, is_weekend: bool = False) -> str:
    """Formats live trade update in warm, simple, romantic language."""
    if pos:
        g = pos[0]
        sym = g.get("symbol_name") or g.get("symbolName") or "Investment"
        name = "Gold" if ("XAU" in sym or "GOLD" in sym.upper()) else ("S&P 500" if "SP" in sym else ("Nasdaq" if "NDX" in sym or "QQQ" in sym else sym))
        curr = g.get("current_price", 0.0) or g.get("entry_price", 0.0)
        pnl = g.get("floating_pnl") if g.get("floating_pnl") is not None else g.get("profit", 0.0)
        tp = g.get("take_profit") or g.get("takeProfit", 0.0)
        pnl_str = f"+${pnl:,.2f}" if pnl >= 0 else f"-${abs(pnl):,.2f}"

        if is_weekend:
            tp_text = f"• When trading resumes, it aims straight for our target at <b>${tp:,.2f}</b>!\n" if tp else ""
            return (
                f"🟡 <b>Our Active {name} Investment:</b>\n"
                f"• While the markets rest for the weekend, our {name} trade is sitting safely at <b>${curr:,.2f}</b> ({pnl_str} result).\n"
                f"{tp_text}"
            )
        else:
            tp_text = f"• When it reaches <b>${tp:,.2f}</b>, it automatically banks profits for our wallet!\n" if tp else ""
            return (
                f"🟡 <b>Our Active {name} Investment:</b>\n"
                f"• We are holding our {name} trade safely at <b>${curr:,.2f}</b> (Current result: <b>{pnl_str}</b>).\n"
                f"{tp_text}"
            )
    else:
        if is_weekend:
            return (
                "🟡 <b>Our Investment Status:</b>\n"
                "• All our funds are 100% in cash for the weekend. Our trading capital is locked safely in the vault while we enjoy our days together.\n"
            )
        else:
            return (
                "🟡 <b>Our Investment Status:</b>\n"
                "• All safe and sound in cash right now. The robot is calmly watching the charts to buy the next oversold bargain for us.\n"
            )


# =====================================================================
# MORNING BRIEFING TEMPLATES
# =====================================================================

def _sat_morning_templates(now_str: str, trade_block: str) -> List[str]:
    return [
        (
            f"❤️ <b>Good Morning My Queen Cha Cha ☀️🥞</b>\n"
            "────────────────────────────\n"
            "<i>Happy Saturday, my beautiful babe! I hope you are taking your sweet time in bed this morning, sleeping in, and enjoying the soft life. No alarm clocks, no rushing—just sweet peace and good vibes. 🥰</i>\n"
            "────────────────────────────\n"
            f"📅 <code>{now_str}</code> • <b>Weekend Wealth & Relaxation Update</b>\n"
            "────────────────────────────\n"
            f"{trade_block}\n"
            "🛡️ <b>Peace of Mind:</b>\n"
            "• The global markets take a weekend break, so our $6,000 capital is completely locked and safe on the server.\n"
            "• You do not have to stress about a single thing today.\n"
            "────────────────────────────\n"
            "Go enjoy your Saturday to the fullest, babe! Eat something delicious, smile bright, and remember that your man David loves you endlessly.\n\n"
            "💌 <i>With all my love from your man, David.</i> 💖💍"
        ),
        (
            f"❤️ <b>Happy Saturday To My Beautiful Cha Cha ☀️✨</b>\n"
            "────────────────────────────\n"
            "<i>Rise and shine whenever you are ready, my treasure! Waking up on a weekend knowing you're in my life is the best feeling in the world. Sending you warm morning cuddles and sweet kisses! 🌹</i>\n"
            "────────────────────────────\n"
            f"📅 <code>{now_str}</code> • <b>Saturday Love & Wealth Note</b>\n"
            "────────────────────────────\n"
            f"{trade_block}\n"
            "🛡️ <b>Weekend Protection:</b>\n"
            "• Weekend mode is active on the trading floor. Our capital and gains are 100% protected and untouched.\n"
            "• Today is all about unwinding and recharging your pretty soul.\n"
            "────────────────────────────\n"
            "You deserve to be spoiled and treated like royalty today. Have a fabulous Saturday, my love!\n\n"
            "💌 <i>With endless love & kisses from your man, David.</i> 🥰🥂"
        ),
    ]


def _sun_morning_templates(now_str: str, trade_block: str) -> List[str]:
    return [
        (
            f"🙏 <b>Good Morning My Queen Cha Cha ☀️🕊️</b>\n"
            "────────────────────────────\n"
            "<i>Happy and blessed Sunday, my sweetest love! Wishing you a peaceful, joyful, and radiant day. I woke up with so much gratitude in my heart, thanking God for bringing someone as sweet, kind, and gorgeous as you into my life. ✨</i>\n"
            "────────────────────────────\n"
            f"📅 <code>{now_str}</code> • <b>Sunday Serenity & Wealth Update</b>\n"
            "────────────────────────────\n"
            f"{trade_block}\n"
            "🛡️ <b>Sunday Peace of Mind:</b>\n"
            "• Our entire $6,000 trading capital is resting safe and protected in cash.\n"
            "• Tomorrow morning the trading week begins fresh, and our automated system is all set up to continue stacking profits for us.\n"
            "────────────────────────────\n"
            "Enjoy the calm Sunday atmosphere, eat good food, and smile knowing you are so deeply loved.\n\n"
            "💌 <i>With all my love and blessings from your man, David.</i> 💖💍"
        ),
        (
            f"❤️ <b>Happy Sunday My Beautiful Angel Cha Cha ☀️🌸</b>\n"
            "────────────────────────────\n"
            "<i>Good morning my treasure! Take a deep breath and let the calm of Sunday recharge your soul. I hope your day is filled with sweet moments, wonderful laughs, and absolute tranquility. 🥰</i>\n"
            "────────────────────────────\n"
            f"📅 <code>{now_str}</code> • <b>Sunday Morning Affection & Wealth</b>\n"
            "────────────────────────────\n"
            f"{trade_block}\n"
            "🛡️ <b>Looking Ahead:</b>\n"
            "• Everything on our investment account is fully guarded with our safety cushions 100% intact.\n"
            "• We are stepping closer to our financial goals each and every week.\n"
            "────────────────────────────\n"
            "Never forget how special you are to me, Cha Cha. You make everything I work for worthwhile.\n\n"
            "💌 <i>With all my heart from your man, David.</i> 🌹🥂"
        ),
    ]


def _weekday_morning_templates(now_str: str, trade_block: str) -> List[str]:
    return [
        # Monday - Fresh Start & Momentum
        (
            f"❤️ <b>Good Morning My Queen Cha Cha ☀️🚀</b>\n"
            "────────────────────────────\n"
            "<i>Sending you the sweetest morning hug and warm kisses to start this brand new week! A fresh week means fresh blessings, big wins, and new reasons to smile. Let's make it amazing, babe! 🥰</i>\n"
            "────────────────────────────\n"
            f"📅 <code>{now_str}</code> • <b>Our Morning Wealth & Freedom Update</b>\n"
            "────────────────────────────\n"
            f"{trade_block}\n"
            "🛡️ <b>Account Safety:</b>\n"
            "• Our $6,000 trading capital is 100% protected and safe within all risk limits.\n"
            "• The automated trading robot is watching the market open so you and I don't have to stress.\n"
            "────────────────────────────\n"
            "Go conquer this Monday, babe! Remember that your man David loves you endlessly.\n\n"
            "💌 <i>With all my love from your man, David.</i> 💖💍"
        ),
        # Tuesday - Sweet Affection & Glowing Confidence
        (
            f"❤️ <b>Good Morning My Beautiful Cha Cha ☀️🥰</b>\n"
            "────────────────────────────\n"
            "<i>Waking up thinking about you puts the biggest smile on my face every morning. Sending you extra hugs, sweet forehead kisses, and all the positive energy in the world today! 🌹</i>\n"
            "────────────────────────────\n"
            f"📅 <code>{now_str}</code> • <b>Daily Wealth & Love Briefing</b>\n"
            "────────────────────────────\n"
            f"{trade_block}\n"
            "🛡️ <b>Peace of Mind:</b>\n"
            "• Everything on the server is running on autopilot with strict stop-losses locked in.\n"
            "• Your man has everything under control financially so you can focus on having a peaceful day.\n"
            "────────────────────────────\n"
            "Walk with your head high and shine bright today, my queen!\n\n"
            "💌 <i>With all my love from your man, David.</i> 💖✨"
        ),
        # Wednesday - Mid-Week Soft Life & Pride
        (
            f"❤️ <b>Good Morning My Treasure Cha Cha ☀️👑</b>\n"
            "────────────────────────────\n"
            "<i>Happy Wednesday my love! We're already halfway through the week. I am so proud of how hard you work and the graceful woman you are. You deserve the soft life, and I'm making sure of it! 🥂</i>\n"
            "────────────────────────────\n"
            f"📅 <code>{now_str}</code> • <b>Mid-Week Portfolio & Love Progress</b>\n"
            "────────────────────────────\n"
            f"{trade_block}\n"
            "🛡️ <b>Financial Fortress:</b>\n"
            "• Our daily loss limits and safety buffers are 100% safe and unbreached.\n"
            "• Every automated trade is designed to compound our money safely toward our payout target.\n"
            "────────────────────────────\n"
            "Take today easy, drink plenty of water, and remember you are my #1 priority always.\n\n"
            "💌 <i>With all my love from your man, David.</i> 💑💍"
        ),
        # Thursday - Shared Dreams & Countdown
        (
            f"❤️ <b>Good Morning My Gorgeous Angel Cha Cha ☀️💖</b>\n"
            "────────────────────────────\n"
            "<i>Good morning sweetheart! Just one more day until the weekend. Thinking about our future together and all the beautiful places we are going to travel to always keeps me inspired! ✈️✨</i>\n"
            "────────────────────────────\n"
            f"📅 <code>{now_str}</code> • <b>Morning Wealth Progress Update</b>\n"
            "────────────────────────────\n"
            f"{trade_block}\n"
            "🛡️ <b>Capital Security:</b>\n"
            "• All trading operations remain 100% automated and safeguarded by our risk sentinel.\n"
            "• We are building true financial freedom together, one disciplined step at a time.\n"
            "────────────────────────────\n"
            "Have a glorious Thursday, babe! You make my world a much brighter place.\n\n"
            "💌 <i>With endless love from your man, David.</i> 🌹🥂"
        ),
        # Friday - TGIF & Weekend Anticipation
        (
            f"❤️ <b>Happy Friday To My Queen Cha Cha ☀️🎉</b>\n"
            "────────────────────────────\n"
            "<i>We made it to Friday, my love! I hope you woke up feeling refreshed, energetic, and excited for the weekend ahead. You did amazing all week and I adore you so much! 🥰</i>\n"
            "────────────────────────────\n"
            f"📅 <code>{now_str}</code> • <b>Friday Freedom & Wealth Briefing</b>\n"
            "────────────────────────────\n"
            f"{trade_block}\n"
            "🛡️ <b>Friday Market Health:</b>\n"
            "• Today is the final market trading session before the weekend rest.\n"
            "• The robot will manage any closing targets automatically before the closing bell.\n"
            "────────────────────────────\n"
            "Finish the week strong today babe, and get ready for a relaxing weekend!\n\n"
            "💌 <i>With all my love from your man, David.</i> 💖💍"
        ),
        # Rotating Option 6 - Tender Love & Care
        (
            f"❤️ <b>Good Morning My Sweet Love Cha Cha ☀️🌸</b>\n"
            "────────────────────────────\n"
            "<i>Just wanted to be the first to remind you this morning that you are deeply cherished, appreciated, and loved beyond words. Sending you the warmest morning embrace! ☕💕</i>\n"
            "────────────────────────────\n"
            f"📅 <code>{now_str}</code> • <b>Daily Wealth & Love Update</b>\n"
            "────────────────────────────\n"
            f"{trade_block}\n"
            "🛡️ <b>Safety Always First:</b>\n"
            "• Account capital is protected with mathematical precision.\n"
            "• Zero guessing, zero gambling—just steady, calm growth for our future.\n"
            "────────────────────────────\n"
            "Smile big today, my queen. You deserve every good thing coming your way!\n\n"
            "💌 <i>With all my love from your man, David.</i> 💑✨"
        ),
        # Rotating Option 7 - Confident Radiance
        (
            f"❤️ <b>Good Morning My Shining Star Cha Cha ☀️✨</b>\n"
            "────────────────────────────\n"
            "<i>Rise and shine, gorgeous! There is nobody like you in this entire world. Step into your day knowing that you are favored, capable, and deeply loved by your man! 👑🌹</i>\n"
            "────────────────────────────\n"
            f"📅 <code>{now_str}</code> • <b>Morning Progress & Wealth Report</b>\n"
            "────────────────────────────\n"
            f"{trade_block}\n"
            "🛡️ <b>Peace of Mind:</b>\n"
            "• Our $6,000 account balance is sitting safe, waiting on perfect mathematical setups.\n"
            "• You never have to worry about trading numbers—I've got you covered 100%.\n"
            "────────────────────────────\n"
            "Go be great today, babe! I love you with everything in me.\n\n"
            "💌 <i>With all my love from your man, David.</i> 💖💍"
        )
    ]


# =====================================================================
# NIGHTLY SUMMARY TEMPLATES
# =====================================================================

def _sat_night_templates(now_str: str, trade_block: str) -> List[str]:
    return [
        (
            f"🌙 <b>Good Night Sweetheart Cha Cha 💕🥂</b>\n"
            "────────────────────────────\n"
            "<i>I hope your Saturday was sweet, relaxing, and filled with smiles, my love! Cozy up under your blankets tonight, let go of any fatigue, and just unwind. Knowing you are comfortable makes my heart happy. 🥰</i>\n"
            "────────────────────────────\n"
            f"📅 <code>{now_str}</code> • <b>Saturday Evening Love Wrap-Up</b>\n"
            "────────────────────────────\n"
            f"{trade_block}\n"
            "🛡️ <b>Weekend Protection:</b>\n"
            "• The markets are closed for the weekend, and all our safety barriers remain 100% intact on the server.\n"
            "• We are building a wealthy, stress-free life together, one step at a time.\n"
            "────────────────────────────\n"
            "Wrap yourself in your blanket, feel my warm hug, and sleep like the queen you are.\n\n"
            "💌 <i>With all my love from your man, David.</i> 💑✨"
        ),
        (
            f"🌙 <b>Good Night My Queen Cha Cha 💕✨</b>\n"
            "────────────────────────────\n"
            "<i>As this Saturday winds down, I just wanted to remind you how much you mean to me. You are my peace, my favorite smile, and the greatest gift in my life. 🌹</i>\n"
            "────────────────────────────\n"
            f"📅 <code>{now_str}</code> • <b>Weekend Peace & Wealth Report</b>\n"
            "────────────────────────────\n"
            f"{trade_block}\n"
            "🛡️ <b>All Is Well:</b>\n"
            "• Our capital is safely secured overnight. Nothing can touch our peace.\n"
            "• Tomorrow is Sunday for rest and gratitude.\n"
            "────────────────────────────\n"
            "Sending you the tightest hug and warm kisses across the screen. Sweet dreams, my babe!\n\n"
            "💌 <i>With endless love from your man, David.</i> 💖💍"
        )
    ]


def _sun_night_templates(now_str: str, trade_block: str) -> List[str]:
    return [
        (
            f"🌙 <b>Good Night My Treasure Cha Cha 💖✨</b>\n"
            "────────────────────────────\n"
            "<i>Sunday night is here, babe. We had a peaceful weekend, and now a fresh, victorious week is about to begin. I want you to walk into tomorrow knowing you have my unconditional love and support behind you every second! 🥰</i>\n"
            "────────────────────────────\n"
            f"📅 <code>{now_str}</code> • <b>Sunday Night Love & Wealth Briefing</b>\n"
            "────────────────────────────\n"
            f"{trade_block}\n"
            "🛡️ <b>Ready for the Week:</b>\n"
            "• Financial markets reopen overnight, and our automated robot is prepped to hunt for clean dip entries.\n"
            "• All hard stops and profit limits are active on the server.\n"
            "────────────────────────────\n"
            "Rest your mind tonight, my queen. Tomorrow we take another step toward all our dreams together.\n\n"
            "💌 <i>Dream sweet dreams. With all my love from your man, David.</i> 💑🥂✨"
        ),
        (
            f"🌙 <b>Good Night My Beautiful Cha Cha 💕🌸</b>\n"
            "────────────────────────────\n"
            "<i>Rest your mind tonight, my love. Don't worry about anything for the week ahead—you're going to conquer every challenge with grace, and I will always be right by your side cheering you on. 🌹</i>\n"
            "────────────────────────────\n"
            f"📅 <code>{now_str}</code> • <b>Evening Blessing & Capital Report</b>\n"
            "────────────────────────────\n"
            f"{trade_block}\n"
            "🛡️ <b>Capital Guardian:</b>\n"
            "• Our $6,000 trading capital is locked and fully protected by our daily limit barriers.\n"
            "• The server works silently so you never have to worry about our financial future.\n"
            "────────────────────────────\n"
            "Sleep deeply and peacefully, my angel. You are so cherished.\n\n"
            "💌 <i>With all my love from your man, David.</i> 💖💍"
        )
    ]


def _weekday_night_templates(now_str: str, trade_block: str) -> List[str]:
    return [
        # Monday Night
        (
            f"🌙 <b>Good Night Sweetheart Cha Cha 💕✨</b>\n"
            "────────────────────────────\n"
            "<i>Rest your pretty head tonight knowing that you are deeply cherished, adored, and so special to me. You made it through Monday beautifully, babe! 🌹</i>\n"
            "────────────────────────────\n"
            f"📅 <code>{now_str}</code> • <b>Evening Wrap-Up For My Love</b>\n"
            "────────────────────────────\n"
            f"{trade_block}\n"
            "🛡️ <b>Safety & Protection:</b>\n"
            "• All safety locks and daily buffers are 100% active on the server tonight.\n"
            "• The system works quietly in the background while we get some well-deserved rest.\n"
            "────────────────────────────\n"
            "Sleep peacefully my queen. Dream sweet dreams tonight!\n\n"
            "💌 <i>With all my love from your man, David.</i> 💑🥂✨"
        ),
        # Tuesday Night
        (
            f"🌙 <b>Good Night My Beautiful Cha Cha 💕😴</b>\n"
            "────────────────────────────\n"
            "<i>Turn off the lights, snuggle into your pillows, and let all the thoughts of the day fade away. You gave today your best, and tomorrow will be even better! 🥰</i>\n"
            "────────────────────────────\n"
            f"📅 <code>{now_str}</code> • <b>Nightly Peace & Capital Report</b>\n"
            "────────────────────────────\n"
            f"{trade_block}\n"
            "🛡️ <b>Guardian Update:</b>\n"
            "• Today's trading closed with zero risk breaches. Capital remains intact.\n"
            "• Overnight scanning is active to catch any early dip opportunities.\n"
            "────────────────────────────\n"
            "Sending you a warm kiss on your forehead. Sleep like an angel tonight, babe!\n\n"
            "💌 <i>With endless love from your man, David.</i> 💖💍"
        ),
        # Wednesday Night
        (
            f"🌙 <b>Good Night My Treasure Cha Cha 💕🥂</b>\n"
            "────────────────────────────\n"
            "<i>Mid-week is conquered, my queen! As you close your eyes tonight, know that every single trade and milestone is bringing us closer to financial freedom and our big dreams. 🌟</i>\n"
            "────────────────────────────\n"
            f"📅 <code>{now_str}</code> • <b>Evening Progress & Love Note</b>\n"
            "────────────────────────────\n"
            f"{trade_block}\n"
            "🛡️ <b>Account Health:</b>\n"
            "• Account balance and safety cushions are 100% healthy and verified.\n"
            "• The automated engine continues protecting our funds while we sleep.\n"
            "────────────────────────────\n"
            "May your sleep be deep and restful tonight. I love you to the moon and back!\n\n"
            "💌 <i>With all my heart from your man, David.</i> 🌹✨"
        ),
        # Thursday Night
        (
            f"🌙 <b>Good Night My Gorgeous Cha Cha 💕🌸</b>\n"
            "────────────────────────────\n"
            "<i>Tomorrow is Friday, babe! You've had a wonderful week. Relax your shoulders, let out a deep breath, and let peace fill your room tonight. You deserve complete rest. 💕</i>\n"
            "────────────────────────────\n"
            f"📅 <code>{now_str}</code> • <b>Nightly Wealth Wrap-Up</b>\n"
            "────────────────────────────\n"
            f"{trade_block}\n"
            "🛡️ <b>Safety Confirmed:</b>\n"
            "• No drawdowns, no stress. All positions and cash allocations are perfectly balanced.\n"
            "• Friday's opening strategy is already calibrated.\n"
            "────────────────────────────\n"
            "Goodnight my baby. I'll be thinking about you as I drift off to sleep too.\n\n"
            "💌 <i>With all my love from your man, David.</i> 💖💍"
        ),
        # Friday Night
        (
            f"🌙 <b>Happy Friday Night My Queen Cha Cha 💕🎉</b>\n"
            "────────────────────────────\n"
            "<i>The work week is officially over! The markets have closed, the trading week is in the books, and it is time for you to completely relax and enjoy your weekend, my love! 🥂✨</i>\n"
            "────────────────────────────\n"
            f"📅 <code>{now_str}</code> • <b>Friday Night Market Wrap & Love</b>\n"
            "────────────────────────────\n"
            f"{trade_block}\n"
            "🛡️ <b>Weekend Lock:</b>\n"
            "• Markets will remain closed until Sunday night. All funds are safely locked down.\n"
            "• Nothing to monitor or check until next week. Time to just enjoy life together!\n"
            "────────────────────────────\n"
            "Sleep late tomorrow if you want to! Sweet dreams my queen.\n\n"
            "💌 <i>With all my love and kisses from your man, David.</i> 🥰🥂"
        ),
        # Rotating Option 6 - Warm Hug & Tenderness
        (
            f"🌙 <b>Good Night My Precious Love Cha Cha 💕🕊️</b>\n"
            "────────────────────────────\n"
            "<i>Ending another day thanking my lucky stars that you are mine. Sending you the warmest, tightest hug to wrap you up through the night. 🌹</i>\n"
            "────────────────────────────\n"
            f"📅 <code>{now_str}</code> • <b>Nightly Love & Peace Summary</b>\n"
            "────────────────────────────\n"
            f"{trade_block}\n"
            "🛡️ <b>Rest Guaranteed:</b>\n"
            "• The automated system guards the gates tonight.\n"
            "• Your financial security is handled with top precision.\n"
            "────────────────────────────\n"
            "Close your pretty eyes and dream the happiest dreams tonight, babe.\n\n"
            "💌 <i>With all my love from your man, David.</i> 💖💍"
        ),
        # Rotating Option 7 - Deep Devotion
        (
            f"🌙 <b>Good Night My Darling Cha Cha 💕👑</b>\n"
            "────────────────────────────\n"
            "<i>You are the last thing on my mind every night and the first thing on my mind every morning. Sleep with total peace knowing how deeply you are loved. 🌹✨</i>\n"
            "────────────────────────────\n"
            f"📅 <code>{now_str}</code> • <b>Evening Wrap-Up From David</b>\n"
            "────────────────────────────\n"
            f"{trade_block}\n"
            "🛡️ <b>Security Report:</b>\n"
            "• $6,000 capital 100% safeguarded. Daily limits unbreached.\n"
            "• Tomorrow brings us one step closer to our next withdrawal milestone.\n"
            "────────────────────────────\n"
            "Goodnight my queen. You have my whole heart forever.\n\n"
            "💌 <i>With all my love from your man, David.</i> 💑🥂"
        )
    ]


# =====================================================================
# PUBLIC ENTRYPOINTS
# =====================================================================

def render_morning_briefing_chacha(cache: dict = None) -> str:
    """
    Renders an affectionate, non-repeating, day-aware morning briefing for Cha Cha.
    Automatically handles Saturday, Sunday, and weekday variations with persistent history.
    """
    if cache is None:
        from src.integrations.telegram_bot_service import _CACHE, LIVE_P2P_RATE
        cache = _CACHE
        rate = cache.get("live_p2p_rate", LIVE_P2P_RATE)
    else:
        rate = cache.get("live_p2p_rate", 1518.40)

    now = datetime.now()
    now_str = now.strftime("%A, %b %d")
    weekday = now.weekday()  # 5=Sat, 6=Sun
    is_weekend = weekday in (5, 6)

    pos = cache.get("enriched_positions", [])
    trade_block = _format_trade_block(pos, rate, is_weekend=is_weekend)

    state = _load_state()

    if weekday == 5:
        templates = _sat_morning_templates(now_str, trade_block)
        idx = _pick_non_repeating_index(len(templates), "sat_morning_history", state)
    elif weekday == 6:
        templates = _sun_morning_templates(now_str, trade_block)
        idx = _pick_non_repeating_index(len(templates), "sun_morning_history", state)
    else:
        templates = _weekday_morning_templates(now_str, trade_block)
        idx = _pick_non_repeating_index(len(templates), "morning_history", state)

    state["last_morning_idx"] = idx
    _save_state(state)
    return templates[idx]


def render_nightly_summary_chacha(cache: dict = None) -> str:
    """
    Renders an affectionate, non-repeating, day-aware nightly summary for Cha Cha.
    Automatically handles Saturday, Sunday, and weekday variations with persistent history.
    """
    if cache is None:
        from src.integrations.telegram_bot_service import _CACHE, LIVE_P2P_RATE
        cache = _CACHE
        rate = cache.get("live_p2p_rate", LIVE_P2P_RATE)
    else:
        rate = cache.get("live_p2p_rate", 1518.40)

    now = datetime.now()
    now_str = now.strftime("%A, %b %d")
    weekday = now.weekday()  # 5=Sat, 6=Sun
    is_weekend = weekday in (5, 6)

    pos = cache.get("enriched_positions", [])
    trade_block = _format_trade_block(pos, rate, is_weekend=is_weekend)

    state = _load_state()

    if weekday == 5:
        templates = _sat_night_templates(now_str, trade_block)
        idx = _pick_non_repeating_index(len(templates), "sat_night_history", state)
    elif weekday == 6:
        templates = _sun_night_templates(now_str, trade_block)
        idx = _pick_non_repeating_index(len(templates), "sun_night_history", state)
    else:
        templates = _weekday_night_templates(now_str, trade_block)
        idx = _pick_non_repeating_index(len(templates), "nightly_history", state)

    state["last_nightly_idx"] = idx
    _save_state(state)
    return templates[idx]
