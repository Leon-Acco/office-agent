@echo off
chcp 65001 >nul
REM ============================================
REM Office_Agent 启动脚本（固定端口 8000）
REM 每次启动前强制清理旧进程，保证运行最新代码
REM ============================================

cd /d "%~dp0"

echo ============================================
echo  Office_Agent 启动脚本
echo ============================================

REM ---- 第 1 步：清理旧的 Python/uvicorn 进程 ----
echo [1/4] 清理旧服务进程...

REM 查找占用 8000 端口的进程并杀掉
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":8000 " ^| findstr "LISTENING"') do (
    echo   - 杀掉占用 8000 端口的进程 PID=%%a
    taskkill /F /PID %%a >nul 2>&1
)

REM 杀掉所有 uvicorn 进程（避免多个服务并存）
tasklist | findstr /I "uvicorn" >nul && (
    echo   - 杀掉所有 uvicorn 进程
    taskkill /F /IM uvicorn.exe >nul 2>&1
)

REM 杀掉可能残留的旧 Python 服务进程（保守策略：只杀监听 80xx 端口的）
for %%p in (8090 8091 8092 8093 8094 8095 8096) do (
    for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":%%p " ^| findstr "LISTENING"') do (
        echo   - 杀掉占用 %%p 端口的进程 PID=%%a
        taskkill /F /PID %%a >nul 2>&1
    )
)

timeout /t 1 /nobreak >nul

REM ---- 第 2 步：环境检查 ----
echo [2/4] 环境检查...

where python >nul 2>&1 || (
    echo [错误] 未找到 python，请先安装 Python 3.10+
    pause
    exit /b 1
)

if not exist ".venv" (
    echo   - 创建虚拟环境...
    python -m venv .venv
)

call .venv\Scripts\activate.bat

REM 安装依赖（仅在 requirements.txt 变更时安装）
python -c "import fastapi, sqlalchemy, aiomysql, redis" 2>nul || (
    echo   - 安装依赖...
    pip install -r requirements.txt -q
)

if not exist logs mkdir logs

REM ---- 第 3 步：启动服务 ----
echo [3/4] 启动 FastAPI 服务（端口 8000）...

REM 使用 uvicorn 启动，单进程，监听 8000
start "Office_Agent_Server" cmd /c "uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload > logs\server.log 2>&1"

REM ---- 第 4 步：等待服务就绪 ----
echo [4/4] 等待服务就绪...

set /a tries=0
:wait_ready
set /a tries+=1
timeout /t 1 /nobreak >nul

REM 检测服务是否启动
netstat -ano | findstr ":8000 " | findstr "LISTENING" >nul && (
    goto :service_up
)

if %tries% lss 20 goto :wait_ready

echo [错误] 服务启动超时，请查看 logs\server.log
pause
exit /b 1

:service_ready
:service_up
echo.
echo ============================================
echo  ✅ 服务启动成功
echo ============================================
echo  访问地址:  http://localhost:8000/
echo  API 文档:  http://localhost:8000/docs
echo  日志文件:  logs\server.log
echo ============================================
echo.
echo 按 Ctrl+C 或关闭此窗口不会停止服务
echo 要停止服务请运行 stop.bat
echo.
pause
