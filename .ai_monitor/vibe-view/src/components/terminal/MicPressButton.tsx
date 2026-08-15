/**
 * ------------------------------------------------------------------------
 * 📄 파일명: components/terminal/MicPressButton.tsx
 * 📝 설명: '누르고 말하기' 단추 하나. 누르는 동안만 듣고 손을 떼면 그대로 보낸다.
 *
 *          [🔴 왜 따로 떼어 놨나] 이 단추는 두 자리에 나타난다 — 터미널이 열려 있으면
 *          전송창 왼쪽(아픽스 보드와 같은 자리), 선택 화면이면 음성 막대 안. 같은 코드를
 *          두 벌 두면 한쪽만 고쳐지는 일이 반드시 생긴다(이 리포에서 이미 여러 번 났다).
 *
 *          [🔴 화면에서 사라지면 안 된다] 과거에 VoiceBar 를 조건부 렌더 안에 뒀다가
 *          다른 화면에서 마이크가 통째로 사라진 사고가 있다(wiki/함정/음성 입출력 함정.md).
 *          그래서 '어느 자리에 그릴지'만 화면이 정하고, **둘 중 하나는 항상 있다.**
 *
 * REVISION HISTORY:
 * - 2026-08-15 Claude: VoiceBar 에서 분리 — 전송창 안에도 같은 단추가 필요해졌다
 * ------------------------------------------------------------------------
 */

import { Mic, Loader2 } from 'lucide-react';
import { voiceBus } from '../../lib/voiceBus';
import { useVoiceState } from '../../hooks/useVoice';

interface Props {
  /** 'T1' 형식. 누르는 동안 이 슬롯이 무조건 대상이 된다. */
  terminalId: string;
  /** true 면 아이콘만(전송창 옆). false 면 글자까지(음성 막대 안). */
  iconOnly?: boolean;
  className?: string;
}

export default function MicPressButton({ terminalId, iconOnly, className = '' }: Props) {
  const v = useVoiceState();
  const hot = v.target === terminalId && v.speaking;

  return (
    <button
      type="button"
      aria-label="누르고 말하기"
      title="누르고 있는 동안 듣습니다. 손을 떼면 그대로 보냅니다"
      onPointerDown={(e) => {
        e.preventDefault();
        // [🔴 포인터를 이 단추에 붙들어 둔다] 누른 채로 커서가 밖으로 나가면 pointerup 이
        //   다른 요소에서 발생해 여기로 안 온다. 그러면 단추가 눌린 채로 굳고 마이크가
        //   열린 상태로 남는다 — 가장 나쁜 상태다.
        (e.currentTarget as HTMLElement).setPointerCapture?.(e.pointerId);
        void voiceBus.pressToTalk(terminalId);
      }}
      onPointerUp={() => voiceBus.releaseToTalk()}
      onPointerCancel={() => voiceBus.releaseToTalk()}
      className={`shrink-0 flex items-center justify-center gap-1 rounded border transition-colors
                  select-none touch-none ${
                    hot
                      ? 'bg-red-500/30 border-red-400/60 text-red-200'
                      : 'bg-[#3c3c3c] border-white/10 hover:bg-white/10 text-white/70'
                  } ${iconOnly ? 'h-[34px] w-[34px]' : 'h-[25px] px-2 text-[10px]'} ${className}`}
    >
      {v.busy ? <Loader2 size={14} className="animate-spin" /> : <Mic size={14} />}
      {!iconOnly && <span>누르고 말하기</span>}
    </button>
  );
}
