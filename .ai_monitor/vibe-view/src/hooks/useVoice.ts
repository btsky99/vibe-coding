/**
 * ------------------------------------------------------------------------
 * 📄 파일명: hooks/useVoice.ts
 * 📝 설명: lib/voiceBus.ts(전역 싱글턴)를 React 에 잇는 얇은 층. 상태 구독과
 *          슬롯 등록/해제만 한다 — 음성 로직은 여기 두지 않는다.
 *
 *          [🔴 왜 얇아야 하나] TerminalSlot 은 여러 개 마운트된다. 훅에 엔진 상태를
 *          두면 슬롯 수만큼 복제되어 '어느 인스턴스가 진짜인지' 알 수 없게 된다.
 *          엔진은 하나(voiceBus), 훅은 그 창문일 뿐이다.
 *
 * REVISION HISTORY:
 * - 2026-08-15 Claude: 최초 작성
 * ------------------------------------------------------------------------
 */

import { useEffect, useRef, useSyncExternalStore } from 'react';
import { voiceBus, type SlotBinding, type VoiceState } from '../lib/voiceBus';

/** 음성 엔진의 현재 상태를 구독한다. */
export function useVoiceState(): VoiceState {
  return useSyncExternalStore(voiceBus.subscribe, voiceBus.getSnapshot, voiceBus.getSnapshot);
}

/**
 * 이 슬롯을 음성 대상 후보로 등록한다.
 *
 * [🔴 콜백을 ref 로 감싸는 이유] onText/onSubmit 은 렌더마다 새 함수다. 그대로 의존성에
 *   넣으면 매 렌더에서 등록/해제가 돌아 말하는 도중에 바인딩이 갈린다. 등록은 id·호출어가
 *   바뀔 때만 하고, 함수는 최신 것을 ref 로 읽는다.
 */
export function useVoiceSlot(
  id: string,
  wakeWord: string,
  onText: (text: string) => void,
  onSubmit: (text: string) => void,
): void {
  const handlers = useRef({ onText, onSubmit });
  handlers.current = { onText, onSubmit };

  useEffect(() => {
    const binding: SlotBinding = {
      id,
      wakeWord,
      onText: (t) => handlers.current.onText(t),
      onSubmit: (t) => handlers.current.onSubmit(t),
    };
    voiceBus.registerSlot(binding);
    return () => voiceBus.unregisterSlot(id);
  }, [id, wakeWord]);
}
