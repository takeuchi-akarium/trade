# Task Scheduler registration script
# Run as admin: powershell -ExecutionPolicy Bypass -File setup_tasks.ps1

$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"

if (-not (Test-Path $Python)) {
    Write-Host "ERROR: $Python not found" -ForegroundColor Red
    exit 1
}

$taskName = "Trade_AutoTrader"
$scriptPath = Join-Path $ProjectRoot "src	raderun.py"

$existing = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
if ($existing) {
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
    Write-Host "  Removed existing: $taskName" -ForegroundColor Yellow
}

$action = New-ScheduledTaskAction -Execute $Python -Argument $scriptPath -WorkingDirectory $ProjectRoot
$trigger = New-ScheduledTaskTrigger -Daily -At "07:00"
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Minutes 5)

Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings -Description "BTC auto trader (daily 07:00)" -Force | Out-Null

Write-Host "OK $taskName (daily 07:00)" -ForegroundColor Green
Write-Host ""
Write-Host "Done! Verify with:" -ForegroundColor Cyan
Write-Host "  Get-ScheduledTask -TaskName Trade_* | Format-Table TaskName, State"
