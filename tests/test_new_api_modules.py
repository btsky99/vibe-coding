# -*- coding: utf-8 -*-
"""
FILE: tests/test_new_api_modules.py
DESCRIPTION: dispatcher_api, tasks_api, files_api 단위 테스트.
             server.py에서 분리된 3개 신규 API 모듈의 핵심 로직을 검증합니다.

             [테스트 전략]
             - HTTP 핸들러는 Mock 객체로 대체 (실제 서버 시작 없이 테스트)
             - PostgreSQL 의존성은 모킹 (list_tasks, save_task 등)
             - 파일 I/O는 tmp_path로 격리

REVISION HISTORY:
- 2026-03-22 Claude: 최초 작성 — server.py 라우트 분리 후 회귀 방지 커버리지
"""

import io
import json
import sys
import time
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

# ── 프로젝트 경로 설정 ──
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_AI_MONITOR = _PROJECT_ROOT / ".ai_monitor"

sys.path.insert(0, str(_AI_MONITOR))
sys.path.insert(0, str(_AI_MONITOR / "api"))
sys.path.insert(0, str(_PROJECT_ROOT / "scripts"))

# auto_dispatcher 모킹 (실제 ITCP/PG 없이 테스트)
_mock_dispatcher = MagicMock()
_mock_dispatcher.AGENT_CAPABILITIES = {
    'claude': {'strengths': ['code', 'debug']},
    'gemini': {'strengths': ['design', 'plan']},
}
_mock_dispatcher.detect_task_type.return_value = 'bug_fix'
_mock_dispatcher.score_agent.return_value = 0.85
_mock_dispatcher.select_best_agent.return_value = 'claude'
_mock_dispatcher.status.return_value = {'active': True, 'agents': 2}
_mock_dispatcher.dispatch.return_value = {'status': 'dispatched', 'assigned_to': 'claude'}
_mock_dispatcher.fan_out.return_value = [{'task': 't1', 'agent': 'claude'}]
_mock_dispatcher.request_verification.return_value = {'status': 'verified'}
sys.modules['auto_dispatcher'] = _mock_dispatcher

import dispatcher_api
import tasks_api
import files_api


# ── Mock HTTP Handler ────────────────────────────────────────────────────────
class MockHandler:
    """server.py의 SSEHandler를 간소하게 모킹합니다."""

    def __init__(self):
        self._response_code = None
        self._headers = {}
        self._output = io.BytesIO()
        self.wfile = self._output

    def send_response(self, code):
        self._response_code = code

    def send_header(self, key, value):
        self._headers[key] = value

    def end_headers(self):
        pass

    def _cors_origin(self):
        return '*'

    @property
    def response_json(self):
        """응답 바디를 JSON으로 파싱합니다."""
        return json.loads(self._output.getvalue().decode('utf-8'))


# ══════════════════════════════════════════════════════════════════════════════
# dispatcher_api 테스트
# ══════════════════════════════════════════════════════════════════════════════

class TestDispatcherApiGet:
    """dispatcher_api.handle_get 테스트."""

    def test_score_returns_best_agent(self):
        """GET /api/dispatcher/score — 최적 에이전트와 점수를 반환해야 한다."""
        handler = MockHandler()
        result = dispatcher_api.handle_get(
            handler, '/api/dispatcher/score',
            {'desc': ['fix bug'], 'type': ['bug_fix']},
            SCRIPTS_DIR=_PROJECT_ROOT / 'scripts',
            list_tasks=MagicMock(return_value=[]),
            current_project_id='test',
        )
        assert result is True
        assert handler._response_code == 200
        data = handler.response_json
        assert data['best_agent'] == 'claude'
        assert 'scores' in data

    def test_status_returns_dispatcher_state(self):
        """GET /api/dispatcher/status — 현재 분배 현황을 반환해야 한다."""
        handler = MockHandler()
        result = dispatcher_api.handle_get(
            handler, '/api/dispatcher/status', {},
            SCRIPTS_DIR=_PROJECT_ROOT / 'scripts',
            list_tasks=MagicMock(return_value=[]),
            current_project_id='test',
        )
        assert result is True
        data = handler.response_json
        assert data['active'] is True

    def test_history_filters_dispatch_tasks(self):
        """GET /api/dispatcher/history — created_by=dispatcher 태스크만 필터링해야 한다."""
        mock_tasks = [
            {'id': '1', 'created_by': 'dispatcher', 'assigned_to': 'claude',
             'status': 'done', 'tags': ['dispatch'], 'timestamp': '2026-03-22T10:00:00'},
            {'id': '2', 'created_by': 'user', 'assigned_to': 'gemini',
             'status': 'pending', 'tags': [], 'timestamp': '2026-03-22T10:01:00'},
        ]
        handler = MockHandler()
        result = dispatcher_api.handle_get(
            handler, '/api/dispatcher/history', {},
            SCRIPTS_DIR=_PROJECT_ROOT / 'scripts',
            list_tasks=MagicMock(return_value=mock_tasks),
            current_project_id='test',
        )
        assert result is True
        data = handler.response_json
        # user 태스크는 필터링되어야 함
        assert len(data) == 1
        assert data[0]['assigned_to'] == 'claude'

    def test_unknown_path_returns_false(self):
        """알 수 없는 경로는 False를 반환해야 한다."""
        handler = MockHandler()
        result = dispatcher_api.handle_get(
            handler, '/api/dispatcher/unknown', {},
            SCRIPTS_DIR=_PROJECT_ROOT / 'scripts',
            list_tasks=MagicMock(return_value=[]),
            current_project_id='test',
        )
        assert result is False


class TestDispatcherApiPost:
    """dispatcher_api.handle_post 테스트."""

    def test_dispatch_returns_assignment(self):
        """POST /api/dispatcher/dispatch — 태스크 분배 결과를 반환해야 한다."""
        handler = MockHandler()
        result = dispatcher_api.handle_post(
            handler, '/api/dispatcher/dispatch',
            {'description': 'fix bug', 'type': 'bug_fix', 'priority': 'high'},
            SCRIPTS_DIR=_PROJECT_ROOT / 'scripts',
        )
        assert result is True
        data = handler.response_json
        assert data['status'] == 'dispatched'
        assert data['assigned_to'] == 'claude'

    def test_verify_returns_result(self):
        """POST /api/dispatcher/verify — 크로스 검증 결과를 반환해야 한다."""
        handler = MockHandler()
        result = dispatcher_api.handle_post(
            handler, '/api/dispatcher/verify',
            {'task_id': 'TASK-1', 'summary': 'done', 'author': 'claude'},
            SCRIPTS_DIR=_PROJECT_ROOT / 'scripts',
        )
        assert result is True
        data = handler.response_json
        assert data['status'] == 'verified'


# ══════════════════════════════════════════════════════════════════════════════
# tasks_api 테스트
# ══════════════════════════════════════════════════════════════════════════════

class TestTasksApiGet:
    """tasks_api.handle_get 테스트."""

    def test_tasks_list(self):
        """GET /api/tasks — 전체 태스크 목록을 반환해야 한다."""
        mock_tasks = [{'id': '1', 'title': 'test', 'status': 'pending'}]
        handler = MockHandler()
        result = tasks_api.handle_get(
            handler, '/api/tasks', {},
            DATA_DIR=Path('/tmp'),
            list_tasks=MagicMock(return_value=mock_tasks),
            current_project_id='test',
        )
        assert result is True
        data = handler.response_json
        assert len(data) == 1
        assert data[0]['title'] == 'test'

    def test_kanban_groups_by_status(self):
        """GET /api/tasks/kanban — 태스크를 5컬럼으로 그룹화해야 한다."""
        mock_tasks = [
            {'id': '1', 'status': 'pending', 'kanban_status': ''},
            {'id': '2', 'status': 'done', 'kanban_status': 'done'},
            {'id': '3', 'status': 'in_progress', 'kanban_status': 'in_progress'},
        ]
        handler = MockHandler()
        result = tasks_api.handle_get(
            handler, '/api/tasks/kanban', {},
            DATA_DIR=Path('/tmp'),
            list_tasks=MagicMock(return_value=mock_tasks),
            current_project_id='test',
        )
        assert result is True
        data = handler.response_json
        assert len(data['todo']) == 1  # pending → todo
        assert len(data['done']) == 1
        assert len(data['in_progress']) == 1
        assert data['stats']['total'] == 3
        assert data['stats']['done'] == 1

    def test_task_logs(self, tmp_path):
        """GET /api/task-logs — JSONL에서 최근 로그를 반환해야 한다."""
        log_file = tmp_path / 'task_logs.jsonl'
        log_file.write_text(
            '{"agent":"claude","terminal_id":"T1","action":"test"}\n'
            '{"agent":"gemini","terminal_id":"T2","action":"plan"}\n',
            encoding='utf-8'
        )
        handler = MockHandler()
        result = tasks_api.handle_get(
            handler, '/api/task-logs',
            {'agent': ['claude'], 'terminal_id': [''], 'limit': ['10']},
            DATA_DIR=tmp_path,
            list_tasks=MagicMock(return_value=[]),
            current_project_id='test',
        )
        assert result is True
        data = handler.response_json
        assert len(data) == 1
        assert data[0]['agent'] == 'claude'


class TestTasksApiPost:
    """tasks_api.handle_post 테스트."""

    def test_create_task(self, tmp_path):
        """POST /api/tasks — 새 태스크를 생성해야 한다."""
        sessions_file = tmp_path / 'sessions.jsonl'
        sessions_file.write_text('', encoding='utf-8')
        mock_save = MagicMock()

        handler = MockHandler()
        result = tasks_api.handle_post(
            handler, '/api/tasks',
            {'title': '새 작업', 'assigned_to': 'claude', 'priority': 'high'},
            SESSIONS_FILE=sessions_file,
            save_task=mock_save,
            update_task=MagicMock(),
            delete_task=MagicMock(),
            current_project_id='test',
            PROJECT_ID='test',
        )
        assert result is True
        data = handler.response_json
        assert data['status'] == 'success'
        assert data['task']['title'] == '새 작업'
        assert data['task']['assigned_to'] == 'claude'
        mock_save.assert_called_once()

    def test_update_task(self):
        """POST /api/tasks/update — 태스크를 업데이트해야 한다."""
        mock_update = MagicMock(return_value={'id': '1', 'status': 'done'})
        handler = MockHandler()
        result = tasks_api.handle_post(
            handler, '/api/tasks/update',
            {'id': '1', 'status': 'done'},
            SESSIONS_FILE=Path('/tmp/s.jsonl'),
            save_task=MagicMock(),
            update_task=mock_update,
            delete_task=MagicMock(),
            current_project_id='test',
            PROJECT_ID='test',
        )
        assert result is True
        data = handler.response_json
        assert data['status'] == 'success'

    def test_delete_task(self):
        """POST /api/tasks/delete — 태스크를 삭제해야 한다."""
        mock_delete = MagicMock()
        handler = MockHandler()
        result = tasks_api.handle_post(
            handler, '/api/tasks/delete',
            {'id': '1'},
            SESSIONS_FILE=Path('/tmp/s.jsonl'),
            save_task=MagicMock(),
            update_task=MagicMock(),
            delete_task=mock_delete,
            current_project_id='test',
            PROJECT_ID='test',
        )
        assert result is True
        data = handler.response_json
        assert data['status'] == 'success'
        mock_delete.assert_called_once_with('1')

    def test_claim_task(self):
        """POST /api/tasks/claim — 태스크를 Claim 처리해야 한다."""
        mock_update = MagicMock(return_value={'id': '1', 'kanban_status': 'claimed', 'claimed_by': 'T3'})
        handler = MockHandler()
        result = tasks_api.handle_post(
            handler, '/api/tasks/claim',
            {'id': '1', 'terminal_id': 'T3'},
            SESSIONS_FILE=Path('/tmp/s.jsonl'),
            save_task=MagicMock(),
            update_task=mock_update,
            delete_task=MagicMock(),
            current_project_id='test',
            PROJECT_ID='test',
        )
        assert result is True
        data = handler.response_json
        assert data['status'] == 'success'
        # update_task에 claimed 상태가 전달되었는지 확인
        call_args = mock_update.call_args
        assert call_args[0][1]['kanban_status'] == 'claimed'
        assert call_args[0][1]['claimed_by'] == 'T3'


# ══════════════════════════════════════════════════════════════════════════════
# files_api 테스트
# ══════════════════════════════════════════════════════════════════════════════

class TestFilesApiGet:
    """files_api.handle_get 테스트."""

    def test_files_list(self, tmp_path):
        """GET /api/files — 디렉토리 내용을 반환해야 한다."""
        # 테스트 파일/폴더 생성
        (tmp_path / "subdir").mkdir()
        (tmp_path / "file.txt").write_text("hello", encoding='utf-8')

        handler = MockHandler()
        result = files_api.handle_get(
            handler, '/api/files',
            {'path': [str(tmp_path)]},
            PROJECT_ROOT=tmp_path,
            validate_file_path=lambda p: Path(p).resolve(),
        )
        assert result is True
        data = handler.response_json
        names = [item['name'] for item in data]
        assert 'subdir' in names
        assert 'file.txt' in names
        # 폴더 우선 정렬 확인
        assert data[0]['isDir'] is True

    def test_read_file(self, tmp_path):
        """GET /api/read-file — 파일 내용을 반환해야 한다."""
        test_file = tmp_path / "test.py"
        test_file.write_text("print('hello')", encoding='utf-8')

        handler = MockHandler()
        result = files_api.handle_get(
            handler, '/api/read-file',
            {'path': [str(test_file)]},
            PROJECT_ROOT=tmp_path,
            validate_file_path=lambda p: Path(p).resolve(),
        )
        assert result is True
        data = handler.response_json
        assert data['content'] == "print('hello')"

    def test_read_file_not_found(self, tmp_path):
        """GET /api/read-file — 존재하지 않는 파일은 에러를 반환해야 한다."""
        handler = MockHandler()
        result = files_api.handle_get(
            handler, '/api/read-file',
            {'path': [str(tmp_path / "nonexistent.py")]},
            PROJECT_ROOT=tmp_path,
            validate_file_path=lambda p: Path(p).resolve(),
        )
        assert result is True
        data = handler.response_json
        assert 'error' in data


class TestFilesApiPost:
    """files_api.handle_post 테스트."""

    def test_save_file(self, tmp_path):
        """POST /api/save-file — 파일을 저장해야 한다."""
        target = tmp_path / "output.txt"

        handler = MockHandler()
        result = files_api.handle_post(
            handler, '/api/save-file',
            {'path': str(target), 'content': 'hello world'},
            validate_file_path=lambda p: Path(p).resolve(),
        )
        assert result is True
        data = handler.response_json
        assert data['status'] == 'success'
        assert target.read_text(encoding='utf-8') == 'hello world'

    def test_create_file(self, tmp_path):
        """POST /api/files/create — 새 파일을 생성해야 한다."""
        target = tmp_path / "new_file.txt"

        handler = MockHandler()
        result = files_api.handle_post(
            handler, '/api/files/create',
            {'path': str(target), 'is_dir': False},
            validate_file_path=lambda p: Path(p).resolve(),
        )
        assert result is True
        data = handler.response_json
        assert data['status'] == 'success'
        assert target.exists()

    def test_create_directory(self, tmp_path):
        """POST /api/files/create — 새 디렉토리를 생성해야 한다."""
        target = tmp_path / "new_dir"

        handler = MockHandler()
        result = files_api.handle_post(
            handler, '/api/files/create',
            {'path': str(target), 'is_dir': True},
            validate_file_path=lambda p: Path(p).resolve(),
        )
        assert result is True
        assert target.is_dir()

    def test_delete_file(self, tmp_path):
        """POST /api/files/delete — 파일을 삭제해야 한다."""
        target = tmp_path / "delete_me.txt"
        target.write_text("bye", encoding='utf-8')

        handler = MockHandler()
        result = files_api.handle_post(
            handler, '/api/files/delete',
            {'path': str(target)},
            validate_file_path=lambda p: Path(p).resolve(),
        )
        assert result is True
        data = handler.response_json
        assert data['status'] == 'success'
        assert not target.exists()

    def test_rename_file(self, tmp_path):
        """POST /api/file-rename — 파일 이름을 변경해야 한다."""
        src = tmp_path / "old_name.txt"
        dest = tmp_path / "new_name.txt"
        src.write_text("content", encoding='utf-8')

        handler = MockHandler()
        result = files_api.handle_post(
            handler, '/api/file-rename',
            {'src': str(src), 'dest': str(dest)},
            validate_file_path=lambda p: Path(p).resolve(),
        )
        assert result is True
        data = handler.response_json
        assert data['status'] == 'success'
        assert not src.exists()
        assert dest.exists()
