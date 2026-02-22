"""
# ------------------------------------------------------------------------
# 📄 파일명: orchestrator.py
# 📂 메인 문서 링크: docs/README.md
# 📝 설명: 하이브 마인드 자동 조율 오케스트레이터.
#          에이전트 활동 현황을 감시하고, 미할당 태스크 자동 배정,
#          유휴 에이전트 감지, 충돌 경고 등을 수행합니다.
# ------------------------------------------------------------------------

사용법:
  python scripts/orchestrator.py            # 단발 실행 (1회 조율 후 종료)
  python scripts/orchestrator.py --daemon   # 데몬 모드 (30초 주기 반복)
  python scripts/orchestrator.py --daemon --interval 60
"""

import sys
import os
import time
import json
import argparse
import sqlite3
import urllib.request
import urllib.error
from datetime import datetime, timedelta

# ─── 설정 상수 ────────────────────────────────────────────────────────────────
DEFAULT_PORTS = [8005, 8000]
KNOWN_AGENTS  = ['claude', 'gemini']    # 알려진 에이전트 목록
IDLE_THRESHOLD_SEC = 300                # 유휴 판정 기준: 5분 (300초)
LOG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        '..', '.ai_monitor', 'data', 'orchestrator_log.jsonl')

# ─── API 헬퍼 ─────────────────────────────────────────────────────────────────

def api_get(path: str, port: int):
    """GET 요청 헬퍼 - 실패 시 None 반환"""
    try:
        with urllib.request.urlopen(f'http://localhost:{port}{path}', timeout=3) as r:
            return json.loads(r.read().decode('utf-8'))
    except Exception:
        return None


def api_post(path: str, body: dict, port: int):
    """POST 요청 헬퍼 - 실패 시 None 반환"""
    try:
        payload = json.dumps(body).encode('utf-8')
        req = urllib.request.Request(
            f'http://localhost:{port}{path}',
            data=payload,
            headers={'Content-Type': 'application/json'},
            method='POST',
        )
        with urllib.request.urlopen(req, timeout=3) as r:
            return json.loads(r.read().decode('utf-8'))
    except Exception:
        return None


def find_port() -> int | None:
    """실행 중인 하이브 서버 포트 자동 감지"""
    for p in DEFAULT_PORTS:
        if api_get('/api/tasks', p) is not None:
            return p
    return None


# ─── 로컬 DB / 파일 접근 헬퍼 ────────────────────────────────────────────────

def _hive_db_path() -> str:
    script_dir = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(script_dir, '..', '.ai_monitor', 'data', 'hive_mind.db')


def _tasks_file_path() -> str:
    script_dir = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(script_dir, '..', '.ai_monitor', 'data', 'tasks.json')


def _open_hive_db() -> sqlite3.Connection:
    """hive_mind.db 커넥션 반환 (없으면 None)"""
    path = _hive_db_path()
    if not os.path.exists(path):
        return None
    conn = sqlite3.connect(path, timeout=5)
    conn.row_factory = sqlite3.Row
    return conn


def _load_tasks() -> list:
    """tasks.json 직접 읽기"""
    path = _tasks_file_path()
    if os.path.exists(path):
        try:
            with open(path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            pass
    return []


def _save_tasks(tasks: list) -> None:
    """tasks.json 직접 쓰기"""
    path = _tasks_file_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(tasks, f, ensure_ascii=False, indent=2)


# ─── 오케스트레이터 핵심 로직 ─────────────────────────────────────────────────

def get_agent_last_seen() -> dict:
    """
    hive_mind.db session_logs 테이블에서 에이전트별 마지막 활동 시각 조회.
    반환: {'claude': '2026-02-23T12:00:00', 'gemini': None, ...}
    """
    conn = _open_hive_db()
    result = {agent: None for agent in KNOWN_AGENTS}
    if not conn:
        return result
    try:
        rows = conn.execute(
            "SELECT agent, MAX(ts_start) as last_seen FROM session_logs "
            "WHERE agent IN ('claude','gemini') GROUP BY agent"
        ).fetchall()
        for row in rows:
            result[row['agent']] = row['last_seen']
    except Exception:
        pass
    finally:
        conn.close()
    return result


def get_agent_task_count(tasks: list) -> dict:
    """에이전트별 미완료 태스크 수 집계"""
    count = {agent: 0 for agent in KNOWN_AGENTS}
    count['all'] = 0
    for t in tasks:
        if t.get('status') == 'done':
            continue
        assignee = t.get('assigned_to', 'all')
        if assignee in count:
            count[assignee] += 1
        else:
            count['all'] += 1
    return count


def pick_best_agent(last_seen: dict, task_count: dict) -> str:
    """
    가장 적합한 에이전트 선택 (미할당 태스크 자동 배정용).
    기준: 1) 최근 활동한 에이전트 우선, 2) 태스크 부하 적은 쪽 우선
    """
    now = datetime.now()
    scores = {}
    for agent in KNOWN_AGENTS:
        seen_str = last_seen.get(agent)
        if seen_str:
            try:
                seen_dt = datetime.fromisoformat(seen_str.replace('Z', ''))
                # 최근 활동일수록 높은 점수 (초 단위 역수)
                recency = 1.0 / max(1, (now - seen_dt).total_seconds())
            except Exception:
                recency = 0.0
        else:
            recency = 0.0
        # 태스크 부하 패널티 (많을수록 낮은 점수)
        load_penalty = task_count.get(agent, 0) * 0.01
        scores[agent] = recency - load_penalty

    # 점수 높은 에이전트 선택 (동점이면 첫 번째)
    best = max(scores, key=lambda a: scores[a])
    return best


def _write_orch_log(action: str, detail: str) -> None:
    """오케스트레이터 액션 로그 기록"""
    entry = {
        'timestamp': datetime.now().isoformat(),
        'action': action,
        'detail': detail,
    }
    os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
    with open(LOG_FILE, 'a', encoding='utf-8') as f:
        f.write(json.dumps(entry, ensure_ascii=False) + '\n')


def send_orch_message(content: str, to: str, port: int | None) -> None:
    """오케스트레이터가 에이전트에게 메시지 전송"""
    body = {
        'from': 'orchestrator',
        'to': to,
        'type': 'info',
        'content': content,
    }
    if port:
        api_post('/api/message', body, port)
    # 서버 없을 때는 메시지 채널 파일에 직접 기록 (간소화)
    _write_orch_log('message_sent', f'[→{to}] {content}')


def auto_assign_tasks(tasks: list, last_seen: dict, task_count: dict,
                      port: int | None) -> list:
    """
    assigned_to='all' 이면서 pending 상태인 태스크를 최적 에이전트에 자동 배정.
    반환: 수행한 액션 설명 리스트
    """
    actions = []
    changed = False

    for t in tasks:
        if t.get('assigned_to') == 'all' and t.get('status') == 'pending':
            best = pick_best_agent(last_seen, task_count)
            t['assigned_to'] = best
            t['updated_at'] = datetime.now().strftime('%Y-%m-%dT%H:%M:%S')
            task_count[best] = task_count.get(best, 0) + 1
            changed = True

            desc = f"태스크 자동 배정: [{t['id']}] '{t['title']}' → {best}"
            actions.append(desc)
            _write_orch_log('auto_assign', desc)

            # 담당 에이전트에게 알림 메시지 전송
            msg = (f"[오케스트레이터] 새 태스크가 당신에게 자동 배정되었습니다.\n"
                   f"태스크: {t['title']}\nID: {t['id']}")
            send_orch_message(msg, best, port)

            # API로 업데이트 시도, 없으면 로컬 파일로
            if port:
                api_post('/api/tasks/update',
                         {'id': t['id'], 'assigned_to': best}, port)

    # 서버 없으면 직접 파일 저장
    if changed and not port:
        _save_tasks(tasks)

    return actions


def detect_idle_agents(last_seen: dict, port: int | None) -> list:
    """
    IDLE_THRESHOLD_SEC 이상 활동 없는 에이전트 감지 → 경고 메시지 전송.
    반환: 경고 설명 리스트
    """
    warnings = []
    now = datetime.now()

    for agent, seen_str in last_seen.items():
        if seen_str is None:
            continue  # 한 번도 활동 안 한 에이전트는 패스
        try:
            seen_dt = datetime.fromisoformat(seen_str.replace('Z', ''))
            idle_sec = (now - seen_dt).total_seconds()
            if idle_sec > IDLE_THRESHOLD_SEC:
                minutes = int(idle_sec // 60)
                warn = f"{agent} 에이전트가 {minutes}분째 비활성 상태입니다."
                warnings.append(warn)
                _write_orch_log('idle_agent', warn)
                send_orch_message(
                    f"[오케스트레이터] {warn} 대기 중인 태스크를 확인하세요.",
                    agent, port
                )
        except Exception:
            pass

    return warnings


def detect_task_overload(task_count: dict, port: int | None) -> list:
    """
    특정 에이전트의 미완료 태스크가 5개 이상이면 과부하 경고.
    반환: 경고 설명 리스트
    """
    warnings = []
    OVERLOAD_THRESHOLD = 5

    for agent, count in task_count.items():
        if agent == 'all':
            continue
        if count >= OVERLOAD_THRESHOLD:
            warn = f"{agent} 에이전트에 태스크 {count}개가 적재되었습니다 (과부하 위험)."
            warnings.append(warn)
            _write_orch_log('task_overload', warn)
            send_orch_message(
                f"[오케스트레이터] {warn} 다른 에이전트에게 일부 위임을 검토하세요.",
                agent, port
            )

    return warnings


def detect_lock_conflicts(port: int | None) -> list:
    """
    동일 파일을 두 에이전트가 동시 점유하는 경우 감지.
    반환: 경고 설명 리스트 (현재 구조상 단일 owner이므로 다중 락 탐지)
    """
    warnings = []
    if port:
        locks = api_get('/api/locks', port) or {}
    else:
        # locks.json 직접 읽기
        lf = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          '..', '.ai_monitor', 'data', 'locks.json')
        try:
            with open(lf, encoding='utf-8') as f:
                locks = json.load(f)
        except Exception:
            locks = {}

    # 파일별 소유자가 다른 에이전트면 충돌 (현재 구조: 단일 owner만 가능)
    # 미래 확장을 위한 자리 - 지금은 잠긴 파일 수 경고만
    if len(locks) > 10:
        warn = f"락(Lock) 파일이 {len(locks)}개로 비정상적으로 많습니다. 강제 해제를 검토하세요."
        warnings.append(warn)
        _write_orch_log('lock_anomaly', warn)
        send_orch_message(f"[오케스트레이터] {warn}", 'all', port)

    return warnings


# ─── 단일 조율 사이클 ─────────────────────────────────────────────────────────

def run_cycle(port: int | None) -> tuple[list, list]:
    """
    한 번의 조율 사이클 수행.
    반환: (actions 리스트, warnings 리스트)
    """
    all_actions: list[str] = []
    all_warnings: list[str] = []

    # 현재 상태 수집
    tasks = []
    if port:
        tasks = api_get('/api/tasks', port) or []
    if not tasks:
        tasks = _load_tasks()

    last_seen = get_agent_last_seen()
    task_count = get_agent_task_count(tasks)

    # 1. 미할당 태스크 자동 배정
    acts = auto_assign_tasks(tasks, last_seen, task_count, port)
    all_actions.extend(acts)

    # 2. 유휴 에이전트 감지
    warns = detect_idle_agents(last_seen, port)
    all_warnings.extend(warns)

    # 3. 태스크 과부하 감지
    warns = detect_task_overload(task_count, port)
    all_warnings.extend(warns)

    # 4. 락 충돌 감지
    warns = detect_lock_conflicts(port)
    all_warnings.extend(warns)

    return all_actions, all_warnings


# ─── 진입점 ──────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description='하이브 마인드 오케스트레이터')
    parser.add_argument('--daemon', action='store_true',
                        help='데몬 모드 (반복 실행, Ctrl+C로 종료)')
    parser.add_argument('--interval', type=int, default=30,
                        help='조율 주기 (초, 기본값: 30)')
    args = parser.parse_args()

    if args.daemon:
        print(f"[오케스트레이터] 데몬 모드 시작 (주기: {args.interval}초, Ctrl+C 종료)")
        while True:
            try:
                port = find_port()
                if not port:
                    print("[오케스트레이터] 서버 미실행 - 파일 직접 접근 모드")
                actions, warnings = run_cycle(port)
                ts = datetime.now().strftime('%H:%M:%S')
                if actions or warnings:
                    for a in actions:
                        print(f"[{ts}][액션] {a}")
                    for w in warnings:
                        print(f"[{ts}][경고] {w}")
                else:
                    print(f"[{ts}][오케스트레이터] 이상 없음")
            except KeyboardInterrupt:
                print("\n[오케스트레이터] 데몬 종료")
                break
            except Exception as e:
                print(f"[오케스트레이터][오류] {e}")
            time.sleep(args.interval)
    else:
        # 단발 실행
        port = find_port()
        if not port:
            print("[오케스트레이터] 서버 미실행 - 파일 직접 접근 모드")
        actions, warnings = run_cycle(port)
        if not actions and not warnings:
            print("[오케스트레이터] 조율 결과: 이상 없음")
        for a in actions:
            print(f"[액션] {a}")
        for w in warnings:
            print(f"[경고] {w}")


if __name__ == '__main__':
    main()
