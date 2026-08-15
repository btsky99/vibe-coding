/**
 * ------------------------------------------------------------------------
 * 📄 파일명: lib/browserVoice.ts
 * 📝 설명: 브라우저(WebView2) 내장 합성기로 읽는 길. 서버 사이드카 없이 즉시 말한다.
 *          voiceBus 가 '먼저 시도하는 길'로 쓰고, 실패하면 사이드카로 넘어간다.
 *
 *          [🔴 왜 이 길을 먼저 두나 — 2026-08-15 사고] 낭독이 사이드카 하나뿐이라,
 *          첫 기동(모델 로딩 ~2분) 동안 화면이 '음성 엔진 준비 중'에 묶였다. 브라우저
 *          합성기는 프로세스도 모델도 없어서 **준비 상태라는 개념 자체가 없다**
 *          (아픽스 보드가 이 구조다 — 그쪽엔 '준비 중'이 존재하지 않는다).
 *
 *          [실측 2026-08-15 — 이 앱이 잡는 목소리는 하나뿐] WebView2(Edg/151) 에서
 *          speechSynthesis.getVoices() = **1개**: Microsoft Heami (ko-KR, localService).
 *          크롬이 주는 'Google 한국의' 계열 온라인 목소리는 **안 보인다** — WebView2 는
 *          OS(SAPI) 목소리만 노출한다. 목록이 늘어날 것을 전제한 코드를 쓰지 말 것.
 *          같은 실측에서 사용자 클릭 없이(페이지 로드만으로) 339ms 만에 소리가 났다 —
 *          자동재생 정책에 막히지 않는다.
 *
 *          [제약] getVoices() 는 첫 호출에서 비어 있을 수 있다. voiceschanged 를 기다려야
 *          하고, 그 이벤트가 영영 안 오는 환경도 있어 폴링을 겸한다.
 *
 * REVISION HISTORY:
 * - 2026-08-15 Claude: 최초 작성 — 사이드카를 기다리지 않는 낭독 경로
 * ------------------------------------------------------------------------
 */

import { chunkSentences, sortVoices, TONES } from './speech';

/** voiceBus.VoiceOption 과 같은 모양. [WHY 임포트 안 하나] 서로 참조하면 순환이 된다. */
export interface BrowserVoiceOption {
  id: string;
  label: string;
  engine: string;
  lang: string;
  note?: string;
}

/** 브라우저 목소리 id 앞에 붙는 표시. 사이드카 목소리('sapi:', 'sherpa:')와 섞이지 않게 한다. */
export const WEB_PREFIX = 'web:';

export function isWebVoiceId(id: string): boolean {
  return String(id || '').startsWith(WEB_PREFIX);
}

export function browserTtsAvailable(): boolean {
  return typeof window !== 'undefined'
    && 'speechSynthesis' in window
    && typeof SpeechSynthesisUtterance === 'function';
}

function rawVoices(): SpeechSynthesisVoice[] {
  if (!browserTtsAvailable()) return [];
  try {
    return window.speechSynthesis.getVoices() || [];
  } catch {
    return [];
  }
}

/** 지금 이 PC 에서 바로 쓸 수 있는 목소리. 한국어 우선·점수순(speech.ts). */
export function browserVoiceOptions(): BrowserVoiceOption[] {
  return sortVoices(rawVoices()).map((v) => ({
    id: WEB_PREFIX + v.voiceURI,
    label: v.name,
    engine: 'web',
    lang: (v.lang || '').toLowerCase().startsWith('ko') ? 'ko' : (v.lang || ''),
    note: '이 PC 내장 · 기다림 없음',
  }));
}

/**
 * 목록이 준비되면 알려 준다.
 *
 * [🔴 이벤트만 믿으면 안 된다] WebView2 는 voiceschanged 를 한 번도 안 쏘고 시작부터
 *   목록을 갖고 있는 경우가 있다. 반대로 첫 getVoices() 가 빈 배열인 경우도 있어,
 *   이벤트와 짧은 폴링을 둘 다 건다. 목록이 한 번이라도 차면 폴링을 멈춘다.
 */
export function watchBrowserVoices(cb: () => void): () => void {
  if (!browserTtsAvailable()) return () => {};
  let stopped = false;
  const onChange = () => { if (!stopped) cb(); };
  try { window.speechSynthesis.addEventListener('voiceschanged', onChange); } catch { /* 구형 */ }

  let tries = 0;
  const tick = () => {
    if (stopped) return;
    if (rawVoices().length > 0) { cb(); return; }
    if (tries++ > 25) return;                      // 5초까지만 — 없으면 없는 것이다
    setTimeout(tick, 200);
  };
  tick();

  return () => {
    stopped = true;
    try { window.speechSynthesis.removeEventListener('voiceschanged', onChange); } catch { /* 무시 */ }
  };
}

export function cancelBrowserSpeech(): void {
  if (!browserTtsAvailable()) return;
  try { window.speechSynthesis.cancel(); } catch { /* 이미 멈춤 */ }
}

interface SpeakOpts {
  /** 'web:...' 형식. 없거나 이 PC 에 없는 id 면 한국어 1순위를 쓴다. */
  voiceId?: string;
  /** 사용자가 고른 배율(0.5~1.5). 프리셋 rate 에 곱한다. */
  speed?: number;
  /** 첫 소리가 실제로 나기 시작한 순간 — 화면 상태를 여기서 바꾼다. */
  onStart?: () => void;
}

/**
 * 문장을 쪼개 사이를 두고 읽는다.
 *
 * [🔴 '기계 같음'의 진짜 원인은 목소리가 아니라 사이다 — 아픽스 실측] 같은 Heami 라도
 *   두세 문장을 쉼 없이 이어 붙이면 딱딱하게 들린다. 사람은 문장 끝에서 숨을 쉰다.
 * [🔴 조각마다 감시 타이머를 둔다] Chromium 은 합성이 길거나 창이 백그라운드로 가면
 *   end 이벤트를 안 쏘는 일이 있다. 그때 await 가 영원히 안 풀리면 낭독이 통째로 멈추고
 *   playing 이 true 로 굳어 마이크가 계속 뮤트된다 — 다음 말이 영영 안 들어간다.
 *
 * @returns 한 조각이라도 실제로 읽었으면 true. 하나도 못 읽었으면 false(→ 호출부가 사이드카로 넘어간다)
 */
export async function speakBrowser(text: string, opts: SpeakOpts = {}): Promise<boolean> {
  if (!browserTtsAvailable()) return false;
  const chunks = chunkSentences(text);
  if (!chunks.length) return false;

  const tone = TONES.normal;                       // 톤 UI 는 아직 없다 — 중립값 고정
  const rate = Math.max(0.5, Math.min(2, tone.rate * (opts.speed ?? 1)));

  const all = rawVoices();
  const picked = (opts.voiceId && isWebVoiceId(opts.voiceId)
    ? all.find((v) => WEB_PREFIX + v.voiceURI === opts.voiceId)
    : null) ?? sortVoices(all)[0] ?? null;

  cancelBrowserSpeech();
  let spokeAny = false;
  let started = false;

  for (const chunk of chunks) {
    const ok = await new Promise<boolean>((resolve) => {
      let done = false;
      const finish = (v: boolean) => { if (!done) { done = true; resolve(v); } };
      try {
        const u = new SpeechSynthesisUtterance(chunk);
        if (picked) { u.voice = picked; u.lang = picked.lang; }
        u.rate = rate;
        u.pitch = tone.pitch;
        u.volume = tone.vol;
        u.onstart = () => {
          if (!started) { started = true; opts.onStart?.(); }
        };
        u.onend = () => finish(true);
        u.onerror = () => finish(false);
        window.speechSynthesis.speak(u);
        // 글자 수 기반 상한 — 한글은 초당 대략 6~8자다. 넉넉히 2배를 준다.
        setTimeout(() => finish(started), Math.max(4000, chunk.length * 320));
      } catch {
        finish(false);
      }
    });
    if (ok) spokeAny = true;
    else if (!spokeAny) return false;              // 첫 조각부터 실패 = 이 길은 못 쓴다
    await new Promise((r) => setTimeout(r, tone.gap));
  }
  return spokeAny;
}
