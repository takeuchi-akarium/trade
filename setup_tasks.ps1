# Task Scheduler registration script
# Run as admin: powershell -ExecutionPolicy Bypass -File setup_tasks.ps1

$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"

if (-not (Test-Path $Python)) {
    Write-Host "ERROR: $Python not found" -ForegroundColor Red
    exit 1
}

$Tasks = @(
    @{ Name = "Trade_5m_Price";   Script = "src\batch_5m.py";    Minutes = 5 }
    @{ Name = "Trade_5m_Signal";  Script = "src\batch_15m.py";   Minutes = 5 }
    @{ Name = "Trade_5m_TDnet";   Script = "src\batch_tdnet.py"; Minutes = 5 }
    @{ Name = "Trade_5m_RSS";     Script = "src\batch_rss.py";   Minutes = 5 }
)

foreach ($t in $Tasks) {
    $taskName = $t.Name
    $scriptPath = Join-Path $ProjectRoot $t.Script
    $interval = $t.Minutes

    $existing = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
    if ($existing) {
        Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
        Write-Host "  Removed existing: $taskName" -ForegroundColor Yellow
    }

    $action = New-ScheduledTaskAction -Execute $Python -Argument $scriptPath -WorkingDirectory $ProjectRoot

    $trigger = New-ScheduledTaskTrigger -Once -At (Get-Date) -RepetitionInterval (New-TimeSpan -Minutes $interval) -RepetitionDuration (New-TimeSpan -Days 365)

    $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Minutes 5)

    Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings -Description "Trade bot: $($t.Script) (every $($interval)min)" -Force | Out-Null

    Write-Host "OK $taskName (every $($interval)min)" -ForegroundColor Green
}

Write-Host ""
Write-Host "Done! Verify with:" -ForegroundColor Cyan
Write-Host "  Get-ScheduledTask -TaskName 'Trade_*' | Format-Table TaskName, State"
