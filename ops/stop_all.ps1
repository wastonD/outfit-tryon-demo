<#
.SYNOPSIS
  停止 server / worker / llama。优先按 ops/run/<服务>.pid 里记录的 PID 停止；
  PID 文件失效时，按端口 + 命令行识别本项目的进程再停止，不会误杀其他 python 进程。

.PARAMETER Only
  只停止列出的服务，逗号分隔，取值 server/worker/llama。默认三个都停。

.PARAMETER Force
  worker 正被 GPU 锁占用（可能是别的任务在用）时，仍然强制停止。

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File ops\stop_all.ps1
  powershell -ExecutionPolicy Bypass -File ops\stop_all.ps1 -Only worker
#>
param(
    [string[]]$Only = @("server", "worker", "llama"),
    [switch]$Force
)

. (Join-Path $PSScriptRoot "common.ps1")

# 停止顺序和启动相反：先 server，再 worker，最后 llama。
$orderedNames = @("server", "worker", "llama") | Where-Object { $Only -contains $_ }
if (-not $orderedNames) {
    Write-Host "无效的 -Only 参数：$($Only -join ',')，可选 server/worker/llama。" -ForegroundColor Red
    exit 1
}

foreach ($name in $orderedNames) {
    $svc = $Services[$name]
    Write-Host "== $name : $($svc.Label) ==" -ForegroundColor Cyan
    $pidPath = Join-Path $RunDir $svc.PidFile

    if ($svc.UsesGpu) {
        $lock = Get-GpuLock
        if ($lock -and -not $Force) {
            Write-Host "  GPU 锁被占用：$lock" -ForegroundColor Red
            Write-Host "  停止 worker 可能中断对方正在跑的任务，已跳过。确认没问题的话加 -Force。" -ForegroundColor Red
            Write-Host ""
            continue
        }
    }

    $stopped = $false

    # 1) 先信 PID 文件。
    $fromPidFile = Get-PidFileProcess -ServiceName $name
    if ($fromPidFile) {
        if (Test-IsProjectProcess -ServiceName $name -CommandLine $fromPidFile.CommandLine) {
            Write-Host "  按 PID 文件停止 PID=$($fromPidFile.ProcessId)。" -ForegroundColor Yellow
            Stop-ProcessTree -ProcessId $fromPidFile.ProcessId
            $stopped = $true
        } else {
            Write-Host "  PID 文件里的 PID=$($fromPidFile.ProcessId) 命令行对不上 $name，当作失效处理。" -ForegroundColor Yellow
        }
    } else {
        Write-Host "  没有有效的 PID 文件（$pidPath）。" -ForegroundColor Yellow
    }

    # 2) PID 文件失效或缺失时，按端口 + 命令行兜底识别。
    if (-not $stopped) {
        $owner = Get-PortOwner -Port $svc.Port
        if (-not $owner) {
            Write-Host "  端口 $($svc.Port) 本来就没有进程在监听，无需停止。" -ForegroundColor Green
        } elseif (Test-IsProjectProcess -ServiceName $name -CommandLine $owner.CommandLine) {
            Write-Host "  按端口 $($svc.Port) 识别到本项目 $name 进程 PID=$($owner.ProcessId)，停止它。" -ForegroundColor Yellow
            Stop-ProcessTree -ProcessId $owner.ProcessId
            $stopped = $true
        } else {
            Write-Host "  端口 $($svc.Port) 被 PID=$($owner.ProcessId)（$($owner.Name)）占用，命令行无法确认是本项目的 $name 进程，为避免误杀不会停止它：" -ForegroundColor Red
            if ($owner.CommandLine) { Write-Host "    $($owner.CommandLine)" -ForegroundColor Red }
            Write-Host "    请自行确认后手动处理。" -ForegroundColor Red
        }
    }

    if (Test-Path $pidPath) { Remove-Item $pidPath -Force -ErrorAction SilentlyContinue }
    if ($stopped) { Write-Host "  已停止。" -ForegroundColor Green }
    Write-Host ""
}

Write-Host "完成。用 powershell -ExecutionPolicy Bypass -File ops\status.ps1 确认。"
