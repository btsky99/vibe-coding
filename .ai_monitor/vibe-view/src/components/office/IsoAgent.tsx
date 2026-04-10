/**
 * ------------------------------------------------------------------------
 * FILE: IsoAgent.tsx
 * DESCRIPTION: 아이소메트릭 오피스 에이전트 캐릭터 SVG 컴포넌트.
 *              CEO(사람) + LLM 에이전트(로봇) 캐릭터.
 * REVISION HISTORY:
 * - 2026-04-10 Claude: 최초 생성 — 아이소메트릭 오피스 재설계
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

/* ── LED 색상 매핑 ── */
const LED_COLOR: Record<AgentStatus, string> = {
  idle:    '#3b82f6',
  working: '#22c55e',
  meeting: '#f97316',
  error:   '#ef4444',
};

/* ── 애니메이션 클래스 매핑 ── */
const ANIM_CLASS: Record<AgentStatus, string> = {
  idle:    'anim-bob',
  working: 'anim-lean',
  meeting: 'anim-nod',
  error:   'anim-shake',
};

/* ── CEO 사람 캐릭터 ── */
function CeoCharacter({ status }: { status: AgentStatus }) {
  return (
    <svg width="40" height="60" viewBox="0 0 40 60" className={ANIM_CLASS[status]}>
      {/* 머리 */}
      <ellipse cx="20" cy="12" rx="10" ry="11" fill="#f5c5a3" stroke="#d4a87a" strokeWidth="1" />
      {/* 머리카락 */}
      <path d="M10,10 Q12,2 20,2 Q28,2 30,10 Q28,6 20,6 Q12,6 10,10Z" fill="#3d2010" />
      {/* 눈 */}
      <circle cx="16" cy="12" r="1.5" fill="#1a1a2e" />
      <circle cx="24" cy="12" r="1.5" fill="#1a1a2e" />
      {/* 눈 하이라이트 */}
      <circle cx="16.5" cy="11.5" r="0.5" fill="white" />
      <circle cx="24.5" cy="11.5" r="0.5" fill="white" />
      {/* 입 (상태별) */}
      {status === 'error'
        ? <path d="M16,17 Q20,15 24,17" stroke="#c0392b" strokeWidth="1" fill="none" />
        : <path d="M16,17 Q20,19 24,17" stroke="#c0392b" strokeWidth="1" fill="none" />
      }
      {/* 정장 몸통 */}
      <rect x="12" y="23" width="16" height="22" rx="2" fill="#1e3a5f" />
      {/* 와이셔츠 */}
      <polygon points="20,23 17,28 20,32 23,28" fill="white" />
      {/* 넥타이 */}
      <polygon points="20,26 18.5,28 20,34 21.5,28" fill="#c0392b" />
      {/* 왕관 (CEO 전용) */}
      <polygon points="12,5 15,1 18,4 20,0 22,4 25,1 28,5" fill="#f59e0b" stroke="#d97706" strokeWidth="0.5" />
      {/* 팔 */}
      <rect x="6" y="24" width="6" height="16" rx="3" fill="#1e3a5f" />
      <rect x="28" y="24" width="6" height="16" rx="3" fill="#1e3a5f" />
      {/* 손 */}
      <circle cx="9" cy="41" r="3" fill="#f5c5a3" />
      <circle cx="31" cy="41" r="3" fill="#f5c5a3" />
      {/* 다리 */}
      <rect x="13" y="45" width="6" height="13" rx="2" fill="#1a2f4a" />
      <rect x="21" y="45" width="6" height="13" rx="2" fill="#1a2f4a" />
      {/* 신발 */}
      <ellipse cx="16" cy="58" rx="5" ry="2.5" fill="#0f1923" />
      <ellipse cx="24" cy="58" rx="5" ry="2.5" fill="#0f1923" />
    </svg>
  );
}

/* ── 공통 로봇 바디 ── */
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
    <svg width="40" height="56" viewBox="0 0 40 56" className={ANIM_CLASS[status]}>
      {/* ── 머리 (형태별) ── */}
      {headShape === 'square' && (
        <g>
          {/* 네모 머리 */}
          <rect x="10" y="2" width="20" height="18" rx="3" fill={bodyColor} stroke={accentColor} strokeWidth="1.5" />
          {/* 안테나 */}
          <line x1="20" y1="2" x2="20" y2="-4" stroke={accentColor} strokeWidth="1.5" />
          <circle cx="20" cy="-5" r="2.5" fill={ledColor} />
          {/* LED 눈 */}
          <rect x="13" y="8" width="5" height="3" rx="1" fill={ledColor} className="anim-blink" />
          <rect x="22" y="8" width="5" height="3" rx="1" fill={ledColor} className="anim-blink" />
          {/* 입 그릴 */}
          <rect x="13" y="14" width="14" height="2" rx="1" fill={accentColor} opacity="0.5" />
          <rect x="15" y="14" width="2" height="2" fill={ledColor} opacity="0.6" />
          <rect x="19" y="14" width="2" height="2" fill={ledColor} opacity="0.6" />
          <rect x="23" y="14" width="2" height="2" fill={ledColor} opacity="0.6" />
        </g>
      )}
      {headShape === 'diamond' && (
        <g>
          {/* 다이아몬드 머리 */}
          <polygon points="20,2 32,11 20,20 8,11" fill={bodyColor} stroke={accentColor} strokeWidth="1.5" />
          {/* LED 눈 */}
          <circle cx="15" cy="11" r="2" fill={ledColor} className="anim-blink" />
          <circle cx="25" cy="11" r="2" fill={ledColor} className="anim-blink" />
          {/* 상단 보석 */}
          <polygon points="20,2 23,7 20,5 17,7" fill={ledColor} opacity="0.8" />
        </g>
      )}
      {headShape === 'cylinder' && (
        <g>
          {/* 실린더 머리 */}
          <ellipse cx="20" cy="6" rx="11" ry="4" fill={accentColor} stroke={bodyColor} strokeWidth="1" />
          <rect x="9" y="6" width="22" height="14" fill={bodyColor} stroke={accentColor} strokeWidth="1" />
          <ellipse cx="20" cy="20" rx="11" ry="4" fill={bodyColor} stroke={accentColor} strokeWidth="1" />
          {/* LED 눈 */}
          <circle cx="15" cy="13" r="2.5" fill={ledColor} className="anim-blink" />
          <circle cx="25" cy="13" r="2.5" fill={ledColor} className="anim-blink" />
          {/* </> 로고 */}
          <text x="20" y="10" textAnchor="middle" fontSize="5" fill={ledColor} fontFamily="monospace" opacity="0.8">
            {`</>`}
          </text>
        </g>
      )}

      {/* ── 몸통 ── */}
      <rect x="10" y="22" width="20" height="20" rx="3" fill={bodyColor} stroke={accentColor} strokeWidth="1" />
      {/* 가슴 로고 */}
      <rect x="14" y="26" width="12" height="8" rx="2" fill="rgba(0,0,0,0.3)" />
      <text x="20" y="32" textAnchor="middle" fontSize="6" fill={accentColor} fontFamily="monospace" fontWeight="bold">
        {label}
      </text>
      {/* 상태 LED */}
      <circle cx="20" cy="39" r="2.5" fill={ledColor} className="anim-blink" />

      {/* ── 팔 ── */}
      <rect x="3" y="23" width="7" height="14" rx="3" fill={bodyColor} stroke={accentColor} strokeWidth="1" />
      <rect x="30" y="23" width="7" height="14" rx="3" fill={bodyColor} stroke={accentColor} strokeWidth="1" />
      {/* 손 (집게) */}
      <circle cx="6.5" cy="38" r="3" fill={accentColor} />
      <circle cx="33.5" cy="38" r="3" fill={accentColor} />

      {/* ── 다리 ── */}
      <rect x="12" y="42" width="7" height="11" rx="2" fill={bodyColor} stroke={accentColor} strokeWidth="1" />
      <rect x="21" y="42" width="7" height="11" rx="2" fill={bodyColor} stroke={accentColor} strokeWidth="1" />
      {/* 발 */}
      <rect x="10" y="51" width="11" height="5" rx="2" fill={accentColor} />
      <rect x="19" y="51" width="11" height="5" rx="2" fill={accentColor} />
    </svg>
  );
}

/* ── 에이전트 타입별 설정 ── */
const AGENT_CONFIG = {
  claude: {
    headShape: 'square' as const,
    bodyColor: '#2d1f4a',
    accentColor: '#a78bfa',
    label: 'C',
  },
  gemini: {
    headShape: 'diamond' as const,
    bodyColor: '#0f2e22',
    accentColor: '#34d399',
    label: 'G',
  },
  codex: {
    headShape: 'cylinder' as const,
    bodyColor: '#0f2535',
    accentColor: '#22d3ee',
    label: '</>',
  },
  unknown: {
    headShape: 'square' as const,
    bodyColor: '#1a2435',
    accentColor: '#64748b',
    label: '?',
  },
  ceo: {
    headShape: 'square' as const,
    bodyColor: '#1e3a5f',
    accentColor: '#f59e0b',
    label: 'CEO',
  },
};

/* ── 메인 IsoAgent 컴포넌트 ── */
export default function IsoAgent({ agentType, name, status, x = 0, y = 0, onClick }: IsoAgentProps) {
  const ledColor = LED_COLOR[status];

  return (
    <div
      className="iso-character"
      style={{ left: x, top: y }}
      onClick={onClick}
      title={name}
    >
      <span className="name-tag">{name}</span>

      {agentType === 'ceo' ? (
        <CeoCharacter status={status} />
      ) : (
        <RobotBody
          headShape={AGENT_CONFIG[agentType]?.headShape ?? 'square'}
          bodyColor={AGENT_CONFIG[agentType]?.bodyColor ?? '#1a2435'}
          accentColor={AGENT_CONFIG[agentType]?.accentColor ?? '#64748b'}
          ledColor={ledColor}
          status={status}
          label={AGENT_CONFIG[agentType]?.label ?? '?'}
        />
      )}

      {/* 상태 LED 배지 */}
      <div
        className={`iso-led ${status}`}
        style={{ marginTop: 3 }}
        title={status}
      />
    </div>
  );
}

/* ── 에이전트 타입 감지 유틸 ── */
export function detectAgentType(name: string): IsoAgentProps['agentType'] {
  const n = name.toLowerCase();
  if (n.includes('claude') || n.includes('t1')) return 'claude';
  if (n.includes('gemini') || n.includes('t2')) return 'gemini';
  if (n.includes('codex') || n.includes('t3')) return 'codex';
  if (n.includes('ceo') || n.includes('boss') || n.includes('owner')) return 'ceo';
  return 'unknown';
}
