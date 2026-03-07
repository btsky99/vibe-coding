@echo off
chcp 65001 >nul
title Agent Shell [T3]
cd /d D:\vibe-coding
python scripts/agent_shell.py --terminal T3 --cli auto
pause
