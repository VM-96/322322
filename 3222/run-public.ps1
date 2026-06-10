#Requires -Version 5.1
<#
  Public URL to local FastAPI (no port forwarding on your router).

  DEFAULT (Russia-friendly): SSH reverse tunnel via localhost.run
    - Needs: Windows OpenSSH Client (optional feature) or ssh in PATH
    - Run:  powershell -ExecutionPolicy Bypass -File .\run-public.ps1
    - The ssh session prints your https://....localhost.run link (may take a few seconds).

  Cloudflare Quick Tunnel (often blocked or broken in Russia since 2025):
    powershell -ExecutionPolicy Bypass -File .\run-public.ps1 -Tunnel cloudflare
    Needs: winget install --id Cloudflare.cloudflared -e

  Reliable production in Russia: deploy on a Russian VPS (Selectel, Timeweb, REG.RU, etc.)
  with nginx + HTTPS, not a free tunnel.

  Change admin password before real use.
#>
param(
    [int]$Port = 8000,
    [string]$Listen = "127.0.0.1",
    [ValidateSet('ssh', 'cloudflare')]
    [string]$Tunnel = 'ssh'
)

$ErrorActionPreference = "Stop"
$Root = $PSScriptRoot
Set-Location $Root

if (-not (Get-Command py -ErrorAction SilentlyContinue)) {
    Write-Host "py not found. Install Python from https://www.python.org/downloads/ (enable py launcher)." -ForegroundColor Red
    exit 1
}

if ($Tunnel -eq 'cloudflare') {
    if (-not (Get-Command cloudflared -ErrorAction SilentlyContinue)) {
        Write-Host "cloudflared not found. Install:" -ForegroundColor Red
        Write-Host "  winget install --id Cloudflare.cloudflared -e" -ForegroundColor Yellow
        exit 1
    }
} else {
    if (-not (Get-Command ssh -ErrorAction SilentlyContinue)) {
        Write-Host "ssh not found. Enable OpenSSH Client:" -ForegroundColor Red
        Write-Host "  Settings -> Apps -> Optional features -> Add OpenSSH Client" -ForegroundColor Yellow
        Write-Host "Or use Cloudflare mode (may not work in Russia): -Tunnel cloudflare" -ForegroundColor DarkGray
        exit 1
    }
}

function Test-TcpPort {
    param([string]$HostName, [int]$TcpPort)
    try {
        $c = New-Object System.Net.Sockets.TcpClient
        $c.ReceiveTimeout = 2000
        $c.SendTimeout = 2000
        $c.Connect($HostName, $TcpPort)
        $c.Close()
        return $true
    } catch {
        return $false
    }
}

Write-Host "Starting uvicorn at http://${Listen}:${Port}/ ..." -ForegroundColor Cyan
$job = Start-Job -ScriptBlock {
    param($ProjectDir, $HostIn, $PortIn)
    Set-Location $ProjectDir
    & py -m uvicorn main:app --host $HostIn --port $PortIn --proxy-headers --forwarded-allow-ips '*'
} -ArgumentList $Root, $Listen, $Port

$opened = $false
foreach ($i in 1..30) {
    Start-Sleep -Milliseconds 400
    if (Test-TcpPort -HostName $Listen -TcpPort $Port) {
        $opened = $true
        break
    }
}

if (-not $opened) {
    Write-Host "Server did not open port $Port. Uvicorn output:" -ForegroundColor Red
    Receive-Job $job 2>&1 | ForEach-Object { Write-Host $_ }
    Stop-Job $job -Force -ErrorAction SilentlyContinue
    Remove-Job $job -Force -ErrorAction SilentlyContinue
    exit 1
}

Write-Host ""
if ($Tunnel -eq 'cloudflare') {
    Write-Host "Mode: cloudflared (may fail in Russia). Watch for https://....trycloudflare.com" -ForegroundColor Green
} else {
    Write-Host "Mode: SSH -> localhost.run (default for RU). Watch this window for https://....localhost.run" -ForegroundColor Green
    Write-Host "First connect may ask to trust host key; tunnel URL appears in ssh output." -ForegroundColor DarkGray
}
Write-Host "Ctrl+C stops tunnel and uvicorn." -ForegroundColor DarkGray
Write-Host ""

try {
    if ($Tunnel -eq 'cloudflare') {
        & cloudflared tunnel --url ("http://${Listen}:${Port}")
    } else {
        $sshTarget = "nokey@localhost.run"
        $sshArgs = @(
            '-o', 'StrictHostKeyChecking=accept-new',
            '-o', 'ServerAliveInterval=30',
            '-o', 'ServerAliveCountMax=3',
            '-R', "80:${Listen}:${Port}",
            $sshTarget
        )
        & ssh @sshArgs
    }
} finally {
    Write-Host ""
    Write-Host "Stopping uvicorn..." -ForegroundColor DarkGray
    Stop-Job $job -Force -ErrorAction SilentlyContinue
    Remove-Job $job -Force -ErrorAction SilentlyContinue
}

