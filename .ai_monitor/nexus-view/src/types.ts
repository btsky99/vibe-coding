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
