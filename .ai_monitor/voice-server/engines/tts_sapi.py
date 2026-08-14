# -*- coding: utf-8 -*-
"""
FILE: .ai_monitor/voice-server/engines/tts_sapi.py
DESCRIPTION: Windows 내장 음성(SAPI5) 낭독 어댑터. 텍스트 → WAV 바이트.

             [WHY 이 엔진이 추가됐나 — 2026-08-15]
               sherpa VITS(ko_KO-kss low)는 화자가 하나뿐이라 '목소리를 고른다'가
               성립하지 않았다. 윈도우에는 한국어 음성(Microsoft Heami, ko-KR)이 이미
               깔려 있다 — 내려받을 것도, GPU 도, 모델 파일도 필요 없다. 선택지를 0개에서
               n개로 만드는 가장 값싼 수단이라 기본 후보로 넣는다.

             [🔴 프로세스를 새로 띄우지 않는다] PowerShell 로 System.Speech 를 부르는 방법도
               있지만, 낭독 한 번마다 콘솔이 번쩍인다(규칙 10). 사이드카는 앱 패키지를
               import 할 수 없어 infra.proc 를 쓸 수도 없다. COM(win32com)은 인프로세스라
               스폰 자체가 없다 — 그래서 pywin32 를 택했다.

             [🔴 COM 은 스레드마다 초기화해야 한다] 사이드카는 ThreadingHTTPServer 라
               요청마다 다른 스레드에서 synth 가 불린다. CoInitialize 없이 Dispatch 하면
               "CoInitialize has not been called" 로 죽는다. 그래서 synth 안에서 매번
               초기화하고, SpVoice 객체는 캐시하지 않는다(아파트가 다르면 재사용 불가).

             [제약] 윈도우 전용. import 자체가 다른 OS 에서 실패하므로 available() 로 먼저
               거른다 — 맥에서 목록에 안 뜨는 게 정상이다.

REVISION HISTORY:
- 2026-08-15 Claude: 최초 작성 — 목소리 선택지 확보(윈도우 내장 한국어 음성)
"""

from __future__ import annotations

import os
import tempfile

# SAPI Rate 는 -10~10 정수이고 1단계가 대략 ×1.15 다. 프론트는 배율(0.5~1.5)로 다루므로
# 여기서 환산한다. [WHY 반올림인가] SAPI 는 정수만 받는다 — 소수를 주면 조용히 0 이 된다.
_RATE_STEP = 0.15


def available() -> bool:
    try:
        import win32com.client  # noqa: F401
    except Exception:                                      # noqa: BLE001
        return False
    return os.name == 'nt'


def list_voices() -> list[dict]:
    """설치된 SAPI 음성 목록. 실패하면 빈 목록 — 목록 조회가 사이드카를 죽이면 안 된다."""
    if not available():
        return []
    try:
        import pythoncom
        import win32com.client
        pythoncom.CoInitialize()
        try:
            voices = []
            for token in win32com.client.Dispatch('SAPI.SpVoice').GetVoices():
                desc = token.GetDescription()
                try:
                    # Language 는 LCID 16진 문자열(412=ko-KR, 409=en-US). 여러 개면 공백 구분.
                    lcid = (token.GetAttribute('Language') or '').split()[0]
                except Exception:                          # noqa: BLE001
                    lcid = ''
                voices.append({
                    'id': f'sapi:{desc}',
                    'label': desc.replace(' Desktop', ''),
                    'engine': 'sapi',
                    'lang': 'ko' if lcid.lower() == '412' else ('en' if lcid.lower() == '409' else lcid),
                })
            return voices
        finally:
            pythoncom.CoUninitialize()
    except Exception:                                      # noqa: BLE001
        return []


class SapiEngine:
    name = 'sapi'

    def __init__(self, voice_id: str = '') -> None:
        # voice_id 는 'sapi:<설명문자열>' 또는 빈 값(기본 음성).
        self.voice_desc = voice_id.split(':', 1)[1] if ':' in voice_id else ''

    def load(self) -> None:
        # [WHY 비어 있나] SAPI 는 올릴 모델이 없다. 인터페이스를 맞추기 위한 no-op 이다.
        if not available():
            raise RuntimeError('이 시스템에서는 Windows 내장 음성을 쓸 수 없습니다')

    def synth(self, text: str, speed: float = 1.0) -> bytes:
        import pythoncom
        import win32com.client

        pythoncom.CoInitialize()
        try:
            voice = win32com.client.Dispatch('SAPI.SpVoice')
            if self.voice_desc:
                for token in voice.GetVoices():
                    if token.GetDescription() == self.voice_desc:
                        voice.Voice = token
                        break
            voice.Rate = max(-10, min(10, int(round((speed - 1.0) / _RATE_STEP))))

            # [🔴 임시 파일을 쓰는 이유] SpMemoryStream 은 WAV 헤더 없는 생 PCM 을 준다.
            #   래핑을 직접 하려면 실제 채택된 포맷을 다시 물어야 해서 더 깨지기 쉽다.
            #   SpFileStream 은 헤더까지 완성해 준다. delete=False 는 윈도우에서 필수 —
            #   열린 파일을 COM 이 다시 열 수 없다.
            fd, path = tempfile.mkstemp(suffix='.wav')
            os.close(fd)
            try:
                stream = win32com.client.Dispatch('SAPI.SpFileStream')
                stream.Open(path, 3)                       # 3 = SSFMCreateForWrite
                voice.AudioOutputStream = stream
                voice.Speak(text)                          # 동기 — 반환 시점에 파일이 완성돼 있다
                stream.Close()
                with open(path, 'rb') as f:
                    return f.read()
            finally:
                try:
                    os.unlink(path)
                except OSError:
                    pass
        finally:
            pythoncom.CoUninitialize()
