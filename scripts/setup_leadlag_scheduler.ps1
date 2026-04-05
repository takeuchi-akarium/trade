# Leadlag strategy - Task Scheduler setup
# Run as Administrator:
# powershell -ExecutionPolicy Bypass -File "G:\workspace\trade\scripts\setup_leadlag_scheduler.ps1"

$taskName = 'LeadlagMorningReport'
$projectRoot = (Resolve-Path "$PSScriptRoot\..").Path
$pythonPath = Join-Path $projectRoot '.venv\Scripts\python.exe'
$scriptPath = Join-Path $projectRoot 'src\batch_leadlag.py'
$logDir = Join-Path $projectRoot 'logs'

if (-not (Test-Path $logDir)) {
  New-Item -ItemType Directory -Path $logDir | Out-Null
}

$existing = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
if ($existing) {
  Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
  Write-Host 'Removed existing task.'
}

$action = New-ScheduledTaskAction `
  -Execute $pythonPath `
  -Argument $scriptPath `
  -WorkingDirectory $projectRoot

$trigger = New-ScheduledTaskTrigger -Daily -At 07:00

$settings = New-ScheduledTaskSettingsSet `
  -AllowStartIfOnBatteries `
  -DontStopIfGoingOnBatteries `
  -StartWhenAvailable `
  -ExecutionTimeLimit (New-TimeSpan -Minutes 30)

Register-ScheduledTask `
  -TaskName $taskName `
  -Action $action `
  -Trigger $trigger `
  -Settings $settings `
  -Description 'Leadlag morning signal report (daily 07:00)' `
  -RunLevel Highest

Write-Host ''
Write-Host 'Task registered successfully.'
Write-Host "  Task: $taskName"
Write-Host "  Time: Daily 07:00"
Write-Host "  Python: $pythonPath"
Write-Host "  Script: $scriptPath"
Write-Host ''
Write-Host 'Commands:'
Write-Host "  Check:  Get-ScheduledTask -TaskName $taskName"
Write-Host "  Run:    Start-ScheduledTask -TaskName $taskName"
Write-Host "  Delete: Unregister-ScheduledTask -TaskName $taskName"
