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

// Git 저장소 실시간 상태
export interface GitStatus {
    branch: string;        // 현재 브랜치명
    ahead: number;         // 로컬이 리모트보다 앞선 커밋 수
    behind: number;        // 리모트가 로컬보다 앞선 커밋 수
    staged: string[];      // 스테이징된 파일
    unstaged: string[];    // 수정됐지만 스테이징 안 된 파일
    untracked: string[];   // git이 추적하지 않는 신규 파일
    conflicts: string[];   // 머지 충돌 마커가 있는 파일
    is_git_repo: boolean;
    error?: string;
}

// Git 커밋 항목
export interface GitCommit {
    hash: string;     // 짧은 커밋 해시
    message: string;  // 커밋 메시지
    author: string;   // 작성자
    date: string;     // 상대적 날짜 (예: 2 hours ago)
}

// 오케스트레이터 에이전트 상태
export interface AgentStatusEntry {
    state: 'active' | 'idle' | 'unknown'; // 활성/유휴/미확인
    last_seen: string | null;              // 마지막 활동 시각 (ISO 문자열)
    idle_sec: number | null;               // 유휴 시간 (초)
}

export interface OrchestratorAction {
    timestamp: string;   // 액션 발생 시각
    action: string;      // 액션 유형 (auto_assign / idle_agent / ...)
    detail: string;      // 액션 상세 내용
}

export interface OrchestratorStatus {
    agent_status: Record<string, AgentStatusEntry>;          // 에이전트별 상태
    task_distribution: Record<string, Record<string, number>>; // 에이전트별 태스크 분배
    recent_actions: OrchestratorAction[];                    // 최근 오케스트레이터 액션
    warnings: string[];                                       // 현재 경고 목록
    timestamp: string;                                        // 조회 시각
    error?: string;
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
