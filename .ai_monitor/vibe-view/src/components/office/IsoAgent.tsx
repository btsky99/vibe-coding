/**
 * ------------------------------------------------------------------------
 * FILE: IsoAgent.tsx
 * DESCRIPTION: 아이소메트릭 오피스 에이전트 캐릭터 SVG 컴포넌트.
 *              CEO(사람) + LLM 에이전트(로봇) 캐릭터.
 * REVISION HISTORY:
 * - 2026-04-10 Gemini: SVG 전용 컴포넌트로 재설계 (Task 5 완료)
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

/* ── CEO 사람 캐릭터 ── */
function CeoCharacter({ status }: { status: AgentStatus }) {
  return (
    <g className={ANIM_CLASS[status]}>
      {/* 머리 */}
      <ellipse cx="20" cy="12" rx="10" ry="11" fill="#f5c5a3" stroke="#d4a87a" strokeWidth="1" />
      {/* 정장 몸통 */}
      <rect x="12" y="23" width="16" height="22" rx="2" fill="#1e3a5f" />
      {/* 넥타이 */}
      <polygon points="20,26 18.5,28 20,34 21.5,28" fill="#c0392b" />
      {/* 왕관 */}
      <polygon points="12,5 15,1 18,4 20,0 22,4 25,1 28,5" fill="#f59e0b" stroke="#d97706" strokeWidth="0.5" />
      {/* 다리 */}
      <rect x="13" y="45" width="6" height="13" rx="2" fill="#1a2f4a" />
      <rect x="21" y="45" width="6" height="13" rx="2" fill="#1a2f4a" />
    </g>
  );
}

/* ── 로봇 바디 ── */
function RobotBody({
  headShape,
  bodyColor,
  accentColor,
  ledColor,
  status,
  label,
}: {
  headShape: 'square' | 'diamond' | 'cylinder';
  bodyColor: string;
  accentColor: string;
  ledColor: string;
  status: AgentStatus;
  label: string;
}) {
  return (
    <g className={ANIM_CLASS[status]}>
      {/* 머리 */}
      {headShape === 'square' && <rect x="8" y="4" width="24" height="20" rx="4" fill={bodyColor} stroke={accentColor} strokeWidth="2" />}
      {headShape === 'cylinder' && <ellipse cx="20" cy="14" rx="14" ry="10" fill={bodyColor} stroke={accentColor} strokeWidth="2" />}
      {headShape === 'diamond' && <polygon points="20,2 34,14 20,26 6,14" fill={bodyColor} stroke={accentColor} strokeWidth="2" />}

      {/* 눈/LED */}
      <rect x="14" y="10" width="12" height="4" rx="2" fill="#000" />
      <rect x="16" y="11" width="8" height="2" rx="1" fill={ledColor} />

      {/* 몸통 */}
      <rect x="10" y="26" width="20" height="18" rx="4" fill={bodyColor} stroke={accentColor} strokeWidth="2" />
      <text x="20" y="40" textAnchor="middle" fontSize="10" fontWeight="bold" fill="white" opacity="0.8">{label}</text>

      {/* 다리/바퀴 */}
      <rect x="13" y="44" width="14" height="6" rx="3" fill="#334155" />
    </g>
  );
}

const AGENT_CONFIG = {
  claude:  { headShape: 'square' as const,   bodyColor: '#2d1f4a', accentColor: '#a78bfa', label: 'C' },
  gemini:  { headShape: 'cylinder' as const, bodyColor: '#0f2e22', accentColor: '#34d399', label: 'G' },
  codex:   { headShape: 'diamond' as const,  bodyColor: '#0f2535', accentColor: '#22d3ee', label: '/' },
  unknown: { headShape: 'square' as const,   bodyColor: '#1a2435', accentColor: '#64748b', label: '?' },
  ceo:     { headShape: 'square' as const,   bodyColor: '#1e3a5f', accentColor: '#f59e0b', label: '★' },
};

export function IsoAgent({ agentType, name, status, x = 0, y = 0, onClick }: IsoAgentProps) {
  const config = AGENT_CONFIG[agentType] || AGENT_CONFIG.unknown;

  return (
    <g transform={`translate(${x}, ${y})`} onClick={onClick} style={{ cursor: 'pointer' }}>
      <ellipse cx="20" cy="52" rx="12" ry="5" fill="black" opacity="0.2" />
      {agentType === 'ceo' ? (
        <CeoCharacter status={status} />
      ) : (
        <RobotBody
          headShape={config.headShape}
          bodyColor={config.bodyColor}
          accentColor={config.accentColor}
          ledColor={LED_COLOR[status]}
          status={status}
          label={config.label}
        />
      )}
      <g transform="translate(20, 68)">
        <rect x="-25" y="-8" width="50" height="14" rx="4" fill="rgba(0,0,0,0.6)" />
        <text x="0" y="3" textAnchor="middle" fontSize="9" fontWeight="bold" fill="white">{name || agentType}</text>
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
