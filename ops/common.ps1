# 共享函数：被 start_all.ps1 / stop_all.ps1 / status.ps1 一起 dot-source。
# 约定：本项目根目录是本文件所在目录（ops/）的上一级。

$Script:RepoRoot = Split-Path -Parent $PSScriptRoot
$Script:LogDir = Join-Path $RepoRoot "ops\logs"
$Script:RunDir = Join-Path $RepoRoot "ops\run"
$Script:GpuLockPath = Join-Path $RepoRoot "ops\run\GPU.lock"

New-Item -ItemType Directory -Force -Path $Script:LogDir | Out-Null
New-Item -ItemType Directory -Force -Path $Script:RunDir | Out-Null

# 三个服务的元信息：端口、健康检查地址、日志/PID 文件名、是否占用 GPU（决定要不要遵守 GPU 锁）。
$Script:Services = [ordered]@{
    llama  = @{ Port = 8080; Health = "http://127.0.0.1:8080/v1/models"; PidFile = "llama.pid";  Log = "llama.log";  UsesGpu = $false; Label = "llama-server (Qwen3-VL analyzer)" }
    worker = @{ Port = 9001; Health = "http://127.0.0.1:9001/v1/health"; PidFile = "worker.pid"; Log = "worker.log"; UsesGpu = $true;  Label = "worker (GPU 推理进程)" }
    server = @{ Port = 8000; Health = "http://127.0.0.1:8000/api/status"; PidFile = "server.pid"; Log = "server.log"; UsesGpu = $false; Label = "server (后端 + 网页)" }
}

function Get-ProjectHostToken {
    # 找一个能通过鉴权的令牌，只用于 status.ps1 探测 /api/status 时带上授权头，不落盘、不打印。
    # 和服务端（server/api/deps.py）同样的优先级：存在 users.json（多用户模式）就用它，
    # 否则退回 server/.env 里的 OUTFIT_API_TOKEN（单用户模式）；都没有就是开放模式，不需要令牌。
    $usersPath = $env:OUTFIT_USERS_FILE
    if (-not $usersPath) { $usersPath = Join-Path $RepoRoot "server\config\users.json" }
    if (Test-Path $usersPath) {
        try {
            $data = Get-Content $usersPath -Raw | ConvertFrom-Json
            $prop = $data.tokens.PSObject.Properties | Select-Object -First 1
            if ($prop) { return $prop.Name }
        } catch {}
        return $null
    }

    $envPath = Join-Path $RepoRoot "server\.env"
    if (-not (Test-Path $envPath)) { return $null }
    foreach ($line in Get-Content $envPath) {
        $t = $line.Trim()
        if ($t -match '^OUTFIT_API_TOKEN\s*=\s*(.+)$') {
            return $Matches[1].Trim().Trim('"').Trim("'")
        }
    }
    return $null
}

function Get-PortOwner {
    param([int]$Port)
    $conn = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
    if (-not $conn) { return $null }
    $proc = Get-CimInstance Win32_Process -Filter "ProcessId=$($conn.OwningProcess)" -ErrorAction SilentlyContinue
    [PSCustomObject]@{
        ProcessId  = $conn.OwningProcess
        CommandLine = if ($proc) { $proc.CommandLine } else { $null }
        Name       = if ($proc) { $proc.Name } else { $null }
    }
}

function Test-IsProjectProcess {
    # 用简单子串匹配（避免路径里的反斜杠给正则表达式转义添麻烦），大小写不敏感。
    # 注意：worker/server 用的是 venv 里的 python.exe，Windows 上这其实是个重定向 launcher，
    # 真正监听端口的子进程会重新执行到 pyvenv.cfg 里的 base 解释器，CommandLine 里不再包含
    # "worker"/"server"/".venv" 这几段路径——所以判断只依赖命令行里模块名这种不会变的部分。
    param([string]$ServiceName, [string]$CommandLine)
    if (-not $CommandLine) { return $false }
    $c = $CommandLine.ToLowerInvariant()
    switch ($ServiceName) {
        "llama"  { return ($c.Contains("llama-server.exe")) -and ($c.Contains("qwen3vl") -or $c.Contains("qwen3-vl")) }
        "worker" { return $c.Contains("app.main") }
        "server" { return $c.Contains("uvicorn") -and $c.Contains("api.main:app") }
    }
    return $false
}

function Test-IsMockServer {
    param([string]$CommandLine)
    return ($CommandLine -and $CommandLine.ToLowerInvariant().Contains("mock_server.py"))
}

function Resolve-PortConflict {
    # 返回 $true 表示端口现在可用（本来就空，或者已经处理掉占用者）；$false 表示放弃启动这个服务。
    param([string]$ServiceName, [int]$Port, [switch]$Force)
    $owner = Get-PortOwner -Port $Port
    if (-not $owner) { return $true }

    Write-Host "[$ServiceName] 端口 $Port 已被占用：PID=$($owner.ProcessId) $($owner.Name)" -ForegroundColor Yellow
    if ($owner.CommandLine) { Write-Host "    命令行: $($owner.CommandLine)" -ForegroundColor Yellow }

    $isSelf = Test-IsProjectProcess -ServiceName $ServiceName -CommandLine $owner.CommandLine
    $isMock = Test-IsMockServer -CommandLine $owner.CommandLine
    if ($isMock) {
        Write-Host "    识别为 extension/dev/mock_server.py 的残留进程（假服务器），和后端占用同一端口 8000，不能同时运行。" -ForegroundColor Yellow
    } elseif ($isSelf) {
        Write-Host "    识别为本项目 $ServiceName 的残留进程（可能是上次没正常退出）。" -ForegroundColor Yellow
    } else {
        Write-Host "    无法确认这是不是本项目的进程，请自行确认后再决定。" -ForegroundColor Red
    }

    if ($Force) {
        Write-Host "    -Force：结束该进程后继续。" -ForegroundColor Yellow
        Stop-Process -Id $owner.ProcessId -Force -ErrorAction SilentlyContinue
        Start-Sleep -Milliseconds 500
        return $true
    }

    $answer = $null
    try {
        $answer = Read-Host "    是否结束该进程并继续启动 $ServiceName ？(y/N)"
    } catch {
        Write-Host "    当前无法交互确认（非终端环境）。请加 -Force 重跑，或者自己确认后手动结束该进程。" -ForegroundColor Red
        return $false
    }
    if ($answer -match '^[Yy]') {
        Stop-Process -Id $owner.ProcessId -Force -ErrorAction SilentlyContinue
        Start-Sleep -Milliseconds 500
        return $true
    }
    Write-Host "    已跳过启动 $ServiceName（端口冲突未解决）。" -ForegroundColor Red
    return $false
}

function Wait-Health {
    param([string]$Url, [int]$TimeoutSec = 60, [int]$IntervalSec = 2)
    $deadline = (Get-Date).AddSeconds($TimeoutSec)
    do {
        try {
            $resp = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 5 -ErrorAction Stop
            if ($resp.StatusCode -eq 200) { return $true }
        } catch {
            $status = $null
            if ($_.Exception.Response) {
                try { $status = [int]$_.Exception.Response.StatusCode } catch {}
            }
            if ($status -eq 401) {
                # 接口存在鉴权（OUTFIT_API_TOKEN），能收到 401 说明进程已经起来了。
                return $true
            }
        }
        Start-Sleep -Seconds $IntervalSec
    } while ((Get-Date) -lt $deadline)
    return $false
}

function Write-LogTail {
    param([string]$LogPath, [int]$Lines = 30)
    if (Test-Path $LogPath) {
        Write-Host "---- $LogPath 最后 $Lines 行 ----" -ForegroundColor Yellow
        Get-Content -Path $LogPath -Tail $Lines | ForEach-Object { Write-Host "    $_" }
    } else {
        Write-Host "    （没有日志文件：$LogPath）" -ForegroundColor Yellow
    }
}

function Get-GpuLock {
    if (Test-Path $GpuLockPath) {
        return (Get-Content $GpuLockPath -Raw).Trim()
    }
    return $null
}

function New-GpuLock {
    param([string]$Task, [string]$Doing, [int]$EtaMinutes = 10)
    $start = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    $eta = (Get-Date).AddMinutes($EtaMinutes).ToString("yyyy-MM-dd HH:mm:ss")
    "$Task | $start | $eta | $Doing" | Set-Content -Path $GpuLockPath -Encoding utf8
}

function Remove-GpuLockIfMine {
    param([string]$Task)
    if (Test-Path $GpuLockPath) {
        $content = (Get-Content $GpuLockPath -Raw)
        $pattern = "^" + [regex]::Escape($Task) + "\s*\|"
        if ($content -match $pattern) {
            Remove-Item $GpuLockPath -Force -ErrorAction SilentlyContinue
        }
    }
}

function Get-PidFileProcess {
    param([string]$ServiceName)
    $svc = $Services[$ServiceName]
    $pidPath = Join-Path $RunDir $svc.PidFile
    if (-not (Test-Path $pidPath)) { return $null }
    $procId = (Get-Content $pidPath -Raw).Trim()
    if (-not $procId) { return $null }
    $proc = Get-CimInstance Win32_Process -Filter "ProcessId=$procId" -ErrorAction SilentlyContinue
    if (-not $proc) { return $null }
    return $proc
}

function Stop-ProcessTree {
    param([int]$ProcessId)
    & taskkill.exe /PID $ProcessId /T /F 2>&1 | Out-Null
}
