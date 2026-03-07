@echo off
chcp 65001 >nul
title Agent Shell [T2]
cd /d D:\vibe-coding
python scripts/agent_shell.py --terminal T2 --cli auto
pause
