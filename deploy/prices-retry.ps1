# Fills days without real prices from data.gov.in (by date). Run every 3 hours by the
# MandiPricesRetry scheduled task (install-daily-task.ps1), so prices arrive soon after
# data.gov.in comes back from an outage. Appends to backend\daily.log.
$backend = Resolve-Path (Join-Path $PSScriptRoot "..\backend")
Set-Location -LiteralPath $backend
cmd /c "python manage.py catch-up-prices >> daily.log 2>&1"
exit $LASTEXITCODE
