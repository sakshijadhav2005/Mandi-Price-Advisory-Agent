# Registers a Windows Scheduled Task that runs the daily job (deploy\daily.ps1) every evening.
# Run once from PowerShell in the project folder:
#     .\deploy\install-daily-task.ps1            (add -At 19:00 to change the time)
# If scripts are disabled:  powershell -ExecutionPolicy Bypass -File .\deploy\install-daily-task.ps1
#
# The task starts powershell.exe directly with the quoted script path. (schtasks /TR and .bat
# files break on a folder name containing "&" or spaces: the path is split by cmd.)
param([string]$At = "18:30", [string]$Name = "MandiDaily")

$script = Join-Path $PSScriptRoot "daily.ps1"
$action = New-ScheduledTaskAction -Execute "powershell.exe" `
    -Argument "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$script`""
$trigger = New-ScheduledTaskTrigger -Daily -At $At
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Hours 2)
Register-ScheduledTask -TaskName $Name -Action $action -Trigger $trigger -Settings $settings -Force | Out-Null

if ($?) {
  Write-Host "Task '$Name' runs $script daily at $At (or as soon as the PC is on, if it was off). Log: backend\daily.log"
  Write-Host "Run it now with:  Start-ScheduledTask -TaskName $Name"
}
