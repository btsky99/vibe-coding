"""
FILE: src/lan_peers.py
DESCRIPTION: LAN 브리지 페어링/신뢰 저장 + HMAC 토큰. 페어링은 '코드 기반 키 파생(PAKE류)' —
             공유키를 네트워크로 보내지 않고, 양쪽이 페어링 코드에서 각자 HKDF로 같은 키를
             파생한다. 네트워크엔 HMAC 증명(proof)만 오가므로 스니핑해도 키를 못 얻는다.
             신뢰는 '기기 단위'라 프로젝트 DB가 아니라 data_dir/lan_peers.json(PC 전역)에 둔다.

REVISION HISTORY:
- 2026-07-19 Claude: 신규 — LAN 브리지 Phase 1 Task 1.
- 2026-07-19 Claude: 보안수정 C2/C1/W1 — shared_key 평문전송 제거(코드→HKDF 파생),
  페어링 proof 교환, 토큰에 body_hash+filename 서명 + nonce 재사용 거부.
"""
# [WHY 코드기반 파생] shared_key를 pair 응답으로 평문 전송하면 LAN 스니퍼가 키를 캡처해
#   토큰을 영구 위조(C2). 대신 shared_key = HKDF(코드) — 코드는 화면→사람→키패드로만 이동하고
#   네트워크를 횡단하지 않는다. 양쪽이 같은 코드로 같은 키를 얻고, 검증은 proof(HMAC)로만.
# [불변식] 토큰 서명 대상 = 발신자(self_id):nonce:ts:body_hash:filename. body/파일명이 서명에
#   포함돼야 캡처-변조 재전송(W1)을 막는다. nonce는 window 안에서 1회용(재사용 거부).
from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import time
import uuid
from pathlib import Path

TOKEN_WINDOW_SEC = 120     # [제약] 토큰 ts 허용 오차 — 재전송 창을 좁히되 PC간 시계 오차 흡수
_PAIR_SALT = b'vibe-lan-pair-v1'
_CODE_ALPHABET = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789'  # base32 유사(혼동문자 0/O/1/I/L 제외)


def _hkdf_sha256(ikm: bytes, salt: bytes, info: bytes, length: int = 32) -> bytes:
    """HKDF-SHA256 (RFC 5869) — stdlib hmac/hashlib만으로. 외부 의존 0(이식성)."""
    prk = hmac.new(salt, ikm, hashlib.sha256).digest()
    okm, t, i = b'', b'', 0
    while len(okm) < length:
        i += 1
        t = hmac.new(prk, t + info + bytes([i]), hashlib.sha256).digest()
        okm += t
    return okm[:length]


def derive_key(code: str) -> str:
    """페어링 코드 → 32바이트 대칭키(hex). 양쪽이 코드만으로 동일 계산 — 키는 전송 안 함."""
    return _hkdf_sha256(code.encode(), _PAIR_SALT, b'shared-key', 32).hex()


def make_pair_proof(code: str, purpose: str, peer_id: str) -> str:
    """페어링 증명 — HMAC(파생키, purpose:peer_id). 코드/키 노출 없이 '코드를 안다'를 증명.

    [보안] 스니퍼는 proof만 봄 → HMAC 역상 저항으로 코드/키 역산 불가. purpose로 init/ack를
    분리해 리플레이(개시 proof를 ack로 되쓰기)를 차단.
    """
    key = derive_key(code)
    return hmac.new(key.encode(), f'{purpose}:{peer_id}'.encode(), hashlib.sha256).hexdigest()


def verify_pair_proof(code: str, purpose: str, peer_id: str, proof: str) -> bool:
    if not proof:
        return False
    return hmac.compare_digest(make_pair_proof(code, purpose, peer_id), proof)


class LanPeers:
    """data_dir/lan_peers.json 백엔드. 단일 프로세스(브리지) 소유 전제 — 파일 락 없음."""

    def __init__(self, data_dir: Path):
        self.path = Path(data_dir) / 'lan_peers.json'
        self._data = self._load()
        self._seen_nonces: dict[str, float] = {}   # nonce -> ts (재사용 거부, window 밖 정리)

    def _load(self) -> dict:
        if self.path.exists():
            try:
                return json.loads(self.path.read_text(encoding='utf-8'))
            except (json.JSONDecodeError, OSError):
                pass   # 손상 시 초기화 — 페어링은 재수행 가능한 재생성 데이터
        return {'self_id': uuid.uuid4().hex, 'peers': {}}

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self._data, ensure_ascii=False, indent=2),
                             encoding='utf-8')

    @property
    def self_id(self) -> str:
        if 'self_id' not in self._data:
            self._data['self_id'] = uuid.uuid4().hex
            self._save()
        return self._data['self_id']

    # ── 페어링 코드 ──────────────────────────────────────────────────────
    @staticmethod
    def generate_pair_code() -> str:
        """8자 코드(엔트로피 ~40bit). [보안C1] 6자리(20bit)는 온라인 브루트포스에 약해
        base32 유사 8자로 상향 — 실패카운터·TTL과 함께 브루트포스를 구조적으로 봉쇄."""
        return ''.join(secrets.choice(_CODE_ALPHABET) for _ in range(8))

    # ── 신뢰 저장 ────────────────────────────────────────────────────────
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

    # ── HMAC 토큰 (body/filename 서명 + nonce 1회용) ─────────────────────
    def make_token(self, peer_id: str, body_hash: str = '', filename: str = '') -> str | None:
        """상대(peer_id)의 공유키로 서명한 토큰. 서명 대상에 body_hash·filename 포함(W1)."""
        key = self._key_of(peer_id)
        if not key:
            return None
        nonce = secrets.token_hex(8)
        ts = str(int(time.time()))
        msg = f'{self.self_id}:{nonce}:{ts}:{body_hash}:{filename}'
        mac = hmac.new(key.encode(), msg.encode(), hashlib.sha256).hexdigest()
        return f'{nonce}:{ts}:{mac}'

    def verify_token(self, peer_id: str, token: str,
                     body_hash: str = '', filename: str = '') -> bool:
        """토큰 검증 — 키·ts윈도우·nonce 1회용·body/filename 바인딩 모두 통과해야 True."""
        key = self._key_of(peer_id)
        if not key or not token:
            return False
        parts = token.split(':')
        if len(parts) != 3:
            return False
        nonce, ts, mac = parts
        now = int(time.time())
        try:
            if abs(now - int(ts)) > TOKEN_WINDOW_SEC:
                return False
        except ValueError:
            return False
        # [보안W1] nonce 재사용 거부 — window 밖 항목은 정리(무한 증가 방지).
        self._seen_nonces = {n: t for n, t in self._seen_nonces.items()
                             if now - t <= TOKEN_WINDOW_SEC}
        if nonce in self._seen_nonces:
            return False
        msg = f'{peer_id}:{nonce}:{ts}:{body_hash}:{filename}'
        expected = hmac.new(key.encode(), msg.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, mac):
            return False
        self._seen_nonces[nonce] = float(now)   # 검증 성공한 nonce만 소비 등록
        return True
