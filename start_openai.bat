@echo off
chcp 65001 >nul
title 藤蔓 QQ 机器人 + OpenAI API
cd /d %~dp0

:: 激活虚拟环境
call .venv\Scripts\activate.bat

:: LLM 配置（LM Studio）
set MEMVINE_LLM_URL=http://localhost:7777/v1
set MEMVINE_LLM_KEY=lm-studio
set MEMVINE_LLM_MODEL=qwen/qwen3.5-9b

:: QQ 机器人配置（改成你自己的）
set QQ_BOT_APP_ID=1904787692
set QQ_BOT_SECRET=laPF6xpicWRNJGEDCCDEGJNRWcjqy7GQ

echo ============================================
echo   藤蔓 MemVine QQ 机器人 + OpenAI API
echo   地址: http://localhost:8009
echo   文档: http://localhost:8009/docs
echo   LLM : %MEMVINE_LLM_URL%  (模型: %MEMVINE_LLM_MODEL%)
echo   QQ  : AppID=%QQ_BOT_APP_ID%
echo ============================================

python openai_server.py

pause