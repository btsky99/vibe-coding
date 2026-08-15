/**
 * ------------------------------------------------------------------------
 * 📄 파일명: components/terminal/VoiceBar.tsx
 * 📝 설명: 전송창 바로 아래 한 줄짜리 음성 막대 — 답 소리 듣기, 호출어 부르기,
 *          이 슬롯의 호출어, 지금 상태, 목소리 고르기.
 *
 *          [🔴 자리가 고정이다 — 접어 넣지 말 것] 아픽스 보드와 같은 배치다. 이 줄을
 *          설정 안으로 숨기거나 조건부 렌더 안에 넣으면 다른 화면에서 통째로 사라진다.
 *          실제로 그 사고가 있었다(wiki/함정/음성 입출력 함정.md — VoiceBar 를
 *          isTerminalMode 안에 뒀다가 선택 카드 화면에서 마이크가 없어졌다).
 *
 *          [🔴 상태는 전역, 표시는 슬롯마다] 마이크는 앱에 하나뿐이므로 어느 슬롯의
 *          VoiceBar 를 눌러도 같은 엔진을 조작한다. 다만 '지금 대상이 나인가'(target)와
 *          호출어는 슬롯마다 다르게 그린다 — 안 그러면 세 슬롯이 전부 '듣는 중'으로
 *          보여서 어디에 말하는지 알 수 없다.
 *
 *          [🔴 🎤 는 여기 있을 때도, 없을 때도 있다] 터미널이 열려 있으면 마이크 단추는
 *          전송창 왼쪽에 붙는다(보드와 같은 자리). 전송창이 없는 화면에서는 이 막대가
 *          대신 그린다 — showMic. **둘 중 하나는 항상 있다**가 불변식이다.
 *
 *          [WHY 마이크 권한 안내를 눈에 보이게 두나] WebView2 는 권한이 막히면 아무
 *          에러 없이 조용히 멈춘다(실측). 그때 사용자가 의심하는 것은 자기 마이크다.
 *
 * REVISION HISTORY:
 * - 2026-08-15 Claude: 최초 작성 — 로컬 음성(STT/TTS) UI
 * - 2026-08-15 Claude: 아이콘만으로는 무슨 기능인지 안 보인다는 지적 — 글자 라벨과
 *   낭독 체크박스를 붙이고, 목소리 선택(⚙ VoiceSettings)을 연다
 * - 2026-08-15 Claude: 아픽스 보드와 같은 조작 모양으로 — ①누르고 말하기(떼면 바로 전송)
 *   ②답 소리 듣기 체크 ③호출어 부르기 체크(기본 꺼짐) ④호출어를 쉼표로 여러 개
 * - 2026-08-15 Claude: 줄이 어긋나 보인다는 지적 — 실측하니 호출어 버튼만 높이 21px·
 *   top +2px 였다(나머지는 25px·0). 높이를 BTN 한 곳으로 묶고, 평평하게 늘어서 있던
 *   다섯 개를 '입력 | 출력 | 이름' 세 묶음으로 가른다
 * - 2026-08-15 Claude: 보드와 같은 순서로 재배치(듣기 → 부르기 → 호출어 → 상태 → 목소리).
 *   🎤 는 전송창으로 이사(MicPressButton), 여기서는 전송창이 없을 때만 그린다
 * ------------------------------------------------------------------------
 */

import { useState } from 'react';
import { Mic, MicOff, Square, Volume2, Check } from 'lucide-react';
import { voiceBus } from '../../lib/voiceBus';
import { wakeWordWarning } from '../../lib/speech';
import { useVoiceState } from '../../hooks/useVoice';
import MicPressButton from './MicPressButton';
import VoiceSettings from './VoiceSettings';

interface Props {
  /** 'T1' 형식 */
  terminalId: string;
  /** 이 슬롯을 부르는 말. 쉼표로 여러 개. 비어 있으면 호출어로 못 부른다. */
  wakeWord: string;
  onWakeWordChange: (w: string) => void;
  /** 전송창이 화면에 없어서 이 막대가 마이크 단추까지 그려야 하는가. */
  showMic?: boolean;
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

/** 체크 표시 한 칸 — 답 듣기·호출어 두 곳이 같은 모양이어야 한 벌로 읽힌다. */
function Box({ on }: { on: boolean }) {
  return (
    <span
      className={`w-3 h-3 rounded-[3px] border flex items-center justify-center ${
        on ? 'bg-primary border-primary text-white' : 'border-white/30'
      }`}
    >
      {on && <Check size={9} strokeWidth={3} />}
    </span>
  );
}

export default function VoiceBar({ terminalId, wakeWord, onWakeWordChange, showMic }: Props) {
  const v = useVoiceState();
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(wakeWord);
  const [showSettings, setShowSettings] = useState(false);

  const isTarget = v.target === terminalId;

  const commit = () => {
    setEditing(false);
    // [🔴 상한을 12→60 으로 올렸다] 쉼표로 변형을 여러 개 적게 했으므로 한 낱말 기준의
    //   상한은 더 이상 맞지 않는다("클로드, 클로드야, 크로드"만 해도 15자다).
    const clean = draft.trim().slice(0, 60);
    if (clean !== wakeWord) onWakeWordChange(clean);
  };

  const rawLabel = v.voices.find((o) => o.id === (v.voice || v.voices[0]?.id))?.label || '';
  const voiceLabel = rawLabel ? shortVoice(rawLabel) : '목소리';
  // 편집 중에는 지금 치고 있는 값에 대해, 아닐 때는 저장된 값에 대해 경고한다.
  const wakeWarning = wakeWordWarning(editing ? draft : wakeWord);

  return (
    <div className="flex items-center gap-1.5 text-[10px] relative">
      {/* 전송창이 없는 화면에서만 — 마이크가 어느 화면에서도 사라지지 않게(헤더 불변식) */}
      {showMic && (
        <>
          <MicPressButton terminalId={terminalId} />
          <Divider />
        </>
      )}

      {/* ── ① 답을 소리로 듣기 ───────────────────────────────────────────────
          [🔴 마이크와 독립이다] 손으로 치고 답만 귀로 듣는 것이 정상적인 사용법이다.
            마이크가 꺼져 있어도 이 체크는 살아 있어야 한다(voiceBus.setTts 주석). */}
      <button
        onClick={() => voiceBus.setTts(!v.ttsOn, terminalId)}
        title={v.ttsOn ? '답 낭독 끄기' : '답 낭독 켜기'}
        className={`${BTN} ${
          v.ttsOn
            ? 'bg-primary/25 border-primary/40 text-primary'
            : 'bg-[#3c3c3c] border-white/10 hover:bg-white/10 text-white/50'
        }`}
      >
        <Box on={v.ttsOn} />
        <span>답을 소리로 듣기</span>
      </button>

      {/* ── ② 호출어로 부르기(상시 대기) ─────────────────────────────────────
          [🔴 기본은 꺼짐이고, 켜는 것은 사람이다] 켜져 있는 동안 마이크가 계속 열려
            있다. 앱이 알아서 켜면 사용자는 자기가 언제부터 청취당했는지 모른다.
          [🔴 입력 레벨을 단추 '안'에 깐 이유] 예전엔 옆에 따로 둔 막대라, 켤 때마다
            그 폭만큼 뒤쪽 단추가 통째로 밀렸다. 레벨은 이 단추의 상태이므로 배경으로
            깔면 폭이 변하지 않고, 소리에 반응해 차오르는 게 그대로 보인다. */}
      <button
        onClick={() => (v.enabled ? voiceBus.disable() : void voiceBus.enable())}
        title={v.enabled
          ? '호출어 대기 끄기 (마이크를 닫습니다)'
          : '호출어 대기 켜기 — 켜 두는 동안 마이크가 계속 열려 있습니다'}
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
          <Box on={v.enabled} />
          {v.enabled ? <Mic size={12} /> : <MicOff size={12} />}
          {/* 보드처럼 부르는 말을 라벨에 넣는다 — 무엇이라고 불러야 하는지가 곧 기능 설명이다 */}
          <span>{wakeWord ? `“${wakeWord.split(',')[0].trim()}”로 부르기` : '호출어로 부르기'}</span>
        </span>
      </button>

      {/* ── ③ 이 슬롯을 부르는 말 ────────────────────────────────────────────
          슬롯마다 다른 유일한 값이다.
          [🔴 쉼표로 여러 개] 사용자가 아무 낱말이나 정하므로 발음 변형을 우리가 만들어
            줄 수 없다(speech.ts parseWakeWords 주석). 본인이 직접 적게 한다. */}
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
          placeholder="예: 클로드, 클로드야"
          title="쉼표로 여러 개를 넣을 수 있습니다. 띄어쓰기·대소문자는 무시합니다"
          className={`h-[25px] w-40 shrink-0 bg-[#1e1e1e] border rounded px-2
                     text-[10px] text-white focus:outline-none ${
                       wakeWordWarning(draft) ? 'border-amber-400/60' : 'border-primary/40'
                     }`}
        />
      ) : (
        <button
          onClick={() => { setDraft(wakeWord); setEditing(true); }}
          title="이 슬롯을 부르는 말 (쉼표로 여러 개 — 예: 클로드, 클로드야)"
          className={`${BTN} max-w-[10rem] ${
            wakeWord
              ? 'border-white/10 bg-[#3c3c3c] text-white/70 hover:bg-white/10'
              : 'border-dashed border-white/20 text-white/35 hover:text-white/60'
          }`}
        >
          <span className="truncate">{wakeWord ? '호출어 바꾸기' : '호출어 설정'}</span>
        </button>
      )}

      {/* 호출어에 대한 경고.
          [🔴 막지 않고 알린다] 짧은 호출어가 늘 틀린 것은 아니다. 다만 대가(아무 말에나
            깨어남)를 모른 채 고르면 사용자는 인식기를 탓하게 된다. */}
      {wakeWarning && (
        <span className="text-amber-300/80 truncate max-w-[13rem]" title={wakeWarning}>
          ⚠ {wakeWarning}
        </span>
      )}
      {v.enabled && !wakeWord && (
        <span className="text-amber-300/80">⚠ 호출어를 먼저 정하세요</span>
      )}

      {/* ── 오른쪽: 지금 벌어지는 일 + 목소리 ────────────────────────────────
          [🔴 ml-auto 로 오른쪽에 몰아 둔다] 낭독 정지·상태 문구·에러는 상황에 따라
            나타났다 사라진다. 단추들 사이에 두면 그때마다 왼쪽 줄이 통째로 밀려
            '가만히 있는데 배치가 바뀌는' 화면이 된다. 오른쪽 끝에서 자라면 안 밀린다. */}
      <div className="ml-auto flex items-center gap-1.5 min-w-0">
        {/* 상태 문구는 대상 슬롯에서만 — 모든 슬롯이 '듣는 중'이면 어디에 말하는지 모른다 */}
        {isTarget && v.message && (
          <span className="text-white/45 truncate" role="status" aria-live="polite">{v.message}</span>
        )}
        {v.error && (
          <span className="text-red-300/80 truncate max-w-[12rem]" title={v.error}>{v.error}</span>
        )}
        {v.playing && (
          <button
            onClick={() => voiceBus.stopSpeaking()}
            className={`${BTN} border-white/10 bg-[#3c3c3c] hover:bg-white/10 text-white/70`}
            title="그만 읽기"
          >
            <Square size={9} />
            <span>그만 읽기</span>
          </button>
        )}

        {/* 목소리 고르기.
            [WHY 톱니가 아니라 스피커인가] 톱니는 '이 줄 전체의 설정'으로 읽힌다. 실제로는
              읽어 주는 목소리 하나를 고르는 것이라, 소리 아이콘이 짝을 정확히 가리킨다. */}
        <button
          onClick={() => {
            // [🔴 여기서 사이드카를 깨우는 이유] 목록의 '더 나은 목소리'는 사이드카가
            //   떠야 나온다. 브라우저 목소리는 이미 채워져 있으므로 패널이 비지는 않는다.
            if (!showSettings) voiceBus.ensureSidecar();
            setShowSettings((s) => !s);
          }}
          aria-expanded={showSettings}
          title={rawLabel ? `읽어 주는 목소리: ${rawLabel}` : '어떤 목소리로 읽을지 고릅니다'}
          className={`${BTN} max-w-[8rem] ${
            showSettings
              ? 'bg-primary/25 border-primary/40 text-primary'
              : 'bg-[#3c3c3c] border-white/10 hover:bg-white/10 text-white/60'
          }`}
        >
          <Volume2 size={12} className="shrink-0" />
          <span className="truncate">{voiceLabel}…</span>
        </button>

        {/* 어디로 나가는지 적어 둔다.
            [🔴 보드와 사실이 다르다] 아픽스 보드는 브라우저 인식기라 "구글로 전송"이라고
              적는다. 이 앱은 받아쓰기를 이 PC 안 사이드카(faster-whisper)가 하고, 낭독도
              이 PC 내장 목소리라 밖으로 나가는 것이 없다. 문구를 그대로 베끼면 거짓말이
              되므로 사실대로 적는다 — 사람이 알고 켜야 한다는 취지는 같다. */}
        <span className="text-white/25 shrink-0 hidden sm:inline">말은 이 PC 안에서 받아씁니다</span>
      </div>

      {showSettings && <VoiceSettings onClose={() => setShowSettings(false)} />}
    </div>
  );
}
