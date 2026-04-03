/**
 * ------------------------------------------------------------------------
 * 📄 파일명: useVibeData.ts
 * 📝 설명: 바이브 코딩 데이터 폴링 커스텀 훅.
 *          App.tsx(클래식 모드)와 OfficeApp(오피스 모드)에서 공유하여
 *          동일한 데이터 스트림을 사용합니다. 백엔드 API 폴링, SSE 스트림,
 *          에이전트 상태, 하이브 헬스 등 모든 실시간 데이터를 관리합니다.
 * REVISION HISTORY:
 * - 2026-04-03 Claude: App.tsx에서 데이터 폴링 로직 추출 → 커스텀 훅으로 분리
 * ------------------------------------------------------------------------
 */

import { useState, useEffect, useMemo } from 'react';
import { API_BASE } from '../constants';
import { LogRecord, AgentMessage, MemoryEntry } from '../types';

export interface VibeData {
  // 실시간 데이터 스트림
  logs: LogRecord[];
  setLogs: React.Dispatch<React.SetStateAction<LogRecord[]>>;
  messages: AgentMessage[];
  memory: MemoryEntry[];
  locks: Record<string, string>;

  // 에이전트 파이프라인 상태
  agentTerminals: Record<string, any>;
  globalPipelineStage: string;
  skillChain: any;

  // 컨텍스트 사용량
  geminiUsage: { total_tokens: number; context_window: number; percentage: number } | null;
  claudeUsage: {
    input_tokens: number; output_tokens: number; cache_read: number; cache_write: number;
    model: string; context_window: number; percentage: number; last_ts: string;
  } | null;

  // 하이브 상태
  hiveHealth: any;
  hiveActivity: any[];
  isHealingActive: boolean;

  // 앱 메타
  appVersion: string;
  updateReady: { version: string } | null;
  setUpdateReady: React.Dispatch<React.SetStateAction<{ version: string } | null>>;
  updateApplying: boolean;
  setUpdateApplying: React.Dispatch<React.SetStateAction<boolean>>;
  updateChecking: boolean;
  setUpdateChecking: React.Dispatch<React.SetStateAction<boolean>>;

  // 배지 카운트
  unreadMsgCount: number;
  setUnreadMsgCount: React.Dispatch<React.SetStateAction<number>>;
  activeTaskCount: number;
  setActiveTaskCount: React.Dispatch<React.SetStateAction<number>>;
  totalGitChanges: number;
  setTotalGitChanges: React.Dispatch<React.SetStateAction<number>>;
  conflictCount: number;
  setConflictCount: React.Dispatch<React.SetStateAction<number>>;
  isAgentRunning: boolean;
  setIsAgentRunning: React.Dispatch<React.SetStateAction<boolean>>;

  // 탐색 경로
  currentPath: string;
  setCurrentPath: React.Dispatch<React.SetStateAction<string>>;
}

export function useVibeData(): VibeData {
  // ─── 실시간 데이터 스트림 ─────────────────────────────────────────
  const [logs, setLogs] = useState<LogRecord[]>([]);
  const [messages, setMessages] = useState<AgentMessage[]>([]);
  const [memory, setMemory] = useState<MemoryEntry[]>([]);
  const [skillChain, setSkillChain] = useState<any>({ status: 'idle' });
  const [locks, setLocks] = useState<Record<string, string>>({});

  // ─── 에이전트 상태 ────────────────────────────────────────────────
  const [agentTerminals, setAgentTerminals] = useState<Record<string, any>>({});
  const [geminiUsage, setGeminiUsage] = useState<VibeData['geminiUsage']>(null);
  const [claudeUsage, setClaudeUsage] = useState<VibeData['claudeUsage']>(null);

  // ─── 하이브 상태 ──────────────────────────────────────────────────
  const [hiveHealth, setHiveHealth] = useState<any>(null);
  const [hiveActivity, setHiveActivity] = useState<any[]>([]);
  const isHealingActive = hiveHealth?.healing_active === true || hiveHealth?.status === 'healing';

  // ─── 앱 메타 ──────────────────────────────────────────────────────
  const [appVersion, setAppVersion] = useState('...');
  const [updateReady, setUpdateReady] = useState<{ version: string } | null>(null);
  const [updateApplying, setUpdateApplying] = useState(false);
  const [updateChecking, setUpdateChecking] = useState(false);

  // ─── 배지 카운트 ──────────────────────────────────────────────────
  const [unreadMsgCount, setUnreadMsgCount] = useState(0);
  const [activeTaskCount, setActiveTaskCount] = useState(0);
  const [totalGitChanges, setTotalGitChanges] = useState(0);
  const [conflictCount, setConflictCount] = useState(0);
  const [isAgentRunning, setIsAgentRunning] = useState(false);

  // ─── 탐색 경로 ────────────────────────────────────────────────────
  const [currentPath, setCurrentPath] = useState('');

  // ═══ 폴링 useEffects ═════════════════════════════════════════════

  // 좀비 서버 방지 하트비트
  useEffect(() => {
    const sendHeartbeat = () => fetch(`${API_BASE}/api/heartbeat`).catch((err) => console.error('[useVibeData] fetch error:', err));
    sendHeartbeat();
    const interval = setInterval(sendHeartbeat, 2000);
    return () => clearInterval(interval);
  }, []);

  // SSE 로그 스트림 — 실시간 이벤트 수신 (최대 200개)
  useEffect(() => {
    const sse = new EventSource(`${API_BASE}/stream`);
    sse.onmessage = (e) => {
      try {
        const data: LogRecord = JSON.parse(e.data);
        setLogs(prev => [...prev.slice(-199), data]);
      } catch {}
    };
    return () => sse.close();
  }, []);

  // 파일 락 폴링 (5초)
  useEffect(() => {
    const fetchLocks = () => {
      fetch(`${API_BASE}/api/locks`)
        .then(res => res.json())
        .then(data => setLocks(data && typeof data === 'object' && !Array.isArray(data) ? data : {}))
        .catch((err) => console.error('[useVibeData] fetch error:', err));
    };
    fetchLocks();
    const interval = setInterval(fetchLocks, 5000);
    return () => clearInterval(interval);
  }, []);

  // 에이전트 간 메시지 폴링 (5초)
  useEffect(() => {
    const fetchMessages = () => {
      fetch(`${API_BASE}/api/messages`)
        .then(res => res.json())
        .then(data => setMessages(Array.isArray(data) ? data : []))
        .catch((err) => console.error('[useVibeData] fetch error:', err));
    };
    fetchMessages();
    const interval = setInterval(fetchMessages, 5000);
    return () => clearInterval(interval);
  }, []);

  // 공유 메모리 폴링 (10초)
  useEffect(() => {
    const fetchMemory = () => {
      fetch(`${API_BASE}/api/memory`)
        .then(res => res.json())
        .then(data => setMemory(Array.isArray(data) ? data : []))
        .catch((err) => console.error('[useVibeData] fetch error:', err));
    };
    fetchMemory();
    const interval = setInterval(fetchMemory, 10000);
    return () => clearInterval(interval);
  }, []);

  // 스킬 체인 상태 폴링 (5초)
  useEffect(() => {
    const fetchChain = () => {
      fetch(`${API_BASE}/api/orchestrator/skill-chain`)
        .then(res => res.json())
        .then(data => { if (data && typeof data === 'object') setSkillChain(data); })
        .catch((err) => console.error('[useVibeData] fetch error:', err));
    };
    fetchChain();
    const interval = setInterval(fetchChain, 5000);
    return () => clearInterval(interval);
  }, []);

  // 에이전트 터미널 상태 폴링 (5초)
  useEffect(() => {
    const fetchTerminals = () => {
      fetch(`${API_BASE}/api/agent/terminals`)
        .then(res => res.json())
        .then(data => setAgentTerminals(typeof data === 'object' && data !== null ? data : {}))
        .catch((err) => console.error('[useVibeData] fetch error:', err));
    };
    fetchTerminals();
    const interval = setInterval(fetchTerminals, 5000);
    return () => clearInterval(interval);
  }, []);

  // 하이브 헬스 폴링 (10초)
  useEffect(() => {
    const fetchHealth = () => {
      fetch(`${API_BASE}/api/hive/health`)
        .then(res => res.json())
        .then(data => setHiveHealth(data))
        .catch((err) => console.error('[useVibeData] fetch error:', err));
    };
    fetchHealth();
    const interval = setInterval(fetchHealth, 10000);
    return () => clearInterval(interval);
  }, []);

  // 하이브 활동 이벤트 폴링 (10초)
  useEffect(() => {
    const fetchActivity = () => {
      fetch(`${API_BASE}/api/hive/activity`)
        .then(res => res.json())
        .then(data => setHiveActivity(Array.isArray(data) ? data : []))
        .catch((err) => console.error('[useVibeData] fetch error:', err));
    };
    fetchActivity();
    const interval = setInterval(fetchActivity, 10000);
    return () => clearInterval(interval);
  }, []);

  // 글로벌 파이프라인 단계 계산
  const globalPipelineStage = useMemo(() => {
    const stages = Object.values(agentTerminals).map((t: any) => t.pipeline_stage);
    if (stages.includes('modifying')) return 'modifying';
    if (stages.includes('verifying')) return 'verifying';
    if (stages.includes('analyzing')) return 'analyzing';
    if (stages.includes('done')) return 'done';
    return 'idle';
  }, [agentTerminals]);

  // Gemini + Claude 컨텍스트 사용량 폴링 (10초)
  useEffect(() => {
    const fetchUsage = () => {
      fetch(`${API_BASE}/api/gemini-context-usage`)
        .then(res => res.json())
        .then(data => { if (!data.error) setGeminiUsage(data); })
        .catch((err) => console.error('[useVibeData] fetch error:', err));
      fetch(`${API_BASE}/api/context-usage`)
        .then(res => res.json())
        .then(data => { if (!data.error) setClaudeUsage(data); })
        .catch((err) => console.error('[useVibeData] fetch error:', err));
    };
    fetchUsage();
    const interval = setInterval(fetchUsage, 10000);
    return () => clearInterval(interval);
  }, []);

  // 앱 버전 + 프로젝트명 로드
  useEffect(() => {
    fetch(`${API_BASE}/api/project-info`)
      .then(res => res.json())
      .then(data => {
        if (data.version) setAppVersion(data.version);
        if (data.project_name) {
          document.title = `바이브 코딩 [${data.project_name}]`;
        }
      })
      .catch((err) => console.error('[useVibeData] fetch error:', err));
  }, []);

  // 업데이트 준비 여부 폴링 (30초)
  useEffect(() => {
    const check = () => {
      fetch(`${API_BASE}/api/check-update-ready`)
        .then(res => res.json())
        .then(data => {
          if (data?.ready) {
            setUpdateReady({ version: data.version });
            if (data.error) alert(`이전 업데이트 적용 실패: ${data.error}`);
          } else {
            setUpdateReady(null);
          }
        })
        .catch((err) => console.error('[useVibeData] fetch error:', err));
    };
    check();
    const interval = setInterval(check, 30000);
    return () => clearInterval(interval);
  }, []);

  return {
    logs, setLogs, messages, memory, locks,
    agentTerminals, globalPipelineStage, skillChain,
    geminiUsage, claudeUsage,
    hiveHealth, hiveActivity, isHealingActive,
    appVersion, updateReady, setUpdateReady, updateApplying, setUpdateApplying,
    updateChecking, setUpdateChecking,
    unreadMsgCount, setUnreadMsgCount,
    activeTaskCount, setActiveTaskCount,
    totalGitChanges, setTotalGitChanges,
    conflictCount, setConflictCount,
    isAgentRunning, setIsAgentRunning,
    currentPath, setCurrentPath,
  };
}
