@echo off
chcp 65001 >nul
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
title Agent Shell [T1]
cd /d D:\vibe-coding
python scripts/agent_shell.py --terminal T1 --cli auto
pause
