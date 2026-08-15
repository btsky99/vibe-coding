# -*- coding: utf-8 -*-
"""
FILE: .ai_monitor/voice-server/engines/__init__.py
DESCRIPTION: 낭독 엔진 어댑터 패키지.

             [불변식] 모든 어댑터는 load() 와 synth(text, speed) -> 오디오 bytes 를 노출한다.
             엔진 교체가 voice_server.load_tts() 의 한 줄로 끝나야, 실측 결과에 따라
             갈아끼우는 일이 코드 수술이 되지 않는다.

             [🔴 형식은 wav 로 고정이 아니다] tts_edge 가 들어오면서 mp3 가 생겼다.
             wav 가 아닌 어댑터는 `mime`(예: 'audio/mpeg')과 `ext`(예: 'mp3') 클래스
             속성을 둔다. 없으면 voice_server 가 wav 로 간주한다 — 기존 어댑터를 안
             고쳐도 되게 한 것이지, 새 어댑터가 생략해도 된다는 뜻이 아니다.

REVISION HISTORY:
- 2026-08-15 Claude: 최초 작성
- 2026-08-15 Claude: mime/ext 규약 추가 — mp3 를 내는 엔진(tts_edge)이 생겼다
"""
