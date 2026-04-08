/**
 * ------------------------------------------------------------------------
 * FILE: useWorkspaceProfiles.ts
 * DESCRIPTION: 오피스 모드 회사 조직 관리 훅.
 *              부서(Department) + 에이전트(AgentSlot) 구조로
 *              조직도를 localStorage에 영구 저장하고 CRUD를 제공한다.
 * REVISION HISTORY:
 * - 2026-04-08 Claude: 부서 시스템으로 전면 개편 (Phase 1)
 * - 2026-04-08 Claude: 초기 생성 — flat 슬롯 방식
 * ------------------------------------------------------------------------
 */

import { useCallback, useState } from 'react';

// ── 타입 ──────────────────────────────────────────────────────────────────

export type AgentCli = 'claude' | 'gemini' | 'codex';

export interface AgentSlot {
  id: string;
  name: string;         // "시니어 백엔드", "QA 테스터"
  role: string;         // "planner", "architect", "frontend", "backend", "fullstack", "reviewer", "qa", "security", "devops"
  cli: AgentCli;
  model: string;
  skills: string[];     // ["brainstorm", "write-plan", "code-review", ...]
  avatar: string;       // 아이콘/이모지 키 (예: "clipboard", "shield", "wrench")
  yolo: boolean;
  order: number;
}

export interface Department {
  id: string;
  name: string;         // "코딩 부서"
  color: string;        // 테마색 hex
  icon: string;         // lucide 아이콘 이름
  agents: AgentSlot[];
}

export interface CompanyProfile {
  id: string;
  name: string;         // "우리 회사"
  departments: Department[];
  createdAt: string;
  isDefault: boolean;
}

// 하위 호환용 — OfficeApp 등에서 flat 목록이 필요할 때
export interface TerminalSlotConfig extends AgentSlot {}

export interface WorkspaceProfile {
  id: string;
  name: string;
  slots: TerminalSlotConfig[];
  departments: Department[];
  createdAt: string;
  isDefault: boolean;
}

// ── 상수 ──────────────────────────────────────────────────────────────────

export const MAX_SLOTS = 32;
export const MAX_DEPARTMENTS = 8;

const STORAGE_KEY_PROFILES = 'office_profiles_v2';
const STORAGE_KEY_ACTIVE = 'office_active_profile';

// ── 역할 정의 ─────────────────────────────────────────────────────────────

export const ROLE_DEFS: Record<string, { label: string; icon: string; defaultSkills: string[] }> = {
  ceo:       { label: '대표 (지휘자)', icon: 'crown',          defaultSkills: ['orchestrate', 'brainstorm', 'write-plan'] },
  planner:   { label: '기획자',       icon: 'clipboard-list', defaultSkills: ['brainstorm', 'write-plan'] },
  architect: { label: '아키텍트',     icon: 'blocks',         defaultSkills: ['brainstorm'] },
  frontend:  { label: '프론트엔드',    icon: 'monitor',        defaultSkills: ['code'] },
  backend:   { label: '백엔드',       icon: 'server',         defaultSkills: ['code'] },
  fullstack: { label: '풀스택',       icon: 'layers',         defaultSkills: ['code'] },
  reviewer:  { label: '코드 리뷰어',  icon: 'search-check',   defaultSkills: ['code-review'] },
  qa:        { label: 'QA 테스터',    icon: 'test-tubes',     defaultSkills: ['tdd'] },
  security:  { label: '보안 담당',    icon: 'shield',         defaultSkills: ['security'] },
  devops:    { label: 'DevOps',       icon: 'wrench',         defaultSkills: ['release'] },
};

// ── 기본 코딩 부서 ────────────────────────────────────────────────────────

const DEFAULT_CODING_DEPT: Department = {
  id: 'dept-coding',
  name: '코딩 부서',
  color: '#22d3ee',
  icon: 'code-2',
  agents: [
    { id: 'a1', name: '기획자',       role: 'planner',   cli: 'claude', model: 'claude-opus-4-6',   skills: ['brainstorm', 'write-plan'], avatar: 'clipboard-list', yolo: true, order: 0 },
    { id: 'a2', name: '아키텍트',     role: 'architect', cli: 'claude', model: 'claude-opus-4-6',   skills: ['brainstorm'],               avatar: 'blocks',         yolo: true, order: 1 },
    { id: 'a3', name: '프론트엔드',    role: 'frontend',  cli: 'gemini', model: 'gemini-2.5-pro',    skills: ['code'],                     avatar: 'monitor',        yolo: true, order: 2 },
    { id: 'a4', name: '백엔드',       role: 'backend',   cli: 'claude', model: 'claude-sonnet-4-6', skills: ['code'],                     avatar: 'server',         yolo: true, order: 3 },
    { id: 'a5', name: '풀스택',       role: 'fullstack', cli: 'gemini', model: 'gemini-2.5-flash',  skills: ['code'],                     avatar: 'layers',         yolo: true, order: 4 },
    { id: 'a6', name: '코드 리뷰어',  role: 'reviewer',  cli: 'claude', model: 'claude-opus-4-6',   skills: ['code-review'],              avatar: 'search-check',   yolo: true, order: 5 },
    { id: 'a7', name: 'QA 테스터',    role: 'qa',        cli: 'codex',  model: 'o4-mini',           skills: ['tdd'],                      avatar: 'test-tubes',     yolo: true, order: 6 },
    { id: 'a8', name: '보안 담당',    role: 'security',  cli: 'claude', model: 'claude-opus-4-6',   skills: ['security'],                 avatar: 'shield',         yolo: true, order: 7 },
    { id: 'a9', name: 'DevOps',       role: 'devops',    cli: 'codex',  model: 'gpt-4.1',           skills: ['release'],                  avatar: 'wrench',         yolo: true, order: 8 },
  ],
};

const DEFAULT_EXECUTIVE_DEPT: Department = {
  id: 'dept-exec',
  name: '경영진',
  color: '#fbbf24',
  icon: 'crown',
  agents: [
    { id: 'ceo', name: '대표 (지휘자)', role: 'ceo', cli: 'claude', model: 'claude-opus-4-6', skills: ['orchestrate', 'brainstorm', 'write-plan'], avatar: 'crown', yolo: true, order: 0 },
  ],
};

const ALL_DEFAULT_DEPTS = [DEFAULT_EXECUTIVE_DEPT, DEFAULT_CODING_DEPT];

const DEFAULT_PROFILE: WorkspaceProfile = {
  id: 'default',
  name: '코딩 회사',
  departments: ALL_DEFAULT_DEPTS,
  slots: flattenDepartments(ALL_DEFAULT_DEPTS),
  createdAt: '2026-04-08T00:00:00.000Z',
  isDefault: true,
};

// ── 유틸 ──────────────────────────────────────────────────────────────────

function generateId(): string {
  return `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
}

/** departments → flat slots 변환 */
function flattenDepartments(departments: Department[]): AgentSlot[] {
  let order = 0;
  const slots: AgentSlot[] = [];
  for (const dept of departments) {
    for (const agent of dept.agents) {
      slots.push({ ...agent, order: order++ });
    }
  }
  return slots;
}

function loadProfiles(): WorkspaceProfile[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY_PROFILES);
    if (raw) {
      const parsed = JSON.parse(raw);
      if (Array.isArray(parsed) && parsed.length > 0) {
        // slots 자동 동기화
        return parsed.map((p: WorkspaceProfile) => ({
          ...p,
          slots: p.departments ? flattenDepartments(p.departments) : p.slots || [],
        }));
      }
    }
    // v1 캐시 삭제 — 더 이상 필요 없음
    localStorage.removeItem('office_profiles');
    localStorage.removeItem('office_active_profile');
  } catch { /* 파싱 실패 시 기본값 */ }
  const defaults = [DEFAULT_PROFILE];
  saveProfiles(defaults);
  return defaults;
}

function loadActiveId(): string {
  return localStorage.getItem(STORAGE_KEY_ACTIVE) || 'default';
}

function saveProfiles(profiles: WorkspaceProfile[]): void {
  localStorage.setItem(STORAGE_KEY_PROFILES, JSON.stringify(profiles));
}

function saveActiveId(id: string): void {
  localStorage.setItem(STORAGE_KEY_ACTIVE, id);
}

// ── 훅 ───────────────────────────────────────────────────────────────────

export function useWorkspaceProfiles() {
  const [profiles, setProfiles] = useState<WorkspaceProfile[]>(loadProfiles);
  const [activeProfileId, setActiveProfileIdState] = useState<string>(loadActiveId);

  const activeProfile = profiles.find(p => p.id === activeProfileId) || profiles[0];

  // ── 프로필 CRUD ──

  const addProfile = useCallback((name: string, departments?: Department[]) => {
    const depts = departments || [{ ...DEFAULT_CODING_DEPT, id: generateId() }];
    const newProfile: WorkspaceProfile = {
      id: generateId(),
      name,
      departments: depts,
      slots: flattenDepartments(depts),
      createdAt: new Date().toISOString(),
      isDefault: false,
    };
    setProfiles(prev => {
      const next = [...prev, newProfile];
      saveProfiles(next);
      return next;
    });
    return newProfile.id;
  }, []);

  const deleteProfile = useCallback((id: string) => {
    setProfiles(prev => {
      const next = prev.filter(p => p.id !== id);
      if (next.length === 0) next.push(DEFAULT_PROFILE);
      saveProfiles(next);
      return next;
    });
    setActiveProfileIdState(prev => {
      if (prev === id) {
        const fallback = 'default';
        saveActiveId(fallback);
        return fallback;
      }
      return prev;
    });
  }, []);

  const updateProfile = useCallback((id: string, patch: Partial<Pick<WorkspaceProfile, 'name'>>) => {
    setProfiles(prev => {
      const next = prev.map(p => p.id === id ? { ...p, ...patch } : p);
      saveProfiles(next);
      return next;
    });
  }, []);

  const setActiveProfile = useCallback((id: string) => {
    setActiveProfileIdState(id);
    saveActiveId(id);
  }, []);

  // ── 부서 CRUD ──

  const addDepartment = useCallback((profileId: string, dept: Omit<Department, 'id'>) => {
    setProfiles(prev => {
      const next = prev.map(p => {
        if (p.id !== profileId) return p;
        if (p.departments.length >= MAX_DEPARTMENTS) return p;
        const newDept: Department = { ...dept, id: generateId() };
        const depts = [...p.departments, newDept];
        return { ...p, departments: depts, slots: flattenDepartments(depts) };
      });
      saveProfiles(next);
      return next;
    });
  }, []);

  const removeDepartment = useCallback((profileId: string, deptId: string) => {
    setProfiles(prev => {
      const next = prev.map(p => {
        if (p.id !== profileId) return p;
        const depts = p.departments.filter(d => d.id !== deptId);
        return { ...p, departments: depts, slots: flattenDepartments(depts) };
      });
      saveProfiles(next);
      return next;
    });
  }, []);

  const updateDepartment = useCallback((profileId: string, deptId: string, patch: Partial<Omit<Department, 'id'>>) => {
    setProfiles(prev => {
      const next = prev.map(p => {
        if (p.id !== profileId) return p;
        const depts = p.departments.map(d => d.id === deptId ? { ...d, ...patch } : d);
        return { ...p, departments: depts, slots: flattenDepartments(depts) };
      });
      saveProfiles(next);
      return next;
    });
  }, []);

  // ── 에이전트 CRUD (부서 내) ──

  const addAgent = useCallback((profileId: string, deptId: string, agent: Omit<AgentSlot, 'id' | 'order'>) => {
    setProfiles(prev => {
      const next = prev.map(p => {
        if (p.id !== profileId) return p;
        const totalAgents = p.departments.reduce((sum, d) => sum + d.agents.length, 0);
        if (totalAgents >= MAX_SLOTS) return p;
        const depts = p.departments.map(d => {
          if (d.id !== deptId) return d;
          const newAgent: AgentSlot = { ...agent, id: generateId(), order: d.agents.length };
          return { ...d, agents: [...d.agents, newAgent] };
        });
        return { ...p, departments: depts, slots: flattenDepartments(depts) };
      });
      saveProfiles(next);
      return next;
    });
  }, []);

  const removeAgent = useCallback((profileId: string, deptId: string, agentId: string) => {
    setProfiles(prev => {
      const next = prev.map(p => {
        if (p.id !== profileId) return p;
        const depts = p.departments.map(d => {
          if (d.id !== deptId) return d;
          return { ...d, agents: d.agents.filter(a => a.id !== agentId).map((a, i) => ({ ...a, order: i })) };
        });
        return { ...p, departments: depts, slots: flattenDepartments(depts) };
      });
      saveProfiles(next);
      return next;
    });
  }, []);

  const updateAgent = useCallback((profileId: string, deptId: string, agentId: string, patch: Partial<Omit<AgentSlot, 'id'>>) => {
    setProfiles(prev => {
      const next = prev.map(p => {
        if (p.id !== profileId) return p;
        const depts = p.departments.map(d => {
          if (d.id !== deptId) return d;
          return { ...d, agents: d.agents.map(a => a.id === agentId ? { ...a, ...patch } : a) };
        });
        return { ...p, departments: depts, slots: flattenDepartments(depts) };
      });
      saveProfiles(next);
      return next;
    });
  }, []);

  // 하위 호환 — 기존 flat 방식 (OfficeApp에서 사용)
  const addSlot = useCallback((profileId: string, slot: Omit<AgentSlot, 'id' | 'order'>) => {
    // 첫 번째 부서에 추가
    const profile = profiles.find(p => p.id === profileId);
    const deptId = profile?.departments[0]?.id;
    if (deptId) addAgent(profileId, deptId, slot);
  }, [profiles, addAgent]);

  const removeSlot = useCallback((profileId: string, slotId: string) => {
    setProfiles(prev => {
      const next = prev.map(p => {
        if (p.id !== profileId) return p;
        const depts = p.departments.map(d => ({
          ...d, agents: d.agents.filter(a => a.id !== slotId).map((a, i) => ({ ...a, order: i })),
        }));
        return { ...p, departments: depts, slots: flattenDepartments(depts) };
      });
      saveProfiles(next);
      return next;
    });
  }, []);

  const updateSlot = useCallback((profileId: string, slotId: string, patch: Partial<Omit<AgentSlot, 'id'>>) => {
    setProfiles(prev => {
      const next = prev.map(p => {
        if (p.id !== profileId) return p;
        const depts = p.departments.map(d => ({
          ...d, agents: d.agents.map(a => a.id === slotId ? { ...a, ...patch } : a),
        }));
        return { ...p, departments: depts, slots: flattenDepartments(depts) };
      });
      saveProfiles(next);
      return next;
    });
  }, []);

  return {
    profiles,
    activeProfile,
    activeProfileId,
    addProfile,
    deleteProfile,
    updateProfile,
    setActiveProfile,
    addDepartment,
    removeDepartment,
    updateDepartment,
    addAgent,
    removeAgent,
    updateAgent,
    addSlot,
    removeSlot,
    updateSlot,
  };
}
