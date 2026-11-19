# ChallengeDaily watchdog 进程检测（独立 ps1，避免 cmd 中 $_ 被展开吃掉导致误判）
# 用法: powershell -File watchdog-check.ps1 <mode>
#   mode = collector | sync | bridge
# exit 0 = running, exit 1 = down

param([string]$Mode = 'collector')

$ErrorActionPreference = 'SilentlyContinue'

if ($Mode -eq 'collector') {
    $hit = Get-CimInstance Win32_Process | Where-Object {
        ($_.Name -eq 'python.exe' -or $_.Name -eq 'pythonw.exe') -and
        $_.CommandLine -match 'main\.py'
    }
    if ($hit) { exit 0 } else { exit 1 }
}

if ($Mode -eq 'sync') {
    $hit = Get-CimInstance Win32_Process | Where-Object {
        ($_.Name -eq 'python.exe' -or $_.Name -eq 'pythonw.exe') -and
        $_.CommandLine -match 'sync_agent\.py'
    }
    if ($hit) { exit 0 } else { exit 1 }
}

if ($Mode -eq 'bridge') {
    $conn = Get-NetTCPConnection -LocalPort 58889 -State Listen -ErrorAction SilentlyContinue
    if ($conn) { exit 0 } else { exit 1 }
}

exit 1
