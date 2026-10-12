@echo off
chcp 65001 >nul
echo ============================================
echo   MemVine + LM Studio 本地 LLM 启动
echo ============================================
echo.

set MEMVINE_LLM_URL=http://localhost:7777/v1
set MEMVINE_LLM_KEY=lm-studio
set MEMVINE_LLM_MODEL=qwen/qwen3.5-9b


rem http://localhost:7777/v1
rem lm-studio
rem qwen/qwen3.5-9b
rem qwen/qwen3.5-9b
rem qwen3.5-4b-mtp

echo   LLM 端点 : %MEMVINE_LLM_URL%
echo   模型     : %MEMVINE_LLM_MODEL%
echo.
echo   确保 LM Studio 已启动并加载了 qwen3.5-4b-mtp
echo   端口: 7777
echo.
echo   正在启动测试...
echo   (Ctrl+C 退出)
echo ============================================
echo.

.venv\Scripts\python.exe chat.py

pause