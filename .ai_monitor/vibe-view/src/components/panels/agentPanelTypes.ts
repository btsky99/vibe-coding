/**
 * ------------------------------------------------------------------------
 * 📄 파일명: agentPanelTypes.ts
 * 📝 설명: AgentPanel 관련 타입 정의, 상수, 유틸리티 함수.
 *          AgentPanel.tsx에서 분리하여 타입/상수/유틸을 단일 파일로 관리합니다.
 *
 * REVISION HISTORY:
 * - 2026-03-22 Claude: AgentPanel.tsx에서 분리 — 타입/상수/유틸 담당
 * ------------------------------------------------------------------------
 */

// ─── 타입 정의 ──────────────────────────────────────────────────────────────

export type AgentStatus   = 'idle' | 'running' | 'done' | 'error' | 'unavailable';
export type CliChoice     = 'orchestrate' | 'auto' | 'claude' | 'antigravity' | 'codex';
export type ActiveTab     = 'workflow' | 'terminal' | 'thoughts' | 'history' | 'orchestrator' | 'hive';

// 하이브 활동 이벤트 타입 — /api/hive/activity 응답 형식
export interface HiveEvent {
  timestamp: string;
  agent: string;
  terminal_id?: string;   // 로그를 남긴 터미널 ID (T1~T8, T0=미설정)
  type: 'memory_read' | 'memory_write' | 'orchestrate' | 'message' | 'heal' | 'hive_ctx' | 'session';
  task: string;
}

// ─── 워크플로우 단계 타입 ─────────────────────────────────────────────────────
export type WorkflowStage = 'idle' | 'analyzing' | 'modifying' | 'verifying' | 'done' | 'error';

/** 출력 텍스트 한 줄을 보고 워크플로우 단계를 추론합니다.
 *  키워드 기반 휴리스틱: Claude Code의 도구 호출 패턴을 우선 감지 */
export function detectStage(line: string): WorkflowStage | null {
  const l = line.toLowerCase();

  // 수정 (Edit/Write/Create 도구 호출) — 분석보다 먼저 체크
  if (
    l.startsWith('● edit') || l.startsWith('● write') || l.startsWith('● create') ||
    l.includes('editfile') || l.includes('writefile') || l.includes('createfile') ||
    l.includes('notebookedit') ||
    l.includes(' edit ') || l.includes('수정 중') || l.includes('파일 수정') ||
    l.includes('코드 수정') || l.includes('변경 중')
  ) return 'modifying';

  // 검증 (Bash/Run/Test 도구 호출)
  if (
    l.startsWith('● bash') || l.startsWith('● run') ||
    l.includes('running test') || l.includes('npm test') || l.includes('pytest') ||
    l.includes('검증 중') || l.includes('테스트 중') || l.includes('빌드 중') ||
    l.includes('실행 중...') || (l.includes('bash') && l.includes('tool'))
  ) return 'verifying';

  // 분석 (Read/Glob/Grep/Search 도구 호출)
  if (
    l.startsWith('● read') || l.startsWith('● glob') || l.startsWith('● grep') ||
    l.startsWith('● search') || l.startsWith('● agent') ||
    l.includes('readfile') || l.includes('분석 중') || l.includes('파악 중') ||
    l.includes('코드 분석') || l.includes('let me read') || l.includes('looking at') ||
    l.includes('확인 중') || l.includes('조사 중')
  ) return 'analyzing';

  // 완료
  if (
    l.includes('완료') || l.includes('✓') || l.includes('모든 작업') ||
    l.includes('성공적') || (l.includes('done') && l.length < 30)
  ) return 'done';

  // 오류/이슈
  if (
    l.startsWith('[오류]') || l.startsWith('error:') || l.includes('✗') ||
    l.includes('실패') || l.includes('오류 발생')
  ) return 'error';

  return null;
}


// ─── 터미널별 상태 타입 ──────────────────────────────────────────────────────
export interface TerminalState {
  status: 'idle' | 'running' | 'done' | 'error';
  task: string;           // 마지막/현재 실행 지시
  cli: string;            // claude | antigravity | ''
  run_id: string;
  ts: string;             // ISO 타임스탬프
  last_line: string;      // 마지막 출력 줄
  pipeline_stage?: string; // 서버에서 직접 받는 파이프라인 단계 (idle|analyzing|modifying|verifying|done|error)
  external?: boolean;     // true = 외부 Antigravity 세션 (다른 프로젝트) — UI에서 숨김
  routing_reason?: string; // 모델 자동 선택 근거 (예: "코드 작업 감지 (수정)")
}

export interface CodexModelPolicy {
  main: string;
  background: string;
}

export interface CodexSetupState {
  enabled: boolean;
  bootPrompt: string;
  lastPath: string;
}

export interface ToolStatusInfo {
  installed: boolean;
  path: string;
  version: string;
}

export interface AgentRun {
  id: string;
  task: string;
  cli: string;
  status: 'done' | 'error' | 'stopped';
  ts: string;
  output_preview?: string[];
}

export interface OutputLine {
  text: string;
  ts: string;
  type: 'output' | 'started' | 'done' | 'error' | 'stopped';
}

export interface ThoughtEntry {
  id: number;
  time: string;
  agent: string;
  text: string;
}

// ─── 상수 ───────────────────────────────────────────────────────────────────

export const CLI_LABELS: Record<CliChoice, string> = {
  orchestrate: '오케스트레이션',
  auto:   '🤖 Auto (자동 선택)',
  claude: '⚡ Claude Code',
  antigravity: '✨ Antigravity CLI',
  codex:  '🟠 Codex CLI',
};

export const ORCHESTRATION_LABEL = '오케스트레이션';
export const AUTO_PREVIEW_INTENT_REGEX = /(보여줘|보여주|열어줘|띄워줘|팝업|show|open|preview)/i;
export const INLINE_PATH_REGEX = /([A-Za-z]:[\\/][^\s"'`()<>]+|\/[^\s"'`()<>]+|(?:\.{1,2}[\\/]|[A-Za-z_.-][A-Za-z0-9_.-]*[\\/])[^\s"'`()<>]+)/g;

export const STATUS_COLORS: Record<AgentStatus, string> = {
  idle:        'text-white/40',
  running:     'text-yellow-400',
  done:        'text-green-400',
  error:       'text-red-400',
  unavailable: 'text-white/20',
};

export const STATUS_LABELS: Record<AgentStatus, string> = {
  idle:        '대기 중',
  running:     '실행 중',
  done:        '완료',
  error:       '오류',
  unavailable: 'CLI 미설치',
};

export const EMPTY_CODEX_MODEL_POLICY: CodexModelPolicy = {
  main: '',
  background: '',
};

export const EMPTY_CODEX_SETUP: CodexSetupState = {
  enabled: true,
  bootPrompt: '',
  lastPath: '',
};

export const EMPTY_TOOL_STATUS: ToolStatusInfo = {
  installed: false,
  path: '',
  version: '',
};

export function readCodexModelPolicy(config: unknown): CodexModelPolicy {
  const source = (config && typeof config === 'object') ? config as Record<string, unknown> : {};
  const nested = (source.codex_models && typeof source.codex_models === 'object')
    ? source.codex_models as Record<string, unknown>
    : {};
  const legacyMain = typeof source.codex_main_model === 'string' ? source.codex_main_model : '';
  const legacyBackground = typeof source.codex_background_model === 'string' ? source.codex_background_model : '';

  return {
    main: typeof nested.main === 'string' ? nested.main : legacyMain,
    background: typeof nested.background === 'string' ? nested.background : legacyBackground,
  };
}

export function readCodexSetup(config: unknown): CodexSetupState {
  const source = (config && typeof config === 'object') ? config as Record<string, unknown> : {};
  const enabled = typeof source.codex_enabled === 'boolean' ? source.codex_enabled : true;
  const bootPrompt = typeof source.codex_boot_prompt === 'string' ? source.codex_boot_prompt : '';
  const lastPath = typeof source.last_path === 'string' ? source.last_path : '';

  return {
    enabled,
    bootPrompt,
    lastPath,
  };
}

export function stripPreviewPath(rawPath: string): string {
  const trimmed = rawPath.trim().replace(/^[("'`[{<]+/, '').replace(/[),\].!?'"`}>]+$/, '');
  if (!trimmed) return '';

  const withoutHashLine = trimmed.replace(/#L\d+(?:C\d+)?$/i, '');
  const lineSuffixMatch = withoutHashLine.match(/:(\d+)(?::\d+)?$/);
  if (!lineSuffixMatch) return withoutHashLine;

  const colonIndex = lineSuffixMatch.index ?? -1;
  const lastSlashIndex = Math.max(withoutHashLine.lastIndexOf('/'), withoutHashLine.lastIndexOf('\\'));
  return colonIndex > lastSlashIndex ? withoutHashLine.slice(0, colonIndex) : withoutHashLine;
}

export function basenameLike(value: string): string {
  const normalized = stripPreviewPath(value).replace(/\\/g, '/');
  const parts = normalized.split('/');
  return parts[parts.length - 1] || normalized;
}

export function compactCommandPreview(command: string): string {
  const singleLine = command.replace(/\s+/g, ' ').trim();
  if (!singleLine) return '';
  return singleLine.length > 72 ? `${singleLine.slice(0, 69)}...` : singleLine;
}

export function summarizeOutputText(raw: string): string {
  const line = raw.replace(/\s+/g, ' ').trim();
  if (!line) return '';

  if (/^[-_=~.]{6,}$/.test(line) || /^[─━]{6,}$/.test(line)) return '';
  if (/^(thinking|working|processing)\.{0,3}$/i.test(line)) return '';

  const inspectMatch = line.match(/(?:Read|Glob|Grep|Search)\(([^)]+)\)/i);
  if (inspectMatch) {
    return `Inspect ${basenameLike(inspectMatch[1])}`;
  }

  const updateMatch = line.match(/(?:Edit|Write|Create)\(([^)]+)\)/i);
  if (updateMatch) {
    return `Update ${basenameLike(updateMatch[1])}`;
  }

  const commandMatch = line.match(/(?:Bash|Shell)\(([^)]+)\)/i);
  if (commandMatch) {
    return `Run ${compactCommandPreview(commandMatch[1])}`;
  }

  const patchMatch = line.match(/apply_patch/i);
  if (patchMatch) {
    return 'Apply patch';
  }

  const openPathMatch = line.match(/([A-Za-z]:[\\/][^\s"'`()<>]+|\/[^\s"'`()<>]+)/);
  if (/^(opening|reading|checking|reviewing|inspecting)\b/i.test(line) && openPathMatch) {
    return `Inspect ${basenameLike(openPathMatch[1])}`;
  }

  return line;
}

export function buildVisibleOutputLines(lines: OutputLine[], compact: boolean): OutputLine[] {
  if (!compact) return lines;

  const visible: OutputLine[] = [];
  let lastOutputText = '';

  for (const line of lines) {
    const nextText = line.type === 'output' ? summarizeOutputText(line.text) : line.text.trim();
    if (!nextText) continue;

    if (line.type === 'output') {
      if (nextText === lastOutputText) continue;
      lastOutputText = nextText;
    } else {
      lastOutputText = '';
    }

    visible.push({ ...line, text: nextText });
  }

  return visible;
}

export function extractAutoPreviewPath(line: string): string | null {
  const toolPathMatch = line.match(/(?:Read|Edit|Write|Create)\s*\(([^)\n]{1,260})\)/i);
  if (toolPathMatch) {
    const candidate = stripPreviewPath(toolPathMatch[1]);
    if (candidate && !candidate.includes('*')) {
      return candidate;
    }
  }

  for (const match of line.matchAll(INLINE_PATH_REGEX)) {
    const candidate = stripPreviewPath(match[0]);
    const protocolProbe = line.slice(Math.max(0, (match.index ?? 0) - 8), match.index ?? 0);
    if (!candidate || (candidate.startsWith('/') && /https?:$/i.test(protocolProbe))) {
      continue;
    }
    return candidate;
  }

  return null;
}

// ─── Props ──────────────────────────────────────────────────────────────────

export interface AgentPanelProps {
  /** App.tsx에 에이전트 실행 상태를 알리는 콜백 (ActivityBar 배지 표시용) */
  onStatusChange?: (running: boolean) => void;
  onOpenFilePath?: (path: string) => void;
}
