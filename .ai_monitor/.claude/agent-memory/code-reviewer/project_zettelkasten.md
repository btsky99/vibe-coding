---
name: project_zettelkasten
description: Hive Zettelkasten 시스템(2026-04-05) 코드 리뷰에서 발견된 버그·패턴 기록
type: project
---

## 발견된 주요 이슈

**Critical**
- zettelkasten.py `_next_zettel_id`: 알파벳 분기 `ORDER BY id DESC` — 사전식 정렬이므로 'z' > 'b'는 맞지만 'b' < 'a'는 아님. 실제로는 정상 작동하나, 분기가 'z'를 초과할 경우(chr('z'+1)='{'}) 유효하지 않은 ID 생성.
- zettel_api.py `handle_post` 경로 충돌: `/api/zettel/note/1a/delete` 경로는 `startswith('/api/zettel/note/')` AND `not endswith('/link')` AND `not endswith('/rescue')` 세 조건을 모두 통과하여 update_note 블록에 먼저 진입한다. `/delete` suffix 체크 블록보다 update_note 블록이 앞에 있기 때문.
- server.py POST 라우팅: `/api/zettel/*` 블록(3915행)이 `elif`로 연결되어 있지만, 앞의 `if` 체인(tools_api)이 `return`이 없어 fall-through 가능성 존재 — 3641행 tools_api 블록이 `if`(elif 아님)로 시작하고 return이 없음.

**Warning**
- zettel_api.py `handle_post` `days` 파라미터: `int(data.get('days', 30))` — 사용자 입력값을 직접 int()로 변환, 음수나 0 입력 시 의미없는 쿼리 실행.
- zettel_sync.py `_safe_filename`: note_id를 그대로 파일명으로 사용. 루만식 ID('1a1')는 안전하지만, custom_id에 '../../passwd' 같은 경로 traversal 문자가 포함될 경우 vault_dir 밖에 파일이 쓰일 수 있음.
- migrate_memory_to_zettel.py: `import json`이 루프 내부(48행)에 위치 — 반복 import는 무해하지만 관례상 최상단으로 이동해야 함.

**How to apply:** 동일 패턴의 경로 충돌·경로 인젝션 이슈는 다른 API 모듈 추가 시에도 동일하게 점검할 것.
