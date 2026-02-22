"""
에이전트 간 메시지 채널 헬퍼 스크립트
---------------------------------------
사용법:
  python scripts/send_message.py <from> <to> <type> <content>

예시:
  python scripts/send_message.py claude gemini handoff "DB 스키마 분석 완료. API 구현 시작해도 됩니다."
  python scripts/send_message.py gemini claude task_complete "UI 컴포넌트 모두 작성 완료."
  python scripts/send_message.py claude all info "공통 유틸 함수 utils.py에 추가했습니다."

type 목록:
  info          - 일반 정보 공유
  handoff       - 다음 작업을 상대에게 위임
  request       - 특정 작업 요청
  task_complete - 작업 완료 알림
  warning       - 경고 (충돌, 에러 등)

서버 포트:
  개발 모드: 8000 / 배포 모드: 8005
  자동 감지하거나 --port 플래그로 지정 가능
"""

import sys
import json
import urllib.request
import urllib.error
import os

# 서버 포트 자동 감지 (개발: 8000, 배포: 8005)
DEFAULT_PORTS = [8005, 8000]


def send_message(from_agent: str, to_agent: str, msg_type: str, content: str, port: int = None) -> bool:
    """
    Nexus View 서버의 /api/message 엔드포인트에 메시지를 전송합니다.
    서버가 실행 중이지 않으면 직접 파일에 기록합니다(폴백).
    """
    # 포트 목록 결정
    ports_to_try = [port] if port else DEFAULT_PORTS

    payload = json.dumps({
        'from': from_agent,
        'to': to_agent,
        'type': msg_type,
        'content': content,
    }).encode('utf-8')

    # API 전송 시도
    for p in ports_to_try:
        try:
            req = urllib.request.Request(
                f'http://localhost:{p}/api/message',
                data=payload,
                headers={'Content-Type': 'application/json'},
                method='POST',
            )
            with urllib.request.urlopen(req, timeout=3) as resp:
                result = json.loads(resp.read().decode('utf-8'))
                if result.get('status') == 'success':
                    print(f"[OK] 메시지 전송 완료 (포트 {p}): {from_agent} → {to_agent} [{msg_type}]")
                    return True
        except (urllib.error.URLError, Exception):
            continue

    # 폴백: 서버가 꺼져있을 경우 직접 파일에 기록
    return _fallback_write(from_agent, to_agent, msg_type, content)


def _fallback_write(from_agent: str, to_agent: str, msg_type: str, content: str) -> bool:
    """서버 미실행 시 messages.jsonl에 직접 기록하는 폴백 함수"""
    import time

    # .ai_monitor/data/messages.jsonl 경로 탐색
    script_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(script_dir)
    data_dir = os.path.join(project_root, '.ai_monitor', 'data')

    os.makedirs(data_dir, exist_ok=True)
    messages_file = os.path.join(data_dir, 'messages.jsonl')

    msg = {
        'id': str(int(time.time() * 1000)),
        'timestamp': time.strftime('%Y-%m-%dT%H:%M:%S'),
        'from': from_agent,
        'to': to_agent,
        'type': msg_type,
        'content': content,
        'read': False,
    }

    try:
        with open(messages_file, 'a', encoding='utf-8') as f:
            f.write(json.dumps(msg, ensure_ascii=False) + '\n')
        print(f"[OK] 메시지 파일 직접 기록 완료: {from_agent} → {to_agent} [{msg_type}]")
        return True
    except Exception as e:
        print(f"[FAIL] 메시지 기록 실패: {e}", file=sys.stderr)
        return False


if __name__ == '__main__':
    # 인자 파싱
    port_override = None
    args = sys.argv[1:]

    # --port 플래그 처리
    if '--port' in args:
        idx = args.index('--port')
        try:
            port_override = int(args[idx + 1])
            args = args[:idx] + args[idx + 2:]
        except (IndexError, ValueError):
            pass

    if len(args) < 4:
        print(__doc__)
        print("Usage: python scripts/send_message.py <from> <to> <type> <content>")
        sys.exit(1)

    from_a, to_a, m_type, *content_parts = args
    content_str = ' '.join(content_parts)

    ok = send_message(from_a, to_a, m_type, content_str, port=port_override)
    sys.exit(0 if ok else 1)
