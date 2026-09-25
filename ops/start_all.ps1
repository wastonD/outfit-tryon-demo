<#
.SYNOPSIS
  按顺序启动 llama-server（8080，服装识别）→ worker（9001，GPU 推理）→ server（8000，后端 + 网页）。

.PARAMETER Only
  只启动列出的服务，逗号分隔，取值 server/worker/llama。默认三个都启动。

.PARAMETER SkipBuild
  跳过"web/dist 比 web/src 旧则自动 npm run build"这一步。

.PARAMETER Force
  端口被占用时，直接结束占用进程（不管是不是本项目的进程），而不是交互确认。

.PARAMETER Lan
  后端额外监听 0.0.0.0（局域网内其他设备可访问），默认只监听 127.0.0.1。
  对外暴露前请先配置 server/config/users.json 访问令牌，并确认防火墙规则。

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File ops\start_all.ps1
  powershell -ExecutionPolicy Bypass -File ops\start_all.ps1 -Only server -SkipBuild
  powershell -ExecutionPolicy Bypass -File ops\start_all.ps1 -Force
#>
param(
    [string[]]$Only = @("llama", "worker", "server"),
    [switch]$SkipBuild,
    [switch]$Force,
    [switch]$Lan
)

. (Join-Path $PSScriptRoot "common.ps1")

$orderedNames = @("llama", "worker", "server") | Where-Object { $Only -contains $_ }
if (-not $orderedNames) {
    Write-Host "无效的 -Only 参数：$($Only -join ',')，可选 server/worker/llama。" -ForegroundColor Red
    exit 1
}

function Test-NeedsWebBuild {
    $distIndex = Join-Path $RepoRoot "web\dist\index.html"
    if (-not (Test-Path $distIndex)) { return $true }
    $distTime = (Get-Item $distIndex).LastWriteTime
    $srcDir = Join-Path $RepoRoot "web\src"
    if (-not (Test-Path $srcDir)) { return $false }
    $newestSrc = Get-ChildItem -Path $srcDir -Recurse -File -ErrorAction SilentlyContinue |
        Sort-Object LastWriteTime -Descending | Select-Object -First 1
    return ($newestSrc -and $newestSrc.LastWriteTime -gt $distTime)
}

function Invoke-WebBuild {
    $webDir = Join-Path $RepoRoot "web"
    $npm = (Get-Command npm.cmd -ErrorAction SilentlyContinue).Source
    if (-not $npm) { $npm = (Get-Command npm -ErrorAction SilentlyContinue).Source }
    if (-not $npm) {
        $fallback = Join-Path $env:LOCALAPPDATA "nodejs\node-v24.21.0-win-x64\npm.cmd"
        if (Test-Path $fallback) { $npm = $fallback }
    }
    if (-not $npm) {
        Write-Host "  找不到 npm，跳过自动构建，请手动 cd web && npm run build。" -ForegroundColor Red
        return $false
    }
    Push-Location $webDir
    try {
        & $npm run build
        return ($LASTEXITCODE -eq 0)
    } finally {
        Pop-Location
    }
}

function Start-OneService {
    param([string]$Name)
    $svc = $Services[$Name]
    $outLog = Join-Path $LogDir $svc.Log
    $errLog = Join-Path $LogDir ($svc.Log -replace '\.log$', '.err.log')

    switch ($Name) {
        "llama" {
            $exe = "powershell.exe"
            $exeArgs = @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
                        (Join-Path $RepoRoot "worker\scripts\start_llama_server.ps1"))
            $workDir = $RepoRoot
        }
        "worker" {
            $exe = Join-Path $RepoRoot "worker\.venv\Scripts\python.exe"
            $exeArgs = @("-m", "app.main")
            $workDir = Join-Path $RepoRoot "worker"
        }
        "server" {
            $exe = Join-Path $RepoRoot "server\.venv\Scripts\python.exe"
            $bindHost = if ($Lan) { "0.0.0.0" } else { "127.0.0.1" }
            $exeArgs = @("-m", "uvicorn", "api.main:app", "--host", $bindHost, "--port", "8000")
            $workDir = Join-Path $RepoRoot "server"
        }
    }

    try {
        $proc = Start-Process -FilePath $exe -ArgumentList $exeArgs -WorkingDirectory $workDir `
            -RedirectStandardOutput $outLog -RedirectStandardError $errLog -WindowStyle Hidden -PassThru
        return $proc
    } catch {
        Write-Host "  启动失败：$_" -ForegroundColor Red
        return $null
    }
}

Write-Host "仓库根目录：$RepoRoot"
Write-Host "计划启动：$($orderedNames -join ' -> ')"
if ($Lan) { Write-Host "server 将监听 0.0.0.0（局域网可访问），请确认已配置访问令牌和防火墙。" -ForegroundColor Yellow }
Write-Host ""

foreach ($name in $orderedNames) {
    $svc = $Services[$name]
    Write-Host "== $name : $($svc.Label) ==" -ForegroundColor Cyan

    # web/dist 是不是要重新构建，和 server 进程要不要重启是两码事：FileResponse 每次请求都从磁盘读，
    # 不用重启 uvicorn 就能生效。所以放在"已经在运行就跳过"判断之前，不管 server 要不要重启都检查一遍。
    if ($name -eq "server" -and -not $SkipBuild) {
        if (Test-NeedsWebBuild) {
            Write-Host "  web/dist 比 web/src 旧（或不存在），先执行 npm run build ..." -ForegroundColor Cyan
            if (-not (Invoke-WebBuild)) {
                Write-Host "  npm run build 失败，继续用旧的 web/dist（如果存在）。" -ForegroundColor Red
            }
        }
    }

    $owner = Get-PortOwner -Port $svc.Port
    if ($owner -and (Test-IsProjectProcess -ServiceName $name -CommandLine $owner.CommandLine)) {
        if (Wait-Health -Url $svc.Health -TimeoutSec 5 -IntervalSec 1) {
            Write-Host "  已经在运行且健康检查通过（PID=$($owner.ProcessId)），跳过启动。" -ForegroundColor Green
            # 只有在没有有效 PID 文件时才用端口占用者的 PID 兜底记录；已有的记录多半是当初启动
            # 用的顶层 launcher PID（stop 脚本按它 taskkill /T 能连子进程一起杀掉），不要覆盖掉。
            if (-not (Get-PidFileProcess -ServiceName $name)) {
                $owner.ProcessId | Set-Content -Path (Join-Path $RunDir $svc.PidFile) -Encoding ascii
            }
            Write-Host ""
            continue
        }
        Write-Host "  端口被本项目 $name 进程占用，但健康检查没通过（PID=$($owner.ProcessId)），当作残留进程处理。" -ForegroundColor Yellow
    }

    $gpuLockAcquired = $false
    if ($svc.UsesGpu) {
        $lock = Get-GpuLock
        if ($lock) {
            Write-Host "  GPU 锁被占用：$lock" -ForegroundColor Red
            Write-Host "  启动/重启 worker 需要 GPU 锁，本次跳过 worker。可以先用 -Only llama,server 启动其他服务，或等锁释放后重跑 -Only worker。" -ForegroundColor Red
            Write-Host ""
            continue
        }
        New-GpuLock -Task "I-ops(start_all)" -Doing "启动/重启 worker" -EtaMinutes 5
        $gpuLockAcquired = $true
    }

    try {
        $ok = Resolve-PortConflict -ServiceName $name -Port $svc.Port -Force:$Force
        if (-not $ok) { continue }

        $proc = Start-OneService -Name $name
        if (-not $proc) { continue }

        $pidPath = Join-Path $RunDir $svc.PidFile
        $proc.Id | Set-Content -Path $pidPath -Encoding ascii
        Write-Host "  已启动，PID=$($proc.Id)，日志：$(Join-Path $LogDir $svc.Log)" -ForegroundColor Green

        Write-Host "  等待健康检查：$($svc.Health) ..." -ForegroundColor Cyan
        if (Wait-Health -Url $svc.Health -TimeoutSec 90 -IntervalSec 2) {
            Write-Host "  健康检查通过。" -ForegroundColor Green
        } else {
            Write-Host "  健康检查超时（90 秒），进程可能没起来或还在加载模型。" -ForegroundColor Red
            Write-LogTail -LogPath (Join-Path $LogDir $svc.Log)
            Write-LogTail -LogPath (Join-Path $LogDir ($svc.Log -replace '\.log$', '.err.log'))
        }
    } finally {
        if ($gpuLockAcquired) {
            Remove-GpuLockIfMine -Task "I-ops(start_all)"
        }
    }
    Write-Host ""
}

Write-Host "完成。用 powershell -ExecutionPolicy Bypass -File ops\status.ps1 查看当前状态。"
