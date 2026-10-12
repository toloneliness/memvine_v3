@echo off
chcp 65001 >nul 2>&1
setlocal enabledelayedexpansion
set "VENV=.venv"
set "ACT=%VENV%\Scripts\activate.bat"

:: 检测虚拟环境
if not exist "%ACT%" (
    echo.
    echo [ERROR] 虚拟环境不存在，请先执行：uv venv
    echo.
    pause
    exit /b 1
)

:: 进入虚拟环境并保持窗口
call "%ACT%"
echo 已进入虚拟环境，可执行 python / uv pip 等命令
echo ==============================================
cmd /k