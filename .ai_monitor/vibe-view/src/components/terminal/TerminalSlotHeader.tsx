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
 * - 2026-08-09 Claude: TerminalSlot.tsx에서 순수 이동(Phase 11 Task 38). 동작 무변경.
 * ------------------------------------------------------------------------
 */
import { useEffect, useRef, useState } from 'react';
import { Terminal, Zap, ClipboardList, MessageSquare, X } from 'lucide-react';

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
  termData: { main_model?: string; bg_model?: string };
  effectivePath: string;
  isActiveProject?: boolean;
  onActivateProject?: () => void;
  onPickProject: () => void;
  onClose: () => void;
}

export default function TerminalSlotHeader({
  displayName, slotName, onRenameSlot, isTerminalMode, activeAgent, agentType, gitBranch,
  lockedFileByAgent, myPendingTasks, recentAgentMsgs, termData, effectivePath, isActiveProject,
  onActivateProject, onPickProject, onClose,
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
        {/* Git 브랜치 배지 — cmux 스타일 수직 탭 컨텍스트 정보 */}
        {gitBranch && (
          <span className="text-[8px] font-mono text-accent/70 bg-accent/10 border border-accent/20 px-1.5 py-0.5 rounded shrink-0">
            {gitBranch}
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
          <button onClick={onClose} className="p-0.5 hover:bg-red-500/20 rounded text-red-400 transition-colors">
            <X className="w-3.5 h-3.5" />
          </button>
        </div>
      )}
    </div>
  );
}
