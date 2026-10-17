"""
AgentQuant GitHub Actions Cloud Runner
======================================
Autonomous cloud execution script designed specifically for GitHub Actions runners.
Runs the Telegram Gold Copier (Mode A: 2-Ticket Execution) and the Telegram Bot Service
in an isolated cloud container without requiring local laptop execution.
"""

import os
import sys
import time
import argparse
import logging
import threading
from datetime import datetime, timezone
from pathlib import Path
from dotenv import load_dotenv

# Ensure root directory is in sys.path
ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

# Load .env if present (fallback for local testing)
load_dotenv(ROOT_DIR / ".env")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("CloudActionsRunner")


def send_cloud_telegram_notification(title: str, message: str):
    """Sends a formatted notification to the primary Telegram chat."""
    import requests
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if not bot_token or not chat_id:
        logger.warning("Telegram credentials not configured. Skipping notification.")
        return

    text = f"☁️ <b>{title}</b>\n\n{message}\n\n<i>Time: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}</i>"
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    try:
        requests.post(url, json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"}, timeout=10)
    except Exception as e:
        logger.error(f"Failed to send Telegram notification: {e}")


if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

def run_system_diagnostic():
    """Runs the pre-live diagnostic check script."""
    import subprocess
    logger.info("Executing Pre-Live Diagnostic Suite...")
    try:
        script_path = ROOT_DIR / "scripts" / "pre_live_system_check.py"
        res = subprocess.run(
            [sys.executable, str(script_path)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False
        )
        if hasattr(sys.stdout, "buffer"):
            sys.stdout.buffer.write(res.stdout.encode("utf-8", errors="replace"))
            sys.stdout.buffer.flush()
        else:
            print(res.stdout.encode("ascii", errors="replace").decode("ascii"))
        return "GO — SYSTEM IS PREPARED FOR LIVE TRADING" in res.stdout or res.returncode == 0
    except Exception as e:
        logger.error(f"Diagnostic failed with exception: {e}")
        return False


def main():
    parser = argparse.ArgumentParser(description="AgentQuant GitHub Actions Cloud Runner")
    parser.add_argument("--action", choices=["start_live_copier", "diagnostic_check_only"], default="start_live_copier")
    parser.add_argument("--duration-hours", type=float, default=5.8, help="Run duration in hours before graceful exit (max 6h for GH Actions)")
    args = parser.parse_args()

    account_id = os.getenv("CTRADER_ACCOUNT_ID", "5942153")
    ticket_mode = os.getenv("GOLD_COPIER_TICKET_MODE", "TWO_TICKETS")
    lot_size = os.getenv("GOLD_COPIER_LOT_SIZE", "0.05")

    logger.info("=" * 60)
    logger.info("AGENTQUANT CLOUD ACTIONS RUNNER INITIATED")
    logger.info(f"Target cTrader Account: {account_id}")
    logger.info(f"Execution Mode: {ticket_mode} (Lots: {lot_size})")
    logger.info(f"Requested Action: {args.action}")
    logger.info(f"Session Max Duration: {args.duration_hours:.2f} hours")
    logger.info("=" * 60)

    # 1. Diagnostic Check
    diagnostic_passed = run_system_diagnostic()
    if not diagnostic_passed:
        logger.error("❌ Diagnostic checks failed. Aborting cloud execution to protect capital.")
        send_cloud_telegram_notification(
            "AGENTQUANT CLOUD: PRE-FLIGHT CHECK FAILED",
            f"❌ Cloud runner diagnostic failed on GitHub Actions.\nAccount: <code>{account_id}</code>\nPlease verify secrets and API tokens."
        )
        sys.exit(1)

    if args.action == "diagnostic_check_only":
        logger.info("Diagnostic completed successfully. Exiting as requested.")
        send_cloud_telegram_notification(
            "AGENTQUANT CLOUD: HEALTHCHECK PASSED ✅",
            f"All cloud systems (cTrader MCP, Telegram Bot, Mode A Engine) verified and 100% operational in GitHub Actions."
        )
        return

    # 2. Notify Telegram that GitHub Actions Cloud Runner is LIVE
    send_cloud_telegram_notification(
        "AGENTQUANT CLOUD RUNNER: LIVE 🚀",
        f"<b>Environment:</b> GitHub Actions Cloud (Ubuntu VM)\n"
        f"<b>cTrader Account:</b> <code>{account_id}</code>\n"
        f"<b>Execution Mode:</b> Mode A (2 Tickets: TP1 + TP2 @ {lot_size} lots)\n"
        f"<b>Breakeven Shield:</b> Triggered at TP1 (+0.30pt buffer)\n"
        f"<b>Status:</b> Actively listening to VIP signals in real-time.\n"
        f"<i>Your laptop does NOT need to be powered on.</i>"
    )

    # 3. Launch Gold Copier Daemon Thread
    from src.integrations.webapp_server import launch_gold_copier_thread
    copier_thread = launch_gold_copier_thread()

    # 4. Launch WebApp / Healthcheck Server in background thread
    from src.integrations.webapp_server import launch_server_in_thread
    launch_server_in_thread(port=8080)

    # 5. Launch Telegram Bot Polling in background thread
    from src.integrations.telegram_bot_service import run_polling
    bot_thread = threading.Thread(target=run_polling, daemon=True, name="TelegramBotPolling")
    bot_thread.start()
    logger.info("[+] Telegram Bot polling service started in background thread.")

    # 6. Monitor Loop with duration timeout for GitHub Actions
    start_time = time.time()
    max_duration_seconds = args.duration_hours * 3600
    heartbeat_interval = 1800  # Log heartbeat every 30 minutes

    logger.info(f"Cloud Runner is running. Monitoring active signals for next {args.duration_hours} hours...")

    try:
        last_heartbeat = start_time
        while True:
            elapsed = time.time() - start_time
            if elapsed >= max_duration_seconds:
                logger.info(f"Reached allocated cycle duration of {args.duration_hours} hours. Preparing graceful handoff...")
                send_cloud_telegram_notification(
                    "AGENTQUANT CLOUD: CYCLE HANDOFF 🔄",
                    f"GitHub Actions runner completed scheduled {args.duration_hours}-hour cycle cleanly.\nAll open positions remain managed with protective Stop Losses on cTrader server."
                )
                break

            if time.time() - last_heartbeat >= heartbeat_interval:
                last_heartbeat = time.time()
                hours_remaining = (max_duration_seconds - elapsed) / 3600
                logger.info(f"[Heartbeat] Cloud Runner healthy. Uptime: {elapsed/3600:.2f}h. Remaining in cycle: {hours_remaining:.2f}h.")

            time.sleep(10)

    except (KeyboardInterrupt, SystemExit):
        logger.info("Shutdown signal received. Stopping Cloud Runner gracefully...")
    except Exception as e:
        logger.error(f"Unexpected error in cloud runner loop: {e}", exc_info=True)
        send_cloud_telegram_notification(
            "AGENTQUANT CLOUD ALERT ⚠️",
            f"An unexpected error occurred in GitHub Actions runner:\n<code>{e}</code>"
        )
        sys.exit(1)

    logger.info("Cloud Runner cycle finished cleanly.")


if __name__ == "__main__":
    main()
