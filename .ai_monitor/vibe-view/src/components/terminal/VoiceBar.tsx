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
 * - 2026-08-15 Claude: 줄이 어긋나 보인다는 지적 — 실측하니 호출어 버튼만 높이 21px·
 *   top +2px 였다(나머지는 25px·0). 높이를 BTN 한 곳으로 묶고, 평평하게 늘어서 있던
 *   다섯 개를 '입력 | 출력 | 이름' 세 묶음으로 가른다
 * ------------------------------------------------------------------------
 */

import { useState } from 'react';
import { Mic, MicOff, Loader2, Square, Volume2, Check } from 'lucide-react';
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

/**
 * 모든 조작 요소의 공통 치수.
 *
 * [🔴 높이를 여기 한 곳에서만 정한다] 예전엔 버튼마다 py 를 따로 썼고, 호출어 버튼만
 *   py-0.5 라 혼자 4px 낮게 앉아 줄 전체가 어긋나 보였다(실측 25px vs 21px). 패딩으로
 *   높이를 만들면 글자 수·아이콘 유무에 따라 언제든 다시 어긋난다 — h 를 고정한다.
 */
const BTN = 'h-[25px] shrink-0 flex items-center gap-1 px-2 rounded border transition-colors';

/** 묶음 사이 구분선. [WHY] 다섯 개가 같은 간격으로 늘어서면 무엇이 한 벌인지 안 보인다. */
function Divider() {
  return <span className="w-px h-3.5 bg-white/10 shrink-0" aria-hidden />;
}

/**
 * 바에 표시할 짧은 목소리 이름.
 *
 * [WHY 자르나] 서버가 주는 label 은 'Microsoft Heami - Korean' 처럼 길다. 좁은 슬롯에서
 *   이것만 폭을 두 배로 먹어 줄의 무게중심이 오른쪽으로 쏠린다. 전체 이름은 ⚙ 을 열면 있다.
 */
function shortVoice(label: string): string {
  return label.replace(/^Microsoft\s+/i, '').split(/\s+[-–]\s+/)[0].trim();
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

  const rawLabel = v.voices.find((o) => o.id === (v.voice || v.voices[0]?.id))?.label || '';
  const voiceLabel = rawLabel ? shortVoice(rawLabel) : '목소리';

  return (
    <div className="flex items-center gap-1.5 text-[10px] relative">
      {/* ── ① 말한다 ─────────────────────────────────────────────────────────
          [WHY 이 둘이 한 묶음인가] 둘 다 '내 목소리를 넣는' 수단이고, 하나를 쓰면
          다른 하나가 필요 없다. 붙여 놓아야 고르는 것임이 보인다. */}
      <div className="flex items-center gap-1 shrink-0">
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
          className={`${BTN} ${
            isTarget && v.speaking
              ? 'bg-red-500/30 border-red-400/60 text-red-200'
              : 'bg-[#3c3c3c] border-white/10 hover:bg-white/10 text-white/70'
          }`}
        >
          {busy ? <Loader2 size={12} className="animate-spin" /> : <Mic size={12} />}
          <span>말하기</span>
        </button>

        {/* 상시 대기 — 호출어로 부르면 깨어난다.
            [🔴 입력 레벨을 버튼 '안'에 깐 이유] 예전엔 옆에 따로 둔 막대라, 켤 때마다
              그 폭만큼 뒤쪽 버튼이 통째로 밀렸다. 레벨은 이 버튼의 상태이므로 배경으로
              깔면 폭이 변하지 않고, 소리에 반응해 차오르는 게 그대로 보인다. */}
        <button
          onClick={() => (v.enabled ? voiceBus.disable() : void voiceBus.enable())}
          title={v.enabled ? '상시 대기 끄기' : '상시 대기 켜기 (호출어로 부르면 반응)'}
          className={`${BTN} relative overflow-hidden ${
            v.enabled
              ? 'bg-primary/20 border-primary/40 text-primary'
              : 'bg-[#3c3c3c] border-white/10 hover:bg-white/10 text-white/50'
          }`}
        >
          {v.enabled && (
            <span
              className="absolute inset-y-0 left-0 bg-primary/30 transition-[width] duration-100 pointer-events-none"
              style={{ width: `${Math.round(v.level * 100)}%` }}
              aria-hidden
            />
          )}
          <span className="relative flex items-center gap-1">
            {v.enabled ? <Mic size={12} /> : <MicOff size={12} />}
            <span>{v.enabled ? '듣는 중' : '상시 대기'}</span>
          </span>
        </button>
      </div>

      <Divider />

      {/* ── ② 듣는다 ─────────────────────────────────────────────────────────
          켤지 말지(체크) 와 어떤 목소리로(이름) 는 한 벌이다. */}
      <div className="flex items-center gap-1 min-w-0">
        <button
          onClick={() => voiceBus.setTts(!v.ttsOn, terminalId)}
          title={v.ttsOn ? '답 낭독 끄기' : '답 낭독 켜기'}
          className={`${BTN} ${
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

        {/* 목소리 고르기.
            [WHY 톱니가 아니라 스피커인가] 톱니는 '이 줄 전체의 설정'으로 읽힌다. 실제로는
              읽어 주는 목소리 하나를 고르는 것이라, 소리 아이콘이 짝을 정확히 가리킨다. */}
        <button
          onClick={() => {
            // [🔴 여기서 checkReady 를 부르는 이유] 사이드카는 첫 status 요청 때 뜬다.
            //   패널을 열었는데 목록이 비어 있으면 사용자는 '목소리가 없다'고 읽는다.
            if (!showSettings) void voiceBus.checkReady();
            setShowSettings((s) => !s);
          }}
          title={rawLabel ? `읽어 주는 목소리: ${rawLabel}` : '어떤 목소리로 읽을지 고릅니다'}
          className={`${BTN} max-w-[8rem] ${
            showSettings
              ? 'bg-primary/25 border-primary/40 text-primary'
              : 'bg-[#3c3c3c] border-white/10 hover:bg-white/10 text-white/60'
          }`}
        >
          <Volume2 size={12} className="shrink-0" />
          <span className="truncate">{voiceLabel}</span>
        </button>
      </div>
      {showSettings && <VoiceSettings onClose={() => setShowSettings(false)} />}

      <Divider />

      {/* ── ③ 이 슬롯을 부르는 말 ────────────────────────────────────────────
          슬롯마다 다른 유일한 값이다. 그래서 앞의 두 묶음(전역 설정)과 떼어 둔다. */}
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
          className="h-[25px] w-24 shrink-0 bg-[#1e1e1e] border border-primary/40 rounded px-2
                     text-[10px] text-white focus:outline-none"
        />
      ) : (
        <button
          onClick={() => { setDraft(wakeWord); setEditing(true); }}
          title="이 슬롯을 부르는 말을 정합니다 (예: 클로드)"
          className={`${BTN} ${
            wakeWord
              ? 'border-white/10 bg-[#3c3c3c] text-white/70 hover:bg-white/10'
              : 'border-dashed border-white/20 text-white/35 hover:text-white/60'
          }`}
        >
          {wakeWord ? `“${wakeWord}”` : '호출어 설정'}
        </button>
      )}

      {/* ── 오른쪽: 지금 벌어지는 일 ─────────────────────────────────────────
          [🔴 ml-auto 로 오른쪽에 몰아 둔다] 낭독 정지·상태 문구·에러는 상황에 따라
            나타났다 사라진다. 버튼들 사이에 두면 그때마다 왼쪽 줄이 통째로 밀려
            '가만히 있는데 배치가 바뀌는' 화면이 된다. 오른쪽 끝에서 자라면 안 밀린다. */}
      <div className="ml-auto flex items-center gap-1.5 min-w-0">
        {v.playing && (
          <button
            onClick={() => voiceBus.stopSpeaking()}
            className={`${BTN} border-white/10 bg-[#3c3c3c] hover:bg-white/10 text-white/70`}
            title="그만 읽기"
          >
            <Square size={9} />
            <span>그만</span>
          </button>
        )}
        {/* 상태 문구는 대상 슬롯에서만 — 모든 슬롯이 '듣는 중'이면 어디에 말하는지 모른다 */}
        {isTarget && v.message && (
          <span className="text-white/45 truncate">{v.message}</span>
        )}
        {v.error && (
          <span className="text-red-300/80 truncate max-w-[12rem]" title={v.error}>{v.error}</span>
        )}
      </div>
    </div>
  );
}
