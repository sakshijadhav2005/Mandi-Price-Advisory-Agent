# Daily job (prices, IMD bulletin, alerts, weekly / monthly checks). Run by the MandiDaily
# scheduled task (install-daily-task.ps1); appends to backend\daily.log.
#
# It changes into backend first, so the command below holds no path at all: a folder
# name with "&" or spaces (like "Mandi Price & Advisory Agent") cannot break it.
$backend = Resolve-Path (Join-Path $PSScriptRoot "..\backend")
Set-Location -LiteralPath $backend
cmd /c "python manage.py daily >> daily.log 2>&1"
exit $LASTEXITCODE
