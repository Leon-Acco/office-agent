# Office Agent 开发服务启动脚本（独立进程，不随 CLI 会话回收）
# 用法：powershell -ExecutionPolicy Bypass -File start_dev.ps1
$ErrorActionPreference = "Continue"

$Port       = 8000
$Host_      = "0.0.0.0"
$BaseDir    = "D:/code/my_workspace_python/Office_Agent"
$PythonExe  = "C:/Users/zhangchao/python/python.exe"
$OutLog     = Join-Path $BaseDir "logs/uvicorn.out.log"
$ErrLog     = Join-Path $BaseDir "logs/uvicorn.err.log"

# 日志目录不存在则创建(日志统一落 logs/,保持根目录整洁)
New-Item -ItemType Directory -Force -Path (Join-Path $BaseDir "logs") | Out-Null

function Write-Step($msg) { Write-Host "======================" -ForegroundColor Cyan; Write-Host $msg -ForegroundColor Cyan }

# 1. 清理占用 8000 端口的旧进程
Write-Step "检查端口 $Port 占用情况..."
$conns = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
if ($conns) {
    foreach ($c in $conns) {
        $pid_ = $c.OwningProcess
        Write-Host "  发现旧进程 PID=$pid_，正在终止..." -ForegroundColor Yellow
        Stop-Process -Id $pid_ -Force -ErrorAction SilentlyContinue
    }
    Start-Sleep -Seconds 1
    Write-Host "  旧进程已清理" -ForegroundColor Green
} else {
    Write-Host "  端口 $Port 空闲" -ForegroundColor Green
}

# 2. 启动 uvicorn（独立隐藏进程，日志落盘）
Write-Step "启动 uvicorn $Host_`:$Port ..."
$proc = Start-Process -FilePath $PythonExe `
    -ArgumentList '-X','utf8','-m','uvicorn','backend.main:app','--host',$Host_,'--port',"$Port" `
    -WorkingDirectory $BaseDir `
    -WindowStyle Hidden `
    -PassThru `
    -RedirectStandardOutput $OutLog `
    -RedirectStandardError $ErrLog

Write-Host "  新进程 PID=$($proc.Id)" -ForegroundColor Green
Write-Host "  日志：$OutLog / $ErrLog" -ForegroundColor Gray

# 3. 等待并验证启动
Write-Step "等待服务就绪..."
$ok = $false
for ($i = 1; $i -le 15; $i++) {
    Start-Sleep -Seconds 1
    try {
        $r = Invoke-WebRequest -Uri "http://127.0.0.1:$Port/api/health" -UseBasicParsing -TimeoutSec 2
        if ($r.StatusCode -eq 200) { $ok = $true; break }
    } catch {
        Write-Host "  第 $i 次探测未就绪..." -ForegroundColor DarkGray
    }
}

if ($ok) {
    Write-Step "服务启动成功"
    Write-Host "  访问地址：http://127.0.0.1:$Port" -ForegroundColor Green
    Write-Host "  健康检查：http://127.0.0.1:$Port/api/health [200]" -ForegroundColor Green
    Write-Host "  PID=$($proc.Id)" -ForegroundColor Green
} else {
    Write-Step "服务启动超时，请查看日志" -ForegroundColor Red
    Write-Host "  错误日志：$ErrLog" -ForegroundColor Red
    Write-Host "  ---- 最近错误日志 ----" -ForegroundColor Red
    if (Test-Path $ErrLog) { Get-Content $ErrLog -Tail 30 | Write-Host }
}
