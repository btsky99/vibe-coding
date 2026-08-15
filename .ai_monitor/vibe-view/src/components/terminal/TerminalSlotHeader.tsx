/**
 * ------------------------------------------------------------------------
 * 📄 파일명: terminal/TerminalSlotHeader.tsx
 * 📝 설명: 터미널 슬롯 상단 바 — 이름·브랜치·락/작업/메시지 배지, 프로젝트 뱃지, 모델 배지.
 *          유휴(에이전트 미실행)와 실행 중일 때 오른쪽 구성이 갈린다.
 *
 * [WHY 분리했나] TerminalSlot.tsx가 1171줄이었다. 좌우 2분할(Phase 11 Task 43)을 그대로
 *   얹으면 규칙 2(파일당 1500줄)를 넘긴다. 헤더는 상태를 거의 갖지 않는 표시 영역이라
 *   가장 안전하게 떼어낼 수 있는 블록이다.
 * [제약] 이 컴포넌트는 상태를 소유하지 않는다(이름 편집은 Task 44에서 콜백으로 추가).
 *   여기에 fetch를 넣지 말 것 — 슬롯 수만큼 곱해진다.
 *
 * 🕒 변경 이력:
 * - 2026-08-15 Claude: 아픽스 보드처럼 '상태 + 지금 하는 일 + 조종 단추'를 머리말로 올림.
 *                      화면만 보고 도는지 멈췄는지 알 수 없다는 지적(같은 날 여러 번)의 해소.
 * - 2026-08-09 Claude: TerminalSlot.tsx에서 순수 이동(Phase 11 Task 38). 동작 무변경.
 * ------------------------------------------------------------------------
 */
import { useEffect, useRef, useState } from 'react';
import { Terminal, Zap, ClipboardList, MessageSquare, X, RotateCw, Square } from 'lucide-react';

interface Props {
  displayName: string;
  /** 현재 저장된 이름(주소 제외). 편집 입력의 초기값. */
  slotName?: string;
  /** 미전달이면 편집 UI를 띄우지 않는다 — 오피스 등 이름을 소유하지 않는 재사용처 보호. */
  onRenameSlot?: (name: string) => void;
  isTerminalMode: boolean;
  activeAgent: string;
  agentType: string;
  gitBranch: string;
  lockedFileByAgent?: string;
  /** 구조적 타입 — 원본(Task)의 전체 필드를 요구하지 않는다. 헤더는 제목만 쓴다. */
  myPendingTasks: Array<{ title: string }>;
  recentAgentMsgs: Array<{ content: string }>;
  effectivePath: string;
  isActiveProject?: boolean;
  onActivateProject?: () => void;
  onPickProject: () => void;
  onClose: () => void;
  /** PTY 바이트가 최근 3초 안에 왔는가 = 지금 도는가. 계산은 TerminalSlot 이 한다. */
  isOutputFlowing?: boolean;
  /** 마지막 출력 이후 경과 초. null = 아직 한 글자도 못 받음. '조용한 지 N초' 표시용. */
  outputAgeSec?: number | null;
  /** 지금 무엇을 하는 중인가 (termData.task). 없으면 표시 생략. */
  liveTask?: string | null;
  /** 재시작 — 마지막 실행 인자 그대로 재생. 미전달이면 단추를 그리지 않는다. */
  onRestart?: () => void;
  /** 중단 — 진행 중인 답만 멈춤(ESC). 미전달이면 단추를 그리지 않는다. */
  onInterrupt?: () => void;
}

export default function TerminalSlotHeader({
  displayName, slotName, onRenameSlot, isTerminalMode, activeAgent, agentType, gitBranch,
  lockedFileByAgent, myPendingTasks, recentAgentMsgs, effectivePath, isActiveProject,
  onActivateProject, onPickProject, onClose,
  isOutputFlowing, outputAgeSec, liveTask, onRestart, onInterrupt,
}: Props) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState('');
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => { if (editing) inputRef.current?.select(); }, [editing]);

  const beginEdit = () => {
    if (!onRenameSlot) return;
    setDraft(slotName || '');
    setEditing(true);
  };
  const commit = () => {
    setEditing(false);
    // [WHY 빈 값도 넘기나] 이름을 지우는 것도 의도된 조작이다 — 호출부가 빈 값을 받으면
    //   키를 삭제해 주소만 남는다. 여기서 막으면 한 번 붙인 이름을 못 뗀다.
    onRenameSlot?.(draft);
  };

  return (
    <div className="h-7 bg-[#2d2d2d] border-b border-black/40 flex items-center justify-between px-3 shrink-0">
      <div className="flex items-center gap-2 max-w-[60%] overflow-hidden">
        <Terminal className="w-3 h-3 text-accent shrink-0" />
        {editing ? (
          <input
            ref={inputRef}
            value={draft}
            onChange={e => setDraft(e.target.value)}
            onBlur={commit}
            onKeyDown={e => {
              if (e.key === 'Enter') { e.preventDefault(); commit(); }
              if (e.key === 'Escape') { e.preventDefault(); setEditing(false); }   // 되돌리기
            }}
            placeholder="이름 (예: 프론트)"
            maxLength={20}
            className="w-28 bg-black/40 border border-primary/40 rounded px-1 py-0.5 text-[10px] text-white outline-none"
          />
        ) : (
          <span
            onDoubleClick={beginEdit}
            title={onRenameSlot ? '더블클릭해서 이름 변경' : undefined}
            className={`text-[10px] font-bold text-[#bbbbbb] uppercase tracking-wider truncate ${onRenameSlot ? 'cursor-text hover:text-white' : ''}`}
          >
            {isTerminalMode ? `${displayName} - ${activeAgent}` : displayName}
          </span>
        )}
        {/* ── 지금 도는가 ──
            [WHY 여기 있나] 이 줄이 없으면 화면만 보고는 에이전트가 일하는 중인지 멎었는지
              알 수 없다. 아래 배지(작업 수·메시지)는 DB 폴링이라 10분짜리 한 건을 붙들고
              있는 동안엔 아무것도 안 바뀐다 — 그때 사람이 "멈춘 것 같은데"라고 말한다.
            [근거] isOutputFlowing 은 PTY 바이트 도착 시각 하나만 본다(TerminalSlot 주석).
              '조용한 지 N초'를 같이 보여주는 이유: '멈춤'이라는 단어만으로는 방금 끝난 것과
              오래 멎어 있는 것이 구분되지 않는다. 숫자가 있어야 사람이 판단한다. */}
        {isTerminalMode && (
          <span
            title={isOutputFlowing ? '터미널에서 출력이 흐르는 중' : '출력이 멎어 있음 — 답을 기다리는 중이거나 입력 대기'}
            className={`flex items-center gap-1 shrink-0 px-1.5 py-0.5 rounded text-[9px] font-bold border ${
              isOutputFlowing
                ? 'bg-green-500/15 border-green-500/40 text-green-400'
                : 'bg-white/5 border-white/10 text-[#858585]'
            }`}
          >
            <span className={`w-1.5 h-1.5 rounded-full ${isOutputFlowing ? 'bg-green-400 animate-pulse' : 'bg-[#555]'}`} />
            {isOutputFlowing ? '도는 중' : '멈춤'}
            {!isOutputFlowing && outputAgeSec !== null && outputAgeSec !== undefined && (
              <span className="text-[#666] font-normal">{outputAgeSec}초</span>
            )}
          </span>
        )}
        {/* Git 브랜치 배지 — cmux 스타일 수직 탭 컨텍스트 정보 */}
        {gitBranch && (
          <span className="text-[8px] font-mono text-accent/70 bg-accent/10 border border-accent/20 px-1.5 py-0.5 rounded shrink-0">
            {gitBranch}
          </span>
        )}
        {/* 무엇을 하는 중인가 — 상태(도는가)와 짝이다. 하나만 있으면 "돌긴 도는데 뭘 하는지
            모르겠다"가 된다. [제약] 폭을 먹으면 폴더 배지·조종 단추를 밀어낸다(2026-07-24에
            같은 이유로 배지 3종을 뺐다) → truncate + max-w 고정, 전문은 title 로만. */}
        {isTerminalMode && liveTask && (
          <span
            title={liveTask}
            className="text-[9px] text-[#9a9a9a] bg-white/5 border border-white/10 px-1.5 py-0.5 rounded truncate max-w-[150px] shrink"
          >
            {liveTask}
          </span>
        )}
        {lockedFileByAgent && (
          <div className="flex items-center gap-1.5 ml-2 px-1.5 py-0.5 bg-yellow-500/10 border border-yellow-500/30 rounded text-[9px] text-yellow-500 animate-pulse shrink-0">
            <Zap className="w-2.5 h-2.5" />
            <span className="font-mono">LOCK: {lockedFileByAgent.split(/[\\/]/).pop()}</span>
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
          {/* [유휴 헤더 — 폴더 먼저, 실행은 나중] 사용자 최종 의도(2026-07-24): "상단에서 폴더
              선택 후 카드를 누르면 그 폴더로 실행"돼야 한다. 카드 클릭마다 폴더창을 띄우는 흐름
              (구 handleLaunchWithPick)은 반대로 매번 물어봐 반려됨. 그래서:
                · 📁 뱃지 = 현재 슬롯 프로젝트 표시 + 클릭 시 사이드 패널 activate
                · '폴더 선택' 버튼 = handlePickProject로 slotProject 갱신(유휴라 팝업만·재시작 없음)
              AgentSelectCards의 카드 클릭은 launchAgent 직결 → 팝업 없이 effectivePath로 spawn. */}
          <button
            onClick={onActivateProject}
            title="이 프로젝트를 사이드 패널(파일·Git·태스크)에 표시"
            className={`px-2 py-0.5 rounded text-[9px] border font-bold truncate max-w-[120px] transition-all ${isActiveProject ? 'bg-accent/25 border-accent/60 text-accent' : 'bg-[#3c3c3c] border-white/5 text-[#cccccc] hover:bg-white/10'}`}
          >
            📁 {effectivePath.split(/[/\\]/).filter(Boolean).pop() || '프로젝트'}
          </button>
          <button
            onClick={onPickProject}
            title="실행할 프로젝트 폴더를 먼저 선택 — 이후 아래 카드를 누르면 이 폴더로 실행됩니다"
            className="px-1.5 py-0.5 rounded text-[9px] border border-white/5 bg-[#3c3c3c] text-[#cccccc] hover:bg-white/10 transition-all"
          >
            폴더 선택
          </button>
          <span className="text-[9px] text-[#858585] font-bold ml-1">→ 아래 카드로 실행</span>
        </div>
      ) : (
        <div className="flex gap-2 items-center">
          {/* [2026-08-11] 모델 배지(M:/BG:) 제거 — 하단 컨텍스트 바와 **다른 모델명을 보여줬다**.
              사용자 판정: 하단이 맞고 헤더가 틀렸다. 헤더는 PTY 스냅샷의 main_model 을 그리는데
              그 값이 실제 세션 모델과 어긋나 있었다(하단 'Opus 5' vs 헤더 'sonnet-4-6').
              🔴 같은 사실을 두 곳에서 각자 계산하면 반드시 갈라진다 — 표시 지점을 하나로 줄인다.
              되살릴 일이 생기면 값을 하단 바와 같은 출처에서 받아 오는 것이 선행 조건이다.
              (termData prop 도 이 배지 전용이라 함께 제거 — 죽은 prop 을 남기지 않는다.) */}

          {/* [2026-07-24] Antigravity 컨텍스트 게이지 / Claude·Codex 쿼터 배지 제거 — 헤더 폭을
              잡아먹어 폴더 배지·변경 버튼을 밀어내던 문제(사용자 요청). 사용률은 하단 컨텍스트
              바와 DB로 확인 가능해 헤더 상시 표시는 불필요. agentQuota prop은 호환성 위해
              TerminalSlot 시그니처에만 남아 있다(미소비). */}

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
            onClick={onPickProject}
            title="이 슬롯의 프로젝트 폴더 변경 (실행 중이면 재시작)"
            className="px-1.5 py-0.5 rounded text-[9px] border border-white/5 bg-[#3c3c3c] text-[#cccccc] hover:bg-white/10 transition-all"
          >
            변경
          </button>

          {/* [2026-07-24] 모니터링 토글 버튼 제거(사용자 요청) — 헤더 혼잡 완화. 미부착 슬롯에선
              여전히 자동 표시되므로 기능 손실 없음. */}

          {/* ── 조종 단추: 중단 · 재시작 · 끄기 ──
              [WHY 이 순서인가] 왼쪽일수록 되돌리기 쉬운 것. 중단은 답 하나만 버리고,
                재시작은 스크롤백을 버리고, 끄기는 세션을 버린다. 오누름의 대가가 커지는 순서로
                놓아야 손이 미끄러졌을 때 덜 잃는다.
              [불변식] 세 단추의 파괴력이 서로 다르다 — 중단(ESC)은 확인 없이, 재시작은 확인을
                받고(호출부 restartAgent), 끄기는 기존대로. 중단에 확인을 붙이면 급할 때 못 멈춘다. */}
          <button
            onClick={onInterrupt}
            title="지금 하던 답만 멈춤 (ESC) — 세션은 유지"
            className="flex items-center gap-1 px-1.5 py-0.5 rounded text-[9px] border border-white/5 bg-[#3c3c3c] text-[#cccccc] hover:bg-yellow-500/20 hover:text-yellow-400 transition-all"
          >
            <Square className="w-2.5 h-2.5 fill-current" /> 중단
          </button>
          <button
            onClick={onRestart}
            title="같은 조건으로 터미널 재시작 (스크롤백은 사라짐)"
            className="flex items-center gap-1 px-1.5 py-0.5 rounded text-[9px] border border-white/5 bg-[#3c3c3c] text-[#cccccc] hover:bg-white/10 transition-all"
          >
            <RotateCw className="w-2.5 h-2.5" /> 재시작
          </button>
          <button onClick={onClose} title="이 슬롯 끄기" className="p-0.5 hover:bg-red-500/20 rounded text-red-400 transition-colors">
            <X className="w-3.5 h-3.5" />
          </button>
        </div>
      )}
    </div>
  );
}
