# Registers a Windows Scheduled Task that runs backend\manage.py daily every evening.
# Run once from PowerShell:  .\deploy\install-daily-task.ps1   (add -At 19:00 to change the time)
param([string]$At = "18:30", [string]$Name = "MandiDaily")
$bat = Join-Path $PSScriptRoot "daily.bat"
schtasks /Create /F /SC DAILY /ST $At /TN $Name /TR "`"$bat`""
if ($LASTEXITCODE -eq 0) {
  Write-Host "Task '$Name' runs $bat daily at $At. Log: backend\daily.log"
  Write-Host "Run it now with:  schtasks /Run /TN $Name"
}
