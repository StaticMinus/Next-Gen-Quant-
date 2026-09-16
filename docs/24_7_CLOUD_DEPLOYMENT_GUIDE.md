# 24/7 Cloud Deployment Guide — AgentQuant Telegram AI & Risk Guardian

This guide explains why the Telegram AI stops when your computer is off and how to keep it running 24/7/365 in the cloud with zero downtime.

---

## 1. Why Does the Bot Stop When Your Computer Is Off?

The Telegram bot (`src/integrations/telegram_bot_service.py`) operates via **long-polling**:
- It runs as a local Python process on your Windows machine.
- Every few seconds, it asks Telegram's servers: *"Are there any new button clicks or messages from David?"*
- **When your PC is powered down or enters Sleep mode:**
  - The CPU stops executing instructions.
  - Power to your network adapter is disconnected.
  - The Python process suspends or terminates.
  - Telegram queues messages on their servers, but no local code is running to reply or manage trades.

To make the AI Coach and Autonomous Risk Guardian available **24 hours a day, 7 days a week**, the process must run on a server that never sleeps.

---

## 2. Option A: 1-Click Cloud Deployment (Recommended)

Since your code is already synchronized to GitHub at [**StaticMinus/Next-Gen-Quant-**](https://github.com/StaticMinus/Next-Gen-Quant-), you can host the bot in the cloud in under 3 minutes.

### Method 1: Railway (Easiest — Takes 2 Minutes)
1. Go to [railway.app](https://railway.app) and log in with your GitHub account.
2. Click **"New Project"** &rarr; **"Deploy from GitHub repo"**.
3. Select `StaticMinus/Next-Gen-Quant-`.
4. Under **Variables**, add the following environment variables (from your local `.env`):
   - `TELEGRAM_BOT_TOKEN`
   - `TELEGRAM_CHAT_ID`
   - `CTRADER_ACCOUNT_ID`
   - `CTRADER_ACCESS_TOKEN`
   - `OPENROUTER_API_KEY`
5. Under **Settings** &rarr; **Start Command**, enter:
   ```bash
   python -m src.integrations.telegram_bot_service
   ```
6. Click **Deploy**. Railway will build the project and keep it running 24/7. You can shut down your laptop anytime and your bot will stay online.

### Method 2: Render.com Background Worker
1. Go to [render.com](https://render.com) and link your GitHub account.
2. Click **"New +"** &rarr; **"Background Worker"** (or use the included `render.yaml` Blueprint).
3. Select `Next-Gen-Quant-`.
4. Set Build Command: `pip install -e '.[llm,data]'`
5. Set Start Command: `python -m src.integrations.telegram_bot_service`
6. Add your environment variables and click **Create Background Worker**.

---

## 3. Option B: Local Windows Auto-Start Service

If you prefer to run the bot on your personal PC whenever you are using Windows:

1. Open PowerShell as Administrator.
2. Navigate to your project directory:
   ```powershell
   cd C:\Users\David\Music\Trade\AgentQuant-main
   ```
3. Run the automated setup script:
   ```powershell
   powershell -ExecutionPolicy Bypass -File scripts\setup_windows_startup.ps1
   ```
4. **What this does:**
   - Registers a Windows Scheduled Task (`AgentQuant_TelegramAI`).
   - Automatically launches `scripts/run_background_bot.vbs` completely silently in the background at Windows logon.
   - Restarts the process automatically if it ever crashes.

> [!NOTE]
> Local background tasks only run while your computer is powered on. For true 24/7 reliability when your laptop is turned off or in your bag, use **Option A (Railway / Render)**.
