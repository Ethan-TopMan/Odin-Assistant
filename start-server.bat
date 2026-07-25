@echo off
chcp 65001 >nul

echo ============================================================
echo   Odin-Assistant 报告 HTTP 服务器
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

echo [模式] 本地 HTTP 服务器
echo [说明] 通过浏览器查看生成的 HTML 报告
echo [提示] 手机访问需与电脑处于同一 WiFi 网络
echo.

REM 启动服务器（自动选择可用端口）
uv run python -m trendradar serve --host 0.0.0.0

pause
