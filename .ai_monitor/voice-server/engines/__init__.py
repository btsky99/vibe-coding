# -*- coding: utf-8 -*-
"""
FILE: .ai_monitor/voice-server/engines/__init__.py
DESCRIPTION: 낭독 엔진 어댑터 패키지.

             [불변식] 모든 어댑터는 load() 와 synth(text) -> wav bytes 둘만 노출한다.
             엔진 교체가 voice_server.load_tts() 의 한 줄로 끝나야, 실측 결과에 따라
             갈아끼우는 일이 코드 수술이 되지 않는다.

REVISION HISTORY:
- 2026-08-15 Claude: 최초 작성
"""
