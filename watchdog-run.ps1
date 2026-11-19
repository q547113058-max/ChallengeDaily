# ChallengeDaily watchdog: detect and restart collector / sync / bridge.
# Run directly by Task Scheduler via powershell.exe -File (no .cmd layer,
# so SmartScreen never prompts for an unsigned script host).
# NOTE: pure ASCII only - Windows PowerShell 5.1 reads BOM-less files as ANSI.
$ErrorActionPreference = 'SilentlyContinue'
$root   = 'D:\project\daily\ChallengeDaily'
$deploy = 'D:\project\daily\deploy'
$py     = Join-Path $root '.venv312\Scripts\python.exe'
if (-not (Test-Path $py)) { $py = Join-Path $root '.venv\Scripts\python.exe' }
$node   = 'C:\Users\54711\AppData\Local\Microsoft\WinGet\Packages\OpenJS.NodeJS.LTS_Microsoft.Winget.Source_8wekyb3d8bbwe\node-v24.16.0-win-x64\node.exe'
if (-not (Test-Path $node)) { $node = 'node' }

function Start-Hidden([string]$exe, [string[]]$argv) {
    Start-Process -FilePath $exe -ArgumentList $argv -WindowStyle Hidden | Out-Null
}

# ---- collector: main.py ----
$collector = Get-CimInstance Win32_Process | Where-Object {
    ($_.Name -eq 'python.exe' -or $_.Name -eq 'pythonw.exe') -and
    $_.CommandLine -match 'main\.py'
}
if (-not $collector) {
    $env:CHALLENGE_DAILY_DATA_DIR = Join-Path $root 'data'
    $env:PORT = '58888'
    $env:PYTHONIOENCODING = 'utf-8'
    $env:PYTHONUNBUFFERED = '1'
    $env:ELECTRON_RUN_AS_NODE = ''
    Start-Hidden $py @('-u', (Join-Path $root 'main.py'))
}

# ---- sync agent ----
$sync = Get-CimInstance Win32_Process | Where-Object {
    ($_.Name -eq 'python.exe' -or $_.Name -eq 'pythonw.exe') -and
    $_.CommandLine -match 'sync_agent\.py'
}
if (-not $sync) {
    $env:CD_SYNC_SERVER = 'http://193.112.246.85:5173'
    $tok = $null
    try {
        $tok = (Get-Content (Join-Path $deploy 'sync_agent.json') -Raw -Encoding UTF8 | ConvertFrom-Json).token
    } catch {
        $tok = $null
    }
    if ($tok) { $env:CD_SYNC_TOKEN = $tok }
    Start-Hidden $py @('-u', (Join-Path $deploy 'sync_agent.py'))
}

# ---- bridge-proxy: port 58889 ----
$b = Get-NetTCPConnection -LocalPort 58889 -State Listen -ErrorAction SilentlyContinue
if (-not $b -and (Test-Path (Join-Path $root 'client\electron\bridge-proxy.cjs'))) {
    Start-Hidden $node @((Join-Path $root 'client\electron\bridge-proxy.cjs'))
}

exit 0
