<#
.SYNOPSIS
  显示 server / worker / llama 是否在运行、端口、PID、显存占用、GPU 锁状态、/api/status 的 features。

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File ops\status.ps1
#>
param()

. (Join-Path $PSScriptRoot "common.ps1")

Write-Host "===== 服务状态 =====" -ForegroundColor Cyan
foreach ($name in @("llama", "worker", "server")) {
    $svc = $Services[$name]
    $owner = Get-PortOwner -Port $svc.Port
    $pidFileProc = Get-PidFileProcess -ServiceName $name

    Write-Host "[$name] $($svc.Label)  端口 $($svc.Port)"
    if (-not $owner) {
        Write-Host "  状态：未运行（端口空闲）" -ForegroundColor DarkYellow
    } else {
        $isSelf = Test-IsProjectProcess -ServiceName $name -CommandLine $owner.CommandLine
        $isMock = Test-IsMockServer -CommandLine $owner.CommandLine
        $healthy = Wait-Health -Url $svc.Health -TimeoutSec 3 -IntervalSec 1
        $color = if ($healthy -and $isSelf) { "Green" } else { "Yellow" }
        Write-Host "  状态：端口被占用，PID=$($owner.ProcessId)，健康检查=$(if ($healthy) {'通过'} else {'未通过'})" -ForegroundColor $color
        if ($isMock) {
            Write-Host "  注意：占用者是 extension/dev/mock_server.py（假服务器），不是真实后端。" -ForegroundColor Red
        } elseif (-not $isSelf) {
            Write-Host "  注意：占用者的命令行不像是本项目的 $name 进程，请自行确认。" -ForegroundColor Red
            if ($owner.CommandLine) { Write-Host "    $($owner.CommandLine)" -ForegroundColor DarkGray }
        }
    }
    if ($pidFileProc) {
        Write-Host "  ops/run/$($svc.PidFile) 记录的启动进程 PID=$($pidFileProc.ProcessId)（还存活）。" -ForegroundColor DarkGray
        if ($owner -and $pidFileProc.ProcessId -ne $owner.ProcessId) {
            Write-Host "    和实际监听端口的 PID 不同属正常现象：worker/server 用的 venv python.exe 是重定向 launcher，llama 是 PowerShell 包装脚本，真正干活的是它们的子进程。" -ForegroundColor DarkGray
        }
    } elseif (Test-Path (Join-Path $RunDir $svc.PidFile)) {
        Write-Host "  ops/run/$($svc.PidFile) 记录的 PID 已经不存在（进程已退出，PID 文件失效）。" -ForegroundColor DarkYellow
    }
    Write-Host ""
}

Write-Host "===== GPU 锁 =====" -ForegroundColor Cyan
$lock = Get-GpuLock
if ($lock) {
    Write-Host "占用中：$lock" -ForegroundColor Yellow
} else {
    Write-Host "空闲（没有 ops/run/GPU.lock）" -ForegroundColor Green
}
Write-Host ""

Write-Host "===== 显存占用（nvidia-smi） =====" -ForegroundColor Cyan
$nvidiaSmi = Get-Command nvidia-smi -ErrorAction SilentlyContinue
if ($nvidiaSmi) {
    try {
        & nvidia-smi --query-gpu=name,memory.used,memory.total,utilization.gpu --format=csv,noheader
    } catch {
        Write-Host "nvidia-smi 调用失败：$_" -ForegroundColor Red
    }
} else {
    Write-Host "本机没有找到 nvidia-smi。" -ForegroundColor DarkYellow
}
Write-Host ""

Write-Host "===== /api/status features =====" -ForegroundColor Cyan
try {
    $headers = @{}
    $token = Get-ProjectHostToken
    if ($token) { $headers["Authorization"] = "Bearer $token" }
    $resp = Invoke-RestMethod -Uri "http://127.0.0.1:8000/api/status" -Headers $headers -TimeoutSec 5 -ErrorAction Stop
    $resp.features | ConvertTo-Json | Write-Host
} catch {
    Write-Host "拿不到 /api/status（server 可能没在运行，或者 OUTFIT_API_TOKEN 对不上）：$_" -ForegroundColor DarkYellow
}
