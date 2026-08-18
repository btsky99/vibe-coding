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
 * - 2026-08-15 Claude: 인터넷 목소리(edge-tts) 끄는 스위치 — 문장이 밖으로 나가는 것을
 *   사용자가 직접 정할 수 있어야 한다. 끄면 목록에서도 빠진다(voiceBus.refreshVoices)
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
                  {/* [🔴 사장님 목소리는 준비 상태를 여기서 말한다 — 2026-08-18]
                      서버는 qwen{installed,running,step,error} 를 계속 보내는데 화면이
                      통째로 버렸다. 그래서 모델이 없든 받는 중이든 실패했든 **똑같이
                      조용했고**, 사장님은 '골랐는데 소리가 안 난다'로만 겪었다.
                      note 아래 한 줄이면 그 침묵이 사라진다. */}
                  {opt.engine === 'qwen' && v.qwen && (
                    v.qwen.error ? (
                      <div className="truncate text-[9px] text-red-400" title={v.qwen.error}>
                        준비 실패 — {v.qwen.error}
                      </div>
                    ) : v.qwen.running ? (
                      <div className="truncate text-[9px] text-amber-400" title={v.qwen.step}>
                        준비 중… {v.qwen.step || '5GB 를 내려받는 중입니다'}
                      </div>
                    ) : v.qwen.installed ? (
                      <div className="truncate text-[9px] text-emerald-400/80" title={v.qwen.home}>
                        준비됨 · {v.qwen.home}
                      </div>
                    ) : (
                      <div className="truncate text-[9px] text-white/45">
                        아직 안 받았습니다 — 고르면 약 5GB 를 내려받습니다
                      </div>
                    )
                  )}
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

      {/* 말하면 바로 보내기 스위치.
          [🔴 기본은 꺼짐 — 2026-08-17 사장 지시] 예전에는 받아쓴 말을 입력칸에 넣자마자
            보내 버려서, 사장님은 **무엇이 들어갔는지 볼 수가 없었다**. 이제 기본은
            '입력칸에 두고 멈춤'이고, 옛 동작(핸즈프리)이 필요한 사람만 켠다.
          [WHY 여기인가] 낭독 설정과 한 판에 두면 '음성에 관한 것은 여기'가 유지된다. */}
      <div className="mt-3 flex items-start gap-2 border-t border-white/10 pt-2">
        <button
          onClick={() => voiceBus.setAutoSend(!v.autoSend)}
          className={`mt-0.5 h-3.5 w-6 shrink-0 rounded-full transition-colors ${
            v.autoSend ? 'bg-primary/70' : 'bg-white/15'
          }`}
          title={v.autoSend ? '끄면 입력칸에 두고 멈춥니다' : '켜면 말하는 즉시 보냅니다'}
        >
          <span
            className={`block h-2.5 w-2.5 rounded-full bg-white transition-transform ${
              v.autoSend ? 'translate-x-3' : 'translate-x-0.5'
            }`}
          />
        </button>
        <div className="min-w-0 flex-1">
          <div className="text-white/70">말하면 바로 보내기</div>
          <div className="text-[9px] leading-tight text-white/35">
            {v.autoSend
              ? '받아쓰는 즉시 보냅니다. 손이 바쁠 때 편하지만 잘못 들어도 그대로 나갑니다'
              : '받아쓴 말을 입력칸에 넣고 멈춥니다 — 확인하고 고쳐서 보낼 수 있어요'}
          </div>
        </div>
      </div>

      {/* 인터넷 목소리 스위치.
          [🔴 목소리 목록 '아래'에 둔다] 이 스위치를 끄면 목록에서 edge 항목이 사라진다.
            위에 두면 사라지는 원인이 눈에 안 들어와 목록이 고장 난 것처럼 보인다.
          [WHY 이런 문구인가] '문장을 밖으로 보낸다'가 사용자가 실제로 결정하는 내용이다.
            'edge-tts'는 그 사실을 말해 주지 않는다 — 이름은 괄호로 뒤에 붙인다. */}
      <div className="mt-3 flex items-start gap-2 border-t border-white/10 pt-2">
        <button
          onClick={() => voiceBus.setEdge(!v.edgeOn)}
          className={`mt-0.5 h-3.5 w-6 shrink-0 rounded-full transition-colors ${
            v.edgeOn ? 'bg-primary/70' : 'bg-white/15'
          }`}
          title={v.edgeOn ? '끄면 이 PC 안에서만 읽습니다' : '켜면 더 자연스러운 목소리를 씁니다'}
        >
          <span
            className={`block h-2.5 w-2.5 rounded-full bg-white transition-transform ${
              v.edgeOn ? 'translate-x-3' : 'translate-x-0.5'
            }`}
          />
        </button>
        <div className="min-w-0 flex-1">
          <div className="text-white/70">인터넷 목소리 쓰기 <span className="text-white/30">(edge-tts)</span></div>
          <div className="text-[9px] leading-tight text-white/35">
            {v.edgeOn
              ? '읽을 문장만 마이크로소프트로 보내 자연스럽게 읽습니다. 끄면 이 PC 안에서만 읽어요'
              : '이 PC 에 깔린 목소리로만 읽습니다. 밖으로 나가는 것이 없어요'}
          </div>
        </div>
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
