/**
 * ------------------------------------------------------------------------
 * FILE: services/officeApi.ts
 * DESCRIPTION: 오피스 모드 API 클라이언트.
 *              - 프로필 CRUD (PostgreSQL SSOT)
 *              - 활성 프로필 변경
 *              - SSE 구독으로 창 간 실시간 동기화
 *              - 오피스 전용 에이전트/태스크 (클래식과 네임스페이스 분리)
 * REVISION HISTORY:
 * - 2026-04-09 Claude: 초기 작성 — localStorage 제거 + API 기반 중앙화
 * ------------------------------------------------------------------------
 */

// ── 타입 ──────────────────────────────────────────────────────────────────

export type AgentCli = 'claude' | 'antigravity' | 'codex';

export interface AgentSlot {
  id: string;
  name: string;
  role: string;
  cli: AgentCli;
  model: string;
  skills: string[];
  avatar: string;
  yolo: boolean;
  order: number;
}

export interface Department {
  id: string;
  name: string;
  color: string;
  icon: string;
  agents: AgentSlot[];
}

// 하위 호환용
export interface TerminalSlotConfig extends AgentSlot {}

export interface WorkspaceProfile {
  id: string;
  name: string;
  departments: Department[];
  slots: TerminalSlotConfig[];
  createdAt: string;
  isDefault: boolean;
}

// 서버 응답 원형: { id, name, data: {...전체 프로필 JSON...}, is_default, created_at, updated_at }
interface ServerProfile {
  id: string;
  name: string;
  data: WorkspaceProfile;
  is_default: boolean;
  created_at: string;
  updated_at: string;
}

interface ListResponse {
  profiles: ServerProfile[];
  activeProfileId: string;
}

// ── 내부 유틸 ────────────────────────────────────────────────────────────

async function _json<T>(res: Response): Promise<T> {
  if (!res.ok) {
    const text = await res.text().catch(() => '');
    throw new Error(`API ${res.status}: ${text || res.statusText}`);
  }
  return res.json() as Promise<T>;
}

/** 서버 row를 프론트 WorkspaceProfile로 정규화. data.slots가 없으면 departments에서 계산. */
function _normalize(row: ServerProfile): WorkspaceProfile {
  const data = row.data || ({} as WorkspaceProfile);
  const departments = (data.departments || []) as Department[];
  let order = 0;
  const slots: AgentSlot[] = [];
  for (const dept of departments) {
    for (const agent of (dept.agents || [])) {
      slots.push({ ...agent, order: order++ });
    }
  }
  return {
    id: row.id,
    name: row.name,
    departments,
    slots,
    createdAt: data.createdAt || row.created_at || '',
    isDefault: !!row.is_default,
  };
}

// ── API 호출 ─────────────────────────────────────────────────────────────

export async function listProfiles(): Promise<{ profiles: WorkspaceProfile[]; activeProfileId: string }> {
  const res = await fetch('/api/office/profiles', { method: 'GET' });
  const body = await _json<ListResponse>(res);
  return {
    profiles: (body.profiles || []).map(_normalize),
    activeProfileId: body.activeProfileId || 'default',
  };
}

export async function getProfile(id: string): Promise<WorkspaceProfile> {
  const res = await fetch(`/api/office/profiles/${encodeURIComponent(id)}`, { method: 'GET' });
  const row = await _json<ServerProfile>(res);
  return _normalize(row);
}

export async function createProfile(profile: WorkspaceProfile): Promise<void> {
  const body = { id: profile.id, name: profile.name, data: profile };
  const res = await fetch('/api/office/profiles', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  await _json<{ id: string; status: string }>(res);
}

export async function updateProfile(profile: WorkspaceProfile): Promise<void> {
  const body = { name: profile.name, data: profile };
  const res = await fetch(`/api/office/profiles/${encodeURIComponent(profile.id)}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  await _json<{ id: string; status: string }>(res);
}

export async function deleteProfile(id: string): Promise<void> {
  const res = await fetch(`/api/office/profiles/${encodeURIComponent(id)}`, {
    method: 'DELETE',
  });
  await _json<{ id: string; status: string }>(res);
}

export async function setActiveProfile(id: string): Promise<void> {
  const res = await fetch(`/api/office/profiles/active/${encodeURIComponent(id)}`, {
    method: 'PUT',
  });
  await _json<{ activeProfileId: string }>(res);
}

// ── SSE 구독 ─────────────────────────────────────────────────────────────

export interface ProfileChangeEvent {
  op: 'INSERT' | 'UPDATE' | 'DELETE';
  id: string;
}

export function subscribeProfileChanges(onChange: (ev: ProfileChangeEvent) => void): () => void {
  const src = new EventSource('/api/office/profiles/stream');
  src.onmessage = (e) => {
    try {
      const parsed = JSON.parse(e.data);
      // 서버가 보내는 TG_OP: 'INSERT' | 'UPDATE' | 'DELETE' | 'delete'
      const op = String(parsed.op || '').toUpperCase() as ProfileChangeEvent['op'];
      onChange({ op, id: String(parsed.id || '') });
    } catch {
      /* 무시 */
    }
  };
  src.onerror = () => {
    // 연결 오류 시 브라우저가 자동 재연결한다. 로깅만.
    console.warn('[officeApi] SSE 연결 오류 — 자동 재연결 시도');
  };
  return () => {
    try { src.close(); } catch { /* noop */ }
  };
}

// ── 오피스 에이전트/태스크 (네임스페이스 분리) ────────────────────────────

export interface OfficeAgentStatus {
  agent_id: string;
  status: string;
  last_beat: string;
  current_task: string | null;
  beat_count: number;
  config: string;
}

export async function listOfficeAgents(): Promise<OfficeAgentStatus[]> {
  const res = await fetch('/api/office/agents/status', { method: 'GET' });
  const body = await _json<{ agents: OfficeAgentStatus[] }>(res);
  return body.agents || [];
}

export async function sendOfficeHeartbeat(agentId: string, status: string, currentTask?: string): Promise<void> {
  const res = await fetch('/api/office/agents/heartbeat', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ agent_id: agentId, status, current_task: currentTask || null }),
  });
  await _json<{ ok: boolean }>(res);
}

export interface OfficeTask {
  id: string;
  title: string;
  description: string;
  status: string;
  assigned_to: string;
  priority: string;
  kanban_status: string;
  role: string;
  claimed_by: string;
  updated_at: string;
  result: string;
}

export async function listOfficeTasks(): Promise<OfficeTask[]> {
  const res = await fetch('/api/office/tasks', { method: 'GET' });
  const body = await _json<{ tasks: OfficeTask[] }>(res);
  return body.tasks || [];
}

export async function createOfficeTask(task: Partial<OfficeTask>): Promise<string> {
  const res = await fetch('/api/office/tasks', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(task),
  });
  const body = await _json<{ id: string; status: string }>(res);
  return body.id;
}
