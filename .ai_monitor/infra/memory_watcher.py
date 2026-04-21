"""
FILE: infra/memory_watcher.py
DESCRIPTION: 에이전트 메모리(Claude Code / Gemini CLI) 파일 감시 + PostgreSQL
             hive_memory 자동 동기화 워처. 임베딩 유틸(fastembed 기반)과
             레거시 파일 메모리 경로 탐색 헬퍼도 함께 제공합니다.

             - MemoryWatcher : ~/.claude/projects/*/memory/*.md,
                               ~/.gemini/tmp/*/logs.json,
                               ~/.gemini/tmp/*/chats/session-*.json 를 폴링
             - embed / cosine_sim : fastembed 기반 벡터화 + 유사도 계산
             - legacy_memory_data_dir : config.json last_path 기반 레거시
               데이터 디렉터리 탐색 (있으면 ensure_legacy_store)

REVISION HISTORY:
- 2026-04-21 Claude: server.py L989~1378 분리 (Task 6.1)
                     embedder lazy-init 글로벌(_embedder/_embedder_lock)을
                     모듈 내부로 캡슐화. PROJECT_ID는 생성자 인자로 주입.
"""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path

from src.pg_store import (
    auto_promote_fleeting,
    ensure_legacy_store,
    ensure_schema,
    get_memory,
    list_memory,
    set_memory,
)


# ── 레거시 파일 메모리 경로 ─────────────────────────────────────────────────
def legacy_memory_data_dir(config_file: Path, default_data_dir: Path) -> Path:
    """config.json의 last_path 하위 .ai_monitor/data 를 우선 사용.

    존재하면 레거시 SQLite 스키마를 보장(ensure_legacy_store)하고 해당
    경로를 반환. 없으면 기본 DATA_DIR을 반환합니다.
    """
    try:
        if config_file.exists():
            cfg_data = json.loads(config_file.read_text(encoding='utf-8'))
            last_path = cfg_data.get('last_path', '')
            if last_path:
                local_dir = Path(last_path) / '.ai_monitor' / 'data'
                if local_dir.exists():
                    ensure_legacy_store(local_dir)
                    return local_dir
    except Exception as e:
        print(f"[FILE ERROR] legacy_memory_data_dir 탐색: {e}")
    return default_data_dir


def init_memory_db(data_dir: Path) -> None:
    """Postgres 기반 메모리 스키마 초기화."""
    ensure_schema(data_dir)


# ── 임베딩 헬퍼 (fastembed 기반, 한국어 포함 다국어 지원) ────────────────────
_embedder = None
_embedder_lock = threading.Lock()
_EMBED_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"


def _get_embedder():
    """fastembed 모델 lazy 초기화 — 첫 호출 시 한 번만 로드."""
    global _embedder
    if _embedder is None:
        with _embedder_lock:
            if _embedder is None:
                try:
                    from fastembed import TextEmbedding
                    _embedder = TextEmbedding(model_name=_EMBED_MODEL)
                    print(f"[Embedding] 모델 로드 완료: {_EMBED_MODEL}")
                except Exception as e:
                    print(f"[Embedding] 모델 로드 실패: {e}")
                    _embedder = False  # 실패 표시 (재시도 방지)
    return _embedder if _embedder else None


def embed(text: str) -> bytes | None:
    """텍스트 → float32 벡터 bytes 변환. 실패 시 None 반환."""
    try:
        import numpy as np
        embedder = _get_embedder()
        if embedder is None:
            return None
        vec = list(embedder.embed([text[:512]]))[0]  # 512자 제한
        return np.array(vec, dtype=np.float32).tobytes()
    except Exception as e:
        print(f"[Embedding] 변환 실패: {e}")
        return None


def cosine_sim(a_bytes: bytes, b_bytes: bytes) -> float:
    """두 float32 벡터 bytes 간 코사인 유사도 (0~1)."""
    try:
        import numpy as np
        a = np.frombuffer(a_bytes, dtype=np.float32)
        b = np.frombuffer(b_bytes, dtype=np.float32)
        denom = np.linalg.norm(a) * np.linalg.norm(b)
        return float(np.dot(a, b) / denom) if denom > 1e-10 else 0.0
    except Exception:
        return 0.0  # 벡터 유사도 계산 실패 — 0.0 반환


# ── 에이전트 메모리 워처 ─────────────────────────────────────────────────────
class MemoryWatcher(threading.Thread):
    """
    Claude Code / Gemini CLI 의 메모리 파일을 감시하여
    변경 발생 시 PostgreSQL hive_memory 테이블에 자동 동기화하는 백그라운드 워처.

    - Claude Code : ~/.claude/projects/*/memory/*.md
    - Gemini CLI  : ~/.gemini/tmp/{프로젝트명}/logs.json
                    ~/.gemini/tmp/{프로젝트명}/chats/session-*.json

    터미널 번호(T1, T2 …)는 최초 감지된 순서로 자동 부여된다.
    """

    POLL_INTERVAL = 30  # 초 단위 폴링 간격 (리소스 아끼기 위해 30초로 완화)

    def __init__(self, project_id: str) -> None:
        super().__init__(daemon=True, name='MemoryWatcher')
        self._project_id = project_id                  # 현재 활성 프로젝트 ID (하이브 메모리 역동기화 필터)
        self._mtimes: dict[str, float] = {}            # 파일경로 → 마지막 mtime
        self._terminal_map: dict[str, int] = {}        # source_key → 터미널 번호
        self._next_terminal: int = 1

    # ── 공개 메서드 ─────────────────────────────────────────────────────────
    def run(self) -> None:
        print("[MemoryWatcher] 에이전트 메모리 감시 시작")
        _sync_tick = 0     # 역방향 동기화 주기 카운터 (40 * 30초 ≈ 20분)
        _promote_tick = 0  # C.4 자동 승격 주기 (10 * 30초 = 5분)
        while True:
            try:
                self._scan_claude_memories()
                self._scan_gemini_logs()
                self._scan_gemini_chats()
                # 10분마다 PostgreSQL hive_memory → MEMORY.md 역방향 동기화 실행
                _sync_tick += 1
                if _sync_tick >= 40:
                    self._sync_to_claude_memory()
                    _sync_tick = 0
                # 5분마다 fleeting → permanent 자동 승격 (C.4)
                _promote_tick += 1
                if _promote_tick >= 10:
                    self._auto_promote_zettel()
                    _promote_tick = 0
            except Exception as e:
                print(f"[MemoryWatcher] 스캔 오류: {e}")
            time.sleep(self.POLL_INTERVAL)

    # ── 내부: C.4 자동 승격 배치 ─────────────────────────────────────────────
    def _auto_promote_zettel(self) -> None:
        """조건 충족한 fleeting 노트를 permanent로 일괄 승격 (5분 배치).
        실패해도 조용히 넘어감 — 다음 주기에 재시도.
        """
        try:
            n = auto_promote_fleeting()
            if n > 0:
                print(f"[MemoryWatcher] 자동 승격 — {n}건 fleeting → permanent")
        except Exception as e:
            print(f"[MemoryWatcher] 자동 승격 오류: {e}")

    # ── 내부: 역방향 동기화 (PostgreSQL hive_memory → MEMORY.md) ────────────
    def _sync_to_claude_memory(self) -> None:
        """Gemini·외부 에이전트가 DB에 쓴 항목을 Claude Code auto-memory 파일에
        역동기화한다. claude:T* 키(Claude가 직접 쓴 메모리)는 제외하여 순환 방지.
        MEMORY.md 의 '## 하이브 공유 메모리' 섹션을 교체/추가한다.
        """
        memory_file = (
            Path.home() / '.claude' / 'projects' / self._project_id / 'memory' / 'MEMORY.md'
        )
        if not memory_file.exists():
            return
        try:
            rows = [
                row for row in list_memory(top_k=30, project_id=self._project_id)
                if not str(row.get('key', '')).startswith('claude:T')
            ][:15]
            if not rows:
                return

            entries = []
            for r in rows:
                e = dict(r)
                e['tags'] = json.loads(e.get('tags', '[]'))
                entries.append(e)

            # 섹션 구성
            HEADER = '## 하이브 공유 메모리 (자동 동기화)'
            lines = [
                HEADER,
                f'_업데이트: {time.strftime("%Y-%m-%dT%H:%M:%S")} | {len(entries)}개 항목_\n',
            ]
            for e in entries:
                tags_str = ' '.join(f'#{t}' for t in e.get('tags', []))
                preview = e['content'][:90].replace('\n', ' ')
                if len(e['content']) > 90:
                    preview += '...'
                lines.append(f"- **[{e['key']}]** `{e.get('author', '?')}` {tags_str}")
                lines.append(f"  {preview}")

            new_section = '\n'.join(lines) + '\n'
            content = memory_file.read_text(encoding='utf-8', errors='replace')

            if HEADER in content:
                start = content.index(HEADER)
                nxt = content.find('\n## ', start + len(HEADER))
                if nxt == -1:
                    content = content[:start].rstrip() + '\n\n' + new_section
                else:
                    content = (
                        content[:start].rstrip() + '\n\n' + new_section
                        + '\n' + content[nxt + 1:]
                    )
            else:
                content = content.rstrip() + '\n\n' + new_section

            memory_file.write_text(content, encoding='utf-8')
            print(f"[MemoryWatcher] MEMORY.md 역동기화 완료: {len(entries)}개 항목")
        except Exception as e:
            print(f"[MemoryWatcher] MEMORY.md 역동기화 오류: {e}")

    # ── 내부: 터미널 번호 부여 ───────────────────────────────────────────────
    def _terminal_id(self, source_key: str) -> int:
        if source_key not in self._terminal_map:
            self._terminal_map[source_key] = self._next_terminal
            self._next_terminal += 1
        return self._terminal_map[source_key]

    # ── 내부: DB 저장 (Postgres-backed memory store) ───────────────────────
    def _upsert(self, key: str, title: str, content: str,
                author: str, tags: list, project_id: str = '') -> None:
        now = time.strftime('%Y-%m-%dT%H:%M:%S')
        proj = project_id or self._project_id
        try:
            existing = get_memory(key)
            created_at = existing.get('created_at', now) if existing else now
            set_memory(
                key=key,
                title=title,
                content=content,
                tags=tags,
                author=author,
                project_id=proj,
                created_at=created_at,
                updated_at=now,
            )
            print(f"[MemoryWatcher] 동기화 완료: {key}")
        except Exception as e:
            print(f"[MemoryWatcher] DB 쓰기 오류: {e}")

    # ── 내부: 파일 변경 여부 확인 ───────────────────────────────────────────
    def _changed(self, path: Path) -> bool:
        try:
            mtime = path.stat().st_mtime
        except OSError:
            return False
        key = str(path)
        # 메모리 누수 방지: 감시 대상 파일 정보가 너무 많아지면 비우기
        if len(self._mtimes) > 5000:
            self._mtimes.clear()

        if self._mtimes.get(key) == mtime:
            return False
        self._mtimes[key] = mtime
        return True

    # ── Claude Code 메모리 스캔 ─────────────────────────────────────────────
    def _scan_claude_memories(self) -> None:
        projects_root = Path.home() / '.claude' / 'projects'
        if not projects_root.exists():
            return
        for proj_dir in projects_root.iterdir():
            if not proj_dir.is_dir():
                continue
            memory_dir = proj_dir / 'memory'
            if not memory_dir.exists():
                continue
            for md_file in memory_dir.glob('*.md'):
                if not self._changed(md_file):
                    continue
                try:
                    content = md_file.read_text(encoding='utf-8', errors='replace').strip()
                    if not content:
                        continue
                    tid = self._terminal_id(f"claude:{proj_dir.name}")
                    stem = md_file.stem  # 예: 'current-work', 'MEMORY'
                    key = f"claude:T{tid}:{stem}"
                    self._upsert(
                        key=key,
                        title=f"[CLAUDE T{tid}] {stem} ({proj_dir.name[:12]})",
                        content=content,
                        author=f"claude-code:terminal-{tid}",
                        tags=['claude', f'terminal-{tid}', stem, proj_dir.name],
                        project_id=proj_dir.name,
                    )
                except Exception as e:
                    print(f"[MemoryWatcher] Claude 파일 오류 {md_file}: {e}")

    # ── Gemini logs.json 스캔 (최신 세션 요약) ─────────────────────────────
    def _scan_gemini_logs(self) -> None:
        gemini_tmp = Path.home() / '.gemini' / 'tmp'
        if not gemini_tmp.exists():
            return
        for proj_dir in gemini_tmp.iterdir():
            if not proj_dir.is_dir():
                continue
            logs_file = proj_dir / 'logs.json'
            if not logs_file.exists() or not self._changed(logs_file):
                continue
            try:
                raw = logs_file.read_text(encoding='utf-8', errors='replace')
                entries = json.loads(raw)
                if not isinstance(entries, list) or not entries:
                    continue

                # 최신 세션 ID 파악
                latest_session = next(
                    (e['sessionId'] for e in reversed(entries) if e.get('sessionId')),
                    None
                )
                if not latest_session:
                    continue

                # 최신 세션 user 메시지 최대 5개
                msgs = [
                    e for e in entries
                    if e.get('sessionId') == latest_session
                    and e.get('type') == 'user'
                ][-5:]
                if not msgs:
                    continue

                proj_name = proj_dir.name
                tid = self._terminal_id(f"gemini:{proj_name}")
                lines = [
                    f"[Gemini 세션: {latest_session[:8]}…] 프로젝트: {proj_name}",
                    f"최근 사용자 메시지 ({len(msgs)}개):",
                ]
                for m in msgs:
                    ts = str(m.get('timestamp', ''))[:16]
                    text = str(m.get('message', ''))[:300]
                    lines.append(f"- [{ts}] {text}")

                self._upsert(
                    key=f"gemini:T{tid}:{proj_name}:log",
                    title=f"[GEMINI T{tid}] {proj_name} 활동 로그",
                    content='\n'.join(lines),
                    author=f"gemini:terminal-{tid}",
                    tags=['gemini', f'terminal-{tid}', proj_name, 'log'],
                    project_id=proj_name,
                )
            except Exception as e:
                print(f"[MemoryWatcher] Gemini logs 오류 {logs_file}: {e}")

    # ── Gemini chats 세션 파일 스캔 ────────────────────────────────────────
    def _scan_gemini_chats(self) -> None:
        gemini_tmp = Path.home() / '.gemini' / 'tmp'
        if not gemini_tmp.exists():
            return
        for proj_dir in gemini_tmp.iterdir():
            if not proj_dir.is_dir():
                continue
            chats_dir = proj_dir / 'chats'
            if not chats_dir.exists():
                continue
            # 가장 최근 세션 파일 하나만 처리 (mtime 기준)
            # 수천 개의 세션 파일이 있을 경우 sorted()는 비효율적이므로 max() 사용
            try:
                session_files = list(chats_dir.glob('session-*.json'))
                if not session_files:
                    continue
                latest = max(session_files, key=lambda p: p.stat().st_mtime)
            except (ValueError, OSError):
                continue

            if not self._changed(latest):
                continue
            try:
                raw = latest.read_text(encoding='utf-8', errors='replace')
                msgs = json.loads(raw)
                if not isinstance(msgs, list) or not msgs:
                    continue

                # model 응답 중 마지막 요약 추출
                model_msgs = [
                    m for m in msgs if m.get('role') == 'model'
                ]
                summary_parts = []
                if model_msgs:
                    last_model = model_msgs[-1]
                    parts = last_model.get('parts', [])
                    for p in parts:
                        if isinstance(p, dict) and p.get('text'):
                            summary_parts.append(p['text'][:400])
                            break

                proj_name = proj_dir.name
                tid = self._terminal_id(f"gemini:{proj_name}")
                content = (
                    f"[Gemini 채팅 세션] 프로젝트: {proj_name}\n"
                    f"파일: {latest.name}\n"
                    f"메시지 수: {len(msgs)}\n"
                )
                if summary_parts:
                    content += f"마지막 응답 요약:\n{summary_parts[0]}"

                self._upsert(
                    key=f"gemini:T{tid}:{proj_name}:chat",
                    title=f"[GEMINI T{tid}] {proj_name} 채팅",
                    content=content,
                    author=f"gemini:terminal-{tid}",
                    tags=['gemini', f'terminal-{tid}', proj_name, 'chat'],
                    project_id=proj_name,
                )
            except Exception as e:
                print(f"[MemoryWatcher] Gemini chat 오류 {latest}: {e}")
