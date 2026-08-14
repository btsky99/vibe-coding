/**
 * ------------------------------------------------------------------------
 * 📄 파일명: lib/voiceBus.ts
 * 📝 설명: 음성 입출력의 전역 단일 소유자. 마이크 한 개를 잡고, 인식된 말이 어느
 *          터미널 슬롯의 것인지 호출어로 가려 그 슬롯에 넘긴다. 낭독도 여기서 한다.
 *
 *          [🔴 왜 싱글턴인가 — 이 앱 고유의 함정] TerminalSlot 은 화면에 여러 개
 *          렌더링된다. 슬롯마다 마이크를 열면 인식기들이 같은 장치를 두고 다투다
 *          전부 죽는다(아픽스도 인식기 둘이 겹치는 것을 금지했다 — 거긴 웨이크워드와
 *          받아쓰기 둘뿐이었고, 여기는 슬롯 수만큼이라 더 나쁘다).
 *          그래서 엔진은 하나, 바뀌는 것은 '지금 누구에게 말하는가(target)'뿐이다.
 *
 *          [🔴 인식은 서버가 한다] 브라우저 SpeechRecognition 은 오디오를 구글로
 *          보낸다. 로컬 오픈소스 전환(2026-08-15 사용자 결정)의 요지가 그 전송을
 *          없애는 것이라, 캡처(audioCapture)→서버(/api/voice/stt) 경로를 쓴다.
 *
 *          [불변식] 낭독 중에는 마이크를 뮤트한다. 안 하면 스피커로 나간 제 목소리를
 *          다시 받아적어 스스로에게 명령한다. 브라우저 에코 제거가 1차, 이게 2차다.
 *
 * REVISION HISTORY:
 * - 2026-08-15 Claude: 최초 작성 — 로컬 STT/TTS + 슬롯별 호출어
 * ------------------------------------------------------------------------
 */

import { API_BASE } from '../constants';
import { MicCapture } from './audioCapture';
import { matchWakeWord, toSpeech } from './speech';

export interface SlotBinding {
  /** 'T1' 형식. TerminalSlot 의 terminalId 와 같아야 한다(턴 조회 키로도 쓰인다). */
  id: string;
  /** 이 슬롯을 부르는 말. 비어 있으면 호출어로는 못 부르고 마이크 버튼으로만 쓴다. */
  wakeWord: string;
  /** 받아쓴 문장을 입력창에 넣는다. */
  onText: (text: string) => void;
  /** 넣은 문장을 보낸다. */
  onSubmit: (text: string) => void;
}

export interface VoiceState {
  /** 상시 대기(마이크 열림)를 켰는가. */
  enabled: boolean;
  /** 지금 사람이 말하는 중인가(VAD 판정). */
  speaking: boolean;
  /** 입력 레벨 0~1 — 마이크가 살아 있음을 눈으로 확인하는 유일한 수단. */
  level: number;
  /** 서버가 인식/합성 중인가. */
  busy: boolean;
  /** 낭독 재생 중인가. */
  playing: boolean;
  /** 답을 소리로 들을 것인가. */
  ttsOn: boolean;
  /** 지금 말 거는 대상 슬롯('T1'). 호출어로 정해진다. */
  target: string | null;
  /** 화면에 보여 줄 짧은 상태 문구. */
  message: string;
  /** 서버 음성 엔진이 준비됐는가(사이드카 기동 여부). */
  ready: boolean;
  /** 마지막 오류 — 조용히 죽지 않게 사람에게 보인다. */
  error: string;
  /** 고를 수 있는 목소리 — 서버가 실제로 합성 가능한 것만 준다. */
  voices: VoiceOption[];
  /** 지금 고른 목소리 id. 빈 값이면 서버 기본값. */
  voice: string;
  /** 낭독 속도 배율(0.5~1.5). */
  speed: number;
}

export interface VoiceOption {
  id: string;
  label: string;
  engine: string;
  lang: string;
  note?: string;
}

const TTS_KEY = 'vibe.voice.tts';
const WAKE_ENABLED_KEY = 'vibe.voice.enabled';
const VOICE_KEY = 'vibe.voice.id';
const SPEED_KEY = 'vibe.voice.speed';

/** 답을 다 읽은 뒤 이 시간 동안은 호출어 없이 바로 이어 말할 수 있다. */
const FOLLOW_MS = 12000;

class VoiceBus {
  private state: VoiceState = {
    enabled: false,
    speaking: false,
    level: 0,
    busy: false,
    playing: false,
    ttsOn: (() => { try { return localStorage.getItem(TTS_KEY) !== '0'; } catch { return true; } })(),
    target: null,
    message: '',
    ready: false,
    error: '',
    voices: [],
    // [WHY localStorage 인가] 목소리는 이 PC 에 뭐가 깔려 있느냐에 달린 기기별 취향이다.
    //   프로젝트 config(=다른 PC 와도 공유되는 값)에 넣으면 그 PC 에 없는 목소리를 가리킨다.
    voice: (() => { try { return localStorage.getItem(VOICE_KEY) || ''; } catch { return ''; } })(),
    speed: (() => {
      try { return Number(localStorage.getItem(SPEED_KEY)) || 1.0; } catch { return 1.0; }
    })(),
  };

  private listeners = new Set<() => void>();
  private slots = new Map<string, SlotBinding>();
  private mic: MicCapture | null = null;
  private audio: HTMLAudioElement | null = null;
  private followUntil = 0;
  private turnSeq = new Map<string, number>();
  private turnTimer: ReturnType<typeof setTimeout> | null = null;
  /** 누르고 말하기로 강제 지정된 슬롯 — 놓을 때까지 호출어를 무시한다. */
  private pressSlot: string | null = null;

  /* ── 구독(useSyncExternalStore) ──────────────────────────────────────── */

  subscribe = (fn: () => void): (() => void) => {
    this.listeners.add(fn);
    return () => { this.listeners.delete(fn); };
  };

  getSnapshot = (): VoiceState => this.state;

  private set(patch: Partial<VoiceState>): void {
    // [WHY 새 객체인가] useSyncExternalStore 는 참조 동일성으로 변경을 판단한다.
    //   제자리 수정하면 화면이 안 바뀐다.
    this.state = { ...this.state, ...patch };
    this.listeners.forEach((fn) => fn());
  }

  /* ── 슬롯 등록 ───────────────────────────────────────────────────────── */

  registerSlot(b: SlotBinding): void {
    this.slots.set(b.id, b);
  }

  unregisterSlot(id: string): void {
    this.slots.delete(id);
    if (this.state.target === id) this.set({ target: null });
    if (this.pressSlot === id) this.pressSlot = null;
  }

  /* ── 켜고 끄기 ───────────────────────────────────────────────────────── */

  /** 저장된 설정을 복원한다. [제약] 마이크는 사용자 제스처 뒤에만 열리므로 여기서 켜지 않는다. */
  restore(): boolean {
    try { return localStorage.getItem(WAKE_ENABLED_KEY) === '1'; } catch { return false; }
  }

  async enable(): Promise<void> {
    if (this.mic) return;
    const mic = new MicCapture({
      onUtterance: (wav) => { void this.onUtterance(wav); },
      onSpeechState: (speaking) => this.set({ speaking }),
      onLevel: (level) => {
        // [WHY 반올림하나] 레벨은 초당 수십 번 온다. 그대로 흘리면 그때마다 리렌더가
        //   돌아 터미널 렌더링과 경합한다. 눈에 보이는 해상도까지만 올린다.
        const q = Math.round(level * 10) / 10;
        if (q !== this.state.level) this.set({ level: q });
      },
      onError: (e) => this.set({ error: String(e), message: '마이크를 열 수 없습니다' }),
    });
    try {
      await mic.start();
    } catch {
      this.set({ enabled: false, message: '마이크 권한이 필요합니다' });
      return;
    }
    this.mic = mic;
    try { localStorage.setItem(WAKE_ENABLED_KEY, '1'); } catch { /* 저장 실패는 무시 */ }
    this.set({ enabled: true, message: '듣는 중…', error: '' });
    void this.checkReady();
    this.scheduleTurnPoll(1500);
  }

  disable(): void {
    this.mic?.stop();
    this.mic = null;
    this.pressSlot = null;
    this.followUntil = 0;
    if (this.turnTimer) { clearTimeout(this.turnTimer); this.turnTimer = null; }
    try { localStorage.setItem(WAKE_ENABLED_KEY, '0'); } catch { /* 저장 실패는 무시 */ }
    this.set({ enabled: false, speaking: false, level: 0, message: '' });
  }

  /**
   * 답을 소리로 들을지.
   *
   * [🔴 마이크와 독립이다] 예전에는 낭독 폴링이 enabled(마이크 켜짐)에 묶여 있어, 마이크를
   *   켜지 않으면 체크를 해도 아무 소리가 나지 않았다 — 사용자에게는 고장으로 보인다.
   *   '손으로 치고 답은 귀로 듣는다'는 정상적인 사용 방식이라 조건에서 뺐다.
   * [WHY slotId 를 받나] 마이크가 없으면 호출어로 대상이 정해질 일이 없다. 체크를 누른
   *   슬롯이 곧 '읽어 줄 대상'이다 — 안 그러면 target 이 null 이라 영영 아무것도 안 읽는다.
   */
  setTts(on: boolean, slotId?: string): void {
    try { localStorage.setItem(TTS_KEY, on ? '1' : '0'); } catch { /* 저장 실패는 무시 */ }
    if (!on) this.stopSpeaking();
    this.set({ ttsOn: on, target: on ? (slotId ?? this.state.target) : this.state.target });
    if (on) {
      void this.checkReady();                 // 사이드카가 아직 없으면 여기서 기동이 시작된다
      this.scheduleTurnPoll(1500);
    } else if (this.turnTimer) {
      clearTimeout(this.turnTimer);
      this.turnTimer = null;
    }
  }

  /* ── 누르고 말하기 ───────────────────────────────────────────────────── */

  /** 마이크 버튼을 누르는 동안 그 슬롯이 무조건 대상이 된다(호출어 불필요). */
  async pressToTalk(slotId: string): Promise<void> {
    this.pressSlot = slotId;
    this.set({ target: slotId, message: '듣는 중…' });
    if (!this.mic) await this.enable();
  }

  releaseToTalk(): void {
    // [🔴 즉시 끄지 않는다] 손을 떼는 순간 말이 아직 캡처 버퍼에 있다. 여기서 마이크를
    //   닫으면 마지막 한 마디가 통째로 사라진다. VAD 가 무음을 보고 스스로 끊게 둔다.
    this.pressSlot = null;
    this.followUntil = Date.now() + 3000;
  }

  /* ── 인식 ────────────────────────────────────────────────────────────── */

  private async onUtterance(wav: Blob): Promise<void> {
    this.set({ busy: true });
    let text = '';
    try {
      const res = await fetch(`${API_BASE}/api/voice/stt`, {
        method: 'POST',
        headers: { 'Content-Type': 'audio/wav' },
        body: wav,
      });
      const data = await res.json();
      text = String(data?.text || '').trim();
      if (data?.error) this.set({ error: String(data.error) });
    } catch (e) {
      this.set({ busy: false, message: '인식 서버에 연결하지 못했습니다', error: String(e) });
      return;
    }
    this.set({ busy: false });
    if (!text) { this.set({ message: '듣는 중…' }); return; }

    this.route(text);
  }

  /**
   * 인식된 문장을 어느 슬롯에 줄지 정한다.
   *
   * [🔴 순서가 곧 정책이다]
   *   ① 마이크 버튼을 누르고 있으면 그 슬롯 (사람이 직접 지목한 것이 가장 세다)
   *   ② 호출어가 있으면 그 슬롯 (대화 중이던 슬롯보다 우선 — 부르면 바뀌어야 한다)
   *   ③ 이어 말하기 창이 열려 있으면 직전 슬롯
   *   ④ 아무것도 아니면 버린다 (옆사람 대화·TV 소리가 명령이 되면 안 된다)
   */
  private route(text: string): void {
    if (this.pressSlot) {
      this.deliver(this.pressSlot, text);
      return;
    }

    const words: Record<string, string> = {};
    for (const [id, b] of this.slots) if (b.wakeWord) words[id] = b.wakeWord;
    const hit = matchWakeWord(text, words);
    if (hit) {
      this.set({ target: hit.slot });
      if (hit.rest) {
        // "클로드, 테스트 돌려줘" — 부르는 말과 지시가 한 문장에 왔다. 바로 보낸다.
        this.deliver(hit.slot, hit.rest);
      } else {
        // 이름만 불렀다. 다음 말을 지시로 받는다.
        this.followUntil = Date.now() + FOLLOW_MS;
        this.set({ message: `${hit.slot} — 말씀하세요` });
      }
      return;
    }

    if (this.state.target && Date.now() < this.followUntil) {
      this.deliver(this.state.target, text);
      return;
    }

    // [WHY 조용히 버리나] 호출어 없이 들린 말은 우리에게 한 말이 아니다. 여기에
    //   "못 알아들었습니다"를 띄우면 방에서 나는 모든 소리마다 화면이 깜빡인다.
    this.set({ message: '듣는 중…' });
  }

  private deliver(slotId: string, text: string): void {
    const b = this.slots.get(slotId);
    if (!b) { this.set({ message: `${slotId} 슬롯이 화면에 없습니다` }); return; }
    this.set({ target: slotId, message: `${slotId} 전송: ${text.slice(0, 20)}` });
    this.followUntil = Date.now() + FOLLOW_MS;
    b.onText(text);
    // [🔴 말을 마친 것이 곧 확인이다] 여기서 또 확인을 요구하면 핸즈프리가 성립하지
    //   않는다(아픽스와 같은 판단). 잘못 들었으면 입력창에 남은 것을 고치면 된다.
    b.onSubmit(text);
    this.scheduleTurnPoll(2000);
  }

  /* ── 낭독 ────────────────────────────────────────────────────────────── */

  private scheduleTurnPoll(ms: number): void {
    if (this.turnTimer) clearTimeout(this.turnTimer);
    if (!this.state.ttsOn) return;              // 마이크 상태와 무관 — setTts 주석 참조
    this.turnTimer = setTimeout(() => { void this.pollTurn(); }, ms);
  }

  /**
   * 대상 슬롯의 마지막 턴을 확인해 새 답이면 읽는다.
   *
   * [🔴 대상 슬롯만 본다] 슬롯 전부를 폴링하면 T1 과 대화하는 중에 T3 의 답이 끼어들어
   *   읽힌다. 사람은 자기가 말 건 쪽의 답만 기대한다.
   * [🔴 첫 폴링은 읽지 않는다] 켜자마자 몇 분 전 답을 읽어 주면 무슨 말인지 모른다.
   *   기준선만 잡고 다음 턴부터 읽는다(아픽스 실측 주석과 같은 이유).
   */
  private async pollTurn(): Promise<void> {
    const slot = this.state.target;
    if (!slot || !this.state.ttsOn) { this.scheduleTurnPoll(8000); return; }
    try {
      const res = await fetch(`${API_BASE}/api/voice/turn?terminal=${encodeURIComponent(slot)}`,
        { cache: 'no-store' });
      const d = await res.json();
      const seq = Number(d?.seq) || 0;
      const known = this.turnSeq.get(slot);
      if (known === undefined) {
        this.turnSeq.set(slot, seq);
      } else if (seq > known) {
        this.turnSeq.set(slot, seq);
        await this.speak(String(d?.text || ''));
      }
    } catch {
      // 폴링 실패는 조용히 넘긴다 — 음성이 안 되는 것보다 화면이 빨개지는 게 나쁘다.
    }
    this.scheduleTurnPoll(this.state.playing ? 8000 : 3000);
  }

  setVoice(id: string): void {
    try { localStorage.setItem(VOICE_KEY, id); } catch { /* 저장 실패는 무시 */ }
    this.set({ voice: id });
  }

  setSpeed(v: number): void {
    const speed = Math.max(0.5, Math.min(1.5, Number(v) || 1.0));
    try { localStorage.setItem(SPEED_KEY, String(speed)); } catch { /* 저장 실패는 무시 */ }
    this.set({ speed });
  }

  /**
   * 고른 목소리를 짧은 문장으로 들려준다.
   *
   * [WHY 미리듣기가 필요한가] 목소리는 이름만 봐서는 고를 수 없다. 실제로 들어 보지 않으면
   *   사용자는 답이 올 때까지 기다렸다가 마음에 안 들면 다시 고르는 짓을 반복한다.
   */
  async preview(id?: string): Promise<void> {
    await this.speak('안녕하세요. 이 목소리로 답을 읽어 드릴게요.', id ?? this.state.voice);
  }

  /** 마크다운 답을 귀로 들을 문장으로 바꿔 서버에 합성을 맡기고 재생한다. */
  async speak(markdown: string, voiceOverride?: string): Promise<void> {
    const text = toSpeech(markdown);
    if (!text) return;
    this.stopSpeaking();
    this.set({ busy: true, message: '읽는 중…' });
    // [불변식] 재생 전에 뮤트한다 — 순서를 바꾸면 첫 문장을 자기가 받아적는다.
    this.mic?.setMuted(true);
    try {
      const res = await fetch(`${API_BASE}/api/voice/tts`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          text,
          voice: voiceOverride ?? this.state.voice,
          speed: this.state.speed,
        }),
      });
      if (!res.ok) throw new Error(`tts ${res.status}`);
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const el = new Audio(url);
      this.audio = el;
      this.set({ busy: false, playing: true });
      el.onended = () => { URL.revokeObjectURL(url); this.onSpeechEnd(); };
      el.onerror = () => { URL.revokeObjectURL(url); this.onSpeechEnd(); };
      await el.play();
    } catch (e) {
      this.set({ busy: false, error: String(e), message: '낭독 실패' });
      this.onSpeechEnd();
    }
  }

  stopSpeaking(): void {
    const el = this.audio;
    this.audio = null;
    if (el) { try { el.pause(); } catch { /* 이미 멈춤 */ } }
    if (this.state.playing) this.set({ playing: false });
    this.mic?.setMuted(false);
  }

  /**
   * 낭독이 끝났을 때.
   *
   * [WHY 여기서 이어 말하기 창을 여나] 답을 듣고 되묻는 것은 한 대화의 연속이다.
   *   매번 이름을 다시 부르게 하면 대화가 아니라 명령이 된다.
   */
  private onSpeechEnd(): void {
    this.audio = null;
    this.mic?.setMuted(false);
    this.followUntil = Date.now() + FOLLOW_MS;
    this.set({ playing: false, message: this.state.enabled ? '이어서 말씀하세요' : '' });
  }

  /* ── 서버 준비 상태 ──────────────────────────────────────────────────── */

  async checkReady(): Promise<void> {
    try {
      const res = await fetch(`${API_BASE}/api/voice/status`, { cache: 'no-store' });
      const d = await res.json();
      const voices: VoiceOption[] = Array.isArray(d?.voices) ? d.voices : [];
      // [🔴 저장된 목소리가 이 PC 에 없을 수 있다] 다른 PC 에서 쓰던 값이 남아 있거나
      //   음성이 제거된 경우다. 그대로 두면 낭독이 매번 실패한다 — 서버 기본값으로 되돌린다.
      const stale = this.state.voice && voices.length > 0
        && !voices.some((v) => v.id === this.state.voice);
      this.set({
        ready: !!d?.ready,
        error: d?.ready ? '' : String(d?.detail || ''),
        voices,
        voice: stale ? String(d?.voice || '') : this.state.voice,
      });
    } catch {
      this.set({ ready: false });
    }
  }
}

/** 앱 전체에 하나. [🔴] 이 모듈을 여러 번 import 해도 인스턴스는 하나여야 한다. */
export const voiceBus = new VoiceBus();
