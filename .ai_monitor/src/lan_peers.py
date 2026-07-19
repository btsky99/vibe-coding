"""
FILE: src/lan_peers.py
DESCRIPTION: LAN 브리지 페어링/신뢰 저장 + HMAC 토큰. 같은 네트워크의 다른 바이브코딩과
             페어링(6자리 코드 → 공유키 교환)하고, 이후 요청을 HMAC 토큰으로 인증한다.
             신뢰는 '기기 단위'라 프로젝트 DB가 아니라 data_dir/lan_peers.json(PC 전역)에 둔다.

REVISION HISTORY:
- 2026-07-19 Claude: 신규 — LAN 브리지 Phase 1 Task 1. project_id 비의존(이식성).
"""
# [WHY] DB(프로젝트 격리)가 아니라 파일 저장 — 페어링 신뢰는 이 PC↔저 PC 관계라 프로젝트가
#   여러 개여도 신뢰는 하나여야 한다. lan_peers.json은 data_dir 런타임 경로라 frozen에서도 안전.
# [불변식] shared_key는 페어링 시 '한쪽이 생성해 코드와 함께 상대에 전달' — 양쪽이 같은 키를
#   갖는 대칭 시크릿. HMAC 검증은 이 대칭키에 의존하므로 평문 노출 금지(로컬 파일 권한에 의존).
from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import time
import uuid
from pathlib import Path

TOKEN_WINDOW_SEC = 120   # [제약] 토큰 ts 허용 오차 — 재전송 공격 창을 좁히되 PC간 시계 오차 흡수


class LanPeers:
    """data_dir/lan_peers.json 백엔드. 단일 프로세스(브리지) 소유 전제 — 파일 락 없음.

    [제약] 브리지 프로세스 하나만 이 파일을 쓴다(싱글턴). server.py 쪽 lan_api는 브리지를
    HTTP로 경유하므로 직접 파일을 만지지 않는다 → 동시 쓰기 없음.
    """

    def __init__(self, data_dir: Path):
        self.path = Path(data_dir) / 'lan_peers.json'
        self._data = self._load()

    def _load(self) -> dict:
        if self.path.exists():
            try:
                return json.loads(self.path.read_text(encoding='utf-8'))
            except (json.JSONDecodeError, OSError):
                # [WHY] 손상 시 초기화 — 페어링은 다시 하면 되는 재생성 가능 데이터라 보존 가치 낮음.
                pass
        return {'self_id': uuid.uuid4().hex, 'peers': {}}

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self._data, ensure_ascii=False, indent=2),
                             encoding='utf-8')

    # ── 자기 식별자 ──────────────────────────────────────────────────────
    @property
    def self_id(self) -> str:
        """이 기기의 고유 peer_id — 최초 생성 후 불변(발견 announce·토큰에 사용)."""
        if 'self_id' not in self._data:
            self._data['self_id'] = uuid.uuid4().hex
            self._save()
        return self._data['self_id']

    # ── 페어링 ───────────────────────────────────────────────────────────
    @staticmethod
    def generate_pair_code() -> str:
        """6자리 페어링 코드. secrets 기반(추측 방지). 코드+shared_key를 상대에 전달."""
        return f'{secrets.randbelow(1000000):06d}'

    @staticmethod
    def new_shared_key() -> str:
        return secrets.token_hex(32)

    def add_peer(self, peer_id: str, name: str, shared_key: str) -> None:
        self._data.setdefault('peers', {})[peer_id] = {
            'name': name, 'shared_key': shared_key,
            'paired_at': time.strftime('%Y-%m-%dT%H:%M:%S'),
        }
        self._save()

    def remove_peer(self, peer_id: str) -> bool:
        if peer_id in self._data.get('peers', {}):
            del self._data['peers'][peer_id]
            self._save()
            return True
        return False

    def list_peers(self) -> list[dict]:
        """신뢰 목록 — shared_key는 노출하지 않고 id/name/paired_at만."""
        return [{'peer_id': pid, 'name': p.get('name', ''), 'paired_at': p.get('paired_at', '')}
                for pid, p in self._data.get('peers', {}).items()]

    def is_trusted(self, peer_id: str) -> bool:
        return peer_id in self._data.get('peers', {})

    def _key_of(self, peer_id: str) -> str | None:
        p = self._data.get('peers', {}).get(peer_id)
        return p.get('shared_key') if p else None

    # ── HMAC 토큰 ────────────────────────────────────────────────────────
    def make_token(self, peer_id: str) -> str | None:
        """상대(peer_id)와의 공유키로 서명한 토큰 'nonce:ts:hmac'. 미신뢰 상대면 None.

        [불변식] 서명 대상은 나(self_id) → 상대가 verify 시 자기 peers[self_id] 키로 검증.
        즉 A가 B에게 보낼 토큰은 A가 B의 shared_key로 만들고, B는 A(=자기 목록의 A)의 키로 검증.
        같은 대칭키라 성립.
        """
        key = self._key_of(peer_id)
        if not key:
            return None
        nonce = secrets.token_hex(8)
        ts = str(int(time.time()))
        mac = hmac.new(key.encode(), f'{self.self_id}:{nonce}:{ts}'.encode(),
                       hashlib.sha256).hexdigest()
        return f'{nonce}:{ts}:{mac}'

    def verify_token(self, peer_id: str, token: str) -> bool:
        """peer_id가 보낸 토큰 검증. shared_key·ts윈도우·HMAC 상수시간 비교 모두 통과해야 True."""
        key = self._key_of(peer_id)
        if not key or not token:
            return False
        parts = token.split(':')
        if len(parts) != 3:
            return False
        nonce, ts, mac = parts
        try:
            if abs(int(time.time()) - int(ts)) > TOKEN_WINDOW_SEC:
                return False
        except ValueError:
            return False
        expected = hmac.new(key.encode(), f'{peer_id}:{nonce}:{ts}'.encode(),
                            hashlib.sha256).hexdigest()
        # [보안] compare_digest — 타이밍 사이드채널 방지.
        return hmac.compare_digest(expected, mac)
