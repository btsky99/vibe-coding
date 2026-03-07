@echo off
chcp 65001 >nul
title Agent Shell [T1]
cd /d D:\vibe-coding
python scripts/agent_shell.py --terminal T1 --cli auto
pause
