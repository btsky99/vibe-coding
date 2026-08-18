# -*- coding: utf-8 -*-
"""
FILE: .ai_monitor/voice-server/engines/tts_cache.py
DESCRIPTION: 합성 결과 디스크 캐시 — 같은 문장을 두 번 만들지 않는다.

             [WHY 캐시가 필요한가 — 2026-08-15 실측] edge-tts 는 마이크로소프트 서버를
               다녀오므로 한 번 합성에 0.5~1.1초가 든다. 그런데 이 앱이 읽는 말은 심하게
               반복된다 — 미리듣기 문장, "테스트를 모두 통과했습니다", 같은 답을 다시
               듣기. 왕복을 없애면 그 자리들이 파일 읽기(~10ms)로 바뀐다.
             [🔴 캐시는 네트워크 장애의 방어선이기도 하다] 인터넷이 끊겨도 이미 만든
               문장은 그대로 들린다. 폴백(브라우저 합성기)으로 내려가는 횟수가 준다.

             [🔴 왜 문장 단위로 안 쪼개고 통째로 캐시하나] 쪼개면 적중률은 오르지만
               조각 mp3 를 이어 붙여야 한다. mp3 는 프레임 경계가 있어 단순 이어붙이기가
               재생기에 따라 잡음·길이 오류를 낸다. 게다가 edge-tts 는 문장부호에서 이미
               사람처럼 쉰다 — 쪼개서 얻을 것이 적고 잃을 것이 크다.

             [🔴 상한이 없으면 사용자가 모르는 사이 디스크를 먹는다] 콘솔 없이 도는
               사이드카라(규칙 10) 아무도 이 폴더를 안 본다. 그래서 상한을 코드에 박는다.
             [WHY 정리를 '쓸 때'만 하나] 읽을 때 정리하면 그 비용이 낭독 지연에 그대로
               얹힌다. 캐시의 목적이 지연 제거인데 본말전도다. 쓰기는 어차피 왕복 뒤라
               수십 ms 가 묻힌다.
             [WHY mtime LRU 인가] 적중할 때 mtime 을 갱신하므로 '최근에 들은 말'이 남는다.
               생성순(ctime)으로 지우면 매일 쓰는 문장이 오래됐다는 이유로 밀려난다.

REVISION HISTORY:
- 2026-08-15 Claude: 최초 작성 — edge-tts 왕복 제거용 디스크 캐시
"""

from __future__ import annotations

import hashlib
import os
import time
from pathlib import Path

# 캐시 뿌리. [WHY 프로젝트 안인가] 사용자가 "바이브 코딩 안에 격리"를 요구했다.
# %TEMP% 에 두면 청소 도구가 지워 적중률이 조용히 0 이 되고, 어디에 얼마나 쌓였는지
# 사용자가 확인할 방법도 없다.
CACHE_DIR = Path(__file__).resolve().parent.parent / 'cache' / 'tts'


def _baked_dirs() -> list[Path]:
    """미리 구워 둔 **사장님 목소리** 보관소들 — 읽기만 한다.

    [🔴 왜 따로 두나 — 2026-08-18] 보드 쪽 굽는 일꾼(G:/apix-voice2 의 ag_bake_now.py)이
      구운 wav 를 이 저장소의 캐시 폴더에 **직접 써 넣는다**(그 파일 77행이 경로를 박아 둔다).
      그런데 그 경로는 개발 트리(D:/vibe-coding/...)로 고정이라, 설치본 사이드카가
      제 폴더(%LOCALAPPDATA%/VibeCoding/app/...)를 보는 순간 **이미 구운 216개가 안 보인다.**
      실측(2026-08-18): 굽는 쪽 216개 55MB / 설치본 쪽 3개.
    [🔴 왜 CACHE_DIR 로 합치지 않고 '읽기 전용 한 겹'인가]
      ① `_evict()` 가 500개 상한으로 **스스로 솎아낸다.** 합쳐 두면 정성껏 구운 사장님
         문장이 일상 대화에 밀려 지워지고, 사장님은 "어떤 날은 내 목소리, 어떤 날은 아닌"
         것으로 겪으신다 — 무음보다 잡기 어려운 고장이다. 여기 있는 것은 **절대 안 지운다.**
      ② 굽는 쪽은 다른 저장소의 파일이다. 그쪽을 고치지 않고도 이 문제를 닫을 수 있으면
         그 편이 안전하다(한 리포를 고쳐도 갈라진 사본은 안 고쳐진다 — 규칙 10의 교훈).
    [불변식] 여기에는 **쓰지 않는다.** put()/_evict() 는 CACHE_DIR 만 만진다.
    [설정] VOICE_TTS_BAKED_DIR 에 os.pathsep 로 여러 곳을 줄 수 있다. 안 주면 아래 후보를
      쓰되 **실제로 있는 것만** 고른다 — 없는 경로를 후보로 들고 있어 봐야 매 요청 헛돈다.
    """
    raw = os.environ.get('VOICE_TTS_BAKED_DIR', '').strip()
    if raw:
        cands = [Path(x) for x in raw.split(os.pathsep) if x.strip()]
    else:
        cands = []
        appdata = os.environ.get('APPDATA', '')
        if appdata:
            cands.append(Path(appdata) / 'VibeCoding' / 'voice-baked' / 'tts')
        # [레거시] 굽는 쪽이 아직 이 자리를 박아 쓰고 있다(ag_bake_now.py:77).
        #   그쪽이 위 공용 자리로 옮겨 오면 이 줄은 지워도 된다.
        cands.append(Path(r'D:/vibe-coding/.ai_monitor/voice-server/cache/tts'))
    out = []
    for c in cands:
        try:
            if c.is_dir() and c.resolve() != CACHE_DIR.resolve():
                out.append(c)
        except OSError:
            continue
    return out

# 상한 두 개. 둘 중 하나라도 넘으면 정리한다.
#   파일 수 — 폴더 스캔 비용이 선형이라 무한정 늘면 쓰기가 느려진다.
#   총 바이트 — 짧은 문장 28KB, 긴 답 200KB 안팎이라 64MB 면 수백 개가 들어간다.
MAX_FILES = 500
MAX_BYTES = 64 * 1024 * 1024

# 정리 후 목표선. [WHY 상한까지만 지우지 않나] 딱 맞춰 지우면 다음 쓰기가 또 정리를
# 부른다(정리가 상시 동작이 된다). 여유를 두고 한 번에 깎는다.
TARGET_RATIO = 0.8

# 한 항목 상한. 이보다 큰 결과는 캐시하지 않는다.
# [WHY] 캐시 하나가 예산을 다 먹으면 자주 쓰는 짧은 문장들이 통째로 밀려난다.
MAX_ENTRY = 4 * 1024 * 1024


def key_of(*parts: object) -> str:
    """캐시 키. 엔진·목소리·속도·본문이 하나라도 다르면 다른 소리다 — 전부 넣는다."""
    h = hashlib.sha256()
    for p in parts:
        h.update(str(p).encode('utf-8', 'replace'))
        h.update(b'\x00')                      # 구분자 없으면 ('ab','c') 와 ('a','bc') 가 같아진다
    return h.hexdigest()[:32]


def _path(key: str, ext: str) -> Path:
    return CACHE_DIR / f'{key}.{ext.lstrip(".")}'


def get(key: str, ext: str = 'mp3') -> bytes | None:
    """적중하면 바이트, 아니면 None. 어떤 실패도 예외로 올리지 않는다 —
    캐시가 낭독을 막으면 캐시가 없느니만 못하다.

    [순서] 내 캐시 → 구워 둔 보관소(_baked_dirs). 보관소 쪽은 mtime 도 안 건드린다 —
      읽기 전용이고, LRU 는 솎기를 위한 것인데 거기는 솎지 않기 때문이다.
    """
    p = _path(key, ext)
    data = None
    try:
        data = p.read_bytes()
    except OSError:
        for d in _baked_dirs():
            try:
                data = (d / f'{key}.{ext.lstrip(".")}').read_bytes()
            except OSError:
                continue
            if data:
                return data                # [불변식] 보관소는 utime 도 안 만진다
            data = None
        return None
    if not data:
        return None
    try:
        # LRU 갱신. [제약] 실패해도 무시 — 다른 프로세스가 같은 파일을 만지는 중일 수 있다.
        now = time.time()
        os.utime(p, (now, now))
    except OSError:
        pass
    return data


def put(key: str, data: bytes, ext: str = 'mp3') -> None:
    if not data or len(data) > MAX_ENTRY:
        return
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        # [🔴 임시 파일에 쓰고 바꿔치기] 그냥 쓰면 쓰다 만 파일을 다음 요청이 읽어
        #   깨진 mp3 를 재생한다. 같은 문장을 두 스레드가 동시에 합성할 수 있다.
        tmp = _path(key, ext).with_suffix(f'.{os.getpid()}.part')
        tmp.write_bytes(data)
        os.replace(tmp, _path(key, ext))
    except OSError:
        return
    _evict()


def _evict() -> None:
    """상한을 넘었으면 오래 안 쓴 것부터 지운다."""
    try:
        entries = []
        total = 0
        with os.scandir(CACHE_DIR) as it:
            for e in it:
                if not e.is_file():
                    continue
                try:
                    st = e.stat()
                except OSError:
                    continue
                entries.append((st.st_mtime, st.st_size, e.path))
                total += st.st_size
    except OSError:
        return

    if len(entries) <= MAX_FILES and total <= MAX_BYTES:
        return

    entries.sort()                              # mtime 오름차순 = 가장 오래 안 쓴 것이 앞
    want_files = int(MAX_FILES * TARGET_RATIO)
    want_bytes = int(MAX_BYTES * TARGET_RATIO)
    left = len(entries)
    for _mt, size, path in entries:
        if left <= want_files and total <= want_bytes:
            break
        try:
            os.unlink(path)
        except OSError:
            continue
        total -= size
        left -= 1


def stats() -> dict:
    """폴더 현황. /status 에 실어 사용자가 캐시가 도는지 눈으로 볼 수 있게 한다."""
    files = 0
    total = 0
    try:
        with os.scandir(CACHE_DIR) as it:
            for e in it:
                if not e.is_file():
                    continue
                try:
                    total += e.stat().st_size
                except OSError:
                    continue
                files += 1
    except OSError:
        pass
    baked = []
    for d in _baked_dirs():
        try:
            baked.append({'dir': str(d), 'files': sum(1 for _ in os.scandir(d))})
        except OSError:
            continue
    # [WHY 화면에 내나] 폴더가 맞았는지 사람이 확인할 길이 이것뿐이다. 안 보이면
    #   '구운 소리가 왜 안 나지'를 코드로만 좇게 된다(오늘 그 값을 치렀다).
    return {'files': files, 'bytes': total, 'dir': str(CACHE_DIR), 'baked': baked}
