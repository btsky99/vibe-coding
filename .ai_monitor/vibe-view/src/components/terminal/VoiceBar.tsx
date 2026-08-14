/**
 * ------------------------------------------------------------------------
 * 📄 파일명: components/terminal/VoiceBar.tsx
 * 📝 설명: 터미널 슬롯 입력줄 옆의 음성 조작부 — 마이크 버튼, 상시 대기 토글,
 *          낭독 토글, 이 슬롯의 호출어 설정.
 *
 *          [🔴 상태는 전역, 표시는 슬롯마다] 마이크는 앱에 하나뿐이므로 어느 슬롯의
 *          VoiceBar 를 눌러도 같은 엔진을 조작한다. 다만 '지금 대상이 나인가'(target)와
 *          호출어는 슬롯마다 다르게 그린다 — 안 그러면 세 슬롯이 전부 '듣는 중'으로
 *          보여서 어디에 말하는지 알 수 없다.
 *
 *          [WHY 마이크 권한 안내를 눈에 보이게 두나] WebView2 는 권한이 막히면 아무
 *          에러 없이 조용히 멈춘다(실측). 그때 사용자가 의심하는 것은 자기 마이크다.
 *
 * REVISION HISTORY:
 * - 2026-08-15 Claude: 최초 작성 — 로컬 음성(STT/TTS) UI
 * - 2026-08-15 Claude: 아이콘만으로는 무슨 기능인지 안 보인다는 지적 — 글자 라벨과
 *   낭독 체크박스를 붙이고, 목소리 선택(⚙ VoiceSettings)을 연다
 * ------------------------------------------------------------------------
 */

import { useState } from 'react';
import { Mic, MicOff, Loader2, Square, Settings2, Check } from 'lucide-react';
import { voiceBus } from '../../lib/voiceBus';
import { useVoiceState } from '../../hooks/useVoice';
import VoiceSettings from './VoiceSettings';

interface Props {
  /** 'T1' 형식 */
  terminalId: string;
  /** 이 슬롯을 부르는 말. 비어 있으면 호출어로 못 부른다. */
  wakeWord: string;
  onWakeWordChange: (w: string) => void;
}

export default function VoiceBar({ terminalId, wakeWord, onWakeWordChange }: Props) {
  const v = useVoiceState();
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(wakeWord);
  const [showSettings, setShowSettings] = useState(false);

  const isTarget = v.target === terminalId;
  const busy = v.busy;

  const commit = () => {
    setEditing(false);
    const clean = draft.trim().slice(0, 12);   // 부르는 말이 길면 인식이 더 자주 흘린다
    if (clean !== wakeWord) onWakeWordChange(clean);
  };

  const voiceLabel = v.voices.find((o) => o.id === (v.voice || v.voices[0]?.id))?.label || '기본';

  return (
    <div className="flex items-center gap-1.5 text-[10px] relative">
      {/* 누르고 말하기 — 호출어 없이 이 슬롯에 바로 말한다.
          [WHY 글자를 같이 두나] 마이크 아이콘 두 개(누르고 말하기 / 상시 대기)가 나란히
          있으면 아이콘만으로는 구분되지 않는다 — 실제로 "마이크 모양이 없다"는 지적을 받았다. */}
      <button
        onPointerDown={(e) => {
          e.preventDefault();
          void voiceBus.pressToTalk(terminalId);
        }}
        onPointerUp={() => voiceBus.releaseToTalk()}
        onPointerCancel={() => voiceBus.releaseToTalk()}
        title="누르고 있는 동안 이 슬롯에 말합니다"
        className={`flex items-center gap-1 px-2 py-1 rounded border transition-colors ${
          isTarget && v.speaking
            ? 'bg-red-500/30 border-red-400/60 text-red-200'
            : 'bg-[#3c3c3c] border-white/10 hover:bg-white/10 text-white/70'
        }`}
      >
        {busy ? <Loader2 size={12} className="animate-spin" /> : <Mic size={12} />}
        <span>말하기</span>
      </button>

      {/* 상시 대기 — 호출어로 부르면 깨어난다 */}
      <button
        onClick={() => (v.enabled ? voiceBus.disable() : void voiceBus.enable())}
        title={v.enabled ? '상시 대기 끄기' : '상시 대기 켜기 (호출어로 부르면 반응)'}
        className={`flex items-center gap-1 px-2 py-1 rounded border transition-colors ${
          v.enabled
            ? 'bg-primary/25 border-primary/40 text-primary'
            : 'bg-[#3c3c3c] border-white/10 hover:bg-white/10 text-white/50'
        }`}
      >
        {v.enabled ? <Mic size={12} /> : <MicOff size={12} />}
        <span>{v.enabled ? '듣는 중' : '상시 대기'}</span>
      </button>

      {/* 답을 소리로 들을 것인가 — 체크 표시로 상태가 한눈에 보이게 한다 */}
      <button
        onClick={() => voiceBus.setTts(!v.ttsOn, terminalId)}
        title={v.ttsOn ? '답 낭독 끄기' : '답 낭독 켜기'}
        className={`flex items-center gap-1 px-2 py-1 rounded border transition-colors ${
          v.ttsOn
            ? 'bg-primary/25 border-primary/40 text-primary'
            : 'bg-[#3c3c3c] border-white/10 hover:bg-white/10 text-white/50'
        }`}
      >
        <span
          className={`w-3 h-3 rounded-[3px] border flex items-center justify-center ${
            v.ttsOn ? 'bg-primary border-primary text-white' : 'border-white/30'
          }`}
        >
          {v.ttsOn && <Check size={9} strokeWidth={3} />}
        </span>
        <span>답 듣기</span>
      </button>

      {/* 목소리 고르기 */}
      <button
        onClick={() => {
          // [🔴 여기서 checkReady 를 부르는 이유] 사이드카는 첫 status 요청 때 뜬다.
          //   패널을 열었는데 목록이 비어 있으면 사용자는 '목소리가 없다'고 읽는다.
          if (!showSettings) void voiceBus.checkReady();
          setShowSettings((s) => !s);
        }}
        title="어떤 목소리로 읽을지 고릅니다"
        className={`flex items-center gap-1 px-2 py-1 rounded border transition-colors max-w-[9rem] ${
          showSettings
            ? 'bg-primary/25 border-primary/40 text-primary'
            : 'bg-[#3c3c3c] border-white/10 hover:bg-white/10 text-white/60'
        }`}
      >
        <Settings2 size={12} className="shrink-0" />
        <span className="truncate">{voiceLabel}</span>
      </button>
      {showSettings && <VoiceSettings onClose={() => setShowSettings(false)} />}

      {v.playing && (
        <button
          onClick={() => voiceBus.stopSpeaking()}
          className="px-2 py-1 rounded border border-white/10 bg-[#3c3c3c] hover:bg-white/10 text-white/70"
          title="그만 읽기"
        >
          <Square size={10} />
        </button>
      )}

      {/* 호출어 */}
      {editing ? (
        <input
          autoFocus
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onBlur={commit}
          onKeyDown={(e) => {
            if (e.key === 'Enter') commit();
            if (e.key === 'Escape') { setDraft(wakeWord); setEditing(false); }
          }}
          placeholder="호출어"
          className="w-20 bg-[#1e1e1e] border border-primary/40 rounded px-1.5 py-0.5 text-[10px] text-white focus:outline-none"
        />
      ) : (
        <button
          onClick={() => { setDraft(wakeWord); setEditing(true); }}
          title="이 슬롯을 부르는 말을 정합니다 (예: 클로드)"
          className={`px-1.5 py-0.5 rounded border transition-colors ${
            wakeWord
              ? 'border-white/10 bg-[#3c3c3c] text-white/70 hover:bg-white/10'
              : 'border-dashed border-white/20 text-white/35 hover:text-white/60'
          }`}
        >
          {wakeWord ? `“${wakeWord}”` : '호출어 설정'}
        </button>
      )}

      {/* 입력 레벨 — 마이크가 살아 있음을 눈으로 확인하는 유일한 수단 */}
      {v.enabled && (
        <span className="w-8 h-1 rounded bg-white/10 overflow-hidden" title="입력 레벨">
          <span
            className="block h-full bg-primary transition-[width] duration-100"
            style={{ width: `${Math.round(v.level * 100)}%` }}
          />
        </span>
      )}

      {/* 상태 문구는 대상 슬롯에서만 — 모든 슬롯이 '듣는 중'이면 어디에 말하는지 모른다 */}
      {isTarget && v.message && (
        <span className="text-white/45 truncate max-w-[10rem]">{v.message}</span>
      )}
      {v.error && (
        <span className="text-red-300/80 truncate max-w-[12rem]" title={v.error}>{v.error}</span>
      )}
    </div>
  );
}
