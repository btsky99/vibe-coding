@echo off
REM ?ŒìŠ¤?¸ìš© ê°€ì§?ë¡œê·¸ ë°œì†¡ ?¤í¬ë¦½íŠ¸
echo ?°ëª¨ ë¡œê·¸ ?„ì†¡ ì¤?.. (AI ëª¨ë‹ˆ??ì°½ì„ ?•ì¸?˜ì„¸??

set "LOGGER=D:\vibe-coding\.ai_monitor\bin\logger.bat"

call "%LOGGER%" start "Claude_Terminal" "claude" "my_demo_project" "ì´ˆê¸° ?˜ê²½ ?¤ì •" "1a2b3c" "?„ë¡œ?íŠ¸ ?Œì¼ ?ìƒ‰ ì¤? "[]"
timeout /t 2 >nul

call "%LOGGER%" phase "Claude_Terminal" "app.py ?ì„± ì¤? "[]"
timeout /t 1 >nul

call "%LOGGER%" phase "Gemini_Terminal" "package.json ?˜ì¡´???¤ì¹˜" "[]"
timeout /t 2 >nul

call "%LOGGER%" phase "Claude_Terminal" "?ŒìŠ¤??ì½”ë“œ ?‘ì„± ?„ë£Œ" "[]"
timeout /t 1 >nul

call "%LOGGER%" end "Claude_Terminal" "success"

echo ?„ì†¡ ?„ë£Œ!
pause
