@echo off
echo ========================================
echo   怪兽的 Jett AI 助手 — 启动中...
echo ========================================

:: 启动 Jett 服务（后台运行）
echo [1/2] 启动 Jett 服务器...
start "Jett服务器" /MIN cmd /c "cd /d D:\AI\claude code\VX-chat-AI && python -m uvicorn main:app --host 0.0.0.0 --port 8000"
timeout /t 3 /nobreak >nul

:: 启动 SSH 隧道（前台运行，窗口保持打开）
echo [2/2] 启动公网隧道...
echo.
echo ========================================
echo   启动后看这里找 Jett 的公网地址：
echo   https://xxxx.lhr.life
echo ========================================
echo.
echo 关闭本窗口 = 停止 Jett
echo.

ssh -o StrictHostKeyChecking=no -o ServerAliveInterval=30 -R 80:localhost:8000 nokey@localhost.run

echo.
echo Jett 已停止。按任意键退出...
pause >nul
