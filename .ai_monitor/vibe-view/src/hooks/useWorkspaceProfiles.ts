/**
 * ------------------------------------------------------------------------
 * FILE: useWorkspaceProfiles.ts
 * DESCRIPTION: 오피스 모드 회사 조직 관리 훅.
 *              PostgreSQL SSOT 기반 — 모든 CRUD가 서버 API로 전달된다.
 *              SSE 구독으로 다른 창의 변경사항이 실시간 반영된다.
 *              낙관적 업데이트 후 API 실패 시 이전 상태로 롤백.
 * REVISION HISTORY:
 * - 2026-04-09 Claude: localStorage → PostgreSQL SSOT 전환 (창 간 데이터 공유)
 * - 2026-04-08 Claude: 부서 시스템으로 전면 개편 (Phase 1)
 * - 2026-04-08 Claude: 초기 생성 — flat 슬롯 방식
 * ------------------------------------------------------------------------
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import {
  listProfiles as apiList,
  createProfile as apiCreate,
  updateProfile as apiUpdate,
  deleteProfile as apiDelete,
  setActiveProfile as apiSetActive,
  subscribeProfileChanges,
  type AgentSlot,
  type Department,
  type WorkspaceProfile,
  type AgentCli,
  type TerminalSlotConfig,
} from '../services/officeApi';

// 타입 재수출 — 다른 컴포넌트가 이 훅에서 타입을 임포트해 왔던 기존 코드 호환
export type { AgentCli, AgentSlot, Department, TerminalSlotConfig, WorkspaceProfile };
export interface CompanyProfile {
  id: string;
  name: string;
  departments: Department[];
  createdAt: string;
  isDefault: boolean;
}

// ── 상수 ──────────────────────────────────────────────────────────────────

export const MAX_SLOTS = 32;
export const MAX_DEPARTMENTS = 8;

const LEGACY_STORAGE_KEY = 'office_profiles_v2';
const LEGACY_ACTIVE_KEY = 'office_active_profile';

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

// ── 유틸 ──────────────────────────────────────────────────────────────────

function generateId(): string {
  return `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
}

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

function withSyncedSlots(profile: WorkspaceProfile): WorkspaceProfile {
  return { ...profile, slots: flattenDepartments(profile.departments || []) };
}

// ── 기본 폴백 프로필 (서버 초기 로드 실패 시만 사용) ────────────────────────

const FALLBACK_CODING_DEPT: Department = {
  id: 'dept-coding',
  name: '코딩 부서',
  color: '#22d3ee',
  icon: 'code-2',
  agents: [],
};
const FALLBACK_PROFILE: WorkspaceProfile = {
  id: 'default',
  name: '코딩 회사',
  departments: [FALLBACK_CODING_DEPT],
  slots: [],
  createdAt: new Date().toISOString(),
  isDefault: true,
};

// ── 1회성 마이그레이션 ────────────────────────────────────────────────────

/**
 * 앱 최초 실행 시 localStorage에 남아있는 v1/v2 프로필을 서버로 밀어넣는다.
 * 성공 시 localStorage 키 삭제. 실패 시 유지 (다음 실행에서 재시도).
 */
async function migrateLegacyProfiles(): Promise<void> {
  try {
    const raw = localStorage.getItem(LEGACY_STORAGE_KEY);
    if (!raw) return;
    const parsed = JSON.parse(raw);
    if (!Array.isArray(parsed) || parsed.length === 0) {
      localStorage.removeItem(LEGACY_STORAGE_KEY);
      localStorage.removeItem(LEGACY_ACTIVE_KEY);
      return;
    }
    // 기본 프로필 충돌 방지 — default는 서버 것을 신뢰, 나머지만 이전
    const nonDefault = parsed.filter((p: WorkspaceProfile) => !p.isDefault && p.id !== 'default');
    for (const p of nonDefault) {
      const normalized = withSyncedSlots(p);
      try {
        await apiCreate(normalized);
      } catch (e) {
        console.warn('[useWorkspaceProfiles] 마이그레이션 실패 (무시):', p.id, e);
      }
    }
    const activeLegacy = localStorage.getItem(LEGACY_ACTIVE_KEY);
    if (activeLegacy && activeLegacy !== 'default') {
      try { await apiSetActive(activeLegacy); } catch { /* 무시 */ }
    }
    localStorage.removeItem(LEGACY_STORAGE_KEY);
    localStorage.removeItem(LEGACY_ACTIVE_KEY);
    localStorage.removeItem('office_profiles'); // v1 잔재
    console.info('[useWorkspaceProfiles] localStorage → 서버 마이그레이션 완료');
  } catch (e) {
    console.warn('[useWorkspaceProfiles] 마이그레이션 중 오류:', e);
  }
}

// ── 훅 ───────────────────────────────────────────────────────────────────

export function useWorkspaceProfiles() {
  const [profiles, setProfiles] = useState<WorkspaceProfile[]>([FALLBACK_PROFILE]);
  const [activeProfileId, setActiveProfileIdState] = useState<string>('default');
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  // 이전 상태 롤백용 참조
  const prevSnapshotRef = useRef<{ profiles: WorkspaceProfile[]; activeId: string } | null>(null);

  // ── 초기 로드 + 마이그레이션 + SSE 구독 ──
  const reload = useCallback(async () => {
    try {
      const { profiles: loaded, activeProfileId: activeId } = await apiList();
      if (loaded.length === 0) {
        setProfiles([FALLBACK_PROFILE]);
        setActiveProfileIdState('default');
      } else {
        setProfiles(loaded.map(withSyncedSlots));
        setActiveProfileIdState(activeId);
      }
      setError(null);
    } catch (e) {
      console.error('[useWorkspaceProfiles] 로드 실패:', e);
      setError(String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      await migrateLegacyProfiles();
      if (!cancelled) await reload();
    })();

    // SSE 구독 — 다른 창의 변경사항 실시간 반영
    const unsubscribe = subscribeProfileChanges(() => {
      if (!cancelled) reload();
    });

    return () => {
      cancelled = true;
      unsubscribe();
    };
  }, [reload]);

  // 낙관적 업데이트 헬퍼 — API 호출 전 UI 먼저 갱신, 실패 시 롤백
  const optimistic = useCallback(
    async (mutator: (profiles: WorkspaceProfile[]) => WorkspaceProfile[], apiCall: () => Promise<void>) => {
      prevSnapshotRef.current = { profiles, activeId: activeProfileId };
      const next = mutator(profiles);
      setProfiles(next);
      try {
        await apiCall();
      } catch (e) {
        console.error('[useWorkspaceProfiles] API 실패, 롤백:', e);
        if (prevSnapshotRef.current) {
          setProfiles(prevSnapshotRef.current.profiles);
          setActiveProfileIdState(prevSnapshotRef.current.activeId);
        }
        setError(String(e));
      }
    },
    [profiles, activeProfileId],
  );

  const activeProfile = profiles.find((p) => p.id === activeProfileId) || profiles[0] || FALLBACK_PROFILE;

  // ── 프로필 CRUD ──

  const addProfile = useCallback(
    (name: string, departments?: Department[]) => {
      const depts = departments || [{ ...FALLBACK_CODING_DEPT, id: generateId() }];
      const newProfile: WorkspaceProfile = withSyncedSlots({
        id: generateId(),
        name,
        departments: depts,
        slots: [],
        createdAt: new Date().toISOString(),
        isDefault: false,
      });
      optimistic(
        (prev) => [...prev, newProfile],
        () => apiCreate(newProfile),
      );
      return newProfile.id;
    },
    [optimistic],
  );

  const deleteProfile = useCallback(
    (id: string) => {
      optimistic(
        (prev) => {
          const next = prev.filter((p) => p.id !== id);
          return next.length === 0 ? [FALLBACK_PROFILE] : next;
        },
        () => apiDelete(id),
      );
      if (activeProfileId === id) {
        setActiveProfileIdState('default');
        apiSetActive('default').catch((e) => console.warn('[useWorkspaceProfiles] active 변경 실패:', e));
      }
    },
    [optimistic, activeProfileId],
  );

  const updateProfileMut = useCallback(
    (id: string, patch: Partial<Pick<WorkspaceProfile, 'name'>>) => {
      const target = profiles.find((p) => p.id === id);
      if (!target) return;
      const updated = withSyncedSlots({ ...target, ...patch });
      optimistic(
        (prev) => prev.map((p) => (p.id === id ? updated : p)),
        () => apiUpdate(updated),
      );
    },
    [optimistic, profiles],
  );

  const setActiveProfile = useCallback((id: string) => {
    setActiveProfileIdState(id);
    apiSetActive(id).catch((e) => {
      console.error('[useWorkspaceProfiles] active 변경 실패:', e);
      setError(String(e));
    });
  }, []);

  // ── 부서 CRUD (공통 패턴: 프로필 객체 통째로 재구성 후 PUT) ──

  const modifyProfile = useCallback(
    (profileId: string, transform: (p: WorkspaceProfile) => WorkspaceProfile) => {
      const target = profiles.find((p) => p.id === profileId);
      if (!target) return;
      const transformed = withSyncedSlots(transform(target));
      optimistic(
        (prev) => prev.map((p) => (p.id === profileId ? transformed : p)),
        () => apiUpdate(transformed),
      );
    },
    [optimistic, profiles],
  );

  const addDepartment = useCallback(
    (profileId: string, dept: Omit<Department, 'id'>) => {
      modifyProfile(profileId, (p) => {
        if (p.departments.length >= MAX_DEPARTMENTS) return p;
        const newDept: Department = { ...dept, id: generateId() };
        return { ...p, departments: [...p.departments, newDept] };
      });
    },
    [modifyProfile],
  );

  const removeDepartment = useCallback(
    (profileId: string, deptId: string) => {
      modifyProfile(profileId, (p) => ({
        ...p,
        departments: p.departments.filter((d) => d.id !== deptId),
      }));
    },
    [modifyProfile],
  );

  const updateDepartment = useCallback(
    (profileId: string, deptId: string, patch: Partial<Omit<Department, 'id'>>) => {
      modifyProfile(profileId, (p) => ({
        ...p,
        departments: p.departments.map((d) => (d.id === deptId ? { ...d, ...patch } : d)),
      }));
    },
    [modifyProfile],
  );

  // ── 에이전트 CRUD (부서 내) ──

  const addAgent = useCallback(
    (profileId: string, deptId: string, agent: Omit<AgentSlot, 'id' | 'order'>) => {
      modifyProfile(profileId, (p) => {
        const totalAgents = p.departments.reduce((sum, d) => sum + d.agents.length, 0);
        if (totalAgents >= MAX_SLOTS) return p;
        return {
          ...p,
          departments: p.departments.map((d) => {
            if (d.id !== deptId) return d;
            const newAgent: AgentSlot = { ...agent, id: generateId(), order: d.agents.length };
            return { ...d, agents: [...d.agents, newAgent] };
          }),
        };
      });
    },
    [modifyProfile],
  );

  const removeAgent = useCallback(
    (profileId: string, deptId: string, agentId: string) => {
      modifyProfile(profileId, (p) => ({
        ...p,
        departments: p.departments.map((d) => {
          if (d.id !== deptId) return d;
          return {
            ...d,
            agents: d.agents.filter((a) => a.id !== agentId).map((a, i) => ({ ...a, order: i })),
          };
        }),
      }));
    },
    [modifyProfile],
  );

  const updateAgent = useCallback(
    (profileId: string, deptId: string, agentId: string, patch: Partial<Omit<AgentSlot, 'id'>>) => {
      modifyProfile(profileId, (p) => ({
        ...p,
        departments: p.departments.map((d) => {
          if (d.id !== deptId) return d;
          return {
            ...d,
            agents: d.agents.map((a) => (a.id === agentId ? { ...a, ...patch } : a)),
          };
        }),
      }));
    },
    [modifyProfile],
  );

  // ── 하위 호환 (OfficeApp의 flat 방식) ──

  const addSlot = useCallback(
    (profileId: string, slot: Omit<AgentSlot, 'id' | 'order'>) => {
      const profile = profiles.find((p) => p.id === profileId);
      const deptId = profile?.departments[0]?.id;
      if (deptId) addAgent(profileId, deptId, slot);
    },
    [profiles, addAgent],
  );

  const removeSlot = useCallback(
    (profileId: string, slotId: string) => {
      modifyProfile(profileId, (p) => ({
        ...p,
        departments: p.departments.map((d) => ({
          ...d,
          agents: d.agents.filter((a) => a.id !== slotId).map((a, i) => ({ ...a, order: i })),
        })),
      }));
    },
    [modifyProfile],
  );

  const updateSlot = useCallback(
    (profileId: string, slotId: string, patch: Partial<Omit<AgentSlot, 'id'>>) => {
      modifyProfile(profileId, (p) => ({
        ...p,
        departments: p.departments.map((d) => ({
          ...d,
          agents: d.agents.map((a) => (a.id === slotId ? { ...a, ...patch } : a)),
        })),
      }));
    },
    [modifyProfile],
  );

  return {
    profiles,
    activeProfile,
    activeProfileId,
    loading,
    error,
    reload,
    addProfile,
    deleteProfile,
    updateProfile: updateProfileMut,
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
