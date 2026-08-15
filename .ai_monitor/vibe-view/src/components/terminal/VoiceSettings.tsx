/**
 * ------------------------------------------------------------------------
 * 📄 파일명: components/terminal/VoiceSettings.tsx
 * 📝 설명: 목소리 고르기 팝오버 — 어떤 음성으로 읽을지, 얼마나 빠르게 읽을지.
 *          VoiceBar 의 ⚙ 버튼이 연다.
 *
 *          [🔴 목록은 서버가 준 것만 그린다] 화면에 후보를 하드코딩하면, 그 PC 에 없는
 *          음성을 고를 수 있게 되고 낭독이 매번 실패한다. 무엇이 설치돼 있는지는
 *          사이드카만 안다(/status 의 voices).
 *
 *          [WHY 미리듣기를 붙였나] 목소리는 이름으로 고를 수 없다. 들어 보지 않으면
 *          사용자는 실제 답이 올 때까지 기다렸다 다시 고르는 짓을 반복한다.
 *
 *          [🔴 설정은 전역이다] 마이크와 마찬가지로 엔진이 하나라, 어느 슬롯의 ⚙ 을
 *          열어도 같은 값을 만진다. 슬롯마다 다른 것은 호출어뿐이다.
 *
 * REVISION HISTORY:
 * - 2026-08-15 Claude: 최초 작성 — 목소리 선택·속도·미리듣기
 * - 2026-08-15 Claude: 준비 폴링을 voiceBus 로 이관 + '준비 중' 표시 제거(읽기는 즉시 됨)
 * ------------------------------------------------------------------------
 */

import { useEffect, useRef } from 'react';
import { Play, X } from 'lucide-react';
import { voiceBus } from '../../lib/voiceBus';
import { useVoiceState } from '../../hooks/useVoice';

interface Props {
  onClose: () => void;
}

export default function VoiceSettings({ onClose }: Props) {
  const v = useVoiceState();
  const boxRef = useRef<HTMLDivElement>(null);

  // 바깥을 누르면 닫는다. [제약] mousedown 으로 잡아야 한다 — click 이면 안쪽 버튼의
  // 동작이 끝나기 전에 닫혀 선택이 씹힌다.
  useEffect(() => {
    const onDown = (e: MouseEvent) => {
      if (!boxRef.current?.contains(e.target as Node)) onClose();
    };
    document.addEventListener('mousedown', onDown);
    return () => document.removeEventListener('mousedown', onDown);
  }, [onClose]);

  // [🔴 여기서 폴링하지 않는다 — 2026-08-15 고착 사고] 예전엔 이 팝오버가 3초마다
  //   /status 를 물었다. 그래서 팝오버를 닫으면 갱신이 멈췄고, 예열이 끝난 뒤에도
  //   화면은 '준비 중'을 영영 붙들고 있었다. 지금은 상태를 소유한 voiceBus 가 스스로
  //   다시 묻는다(ensureSidecar). 화면은 열려 있든 아니든 결과만 받는다.
  useEffect(() => { voiceBus.ensureSidecar(); }, []);

  const current = v.voice || (v.voices[0]?.id ?? '');

  return (
    <div
      ref={boxRef}
      className="absolute bottom-full left-0 mb-1.5 z-50 w-72 rounded-lg border border-white/10
                 bg-[#252526] p-3 shadow-2xl text-[11px]"
    >
      <div className="flex items-center justify-between mb-2">
        <span className="font-bold text-white">음성 설정</span>
        <button onClick={onClose} className="text-white/40 hover:text-white/80" title="닫기">
          <X size={12} />
        </button>
      </div>

      <div className="text-white/45 mb-1.5">목소리</div>
      {v.voices.length === 0 ? (
        <div className="rounded border border-dashed border-white/15 px-2 py-3 text-center text-white/35">
          이 PC 에서 쓸 수 있는 목소리가 없습니다
        </div>
      ) : (
        <div className="flex flex-col gap-1 max-h-44 overflow-y-auto custom-scrollbar">
          {v.voices.map((opt) => {
            const on = opt.id === current;
            return (
              <div
                key={opt.id}
                className={`flex items-center gap-2 rounded border px-2 py-1.5 transition-colors ${
                  on ? 'border-primary/50 bg-primary/15' : 'border-white/10 hover:bg-white/5'
                }`}
              >
                <button
                  onClick={() => voiceBus.setVoice(opt.id)}
                  className="flex-1 text-left min-w-0"
                >
                  <div className={`truncate ${on ? 'text-primary font-bold' : 'text-white/80'}`}>
                    {opt.label}
                    <span className="ml-1 text-[9px] text-white/35">
                      {opt.lang === 'ko' ? '한국어' : opt.lang}
                    </span>
                  </div>
                  {opt.note && <div className="truncate text-[9px] text-white/35">{opt.note}</div>}
                </button>
                <button
                  onClick={() => void voiceBus.preview(opt.id)}
                  disabled={v.busy}
                  title="이 목소리로 들어보기"
                  className="shrink-0 rounded border border-white/10 p-1 text-white/60
                             hover:bg-white/10 disabled:opacity-40"
                >
                  <Play size={10} />
                </button>
              </div>
            );
          })}
        </div>
      )}

      <div className="mt-3 flex items-center gap-2">
        <span className="text-white/45 shrink-0">읽는 속도</span>
        <input
          type="range"
          min={0.5}
          max={1.5}
          step={0.05}
          value={v.speed}
          onChange={(e) => voiceBus.setSpeed(Number(e.target.value))}
          className="flex-1 accent-primary"
        />
        <span className="w-8 text-right tabular-nums text-white/60">{v.speed.toFixed(2)}</span>
      </div>

      {/* 상태 한 줄.
          [🔴 '준비 중'을 기본으로 띄우지 않는다] 읽기는 이 PC 내장 목소리로 이미 되므로
            기다리라고 말할 이유가 없다. 여기서 알릴 것은 '받아쓰기가 아직인가' 하나뿐이고,
            그것도 사람이 말을 걸어야 의미가 생긴다. */}
      <div className="mt-2 border-t border-white/10 pt-2 text-[10px]">
        {v.error ? (
          <span className="text-amber-300/70">● {v.error}</span>
        ) : v.sttReady ? (
          <span className="text-emerald-300/70">● 듣기·읽기 모두 준비됨</span>
        ) : (
          <span className="text-white/40">● 읽기는 바로 됩니다 · 받아쓰기 준비 중</span>
        )}
      </div>
    </div>
  );
}
