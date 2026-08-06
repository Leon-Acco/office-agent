@echo off
chcp 65001 >nul
REM ============================================
REM Office_Agent 停止脚本
REM ============================================

echo ============================================
echo  停止 Office_Agent 服务
echo ============================================

REM 杀掉 uvicorn
tasklist | findstr /I "uvicorn" >nul && (
    taskkill /F /IM uvicorn.exe >nul 2>&1
    echo   已停止 uvicorn
)

REM 杀掉占用 8000 的进程
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":8000 " ^| findstr "LISTENING"') do (
    taskkill /F /PID %%a >nul 2>&1
    echo   已停止 PID=%%a
)

REM 杀掉可能的残留 80xx 端口
for %%p in (8090 8091 8092 8093 8094 8095 8096) do (
    for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":%%p " ^| findstr "LISTENING"') do (
        taskkill /F /PID %%a >nul 2>&1
        echo   已停止 %%p 端口 PID=%%a
    )
)

echo.
echo ✅ 所有服务已停止
pause
