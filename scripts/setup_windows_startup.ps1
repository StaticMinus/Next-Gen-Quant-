# setup_windows_startup.ps1
# =========================
# Registers AgentQuant Telegram AI bot in Windows Task Scheduler
# to launch silently at user logon and automatically restart if interrupted.

$TaskName = "AgentQuant_TelegramAI"
$WorkDir = "C:\Users\David\Music\Trade\AgentQuant-main"
$VbsScript = "$WorkDir\scripts\run_background_bot.vbs"

if (!(Test-Path $VbsScript)) {
    Write-Error "Script not found: $VbsScript"
    exit 1
}

$Action = New-ScheduledTaskAction -Execute "wscript.exe" -Argument "`"$VbsScript`"" -WorkingDirectory $WorkDir
$Trigger = New-ScheduledTaskTrigger -AtLogOn
$Settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit 0

try {
    Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger -Settings $Settings -Description "AgentQuant 24/7 Telegram AI Bot & Risk Guardian" -Force
    Write-Host "✅ Successfully registered '$TaskName' to launch automatically at logon!"
    Write-Host "ℹ️ You can also start it on-demand with: Start-ScheduledTask -TaskName '$TaskName'"
} catch {
    Write-Error "Failed to register scheduled task: $_"
}
