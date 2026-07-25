@echo off
chcp 65001 >nul

echo ============================================================
echo   Odin-Assistant 报告服务器（外网隧道模式）
echo ============================================================
echo.

REM 检查虚拟环境
if not exist ".venv\Scripts\python.exe" (
    echo ❌ [错误] 虚拟环境未找到
    echo 请先运行 setup-windows.bat 进行部署
    echo.
    pause
    exit /b 1
)

echo [模式] HTTP + 外网隧道
echo [说明] 通过 ngrok 创建外网隧道，可在非局域网环境通过手机访问
echo.

REM 选择隧道工具
set TUNNEL_TOOL=ngrok
if "%1"=="cloudflared" set TUNNEL_TOOL=cloudflared
if "%1"=="cf" set TUNNEL_TOOL=cloudflared

echo 使用隧道工具: %TUNNEL_TOOL%
echo.

REM 检查工具是否安装
where %TUNNEL_TOOL% >nul 2>nul
if errorlevel 1 (
    echo ⚠️ 未找到 %TUNNEL_TOOL%，请先安装：
    if "%TUNNEL_TOOL%"=="ngrok" (
        echo   下载地址: https://ngrok.com/download
        echo   安装后执行: ngrok config add-authtoken ^<你的token^>
    ) else (
        echo   安装命令: scoop install cloudflared
        echo   首次使用: cloudflared tunnel login
    )
    echo.
    echo 如果已安装但不在 PATH 中，请将启动参数改为 cloudflared
    echo.
    pause
    exit /b 1
)

echo [提示] 按 Ctrl+C 停止服务
echo.

uv run python -m trendradar serve --host 0.0.0.0 --tunnel %TUNNEL_TOOL%

pause
