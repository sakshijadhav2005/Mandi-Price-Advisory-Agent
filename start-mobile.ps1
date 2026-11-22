# Starts everything the mobile app needs: the backend API, then the Expo dev server.
#
#   .\start-mobile.ps1              backend + Expo (scan the QR code with Expo Go)
#   .\start-mobile.ps1 -BackendOnly backend only (for the installed APK)
#   .\start-mobile.ps1 -Port 8001   use another API port
#
# The backend opens in its own window and listens on all network interfaces, so a phone
# on the same Wi-Fi can reach it. Close that window (or Ctrl+C in it) to stop the API.
# Paths are passed as -LiteralPath / working directories, never through cmd.exe, so the
# "&" in the folder name cannot break anything.
param(
    [int]$Port = 8000,
    [switch]$BackendOnly
)

$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
$backend = Join-Path $root "backend"
$mobile = Join-Path $root "apps\mobile"

function Test-Api([string]$url) {
    try {
        $r = Invoke-WebRequest -Uri "$url/meta" -UseBasicParsing -TimeoutSec 3
        return $r.StatusCode -eq 200
    } catch { return $false }
}

# The PC's address on the local network (Wi-Fi / Ethernet), skipping virtual adapters.
function Get-LanIp {
    $ip = Get-NetIPConfiguration -ErrorAction SilentlyContinue |
        Where-Object { $_.IPv4DefaultGateway -and $_.NetAdapter.Status -eq "Up" } |
        ForEach-Object { $_.IPv4Address.IPAddress } |
        Select-Object -First 1
    if ($ip) { return $ip }
    return "10.0.2.2"   # no network: the Android emulator's view of this PC
}

$local = "http://127.0.0.1:$Port"

# 1. Backend
if (Test-Api $local) {
    Write-Host "Backend already running on port $Port." -ForegroundColor Green
} else {
    Write-Host "Starting backend on port $Port ..." -ForegroundColor Cyan
    Start-Process -FilePath "python" `
        -ArgumentList "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "$Port" `
        -WorkingDirectory $backend | Out-Null

    $deadline = (Get-Date).AddSeconds(60)
    while (-not (Test-Api $local)) {
        if ((Get-Date) -gt $deadline) {
            Write-Host "Backend did not answer within 60 s. Check its window for the error." -ForegroundColor Red
            exit 1
        }
        Start-Sleep -Milliseconds 700
    }
    Write-Host "Backend is up." -ForegroundColor Green
}

$lan = Get-LanIp
$apiBase = "http://${lan}:$Port"
Write-Host ""
Write-Host "Server address for the app: $apiBase" -ForegroundColor Yellow
Write-Host "(Phone and PC must be on the same Wi-Fi. If the phone cannot connect, allow"
Write-Host " port $Port in Windows Firewall, or set this address in the app's Settings.)"
Write-Host ""

if ($BackendOnly) { exit 0 }

# 2. Expo. EXPO_PUBLIC_API_BASE becomes the app's default server address.
$env:EXPO_PUBLIC_API_BASE = $apiBase
Set-Location -LiteralPath $mobile
& node (Join-Path $root "node_modules\expo\bin\cli") start
