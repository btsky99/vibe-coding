/**
 * ------------------------------------------------------------------------
 * 📄 파일명: TerminalSlot.tsx
 * 📝 설명: 하이브 대시보드의 단일 터미널 슬롯 컴포넌트.
 *          에이전트 선택 카드(Claude/Antigravity), XTerm.js 터미널 실행, 자율 에이전트
 *          모니터링 뷰(상태/태스크/로그), 단축어 바, 슬래시 커맨드 팝업, 단축어 편집 모달을 담당합니다.
 * REVISION HISTORY:
 * - 2026-07-15 Claude: 1500줄 상한 도달로 3분할 — ClaudeContextBar(컨텍스트 바+상세 팝업),
 *                      AgentSelectCards(선택 카드 3장+배경 로그), QuotaBadge(헤더 쿼터 배지)를
 *                      terminal/ 하위로 이동. 로직 무변경, 타입은 자식이 export(순환 없음).
 * - 2026-07-12 Claude: 선택 하이라이트가 "사라진 채로 굳던" 레이스 근본 수정 — restoringSelRef
 *                      불리언 플래그가 select() 이벤트 미발화/rAF 병합 시 stuck. 무상태 내용 비교
 *                      재진입 가드 + 저장 좌표 버퍼 바운드 검증(alt 버퍼 전환/트림 시 폐기)으로 자가 복구.
 * - 2026-07-05 Claude: 드래그 하이라이트 유지 — 복사는 되지만 파란 영역이 순식간에 사라지던 문제.
 *                      TUI(claude)의 DSR 자동응답이 userInput으로 집계돼 xterm이 선택을 즉시 clear.
 *                      onSelectionChange에서 getSelectionPosition 버퍼 절대좌표를 저장 → spurious clear 시
 *                      select()로 재적용해 유지. 사용자 클릭/복사로 지운 경우(userClearedSelRef)만 복원 제외.
 * - 2026-07-05 Claude: 드래그 선택 즉시 사라짐 수정 — mousedown만 shift 합성하던 v3.7.243은 앵커만 생기고
 *                      이동분(mousemove)이 TUI로 새어 리포팅 응답이 선택을 초기화. 드래그 세션 전체
 *                      (mousedown→mousemove→mouseup)를 shift로 재디스패치해 로컬 선택 확장 유지.
 * - 2026-07-04 Claude: TUI 마우스 리포팅 중 드래그 선택 복원 — capture 단계에서 좌클릭 mousedown을
 *                      shiftKey 합성 이벤트로 재디스패치해 xterm 로컬 선택 강제. "드래그→우클릭 복사→
 *                      외부 붙여넣기" 워크플로우 복구. 붙여넣기 실패 시 터미널에 안내 출력(무음 실패 제거).
 * - 2026-07-04 Claude: 복사 버튼 상시 표시 전환 — TUI 마우스 리포팅(DECSET 1000/1006) 중엔 드래그가
 *                      로컬 선택을 아예 못 만들어 조건부 렌더가 영영 미충족(어제 캐시 수정으론 미커버).
 *                      선택 없으면 비활성(회색) + Shift+드래그 안내 힌트.
 * - 2026-07-04 Claude: 헤더 플랜 쿼터 배지 추가 — Claude/Codex 5h 게이지+% · 7d %, 세션 데이터 없어도 상시 표시.
 *                      기존 컨텍스트 바 2번째 줄 9px 텍스트가 안 보인다는 피드백의 근본 해결 (Antigravity는 기존 컨텍스트 위젯 유지).
 * - 2026-07-03 Claude: 우클릭 메뉴 복사 버튼 미표시/빈 복사 수정 — 선택 텍스트를 드래그 시점에 캐시.
 *                      근본 원인: xterm SelectionService가 onUserInput마다 선택을 지우는데, TUI(claude 등)의
 *                      DSR 커서 질의 자동 응답도 userInput으로 집계돼 우클릭 시점엔 hasSelection()=false.
 * - 2026-03-26 Claude: xterm.js 스크롤 전면 수정 — scrollback 10000줄, smoothScrollDuration 100ms,
 *                      scrollOnUserInput true 추가. 컨테이너 overflow-hidden 제거로 xterm 내장 스크롤바 활성화.
 *                      Antigravity/Codex 긴 출력 시 이전 내용 확인 불가 문제 해결.
 * - 2026-03-20 Claude: 장시간 idle 시 WS 끊김 → 자동 재연결 + 서버 ping/pong keepalive.
 *                      onclose에서 지수 백오프(1s~30s, 최대 10회)로 자동 재연결. 서버에 ping_interval=30s 추가.
 * - 2026-03-15 Claude: 절전/노트북 덮개 복귀 시 WebSocket 자동 재연결 — visibilitychange 이벤트 감지.
 *                      isTerminalMode=true && hasAttachedTerminal=false 상태에서 화면 복귀 시 launchAgent 자동 호출.
 *                      근본 원인: ws.onclose가 hasAttachedTerminal=false로 하지만 isTerminalMode는 유지 → 팝업 무한 표시 버그.
 * - 2026-03-08 Claude: 서버 실행 상태 자동 감지 — agentTerminals 폴링으로 LLM 실행 중인 슬롯 자동 터미널 모드 전환.
 *                      isTerminalMode=false 상태에서 T${slotId+1}.status==='running'이면 선택 카드 건너뛰고 모니터링 뷰 표시.
 * - 2026-03-08 Claude: Codex CLI 에이전트 선택 카드 추가 — Code2 아이콘 + 오렌지 색상테마.
 *                      launchAgent('codex', yolo) 연결 완료. 백엔드 codex 케이스는 이미 존재함.
 * - 2026-03-07 Claude: 모니터링 뷰 슬림화 — max-h 280px→160px, 헤더 h-6→h-5로 축소.
 *                      파이프라인 단계 표시는 ActivityBar LED 링으로 통합 완료.
 * - 2026-03-01 Claude: App.tsx에서 독립 컴포넌트로 분리. constants.ts의 공유 상수 사용.
 * - 2026-03-05 Claude: 파일 뷰어 제거 → 자율 에이전트 모니터링 뷰로 교체.
 *                      showActiveFile → showMonitor, 파일 fetch 로직 완전 삭제.
 *                      모니터링 뷰: 에이전트 상태/현재 태스크/최근 로그5줄/최신 메시지 표시.
 * - 2026-03-05 Claude: 모니터링 뷰에 터미널별 스킬 실행 기록 추가.
 *                      skill_results.jsonl에서 terminal_id 필터링 → 각 슬롯 귀속 결과 표시.
 *                      모니터링 높이 h-[160px] 고정 → max-h-[280px] 스크롤로 변경.
 * ------------------------------------------------------------------------
 */

import { useState, useEffect, useRef } from 'react';
import {
  Terminal, X, Zap, ClipboardList, MessageSquare, Activity, CheckCircle2, Clock
} from 'lucide-react';
import { Terminal as XTerm } from '@xterm/xterm';
import { FitAddon } from '@xterm/addon-fit';
import { WebLinksAddon } from '@xterm/addon-web-links';
import '@xterm/xterm/css/xterm.css';
import { API_BASE, WS_PORT, Shortcut, defaultShortcuts, SLASH_COMMANDS } from '../constants';
import { LogRecord, AgentMessage, Task } from '../types';
import { slugifyProjectPath } from '../lib/projectContext';
import { pickFolderDialog } from '../lib/folderPicker';
import ChatSlot from './ChatSlot';
import ShortcutEditModal from './terminal/ShortcutEditModal';
import SlashCommandMenu from './terminal/SlashCommandMenu';
import { copyTextToClipboard, captureSelectRestore, installClipboardShortcuts } from './terminal/xtermSelection';
import { readClipboardText } from '../lib/clipboard';
import ClaudeContextBar, { type ClaudeUsage } from './terminal/ClaudeContextBar';
import AgentSelectCards from './terminal/AgentSelectCards';
import QuotaBadge, { type AgentQuotaInfo } from './terminal/QuotaBadge';
import MonitorView from './terminal/MonitorView';

// 파이프라인 단계 정의는 이제 ActivityBar로 통합되었습니다.

interface TerminalSlotProps {
  slotId: number;
  logs: LogRecord[];
  currentPath: string;
  terminalCount: number;
  locks: Record<string, string>;
  messages: AgentMessage[];
  tasks: Task[];
  antigravityUsage: any;
  // Claude Code 세션 컨텍스트 사용량 — 컬러 블록 바 표시용 (타입: terminal/ClaudeContextBar)
  claudeUsage: ClaudeUsage | null;
  // [2026-07-04] 헤더 쿼터 배지 — 에이전트별 플랜 사용률 (/api/agent-quota).
  // 키: 'claude' | 'codex'. antigravity는 플랜 쿼터 공개 경로가 없어 컨텍스트 게이지 유지.
  agentQuota?: Record<string, AgentQuotaInfo> | null;
  // 터미널별 에이전트 파이프라인 상태 — App.tsx에서 /api/agent/terminals 폴링으로 수신
  agentTerminals?: Record<string, any>;
  // 오케스트레이터 스킬 체인 데이터 — /api/orchestrator/skill-chain 폴링
  orchestratorData?: { skill_registry?: any[]; terminals?: Record<string, any> };
  // 하이브 활동 이벤트 — /api/hive/activity 폴링 (memory_write/orchestrate 여부 표시용)
  hiveActivity?: Array<{ timestamp: string; agent: string; type: string; task: string }>;
  // 오피스 워크스페이스 프로필: 슬롯 사용자 지정 이름
  slotName?: string;
  // 오피스 워크스페이스 프로필: 선택된 모델 ID
  slotModel?: string;
  // 오피스 워크스페이스 프로필: 선택된 CLI (claude/antigravity/codex)
  slotCli?: string;
  // [슬롯별 프로젝트] 이 슬롯이 실행할 프로젝트 경로. 미지정 시 App이 currentPath를 넘김(하위호환).
  //   이 값이 PTY spawn cwd/project_id를 결정 → 슬롯마다 다른 프로젝트로 터미널이 뜬다.
  slotProject?: string;
  // 이 슬롯이 현재 사이드 패널을 지배하는 활성 슬롯인지 (헤더 하이라이트용)
  isActiveProject?: boolean;
  // "이 프로젝트 보기" — 슬롯 프로젝트를 앱 활성 프로젝트로 승격(패널 전환)
  onActivateProject?: () => void;
  // "📁 프로젝트" — 이 슬롯의 프로젝트 경로 지정
  onPickProject?: (path: string) => void;
}

export default function TerminalSlot({
  slotId, logs, currentPath, terminalCount, locks, messages, tasks, antigravityUsage, claudeUsage, agentQuota, agentTerminals, orchestratorData, hiveActivity, slotName, slotModel, slotCli, slotProject, isActiveProject, onActivateProject, onPickProject
}: TerminalSlotProps) {
  // [슬롯별 프로젝트] cwd/project_id 산출의 단일 기준. 미지정이면 전역 currentPath로 폴백.
  const effectivePath = slotProject || currentPath;
  const xtermRef = useRef<HTMLDivElement>(null);
  const termRef = useRef<XTerm | null>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const isComposingRef = useRef(false);
  // FitAddon 참조 보관 (모니터링 뷰 토글 시 xterm 재조정용)
  const fitAddonRef = useRef<FitAddon | null>(null);
  // ResizeObserver 참조: 터미널 컨테이너 크기 변화 자동 감지용
  const resizeObserverRef = useRef<ResizeObserver | null>(null);
  // [버그수정 2026-03-20] WebSocket 자동 재연결 타이머 참조
  const wsReconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const wsReconnectAttemptRef = useRef(0);

  const [isTerminalMode, setIsTerminalMode] = useState(false);
  const [hasAttachedTerminal, setHasAttachedTerminal] = useState(false);
  const [activeAgent, setActiveAgent] = useState('');
  const [inputValue, setInputValue] = useState('');
  const [shortcuts, setShortcuts] = useState<Shortcut[]>(() => {
    try {
      const saved = localStorage.getItem('hive_shortcuts');
      return saved ? JSON.parse(saved) : defaultShortcuts;
    } catch { return defaultShortcuts; }
  });
  const [showShortcutEditor, setShowShortcutEditor] = useState(false);
  // 슬래시 커맨드 팝업 표시 여부
  const [showSlashMenu, setShowSlashMenu] = useState(false);

  // 터미널 우클릭 컨텍스트 메뉴 위치 + 복사 대상 텍스트 스냅샷
  // [WHY] hasSelection 불리언 대신 텍스트 자체를 담는다 — 메뉴가 뜬 뒤 클릭 시점에
  // getSelection()을 다시 읽으면 TUI의 DSR 응답으로 선택이 이미 지워져 빈 문자열이 복사되는 사고 방지.
  // mouseTracking: TUI가 마우스 리포팅(DECSET 1000/1006)을 켜면 드래그가 로컬 선택을 못 만듦 —
  // 이때 복사 비활성 사유를 메뉴에 안내하기 위한 플래그 (2026-07-04 사고: 복사 버튼 미표시 재발)
  const [ctxMenu, setCtxMenu] = useState<{ x: number; y: number; selText: string; mouseTracking: boolean } | null>(null);
  // [WHY] 아래 명령어 전송 textarea는 xterm과 별개다. 맥 PyWebView(WKWebView) 백엔드는 편집 입력창에
  // 기본 우클릭 복사/붙여넣기 메뉴를 제공하지 않아(자동완성 항목만 뜸) — textarea 전용 커스텀 메뉴로 보완.
  // 윈도우 WebView2에선 기본 메뉴가 떠서 안 보이던 차이가 맥 대응 후 드러난 문제.
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const [inputCtxMenu, setInputCtxMenu] = useState<{ x: number; y: number; hasSel: boolean } | null>(null);
  // [WHY] xterm은 onUserInput마다 선택을 지운다(TUI 자동 응답 포함) — 우클릭 시점에 선택이
  // 사라져 있어도 복사가 가능하도록 마지막 비어있지 않은 선택 텍스트를 캐시.
  const lastSelectionRef = useRef('');
  // contextmenu 리스너 누적 방지 — 터미널 재시작마다 addEventListener가 쌓이지 않도록 이전 핸들러 보관
  const ctxMenuHandlerRef = useRef<((e: MouseEvent) => void) | null>(null);
  // 드래그 선택 강제 핸들러도 동일 사유로 보관 (터미널 재시작 시 교체)
  const dragSelectHandlerRef = useRef<((e: MouseEvent) => void) | null>(null);
  // [WHY] 하이라이트 유지용 — TUI(claude)가 DSR 자동응답을 userInput으로 집계해 선택을 만들자마자
  // 지운다(복사는 캐시로 되지만 파란 영역이 순식간에 사라짐). getSelectionPosition의 버퍼 절대 좌표를
  // 저장해 두었다가 spurious clear가 오면 select()로 즉시 재적용해 시각적 선택을 유지한다.
  const selPosRef = useRef<{ col: number; row: number; len: number } | null>(null);
  // [불변식] 사용자가 새 좌클릭/복사로 의도적으로 선택을 지운 경우에만 true — 이때는 복원하지 않는다.
  // TUI의 자동 clear(userClearedSelRef=false)와 사용자 clear를 구분하는 유일한 신호.
  const userClearedSelRef = useRef(false);

  // 자율 에이전트 모니터링 뷰 표시 여부 — localStorage에서 마지막 상태 복원 (기본값: false)
  // 기본값 false: 터미널 화면 최대 확보, 필요 시 버튼으로 토글
  const [showMonitor, setShowMonitor] = useState<boolean>(() => {
    const saved = localStorage.getItem('hive_monitor_enabled');
    return saved === null ? false : saved === 'true';
  });

  // Git 브랜치명 — 헤더에 현재 브랜치 표시 (cmux 스타일)
  const [gitBranch, setGitBranch] = useState<string>('');

  // 에이전트 완료 알림 — 이전 상태 추적용 ref (WORKING→IDLE 전환 시 브라우저 알림)
  const prevAgentStatus = useRef<string>('IDLE');

  // 이 슬롯의 터미널 ID — cli_agent.py의 _terminals 키와 일치 (T1, T2, ...)
  const terminalId = `T${slotId + 1}`;
  // 오피스 프로필 사용자 이름 (없으면 T1 등 기본값)
  const displayName = slotName || terminalId;

  // 이 슬롯의 에이전트 타입 (claude / antigravity / codex)
  // [버그수정 2026-03-08] Codex가 'claude'로 분류되어 T1 데이터를 T3에 표시하는 문제 수정
  const agentType = activeAgent.toLowerCase().includes('antigravity') ? 'antigravity'
    : activeAgent.toLowerCase().includes('codex') ? 'codex'
    : 'claude';

  // 이 슬롯의 데이터 결정 전략:
  // 1순위) 같은 ID의 터미널 데이터 (terminalId 일치)
  // 2순위) 같은 에이전트 타입 중 가장 최근 활성 터미널 (TERMINAL_ID 환경변수 불일치 대응)
  //        → 예: 사용자가 TERMINAL_ID=2로 Claude 실행 → T2 데이터를 UI슬롯1(T1)에서도 볼 수 있게
  const termDataById = agentTerminals?.[terminalId] as any;
  // T1 데이터가 있어도 cli(에이전트 타입)가 다르면 폴백 — 슬롯 번호≠TERMINAL_ID 환경변수 대응
  const slotMatchesAgent = termDataById && termDataById.cli === agentType;
  const termDataByAgent = !slotMatchesAgent
    ? (Object.values(agentTerminals ?? {}) as any[])
        .filter((t: any) => t.cli === agentType && t.status === 'running')
        .sort((a: any, b: any) => (b.ts ?? '').localeCompare(a.ts ?? ''))
        [0] ?? {}
    : null;
  const termData: any = slotMatchesAgent ? termDataById : (termDataByAgent ?? {});

  const pipelineStage = termData.pipeline_stage ?? 'idle';
  // 현재 실행 중인 태스크 설명 — 완료(done)된 경우 표시 안 함 (사용자 지시문이 잔류하는 문제 방지)
  const liveTask: string | null = (termData.task && termData.task !== '[외부]' && termData.status !== 'done')
    ? termData.task
    : null;

  // 오케스트레이터 스킬 체인 — 이 터미널에 할당된 체인 (slotId+1 = 터미널 번호)
  const chainData = orchestratorData?.terminals?.[String(slotId + 1)] ?? null;
  const chainSteps: any[] = chainData?.steps ?? [];
  const chainRequest: string = chainData?.request ?? '';

  // 현재 에이전트가 잠근 파일 찾기
  const lockedFileByAgent = Object.entries(locks).find(([_, owner]) => owner === activeAgent)?.[0];

  // 이 에이전트에게 할당된 진행 중 / 대기 작업 수
  const myPendingTasks = isTerminalMode
    ? tasks.filter(t => (t.assigned_to === activeAgent || t.assigned_to === 'all') && t.status !== 'done')
    : [];

  // 현재 에이전트에게 온 최근 메시지 (최근 10분 이내, 터미널 실행 중일 때만 표시)
  const recentAgentMsgs = isTerminalMode ? messages.filter(m => {
    const isForMe = m.to === activeAgent || m.to === 'all';
    const isRecent = (Date.now() - new Date(m.timestamp).getTime()) < 10 * 60 * 1000;
    return isForMe && isRecent;
  }) : [];

  const saveShortcuts = (newShortcuts: Shortcut[]) => {
    setShortcuts(newShortcuts);
    localStorage.setItem('hive_shortcuts', JSON.stringify(newShortcuts));
  };

  // XTerm 인스턴스 생성 + WebSocket PTY 연결 + ResizeObserver 등록
  // [슬롯별 프로젝트] cwdOverride: 프로젝트 변경 재시작 시 새 경로를 명시 주입.
  //   effectivePath는 이번 렌더 클로저 값이라 onPickProject 직후엔 아직 옛 값(stale) → override로 회피.
  const launchAgent = (agent: string, yolo: boolean = false, cwdOverride?: string) => {
    const connectPath = cwdOverride || effectivePath;
    // 기존 터미널이 살아있으면 먼저 정리 — dispose 없이 덮어쓰면
    // 이전 xterm 캔버스가 DOM에 남아 잔상(이중 삼중 출력) 현상 발생
    // [버그수정 2026-03-20] 재연결 타이머 정리 (새 연결 시작 전)
    if (wsReconnectTimerRef.current) {
      clearTimeout(wsReconnectTimerRef.current);
      wsReconnectTimerRef.current = null;
    }
    if (termRef.current) {
      termRef.current.dispose();
      termRef.current = null;
    }
    if (wsRef.current) {
      wsRef.current.close(1000);
      wsRef.current = null;
    }
    resizeObserverRef.current?.disconnect();
    resizeObserverRef.current = null;
    // xterm이 DOM에 주입한 캔버스/래퍼 엘리먼트 제거 (dispose만으론 DOM 잔여물 남음)
    if (xtermRef.current) {
      xtermRef.current.innerHTML = '';
    }

    setIsTerminalMode(true);
    setActiveAgent(agent);
    // 새 터미널 인스턴스 — 이전 선택 좌표가 남으면 새 버퍼에 spurious 복원될 수 있어 초기화.
    selPosRef.current = null;
    userClearedSelRef.current = false;
    // 터미널 재시작 시 localStorage 기반으로 모니터링 뷰 상태 복원
    // closeTerminal이 isTerminalMode만 false로 하므로, showMonitor를 명시적으로 동기화
    setShowMonitor(localStorage.getItem('hive_monitor_enabled') !== 'false');

    setTimeout(() => {
      if (!xtermRef.current) return;
      const term = new XTerm({
        theme: { background: '#1e1e1e', foreground: '#cccccc', cursor: '#3794ef', selectionBackground: '#3794ef55' },
        fontFamily: "'Fira Code', 'Consolas', monospace",
        fontSize: 13,
        cursorBlink: true,
        // 스크롤 설정 — 이전 출력 확인 가능하도록 충분한 버퍼 확보
        scrollback: 10000,
        smoothScrollDuration: 100,
        scrollOnUserInput: true
      });
      const fitAddon = new FitAddon();
      term.loadAddon(fitAddon);
      term.loadAddon(new WebLinksAddon((_event, uri) => {
        fetch(`${API_BASE}/api/open-external`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ url: uri }),
        }).catch(() => {
          window.open(uri, '_blank', 'noopener,noreferrer');
        });
      }));
      term.open(xtermRef.current);
      fitAddon.fit();
      termRef.current = term;

      // 키보드 복붙 단축키 — 맥 ⌘C/⌘V, 윈도우 Ctrl+Shift+C/V (플랫폼 분기는 헬퍼 내부).
      // [제약] term.textarea는 open() 이후에만 존재 → 반드시 이 위치에서 호출.
      installClipboardShortcuts(term, () => lastSelectionRef.current, () => {
        term.write('\r\n\x1b[33m[클립보드 읽기 실패 — 우클릭 메뉴의 붙여넣기를 사용하세요]\x1b[0m\r\n');
      });

      // 텍스트 드래그(선택) 시 자동 클립보드 복사 + 마지막 선택 캐시 + 하이라이트 유지 복원.
      // [제약] 선택 해제 이벤트에서도 발화하므로 hasSelection 가드 필수 — 캐시를 빈 값으로 덮지 않는다.
      term.onSelectionChange(() => {
        if (term.hasSelection()) {
          const sel = term.getSelection();
          // [재진입 가드 — 무상태 내용 비교] 복원한 선택은 직전 캐시와 내용이 동일 → 조용히 통과.
          // 불리언 플래그는 select()가 이벤트를 안 흘리거나 rAF로 뭉치면 stuck → 다음 진짜 clear를
          // 삼켜 선택이 영영 사라졌다(과거 레이스). 내용 비교는 상태가 없어 stuck 불가.
          if (sel && sel === lastSelectionRef.current) return;
          if (sel) {
            lastSelectionRef.current = sel;
            copyTextToClipboard(sel);
            // [복원] 버퍼 절대 좌표 스냅샷 저장 — 상세 계산은 captureSelectRestore 참조.
            selPosRef.current = captureSelectRestore(term);
          }
          userClearedSelRef.current = false;
        } else {
          // 선택이 사라짐. 사용자가 의도적으로 지웠거나(새 클릭/복사) 저장분이 없으면 그대로 둔다.
          if (userClearedSelRef.current || !selPosRef.current) {
            selPosRef.current = null;
            userClearedSelRef.current = false;
            return;
          }
          const { col, row, len } = selPosRef.current;
          // [바운드 검증 — 자가 복구] 저장 좌표가 버퍼 범위를 벗어나면(TUI의 alt 버퍼 전환·스크롤백
          // 트림·창 축소) select()가 빈 선택을 만들어 복원이 굳는다 → 저장분 폐기로 영구 실패를 끊는다.
          if (row < 0 || row >= term.buffer.active.length || col < 0 || col >= term.cols) {
            selPosRef.current = null;
            return;
          }
          // TUI 자동 clear로 판단 → 저장 좌표로 즉시 재적용해 하이라이트 유지.
          term.select(col, row, len);
        }
      });

      // [WHY] TUI(claude 등)가 마우스 리포팅(DECSET 1000/1002)을 켜면 xterm이 좌클릭 드래그를
      // TUI로 전달해 로컬 선택이 아예 안 생긴다 → "드래그→우클릭 복사"가 통째로 죽음(2026-07-04 사고).
      // xterm 내부 SelectionService는 shiftKey 이벤트만 마우스 리포팅 중에도 로컬 선택으로 처리하므로,
      // capture 단계에서 일반 좌클릭 mousedown을 shiftKey=true 합성 이벤트로 재디스패치해 선택을 강제한다.
      // [제약] 이로 인해 마우스 리포팅 중 좌클릭은 TUI에 전달되지 않는다 — claude CLI는 좌클릭을
      // 쓰지 않고(스크롤 휠은 별도 경로라 영향 없음) 사용자 워크플로우(드래그 복사)가 우선.
      // 합성 이벤트는 shiftKey=true라 첫 가드에서 통과 → 재귀 없음. 일반 셸(리포팅 OFF)은 미개입.
      // [과거사고] v3.7.243은 mousedown만 shift로 합성 → 선택 앵커(시작점)만 생기고
      // 드래그 이동분(mousemove)이 shift 없이 TUI로 새어나가 리포팅 응답이 선택을 즉시 초기화.
      // 증상(2026-07-05 리포트): "복사는 되는데 드래그하면 하이라이트가 바로 사라짐".
      // 해결: 드래그 세션 전체(mousedown→mousemove→mouseup)를 shift 이벤트로 재디스패치해
      // xterm 로컬 선택 확장을 유지하고 원본 이벤트는 stopImmediatePropagation으로 리포팅 경로 차단.
      const redispatchAsShift = (src: MouseEvent, type: string) =>
        src.target?.dispatchEvent(new MouseEvent(type, {
          bubbles: true, cancelable: true, view: window,
          clientX: src.clientX, clientY: src.clientY, screenX: src.screenX, screenY: src.screenY,
          button: src.button, buttons: src.buttons, detail: src.detail, shiftKey: true,
        }));
      const dragSelectHandler = (e: MouseEvent) => {
        if (e.button !== 0 || e.shiftKey) return;
        if (!term.element?.classList.contains('enable-mouse-events')) return;
        // 새 좌클릭 = 이전 선택을 의도적으로 해제하는 것 → 이번 clear는 복원하지 않는다.
        // 드래그로 새 선택이 생기면 onSelectionChange(hasSelection)에서 다시 false로 내려간다.
        userClearedSelRef.current = true;
        e.preventDefault();
        e.stopImmediatePropagation();
        redispatchAsShift(e, 'mousedown');
        // [불변식] 합성 이벤트는 shiftKey=true라 각 핸들러 첫 가드에서 return → 무한 재귀 없음.
        // 드래그가 터미널 밖으로 나가도 추적되도록 document capture에 세션 리스너를 건다.
        const endDrag = () => {
          document.removeEventListener('mousemove', onMove, true);
          document.removeEventListener('mouseup', onUp, true);
        };
        const onMove = (me: MouseEvent) => {
          if (me.shiftKey) return;               // 합성 이벤트 — 재진입 차단
          if (!(me.buttons & 1)) { endDrag(); return; }  // 좌클릭 뗌 → 세션 종료 안전장치
          me.preventDefault();
          me.stopImmediatePropagation();
          redispatchAsShift(me, 'mousemove');
        };
        const onUp = (ue: MouseEvent) => {
          endDrag();
          if (ue.shiftKey) return;
          ue.preventDefault();
          ue.stopImmediatePropagation();
          redispatchAsShift(ue, 'mouseup');      // 선택 확정
        };
        document.addEventListener('mousemove', onMove, true);
        document.addEventListener('mouseup', onUp, true);
      };
      if (dragSelectHandlerRef.current) {
        xtermRef.current.removeEventListener('mousedown', dragSelectHandlerRef.current, true);
      }
      xtermRef.current.addEventListener('mousedown', dragSelectHandler, true);
      dragSelectHandlerRef.current = dragSelectHandler;

      // 터미널 우클릭: 컨텍스트 메뉴 표시 — 복사 대상 텍스트를 이 시점에 스냅샷
      // [WHY] 라이브 선택이 TUI DSR 응답으로 이미 지워졌으면 캐시(lastSelectionRef)로 폴백 —
      // "드래그 → 우클릭했는데 복사 버튼이 없다" 사고(2026-07-03) 방지.
      const ctxHandler = (e: MouseEvent) => {
        e.preventDefault();
        const liveSel = term.hasSelection() ? term.getSelection() : '';
        // [WHY] enable-mouse-events 클래스 = TUI가 마우스 리포팅 중 — 일반 드래그로는 선택이
        // 아예 생성되지 않는다(onSelectionChange 미발화). Shift+드래그만 로컬 선택 허용.
        const mouseTracking = term.element?.classList.contains('enable-mouse-events') ?? false;
        setCtxMenu({ x: e.clientX, y: e.clientY, selText: liveSel || lastSelectionRef.current, mouseTracking });
      };
      if (ctxMenuHandlerRef.current) {
        xtermRef.current.removeEventListener('contextmenu', ctxMenuHandlerRef.current);
      }
      xtermRef.current.addEventListener('contextmenu', ctxHandler);
      ctxMenuHandlerRef.current = ctxHandler;

      // ref에 저장하여 모니터링 뷰 토글 시에도 fit() 호출 가능하게
      fitAddonRef.current = fitAddon;
      // ResizeObserver: 터미널 컨테이너 크기 변화 감지 시 자동으로 xterm 재조정
      // 모니터링 뷰 열기/닫기로 컨테이너 높이가 바뀔 때마다 즉시 반응
      const termContainer = xtermRef.current;
      if (termContainer) {
        const ro = new ResizeObserver(() => fitAddon.fit());
        ro.observe(termContainer);
        resizeObserverRef.current = ro;
      }
      // WebSocket에 yolo/model/name + project_id 상태 전달 (Phase 2-5.3a)
      // [슬롯별 프로젝트] cwd/project_id는 connectPath(슬롯 프로젝트 우선, 재시작 override) 기준 — 슬롯마다 다른 프로젝트로 spawn
      const projectId = slugifyProjectPath(connectPath);
      const wsParams = new URLSearchParams({
        agent: slotCli || agent,
        cwd: connectPath,
        cols: term.cols.toString(),
        rows: term.rows.toString(),
        yolo: yolo.toString(),
        ...(projectId ? { project_id: projectId } : {}),
        ...(slotModel ? { model: slotModel } : {}),
        ...(slotName ? { name: slotName } : {}),
      });
      const ws = new WebSocket(`ws://${window.location.hostname}:${WS_PORT}/pty/slot${slotId}?${wsParams.toString()}`);
      wsRef.current = ws;
      ws.onopen = () => {
        setHasAttachedTerminal(true);
        // 재연결 성공 시 카운터 리셋
        wsReconnectAttemptRef.current = 0;
        const modeText = yolo ? "\x1b[38;5;196m[YOLO MODE]\x1b[0m" : "\x1b[38;5;34m[NORMAL MODE]\x1b[0m";
        term.write(`\r\n\x1b[38;5;39m[HIVE] ${agent.toUpperCase()} ${modeText} 터미널 연결 성공 \x1b[38;5;245m[node-pty]\x1b[0m\r\n\x1b[38;5;244m> CWD: ${connectPath}\x1b[0m\r\n\r\n`);
        // WS 연결 직후 현재 터미널 크기를 PTY에 전달
        // ResizeObserver가 WS 연결 전에 fire됐을 경우 누락된 resize를 보정
        ws.send(JSON.stringify({ type: 'resize', cols: term.cols, rows: term.rows }));
      };
      // [버그수정 2026-03-20] 장시간 idle 시 WS 끊김 → 자동 재연결
      // 원인: OS TCP keepalive 타임아웃 또는 네트워크 일시 단절로 WS가 닫힘.
      // 해결: onclose에서 지수 백오프(1s→2s→4s...최대30s)로 자동 재연결 시도.
      //       사용자가 명시적으로 터미널을 닫은 경우(cleanupTerminal)는 재연결하지 않음.
      // [2026-03-30 Claude] Stale closure 버그 수정 — hasAttachedTerminal 대신 ref 사용
      // 기존: onclose 콜백이 클로저 시점의 hasAttachedTerminal(항상 false)을 캡처
      // → 정상 연결 중에도 재연결 시도 가능 (무한 재연결 루프 위험)
      // 수정: wsRef.current?.readyState로 실제 연결 상태를 직접 확인
      ws.onclose = (event) => {
        setHasAttachedTerminal(false);
        // code 1000(정상종료) 또는 터미널 모드가 꺼진 경우 재연결하지 않음
        if (event.code === 1000) return;
        // 지수 백오프: 1s, 2s, 4s, 8s, 16s, 30s (최대)
        const attempt = wsReconnectAttemptRef.current;
        const delay = Math.min(1000 * Math.pow(2, attempt), 30000);
        wsReconnectAttemptRef.current = attempt + 1;
        if (attempt < 10) {
          term.write(`\r\n\x1b[38;5;208m[HIVE] 연결 끊김 — ${delay / 1000}초 후 자동 재연결 (${attempt + 1}/10)\x1b[0m\r\n`);
          wsReconnectTimerRef.current = setTimeout(() => {
            // ref 기반으로 실제 상태 확인 — stale closure 방지
            const currentWs = wsRef.current;
            const isAlreadyConnected = currentWs && currentWs.readyState === WebSocket.OPEN;
            if (termRef.current && !isAlreadyConnected) {
              launchAgent(agent, false);
            }
          }, delay);
        }
      };
      ws.onmessage = async (e) => {
        const data = e.data instanceof Blob ? await e.data.text() : e.data;
        term.write(data);
      };
      term.onData(data => ws.readyState === WebSocket.OPEN && ws.send(data));
      // xterm cols/rows가 바뀔 때마다 서버 PTY에 SIGWINCH 전달
      // fitAddon.fit() → term.onResize 순으로 발생하므로 여기서 resize 메시지 전송
      term.onResize(({ cols, rows }) => {
        if (ws.readyState === WebSocket.OPEN) {
          ws.send(JSON.stringify({ type: 'resize', cols, rows }));
        }
      });
      // 창 크기 변경 시 터미널 재조정 (클린업 포함)
      const handleResize = () => fitAddon.fit();
      window.addEventListener('resize', handleResize);
      return () => window.removeEventListener('resize', handleResize);
    }, 50);
  };

  // 컨텍스트 메뉴가 열려 있을 때 바깥 클릭 시 닫기
  useEffect(() => {
    if (!ctxMenu) return;
    const close = () => setCtxMenu(null);
    window.addEventListener('click', close);
    return () => window.removeEventListener('click', close);
  }, [ctxMenu]);

  // 입력창 컨텍스트 메뉴도 바깥 클릭/스크롤 시 닫기
  useEffect(() => {
    if (!inputCtxMenu) return;
    const close = () => setInputCtxMenu(null);
    window.addEventListener('click', close);
    window.addEventListener('scroll', close, true);
    return () => {
      window.removeEventListener('click', close);
      window.removeEventListener('scroll', close, true);
    };
  }, [inputCtxMenu]);

  // 모니터링 뷰 토글 시 xterm 터미널 크기 재조정
  // ResizeObserver가 주 역할이며, 이 타이머는 폴백으로 이중 호출해 안정성 확보
  useEffect(() => {
    if (!fitAddonRef.current) return;
    const fitNow = () => {
      fitAddonRef.current?.fit();
      termRef.current?.scrollToBottom();
    };
    const raf1 = requestAnimationFrame(fitNow);
    const raf2 = requestAnimationFrame(() => requestAnimationFrame(fitNow));
    const t1 = setTimeout(fitNow, 100);
    const t2 = setTimeout(fitNow, 350);
    return () => {
      cancelAnimationFrame(raf1);
      cancelAnimationFrame(raf2);
      clearTimeout(t1);
      clearTimeout(t2);
    };
  }, [showMonitor]);


  const closeTerminal = () => {
    // [버그수정 2026-03-20] 명시적 종료 시 재연결 타이머 정리
    if (wsReconnectTimerRef.current) {
      clearTimeout(wsReconnectTimerRef.current);
      wsReconnectTimerRef.current = null;
    }
    wsReconnectAttemptRef.current = 0;
    setIsTerminalMode(false);
    setHasAttachedTerminal(false);
    fitAddonRef.current = null;
    // ResizeObserver 해제 (메모리 누수 방지)
    resizeObserverRef.current?.disconnect();
    resizeObserverRef.current = null;
    if (wsRef.current) wsRef.current.close(1000);  // 1000=정상종료 → onclose에서 재연결 안 함
    if (termRef.current) termRef.current.dispose();
  };

  // [슬롯별 프로젝트] 이 슬롯의 프로젝트 폴더 지정. 실행 중이면 재시작 확인 후 새 cwd로 재연결.
  //   [불변식] PTY cwd는 spawn 시 고정 → 살아있는 터미널의 프로젝트는 재시작 없이 못 바꾼다.
  //   재연결 시 launchAgent에 next를 명시 주입 — onPickProject 직후 effectivePath는 아직 옛 값(stale).
  const handlePickProject = async () => {
    if (!onPickProject) return;
    // [코드리뷰 2026-07-24] window.prompt 재발명 금지 — FileExplorer와 동일한 네이티브 다이얼로그
    //   공유 헬퍼 사용(검증된 실제 경로만 수신, mac WKWebView prompt 신뢰성 문제 회피).
    const picked = await pickFolderDialog();
    if (!picked) return;  // 취소 또는 다이얼로그 불가
    const next = picked.replace(/\\/g, '/').trim();
    if (!next || next === slotProject) return;
    if (hasAttachedTerminal) {
      // [불변식] 재시작은 xterm dispose + 새 PTY spawn = 스크롤백 전량 소실. 사용자에게 명시.
      if (!window.confirm('프로젝트를 바꾸려면 이 터미널을 재시작합니다 (현재 스크롤백은 사라집니다). 진행할까요?')) return;
      onPickProject(next);
      launchAgent(activeAgent || 'claude', false, next);
    } else {
      onPickProject(next);
    }
  };

  const handleSend = (text: string) => {
    if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) return;
    const ws = wsRef.current;
    const cleanText = text.replace(/[\r\n]+$/, '');
    if (!cleanText) return;

    const lines = cleanText.replace(/\r\n/g, '\n').split('\n');
    for (const line of lines) {
      ws.send(`${line}\r`);
    }
    setInputValue('');
    termRef.current?.focus();
  };

  // 터미널 실행 중이면 활성 에이전트 이름으로 로그 필터링 (정확한 귀속)
  // 유휴 상태이면 해시 기반 분배 (배경 로그 표시용)
  const slotLogs = isTerminalMode
    ? logs.filter(l => l.agent?.toLowerCase() === activeAgent.toLowerCase())
    : logs.filter(l => {
        let hash = 0;
        // [버그수정] terminal_id가 null/undefined일 때 .length 접근 → TypeError 방어
        const tid = l.terminal_id ?? '';
        for (let i = 0; i < tid.length; i++) hash = ((hash << 5) - hash) + tid.charCodeAt(i);
        return Math.abs(hash) % terminalCount === slotId;
      });

  // Git 브랜치 폴링 — 터미널 실행 중일 때 5초마다 현재 브랜치 확인
  useEffect(() => {
    if (!isTerminalMode) return;
    const fetchBranch = () => {
      fetch(`${API_BASE}/api/git/status`)
        .then(res => res.json())
        .then(data => { if (data.branch) setGitBranch(data.branch); })
        .catch((err) => console.error('[TerminalSlot] fetch error:', err));
    };
    fetchBranch();
    const iv = setInterval(fetchBranch, 5000);
    return () => clearInterval(iv);
  }, [isTerminalMode]);

  // 모니터링 뷰: 에이전트 상태 계산
  // 최근 30초 이내 로그가 있으면 RUNNING, 태스크 진행 중이면 WORKING, 그 외 IDLE
  const now = Date.now();
  const recentLog = slotLogs.find(l => (now - new Date(l.ts_start ?? 0).getTime()) < 30_000);
  const inProgressTask = myPendingTasks.find(t => t.status === 'in_progress');
  // pipelineStage도 agentStatus 판단에 반영 — hook에서 modifying/analyzing 단계면 WORKING 표시
  const isActiveStage = ['analyzing', 'modifying', 'verifying'].includes(pipelineStage);
  // termData.status === 'running': 외부 Antigravity 감지(_detect_external_antigravity) 포함, 서버가 실행 중으로 판단한 경우 RUNNING 표시
  const isServerRunning = termData.status === 'running' || termData.status === 'started';
  const agentStatus = isActiveStage ? 'WORKING' : inProgressTask ? 'WORKING' : recentLog ? 'RUNNING' : isServerRunning ? 'RUNNING' : 'IDLE';
  const statusColor = agentStatus === 'WORKING' ? 'text-yellow-400' : agentStatus === 'RUNNING' ? 'text-green-400' : 'text-[#858585]';
  const statusDot = agentStatus === 'IDLE' ? 'bg-[#555]' : agentStatus === 'RUNNING' ? 'bg-green-400 animate-pulse' : 'bg-yellow-400 animate-pulse';

  // 에이전트 완료 알림 — WORKING/RUNNING → IDLE 전환 시 브라우저 알림 발송 (cmux 알림 시스템)
  useEffect(() => {
    if (!isTerminalMode) return;
    const prev = prevAgentStatus.current;
    if ((prev === 'WORKING' || prev === 'RUNNING') && agentStatus === 'IDLE') {
      if ('Notification' in window && Notification.permission === 'granted') {
        new Notification(`[T${slotId + 1}] ${activeAgent} 작업 완료`, {
          body: liveTask ?? '에이전트가 작업을 완료했습니다.',
          icon: '/favicon.ico',
        });
      } else if ('Notification' in window && Notification.permission !== 'denied') {
        Notification.requestPermission();
      }
    }
    prevAgentStatus.current = agentStatus;
  }, [agentStatus, isTerminalMode, activeAgent, slotId, liveTask]);

  // 서버 실행 상태 자동 감지 — agentTerminals 폴링(3초) 결과에 따라 터미널 모드 자동 전환
  // 사용자가 버튼을 누르지 않아도 서버에서 LLM이 실행 중이면 선택 카드를 건너뜁니다.
  // 반대로 idle/done 전환 시에는 자동 복귀하지 않음 (출력 내용 보존, 사용자가 직접 닫기)
  // [버그수정 2026-03-08] isTerminalMode=true여도 activeAgent는 항상 서버 cli에 동기화해야 함.
  // 이전에 Claude로 실행 후 Codex로 재시작하면 activeAgent='claude' 잔류 → T1 데이터 표시 버그.
  useEffect(() => {
    const serverStatus = agentTerminals?.[terminalId];
    if (serverStatus?.status === 'running' || serverStatus?.status === 'started') {
      const detectedCli = serverStatus.cli ?? 'claude';
      // activeAgent는 항상 갱신 — 에이전트 타입이 바뀌어도 올바른 termData 선택 보장
      if (detectedCli) setActiveAgent(detectedCli);
      if (!isTerminalMode && !hasAttachedTerminal) {
        setShowMonitor(true); // 모니터링 뷰 자동 활성화 (XTerm 없이도 상태 확인 가능)
      }
    }
  }, [agentTerminals, terminalId, isTerminalMode, hasAttachedTerminal]);

  // [버그수정 2026-03-15] 절전/노트북 덮개 복귀 시 WebSocket 자동 재연결
  // 원인: PC 절전 또는 노트북 덮개 닫기 → 열기 시 WebSocket이 끊어지면
  //       ws.onclose → hasAttachedTerminal=false 되지만 isTerminalMode=true 유지됨.
  //       visibilitychange 이벤트 미처리로 인해 "터미널 출력 연결이 아직 없습니다" 팝업이 계속 떠 있음.
  // 해결: visibilitychange 이벤트로 화면 복귀를 감지하고 터미널 자동 재연결.
  useEffect(() => {
    if (!isTerminalMode) return;
    const handleVisibilityChange = () => {
      if (document.visibilityState === 'visible' && !hasAttachedTerminal) {
        // 화면이 다시 켜질 때 WS가 끊어진 상태이면 같은 에이전트로 자동 재연결
        launchAgent(activeAgent || 'claude', false);
      }
    };
    document.addEventListener('visibilitychange', handleVisibilityChange);
    return () => document.removeEventListener('visibilitychange', handleVisibilityChange);
  }, [isTerminalMode, hasAttachedTerminal, activeAgent]);

  // 알림 링 글로우 — 에이전트 상태에 따라 패널 테두리 색상/그림자 변경 (cmux 스타일)
  const ringClass = !isTerminalMode
    ? 'border border-black/40'
    : agentStatus === 'WORKING'
      ? 'border border-yellow-400/50 shadow-[0_0_12px_2px_rgba(234,179,8,0.25)]'
      : agentStatus === 'RUNNING'
        ? 'border border-blue-400/50 shadow-[0_0_12px_2px_rgba(96,165,250,0.2)]'
        : 'border border-black/40';

  return (
    // h-full: 그리드 셀 높이를 명시적으로 채워야 flex 자식들이 올바른 높이를 전달받음
    <div className={`h-full min-w-0 min-h-0 bg-[#252526] ${ringClass} rounded-md flex flex-col overflow-hidden shadow-inner relative transition-all duration-700`}>
      {/* 터미널 헤더 — 슬롯 번호, 에이전트명, 락/작업/메시지 배지 */}
      <div className="h-7 bg-[#2d2d2d] border-b border-black/40 flex items-center justify-between px-3 shrink-0">
        <div className="flex items-center gap-2 max-w-[60%] overflow-hidden">
          <Terminal className="w-3 h-3 text-accent shrink-0" />
          <span className="text-[10px] font-bold text-[#bbbbbb] uppercase tracking-wider truncate">
            {isTerminalMode ? `${displayName} - ${activeAgent}` : displayName}
          </span>
          {/* Git 브랜치 배지 — cmux 스타일 수직 탭 컨텍스트 정보 */}
          {gitBranch && (
            <span className="text-[8px] font-mono text-accent/70 bg-accent/10 border border-accent/20 px-1.5 py-0.5 rounded shrink-0">
              {gitBranch}
            </span>
          )}
          {lockedFileByAgent && (
            <div className="flex items-center gap-1.5 ml-2 px-1.5 py-0.5 bg-yellow-500/10 border border-yellow-500/30 rounded text-[9px] text-yellow-500 animate-pulse shrink-0">
              <Zap className="w-2.5 h-2.5" />
              <span className="font-mono">LOCK: {lockedFileByAgent.split(/[\\\/]/).pop()}</span>
            </div>
          )}
          {/* 이 에이전트에게 할당된 작업 수 배지 */}
          {myPendingTasks.length > 0 && (
            <div
              className="flex items-center gap-1 ml-1 px-1.5 py-0.5 bg-yellow-500/10 border border-yellow-500/30 rounded text-[9px] text-yellow-400 shrink-0"
              title={myPendingTasks.map(t => t.title).join(', ')}
            >
              <ClipboardList className="w-2.5 h-2.5" />
              <span>{myPendingTasks.length}개 작업</span>
            </div>
          )}
          {/* 이 에이전트에게 온 최근 메시지 알림 배지 */}
          {recentAgentMsgs.length > 0 && (
            <div
              className="flex items-center gap-1 ml-1 px-1.5 py-0.5 bg-primary/10 border border-primary/30 rounded text-[9px] text-primary shrink-0 animate-pulse"
              title={recentAgentMsgs[recentAgentMsgs.length - 1].content}
            >
              <MessageSquare className="w-2.5 h-2.5" />
              <span>{recentAgentMsgs.length}개 메시지</span>
            </div>
          )}
        </div>
        {!isTerminalMode ? (
          <div className="flex gap-2 items-center">
            <span className="text-[9px] text-[#858585] font-bold mr-1">에이전트 선택 대기 중...</span>
          </div>
        ) : (
          <div className="flex gap-2 items-center">
            {/* Claude Code 모델 배지 — main_model / bg_model 표시 (Claude 에이전트 실행 중일 때만) */}
            {agentType === 'claude' && termData.main_model && (
              <div className="flex items-center gap-1 px-1.5 py-0.5 bg-[#1a1a2e]/80 border border-blue-500/20 rounded text-[8px] text-blue-300/80 font-mono">
                <span className="opacity-60">M:</span>
                <span className="font-bold">{String(termData.main_model).replace('claude-', '').replace(/-\d{8}$/, '')}</span>
                {termData.bg_model && (
                  <>
                    <span className="opacity-40 mx-0.5">|</span>
                    <span className="opacity-60">BG:</span>
                    <span className="font-bold text-green-300/70">{String(termData.bg_model).replace('claude-', '').replace(/-\d{8}$/, '')}</span>
                  </>
                )}
              </div>
            )}

            {/* Antigravity 컨텍스트 사용량 표시 (에이전트가 antigravity일 때만) */}
            {activeAgent.toLowerCase().includes('antigravity') && antigravityUsage && (
              <div className="flex items-center gap-2 mr-2 px-2 py-0.5 bg-accent/10 border border-accent/20 rounded text-[9px] text-accent animate-in fade-in duration-500">
                <div className="flex flex-col items-end leading-none gap-0.5">
                  <span className="font-bold opacity-80 uppercase text-[8px]">Context</span>
                  <span className="font-black">{((antigravityUsage.total_tokens ?? 0) / 1000).toFixed(1)}K / {((antigravityUsage.context_window ?? 0) / 1000).toFixed(1)}K</span>
                </div>
                <div className="w-12 h-1.5 bg-black/40 rounded-full overflow-hidden border border-white/5 relative">
                  <div
                    className={`h-full transition-all duration-1000 ${antigravityUsage.percentage > 80 ? 'bg-red-500' : antigravityUsage.percentage > 50 ? 'bg-yellow-500' : 'bg-accent'}`}
                    style={{ width: `${Math.min(100, antigravityUsage.percentage)}%` }}
                  />
                </div>
                <span className="font-bold w-6 text-right">{Math.round(antigravityUsage.percentage ?? 0)}%</span>
              </div>
            )}

            {/* [2026-07-04] 플랜 쿼터 배지 — Claude/Codex 슬롯 헤더 상시 표시 (terminal/QuotaBadge) */}
            {(agentType === 'claude' || agentType === 'codex') && (
              <QuotaBadge agentType={agentType} quota={agentQuota?.[agentType]} />
            )}

            {/* [슬롯별 프로젝트] 프로젝트 뱃지(클릭=이 프로젝트로 패널 전환) + 변경 버튼.
                isActiveProject면 하이라이트 — 지금 사이드 패널이 이 슬롯 프로젝트를 보고 있다는 표시. */}
            <button
              onClick={onActivateProject}
              title="이 프로젝트를 사이드 패널(파일·Git·태스크)에 표시"
              className={`px-2 py-0.5 rounded text-[9px] border font-bold truncate max-w-[120px] transition-all ${isActiveProject ? 'bg-accent/25 border-accent/60 text-accent' : 'bg-[#3c3c3c] border-white/5 text-[#cccccc] hover:bg-white/10'}`}
            >
              📁 {effectivePath.split(/[/\\]/).filter(Boolean).pop() || '프로젝트'}
            </button>
            <button
              onClick={handlePickProject}
              title="이 슬롯의 프로젝트 폴더 변경 (실행 중이면 재시작)"
              className="px-1.5 py-0.5 rounded text-[9px] border border-white/5 bg-[#3c3c3c] text-[#cccccc] hover:bg-white/10 transition-all"
            >
              변경
            </button>

            {/* 자율 에이전트 모니터링 뷰 토글 버튼 — 상태를 localStorage에 저장하여 다음 실행 시 복원 */}
            <button
              onClick={() => { const next = !showMonitor; setShowMonitor(next); localStorage.setItem('hive_monitor_enabled', String(next)); }}
              className={`px-2 py-0.5 rounded text-[9px] border transition-all font-bold flex items-center gap-1 ${showMonitor ? 'bg-green-500/20 border-green-500/50 text-green-400' : 'bg-[#3c3c3c] border-white/5 text-[#cccccc] hover:bg-white/10'}`}
              title="자율 에이전트 실시간 모니터링"
            >
              <Activity className="w-2.5 h-2.5" />
              모니터링
            </button>
            <button onClick={closeTerminal} className="p-0.5 hover:bg-red-500/20 rounded text-red-400 transition-colors"><X className="w-3.5 h-3.5" /></button>
          </div>
        )}
      </div>

      {/* ── Claude 컨텍스트 컬러 블록 바 — terminal/ClaudeContextBar로 분리 (2026-07-15) ── */}
      {isTerminalMode && agentType === 'claude' && <ClaudeContextBar ctx={claudeUsage} />}

      {/* ── 터미널 뷰: isTerminalMode일 때 표시, 채팅 전환 시 hidden으로 유지 (unmount 안 함) ── */}
      {isTerminalMode && (
        <div className="flex-1 min-w-0 flex flex-col min-h-0 bg-[#1e1e1e]">

          {/* ── 자율 에이전트 모니터링 뷰 — terminal/MonitorView로 분리 (2026-07-15) ── */}
          {showMonitor && (
            <MonitorView
              activeAgent={activeAgent} agentStatus={agentStatus}
              statusColor={statusColor} statusDot={statusDot}
              chainSteps={chainSteps} chainRequest={chainRequest}
              liveTask={liveTask} inProgressTask={inProgressTask}
              myPendingTasks={myPendingTasks} hiveActivity={hiveActivity}
            />
          )}

          {/* xterm.js v6 내장 스크롤바 사용 — 외부 overflow-hidden 제거하여 스크롤 활성화 */}
          <div className="flex-1 relative min-w-0 min-h-0">
            <div className="absolute inset-0 p-2">
              <div ref={xtermRef} className="h-full w-full" />
            </div>
            {!hasAttachedTerminal && (
              <div className="absolute inset-0 flex items-center justify-center p-6">
                <div className="max-w-md rounded-2xl border border-white/10 bg-[#252526] px-5 py-4 text-left shadow-2xl">
                  <div className="text-[12px] font-bold text-white">터미널 출력 연결이 아직 없습니다.</div>
                  <div className="mt-2 text-[11px] leading-relaxed text-[#b8b8b8]">
                    실행 상태는 감지됐지만 이 슬롯에 실제 터미널 화면이 붙지 않아 빈 화면처럼 보일 수 있습니다.
                  </div>
                  <div className="mt-4 flex items-center gap-2">
                    <button
                      onClick={() => launchAgent(activeAgent || 'claude', false)}
                      className="rounded bg-primary px-3 py-1.5 text-[11px] font-bold text-white transition-colors hover:bg-primary/80"
                    >
                      이 슬롯에서 새 터미널 열기
                    </button>
                    <button
                      onClick={() => setIsTerminalMode(false)}
                      className="rounded border border-white/10 px-3 py-1.5 text-[11px] font-bold text-[#cccccc] transition-colors hover:bg-white/5"
                    >
                      선택 화면으로 돌아가기
                    </button>
                  </div>
                </div>
              </div>
            )}
          </div>

          {/* 터미널 한글 입력 및 단축어 바 */}
          <div className="p-2 border-t border-black/40 bg-[#252526] shrink-0 flex flex-col gap-2 z-10">
            <div className="flex gap-1.5 overflow-x-auto custom-scrollbar pb-0.5 opacity-80 hover:opacity-100 transition-opacity items-center">
              <button onClick={() => setShowShortcutEditor(true)} className="px-2 py-0.5 bg-primary/20 hover:bg-primary/40 text-primary rounded text-[10px] whitespace-nowrap border border-primary/30 font-bold transition-colors">✏️ 편집</button>
              {shortcuts.map((sc, i) => (
                <button key={i} onClick={() => handleSend(sc.cmd)} className="px-2 py-0.5 bg-[#3c3c3c] hover:bg-white/10 rounded text-[10px] whitespace-nowrap border border-white/5 transition-colors" title={sc.cmd}>
                  {sc.label}
                </button>
              ))}
            </div>
            <div className="flex gap-2 items-end relative">
              <textarea
                ref={inputRef}
                value={inputValue}
                onChange={e => setInputValue(e.target.value)}
                onContextMenu={e => {
                  // [WHY] 기본 메뉴(맥 WKWebView는 자동완성만 노출) 차단 후 커스텀 메뉴 오픈.
                  // 선택 여부를 이 시점에 스냅샷 — 메뉴 클릭 시 selectionStart/End는 유지되지만
                  // 포커스가 흔들려 빈 선택으로 읽히는 경우를 대비해 hasSel을 미리 저장.
                  e.preventDefault();
                  const el = inputRef.current;
                  const hasSel = !!el && el.selectionStart !== el.selectionEnd;
                  setInputCtxMenu({ x: e.clientX, y: e.clientY, hasSel });
                }}
                onCompositionStart={() => {
                  isComposingRef.current = true;
                }}
                onCompositionEnd={() => {
                  isComposingRef.current = false;
                }}
                onKeyDown={e => {
                  if (e.key === 'Enter' && !e.shiftKey) {
                    if (isComposingRef.current || e.nativeEvent.isComposing || e.nativeEvent.keyCode === 229) {
                      return;
                    }
                    // 엔터 키 입력 시 즉시 기본 줄바꿈 동작을 차단합니다.
                    e.preventDefault();
                    // 명령어를 즉시 전송합니다. (한글 입력 시에도 엔터 한 번으로 전송되도록 복원)
                    if (inputValue.trim()) {
                      handleSend(inputValue);
                      // 전송 후 입력창을 확실히 비웁니다.
                    }
                  }
                }}
                placeholder="터미널 명령어 전송 (한글 완벽 지원, 엔터:전송, 쉬프트+엔터:줄바꿈)..."
                rows={2}
                className="flex-1 bg-[#1e1e1e] border border-white/10 hover:border-white/30 rounded px-3 py-2 text-xs focus:outline-none focus:border-primary text-white resize-none custom-scrollbar leading-relaxed"
              />
              <SlashCommandMenu
                activeAgent={activeAgent}
                showSlashMenu={showSlashMenu}
                setShowSlashMenu={setShowSlashMenu}
                onSelect={(cmd) => setInputValue(cmd + ' ')}
              />
              <button
                onClick={() => handleSend(inputValue)}
                className="px-4 py-2 bg-primary/80 hover:bg-primary text-white rounded text-xs font-bold transition-colors shadow-sm"
              >
                전송
              </button>
            </div>
          </div>
        </div>
      )}

      {/* 터미널 우클릭 컨텍스트 메뉴 */}
      {ctxMenu && (
        <div
          className="fixed z-[9999] bg-[#2d2d2d] border border-white/20 rounded shadow-xl text-xs text-white min-w-[120px] py-1"
          style={{ left: ctxMenu.x, top: ctxMenu.y }}
          onMouseLeave={() => setCtxMenu(null)}
        >
          {/* [WHY] 조건부 렌더 금지 — TUI 마우스 리포팅 중엔 선택이 아예 안 생겨 selText가
              항상 빈 값 → 버튼이 영영 안 뜨던 사고(2026-07-04). 상시 표시 + 비활성 처리로 전환. */}
          <button
            disabled={!ctxMenu.selText}
            className={`w-full text-left px-4 py-1.5 transition-colors ${
              ctxMenu.selText ? 'hover:bg-white/10' : 'text-white/30 cursor-not-allowed'
            }`}
            onClick={async () => {
              // [WHY] 클릭 시점 getSelection() 재조회 금지 — 메뉴가 떠 있는 사이 TUI 응답으로
              // 선택이 지워지면 빈 문자열이 복사됨. 메뉴 오픈 시점 스냅샷(selText)을 사용.
              try {
                await copyTextToClipboard(ctxMenu.selText);
                // 복사 후엔 하이라이트가 사라져야 함 — 복원 금지 신호를 켠 뒤 해제.
                userClearedSelRef.current = true;
                selPosRef.current = null;
                termRef.current?.clearSelection();
              } catch (err) { console.error(err); }
              setCtxMenu(null);
            }}
          >
            복사
          </button>
          {!ctxMenu.selText && (
            <div className="px-4 py-1 text-[10px] text-white/40 border-t border-white/10">
              드래그로 텍스트를 선택한 뒤 우클릭하세요
            </div>
          )}
          <button
            className="w-full text-left px-4 py-1.5 hover:bg-white/10 transition-colors"
            onClick={async () => {
              try {
                const text = await readClipboardText();
                // [WHY] ws.send 직송 금지 — bracketed paste 모드를 우회해 TUI(claude CLI)에서
                // 멀티라인 붙여넣기가 줄 단위로 즉시 실행됨. term.paste()는 onData 경유로
                // \x1b[200~ 래핑을 적용한 뒤 같은 ws로 흘러간다.
                if (text) termRef.current?.paste(text);
              } catch (err) {
                console.error(err);
                // [WHY] 무음 실패 금지 — WebView2 클립보드 읽기 권한 거부 시 사용자가 원인을
                // 알 수 없던 사고(2026-07-04). 로컬 표시 전용 write라 pty로는 전송되지 않는다.
                termRef.current?.write('\r\n\x1b[33m[클립보드 읽기 실패 — 터미널 클릭 후 Ctrl+V(맥은 ⌘V)를 사용하세요]\x1b[0m\r\n');
              }
              setCtxMenu(null);
            }}
          >
            붙여넣기
          </button>
        </div>
      )}

      {/* 명령어 전송 입력창 우클릭 컨텍스트 메뉴 (맥 WKWebView 기본 메뉴 부재 보완) */}
      {inputCtxMenu && (
        <div
          className="fixed z-[9999] bg-[#2d2d2d] border border-white/20 rounded shadow-xl text-xs text-white min-w-[130px] py-1"
          style={{ left: inputCtxMenu.x, top: inputCtxMenu.y }}
          onMouseLeave={() => setInputCtxMenu(null)}
        >
          {/* [불변식] value는 inputValue(React 상태)로 제어됨 — 잘라내기/붙여넣기는 반드시 setInputValue로
              갱신하고, 재렌더 후 selectionStart/End를 requestAnimationFrame으로 복원해야 커서가 튀지 않음. */}
          <button
            disabled={!inputCtxMenu.hasSel}
            className={`w-full text-left px-4 py-1.5 transition-colors ${
              inputCtxMenu.hasSel ? 'hover:bg-white/10' : 'text-white/30 cursor-not-allowed'
            }`}
            onClick={async () => {
              const el = inputRef.current;
              if (el) {
                const sel = el.value.substring(el.selectionStart, el.selectionEnd);
                if (sel) { try { await copyTextToClipboard(sel); } catch (err) { console.error(err); } }
              }
              setInputCtxMenu(null);
            }}
          >
            복사
          </button>
          <button
            disabled={!inputCtxMenu.hasSel}
            className={`w-full text-left px-4 py-1.5 transition-colors ${
              inputCtxMenu.hasSel ? 'hover:bg-white/10' : 'text-white/30 cursor-not-allowed'
            }`}
            onClick={async () => {
              const el = inputRef.current;
              if (el) {
                const start = el.selectionStart, end = el.selectionEnd;
                const sel = el.value.substring(start, end);
                if (sel) {
                  try { await copyTextToClipboard(sel); } catch (err) { console.error(err); }
                  const next = el.value.slice(0, start) + el.value.slice(end);
                  setInputValue(next);
                  requestAnimationFrame(() => { el.focus(); el.setSelectionRange(start, start); });
                }
              }
              setInputCtxMenu(null);
            }}
          >
            잘라내기
          </button>
          <button
            className="w-full text-left px-4 py-1.5 hover:bg-white/10 transition-colors"
            onClick={async () => {
              const el = inputRef.current;
              try {
                const text = await readClipboardText();
                if (el && text) {
                  const start = el.selectionStart, end = el.selectionEnd;
                  const next = el.value.slice(0, start) + text + el.value.slice(end);
                  setInputValue(next);
                  const caret = start + text.length;
                  requestAnimationFrame(() => { el.focus(); el.setSelectionRange(caret, caret); });
                }
              } catch (err) {
                // [WHY] 무음 실패 금지 — 클립보드 읽기 권한 거부 시 ⌘V 안내 (터미널 메뉴와 동일 정책).
                console.error(err);
              }
              setInputCtxMenu(null);
            }}
          >
            붙여넣기
          </button>
          <div className="border-t border-white/10 my-0.5" />
          <button
            className="w-full text-left px-4 py-1.5 hover:bg-white/10 transition-colors"
            onClick={() => {
              const el = inputRef.current;
              if (el) { el.focus(); el.select(); }
              setInputCtxMenu(null);
            }}
          >
            전체 선택
          </button>
        </div>
      )}

      {/* ── 에이전트 선택 카드 — terminal/AgentSelectCards로 분리 (2026-07-15) ── */}
      {/* [근본수정 2026-07-15] 실행 감지(isServerRunning) 시 미부착 슬롯에도 모니터링 표시.
          기존엔 자동 감지가 showMonitor만 켜고 뷰가 isTerminalMode 안에만 있어 도달 불가 —
          "선택 카드 건너뛰고 모니터링 표시"(2026-03-08)가 코드상 불가능했던 회귀. */}
      {!isTerminalMode && (
        <div className="flex-1 min-w-0 flex flex-col min-h-0">
          {showMonitor && isServerRunning && (
            <MonitorView
              activeAgent={activeAgent} agentStatus={agentStatus}
              statusColor={statusColor} statusDot={statusDot}
              chainSteps={chainSteps} chainRequest={chainRequest}
              liveTask={liveTask} inProgressTask={inProgressTask}
              myPendingTasks={myPendingTasks} hiveActivity={hiveActivity}
            />
          )}
          <AgentSelectCards logs={slotLogs} onLaunch={launchAgent} />
        </div>
      )}

      {/* 단축어 편집 모달 팝업 — 별도 컴포넌트로 분리 */}
      {showShortcutEditor && (
        <ShortcutEditModal
          shortcuts={shortcuts}
          saveShortcuts={saveShortcuts}
          onClose={() => setShowShortcutEditor(false)}
        />
      )}
    </div>
  );
}
