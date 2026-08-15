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

  // 엔진이 준비될 때까지 다시 묻는다.
  // [WHY 필요한가] 사이드카 첫 기동은 수십 초다. 한 번만 묻고 말면 패널은 준비 안 된
  //   상태로 굳고, 사용자는 닫았다 여는 것 말고는 할 수 있는 게 없다.
  // [🔴 종료 조건이 voices 면 안 된다 — 사고 2026-08-15] 서버의 /status 는 목소리 목록을
  //   **엔진 로딩과 무관하게 즉시** 준다(voice_server.py: list_voices() 는 상태를 안 봄).
  //   반면 ready 는 STT/TTS 예열이 끝나야 true 다. 종료 조건을 voices.length 로 두면
  //   첫 응답에서 목록이 차는 순간 폴링이 멈추고, 뒤늦게 온 ready=true 를 영영 못 받아
  //   화면이 '음성 엔진 준비 중…' 에 **영구 고착**됐다(백엔드는 정상인데 화면만 거짓말).
  //   표시가 보는 값(ready)과 폴링이 멈추는 값이 같아야 한다.
  useEffect(() => {
    if (v.ready) return;
    const t = setInterval(() => { void voiceBus.checkReady(); }, 3000);
    return () => clearInterval(t);
  }, [v.ready]);

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
          {v.ready ? '고를 수 있는 목소리가 없습니다' : '음성 엔진을 준비하는 중…'}
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

      {/* 엔진 상태 — 낭독이 안 될 때 사용자가 자기 스피커를 의심하지 않게 한다. */}
      <div className="mt-2 border-t border-white/10 pt-2 text-[10px]">
        {v.ready ? (
          <span className="text-emerald-300/70">● 음성 엔진 준비됨</span>
        ) : (
          <span className="text-amber-300/70">● {v.error || '음성 엔진 준비 중…'}</span>
        )}
      </div>
    </div>
  );
}
