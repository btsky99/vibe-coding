export interface LogRecord {
    session_id: string;
    terminal_id: string;
    project: string;
    agent: string;
    trigger: string;
    status: 'running' | 'success' | 'failed';
    commit?: string;
    ts_start: string;
}

// 에이전트 간 공유 메모리 — 지식 베이스 항목
export interface MemoryEntry {
    id: string;          // 고유 ID
    key: string;         // 식별 키 (예: db_schema, auth_method)
    title: string;       // 사람이 읽기 쉬운 제목
    content: string;     // 내용 본문
    tags: string[];      // 태그 목록 (분류용)
    author: string;      // 작성 에이전트
    timestamp: string;   // 최초 생성 시각
    updated_at: string;  // 최종 수정 시각
}

// 에이전트 간 작업 큐 — 태스크 보드 데이터 구조
export interface Task {
    id: string;                        // 고유 ID (timestamp 기반)
    timestamp: string;                 // 생성 시각
    updated_at: string;                // 최종 수정 시각
    title: string;                     // 작업 제목
    description: string;               // 상세 설명 (선택)
    status: 'pending' | 'in_progress' | 'done';
    assigned_to: string;               // 담당 에이전트 (claude / gemini / all)
    priority: 'high' | 'medium' | 'low';
    created_by: string;                // 생성 주체
}

// 에이전트 간 직접 메시지 채널 데이터 구조
export interface AgentMessage {
    id: string;                    // 고유 ID (timestamp 기반)
    timestamp: string;             // ISO 형식 타임스탬프
    from: string;                  // 발신 에이전트 (claude / gemini / system)
    to: string;                    // 수신 대상 (claude / gemini / all)
    type: 'info' | 'handoff' | 'request' | 'task_complete' | 'warning';
    content: string;               // 메시지 본문
    read: boolean;                 // 읽음 여부
}
