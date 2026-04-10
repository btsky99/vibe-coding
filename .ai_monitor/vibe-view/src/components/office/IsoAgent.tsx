/**
 * ------------------------------------------------------------------------
 * FILE: IsoAgent.tsx
 * DESCRIPTION: 아이소메트릭 오피스 에이전트 캐릭터 SVG 컴포넌트.
 *              LEGO 스타일 조립 구조 (Parts-based Composition).
 * REVISION HISTORY:
 * - 2026-04-10 Gemini: LEGO 조립형 모듈 구조로 전면 개편
 * ------------------------------------------------------------------------
 */

export type AgentStatus = 'idle' | 'working' | 'meeting' | 'error';

export interface IsoAgentProps {
  agentType: 'claude' | 'gemini' | 'codex' | 'ceo' | 'unknown';
  name: string;
  status: AgentStatus;
  x?: number;
  y?: number;
  onClick?: () => void;
  level?: number;
  totalXp?: number;
  taskCount?: number;
}

const LED_COLOR: Record<AgentStatus, string> = {
  idle:    '#3b82f6',
  working: '#22c55e',
  meeting: '#f97316',
  error:   '#ef4444',
};

const ANIM_CLASS: Record<AgentStatus, string> = {
  idle:    'anim-bob',
  working: 'anim-lean',
  meeting: 'anim-nod',
  error:   'anim-shake',
};

// ─── LEGO 파츠 (Parts) ───

function PartShadow({ rx = 14, ry = 6, opacity = 0.15 }: { rx?: number; ry?: number; opacity?: number }) {
  return <ellipse cx="20" cy="54" rx={rx} ry={ry} fill="black" opacity={opacity} />;
}

function PartHumanHead({ hairColor = "#451a03", skinColor = "#ffdbac" }) {
  return (
    <g>
      <ellipse cx="20" cy="14" rx="10" ry="11" fill="#fde047" opacity="0.2" transform="translate(0, -2)" />
      <ellipse cx="20" cy="14" rx="9" ry="10" fill={skinColor} stroke="#d4a87a" strokeWidth="0.5" />
      <path d="M11 11 Q11 2 20 2 Q29 2 29 11 L29 14 Q25 10 20 10 Q15 10 11 14 Z" fill={hairColor} />
      <path d="M14 13 L18 13" stroke="#1e293b" strokeWidth="1" fill="none" />
      <path d="M22 13 L26 13" stroke="#1e293b" strokeWidth="1" fill="none" />
      <path d="M18 13 L22 13" stroke="#1e293b" strokeWidth="0.5" fill="none" />
      <path d="M18 19 Q20 21 22 19" stroke="#92400e" strokeWidth="1" fill="none" />
    </g>
  );
}

function PartRobotHead({ shape, color, accent, ledColor }: { shape: string; color: string; accent: string; ledColor: string }) {
  return (
    <g>
      {shape === 'square' && <rect x="8" y="4" width="24" height="20" rx="4" fill={color} stroke={accent} strokeWidth="2" />}
      {shape === 'cylinder' && <ellipse cx="20" cy="14" rx="14" ry="10" fill={color} stroke={accent} strokeWidth="2" />}
      {shape === 'diamond' && <polygon points="20,2 34,14 20,26 6,14" fill={color} stroke={accent} strokeWidth="2" />}
      <rect x="14" y="10" width="12" height="4" rx="2" fill="#000" />
      <rect x="16" y="11" width="8" height="2" rx="1" fill={ledColor} />
    </g>
  );
}

function PartBody({ type, color, accent, label }: { type: 'suit' | 'robot'; color: string; accent: string; label?: string }) {
  if (type === 'suit') {
    return (
      <g>
        <rect x="11" y="24" width="18" height="22" rx="4" fill={color} stroke="#1e293b" strokeWidth="1" />
        <path d="M11 24 L20 46 L29 24 Z" fill="#1e293b" opacity="0.2" />
        <path d="M16 24 L20 32 L24 24" fill="white" />
        <path d="M19 24 L20 34 L21 24" fill="#e11d48" />
        <rect x="8" y="26" width="5" height="16" rx="2" fill={color} stroke="#1e293b" strokeWidth="0.5" transform="rotate(5, 10, 26)" />
        <rect x="27" y="26" width="5" height="16" rx="2" fill={color} stroke="#1e293b" strokeWidth="0.5" transform="rotate(-5, 30, 26)" />
      </g>
    );
  }
  return (
    <g>
      <rect x="10" y="26" width="20" height="18" rx="4" fill={color} stroke={accent} strokeWidth="2" />
      {label && <text x="20" y="40" textAnchor="middle" fontSize="10" fontWeight="bold" fill="white" opacity="0.8">{label}</text>}
    </g>
  );
}

function PartLegs({ type, color }: { type: 'pants' | 'wheels'; color: string }) {
  if (type === 'pants') {
    return (
      <g>
        <rect x="13" y="44" width="6" height="12" rx="1.5" fill={color} />
        <rect x="21" y="44" width="6" height="12" rx="1.5" fill={color} />
        <path d="M13 54 Q13 58 19 58 L19 54 Z" fill="#0f172a" />
        <path d="M21 54 Q21 58 27 58 L27 54 Z" fill="#0f172a" />
      </g>
    );
  }
  return <rect x="13" y="44" width="14" height="6" rx="3" fill="#334155" />;
}

function PartAccessory({ type }: { type: 'crown' | 'none' }) {
  if (type === 'crown') {
    return (
      <g>
        <path d="M13 6 L15 2 L17 5 L20 1 L23 5 L25 2 L27 6 L27 8 L13 8 Z" fill="#fbbf24" stroke="#d97706" strokeWidth="0.5" />
        <circle cx="20" cy="5" r="1.5" fill="#f59e0b" />
      </g>
    );
  }
  return null;
}

// ─── 조립기 (Assemblers) ───

function CeoCharacter({ status }: { status: AgentStatus }) {
  return (
    <g className={ANIM_CLASS[status]}>
      <PartShadow />
      <PartLegs type="pants" color="#1e293b" />
      <PartBody type="suit" color="#334155" accent="#1e293b" />
      <PartHumanHead />
      <PartAccessory type="crown" />
    </g>
  );
}

function RobotCharacter({ config, status, ledColor }: { config: any; status: AgentStatus; ledColor: string }) {
  return (
    <g className={ANIM_CLASS[status]}>
      <PartShadow rx={12} ry={5} />
      <PartLegs type="wheels" color="#334155" />
      <PartBody type="robot" color={config.bodyColor} accent={config.accentColor} label={config.label} />
      <PartRobotHead shape={config.headShape} color={config.bodyColor} accent={config.accentColor} ledColor={ledColor} />
    </g>
  );
}

// ─── 메인 컴포넌트 ───

const AGENT_CONFIG = {
  claude:  { headShape: 'square' as const,   bodyColor: '#2d1f4a', accentColor: '#a78bfa', label: 'C' },
  gemini:  { headShape: 'cylinder' as const, bodyColor: '#0f2e22', accentColor: '#34d399', label: 'G' },
  codex:   { headShape: 'diamond' as const,  bodyColor: '#0f2535', accentColor: '#22d3ee', label: '/' },
  unknown: { headShape: 'square' as const,   bodyColor: '#1a2435', accentColor: '#64748b', label: '?' },
  ceo:     { headShape: 'square' as const,   bodyColor: '#4a3520', accentColor: '#fbbf24', label: '★' },
};

// 레벨에 따른 뱃지 색상
const LEVEL_COLOR = (level: number): string => {
  if (level >= 10) return '#fbbf24'; // 금
  if (level >= 7)  return '#a78bfa'; // 보라
  if (level >= 4)  return '#22d3ee'; // 청록
  return '#94a3b8'; // 회색
};

// 다음 레벨까지 필요한 XP 계산 (level = floor(sqrt(xp/100)))
const xpForLevel = (level: number): number => level * level * 100;

export function IsoAgent({ agentType, name, status, x = 0, y = 0, onClick, level, totalXp, taskCount }: IsoAgentProps) {
  const config = AGENT_CONFIG[agentType] || AGENT_CONFIG.unknown;
  const ledColor = LED_COLOR[status];
  const hasStats = level != null && level > 0;
  const currentXp = totalXp ?? 0;
  const nextLevelXp = hasStats ? xpForLevel(level! + 1) : 100;
  const prevLevelXp = hasStats ? xpForLevel(level!) : 0;
  const xpProgress = hasStats ? Math.min(1, (currentXp - prevLevelXp) / Math.max(1, nextLevelXp - prevLevelXp)) : 0;

  return (
    <g transform={`translate(${x}, ${y})`} onClick={onClick} style={{ cursor: 'pointer' }}>
      {/* 모든 에이전트는 로봇 — CEO도 금색 로봇 + 왕관 */}
      <RobotCharacter config={config} status={status} ledColor={ledColor} />
      {agentType === 'ceo' && <PartAccessory type="crown" />}

      {/* 레벨 뱃지 — 캐릭터 머리 위 (큰 사이즈) */}
      {hasStats && (
        <g transform="translate(20, -14)">
          {/* 글로우 이펙트 */}
          <ellipse cx="0" cy="-2" rx="20" ry="12" fill={LEVEL_COLOR(level!)} fillOpacity="0.15" />
          {/* 뱃지 배경 — 둥근 필 형태 */}
          <rect x="-18" y="-12" width="36" height="20" rx="10" fill={LEVEL_COLOR(level!)} stroke="white" strokeWidth="1.5" />
          {/* 별 아이콘 (레벨 7 이상) */}
          {level! >= 7 && <text x="-10" y="4" fontSize="8" fill="white">★</text>}
          <text x={level! >= 7 ? 4 : 0} y="4" textAnchor="middle" fontSize="11" fontWeight="900" fill="white">
            Lv.{level}
          </text>
        </g>
      )}

      {/* 이름표 + XP 바 */}
      <g transform="translate(20, 68)">
        <rect x="-30" y="-9" width="60" height={hasStats ? 26 : 16} rx="5" fill="rgba(0,0,0,0.7)" stroke="rgba(255,255,255,0.1)" strokeWidth="0.5" />
        <text x="0" y="3" textAnchor="middle" fontSize="10" fontWeight="bold" fill="white">{name || agentType}</text>
        {/* XP 진행 바 */}
        {hasStats && (
          <g transform="translate(0, 9)">
            <rect x="-24" y="0" width="48" height="5" rx="2.5" fill="rgba(255,255,255,0.12)" />
            <rect x="-24" y="0" width={Math.max(3, 48 * xpProgress)} height="5" rx="2.5" fill={LEVEL_COLOR(level!)} />
            <text x="0" y="-1" textAnchor="middle" fontSize="6" fill="rgba(255,255,255,0.4)">{currentXp} XP</text>
          </g>
        )}
      </g>
    </g>
  );
}

export function detectAgentType(name: string): IsoAgentProps['agentType'] {
  const n = name.toLowerCase();
  if (n.includes('claude')) return 'claude';
  if (n.includes('gemini')) return 'gemini';
  if (n.includes('codex')) return 'codex';
  if (n.includes('ceo')) return 'ceo';
  return 'unknown';
}
