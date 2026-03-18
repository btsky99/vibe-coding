# -*- coding: utf-8 -*-
"""
# ------------------------------------------------------------------------
# 📄 파일명: scripts/osc_parser.py
# 📝 설명: 터미널 출력 스트림에서 OSC(Operating System Command) 시퀀스를 감지하여
#          알림/상태 이벤트를 추출하는 파서. cmux의 OscHandler.cs를 Python으로 포팅.
#
#          [지원 OSC 코드]
#          - OSC 9:   단순 알림 (\033]9;body\007)
#          - OSC 99:  리치 알림 Kitty 프로토콜 (\033]99;t=title;b=body;s=subtitle\007)
#          - OSC 777: RXVT 알림 (\033]777;notify;title;body\007)
#          - OSC 133: 셸 프롬프트 마커 (\033]133;A/B/C/D\007)
#          - OSC 0/2: 윈도우 타이틀 변경
#          - OSC 7:   작업 디렉토리 변경 (file://host/path)
#
#          [사용법]
#          from osc_parser import OscParser
#          parser = OscParser()
#          events = parser.parse(terminal_output_text)
#          clean_text = parser.strip(terminal_output_text)
#
# REVISION HISTORY:
# [2026-03-18] Claude: 최초 구현 — cmux OscHandler.cs 기반 Python 포팅
#   - 정규식 기반 OSC 추출 (RE_OSC 패턴)
#   - parse(): 텍스트에서 이벤트 리스트 추출
#   - strip(): OSC 시퀀스 제거된 클린 텍스트 반환
#   - OSC 99 키-값 파싱 (t=title, b=body, s=subtitle, p=progress)
# ------------------------------------------------------------------------
"""

import re
from typing import Optional


# OSC 시퀀스 정규식: ESC ] <code> ; <payload> (BEL 또는 ST로 종료)
# BEL = \x07, ST = ESC \ = \x1b\\
RE_OSC = re.compile(r'\x1b\](\d+);(.*?)(?:\x07|\x1b\\)')


class OscParser:
    """터미널 출력 스트림에서 OSC 시퀀스를 감지하여 구조화된 이벤트를 반환합니다.

    [설계 의도] cmux의 OscHandler.cs를 Python으로 포팅.
    cli_agent.py의 기존 _ANSI_ESCAPE 필터가 OSC를 제거하기 전에
    이 파서로 먼저 알림 이벤트를 추출하여 vibe 알림 시스템에 전달합니다.
    """

    def parse(self, text: str) -> list[dict]:
        """텍스트에서 모든 OSC 시퀀스를 추출하여 이벤트 리스트로 반환합니다.

        Args:
            text: 터미널 출력 텍스트 (VT 시퀀스 포함)

        Returns:
            이벤트 딕셔너리 리스트. 각 이벤트:
            {
                'type': 'notification' | 'title' | 'cwd' | 'prompt',
                'osc_code': int,
                'title': str | None,
                'subtitle': str | None,
                'body': str | None,
                'raw': str,           # 원본 페이로드
                'source': str,        # 'osc9' | 'osc99' | 'osc777' | 'osc133'
            }
        """
        events = []
        for match in RE_OSC.finditer(text):
            code_str, payload = match.group(1), match.group(2)
            try:
                code = int(code_str)
            except ValueError:
                continue

            event = self._dispatch(code, payload)
            if event:
                events.append(event)

        return events

    def strip(self, text: str) -> str:
        """텍스트에서 모든 OSC 시퀀스를 제거한 클린 텍스트를 반환합니다.

        [설계 의도] cli_agent.py의 _ANSI_ESCAPE와 동일 역할이지만,
        OSC에 특화되어 있어 parse() 후 strip()을 호출하면
        "추출 후 제거" 패턴이 가능합니다.
        """
        return RE_OSC.sub('', text)

    def _dispatch(self, code: int, payload: str) -> Optional[dict]:
        """OSC 코드별 이벤트 처리 분기.

        cmux OscHandler.cs의 switch(code) 구조를 미러링합니다.
        """
        if code in (0, 2):
            # 윈도우 타이틀 변경
            return {
                'type': 'title',
                'osc_code': code,
                'title': payload,
                'subtitle': None,
                'body': None,
                'raw': payload,
                'source': f'osc{code}',
            }
        elif code == 7:
            # 작업 디렉토리 변경 (file://host/path 형식)
            return {
                'type': 'cwd',
                'osc_code': 7,
                'title': None,
                'subtitle': None,
                'body': payload,
                'raw': payload,
                'source': 'osc7',
            }
        elif code == 9:
            # 단순 알림: ESC ] 9 ; <body> BEL
            return {
                'type': 'notification',
                'osc_code': 9,
                'title': 'Terminal',
                'subtitle': None,
                'body': payload,
                'raw': payload,
                'source': 'osc9',
            }
        elif code == 99:
            # 리치 알림 (Kitty 프로토콜): ESC ] 99 ; t=title;b=body;s=subtitle BEL
            return self._parse_osc99(payload)
        elif code == 777:
            # RXVT 알림: ESC ] 777 ; notify;title;body BEL
            return self._parse_osc777(payload)
        elif code == 133:
            # 셸 프롬프트 마커: ESC ] 133 ; A/B/C/D BEL
            # A=프롬프트 시작, B=명령 시작, C=출력 시작, D=출력 끝
            marker = payload[0] if payload else '?'
            return {
                'type': 'prompt',
                'osc_code': 133,
                'title': None,
                'subtitle': None,
                'body': marker,
                'raw': payload,
                'source': 'osc133',
            }
        return None

    def _parse_osc99(self, payload: str) -> dict:
        """OSC 99 (Kitty 프로토콜) 키-값 파싱.

        포맷: t=Title;b=Body;s=Subtitle;p=0.75
        키 매핑:
        - t: title
        - b: body
        - s: subtitle
        - p: progress (0.0~1.0)
        - i: notification id
        """
        kv: dict[str, str] = {}
        if '=' in payload:
            for pair in payload.split(';'):
                eq = pair.find('=')
                if eq > 0:
                    kv[pair[:eq].strip()] = pair[eq + 1:].strip()

        title = kv.get('t', 'Terminal')
        body = kv.get('b', kv.get('t', payload))
        subtitle = kv.get('s')

        return {
            'type': 'notification',
            'osc_code': 99,
            'title': title,
            'subtitle': subtitle,
            'body': body,
            'raw': payload,
            'source': 'osc99',
            # 추가 메타: progress, id
            'progress': kv.get('p'),
            'notification_id': kv.get('i'),
        }

    def _parse_osc777(self, payload: str) -> dict:
        """OSC 777 (RXVT 프로토콜) 파싱.

        포맷: notify;Title;Body
        첫 번째 세미콜론 뒤가 title, 두 번째 뒤가 body.
        """
        parts = payload.split(';', 2)
        # parts[0] = "notify" (고정), parts[1] = title, parts[2] = body
        title = parts[1] if len(parts) > 1 else 'Terminal'
        body = parts[2] if len(parts) > 2 else (parts[1] if len(parts) > 1 else payload)

        return {
            'type': 'notification',
            'osc_code': 777,
            'title': title,
            'subtitle': None,
            'body': body,
            'raw': payload,
            'source': 'osc777',
        }


# ── 모듈 수준 싱글톤 (편의용) ────────────────────────────────────────────
_default_parser = OscParser()


def parse(text: str) -> list[dict]:
    """모듈 수준 parse() — OscParser().parse() 단축 호출"""
    return _default_parser.parse(text)


def strip(text: str) -> str:
    """모듈 수준 strip() — OscParser().strip() 단축 호출"""
    return _default_parser.strip(text)


# ── CLI 테스트용 ──────────────────────────────────────────────────────────
if __name__ == '__main__':
    # 테스트: 각 OSC 타입별 파싱 검증
    test_cases = [
        # OSC 9 단순 알림
        ('\x1b]9;Build complete\x07', 'osc9'),
        # OSC 99 리치 알림
        ('\x1b]99;t=Build Done;b=All tests passed;s=Project X\x07', 'osc99'),
        # OSC 777 RXVT 알림
        ('\x1b]777;notify;Deploy;Completed successfully\x07', 'osc777'),
        # OSC 133 프롬프트 마커
        ('\x1b]133;A\x07', 'osc133'),
        # OSC 0 타이틀
        ('\x1b]0;my-terminal\x07', 'osc0'),
        # 혼합 텍스트
        ('Hello \x1b]9;Alert!\x07 World \x1b]777;notify;Title;Body\x07 End', 'mixed'),
    ]

    parser = OscParser()
    passed = 0
    failed = 0

    for text, label in test_cases:
        events = parser.parse(text)
        clean = parser.strip(text)
        if events:
            print(f"  [PASS] {label}: {len(events)} event(s) → {events[0].get('source', '?')}")
            passed += 1
        else:
            print(f"  [FAIL] {label}: no events parsed")
            failed += 1

    # 혼합 텍스트 strip 검증
    mixed = 'Hello \x1b]9;Alert!\x07 World'
    clean = parser.strip(mixed)
    assert clean == 'Hello  World', f"strip 실패: {clean!r}"
    passed += 1

    print(f"\n결과: {passed} passed, {failed} failed")
