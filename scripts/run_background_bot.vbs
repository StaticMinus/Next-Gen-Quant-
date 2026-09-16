' AgentQuant Silent Background Daemon Runner
Set WshShell = CreateObject("WScript.Shell")
WshShell.CurrentDirectory = "C:\Users\David\Music\Trade\AgentQuant-main"
WshShell.Run "cmd /c .venv\Scripts\python.exe -m src.integrations.telegram_bot_service", 0, False
