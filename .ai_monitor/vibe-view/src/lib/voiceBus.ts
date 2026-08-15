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
 *          [🔴 낭독은 사이드카(edge-tts)가 먼저 한다 — 2026-08-15 실측으로 뒤집힘]
 *          로컬 합성 6종이 전부 떨어져 edge-tts 를 기본으로 삼았다(engines/tts_edge.py).
 *          인식과 달리 낭독은 '읽을 문장'만 나가고 마이크 오디오는 나가지 않는다 —
 *          위험의 크기가 다르므로 판단도 다르다. 그래도 싫은 사람이 있으므로 끄는
 *          스위치를 뒀다(state.edgeOn). 끄면 브라우저 내장 합성기로만 읽는다.
 *
 *          [불변식] 낭독 중에는 마이크를 뮤트한다. 안 하면 스피커로 나간 제 목소리를
 *          다시 받아적어 스스로에게 명령한다. 브라우저 에코 제거가 1차, 이게 2차다.
 *
 * REVISION HISTORY:
 * - 2026-08-15 Claude: 최초 작성 — 로컬 STT/TTS + 슬롯별 호출어
 * - 2026-08-15 Claude: 낭독을 브라우저 합성기 우선으로 — '준비 중' 대기 제거.
 *   준비 상태 폴링을 팝오버에서 이 버스로 이관(팝오버를 닫으면 고착되던 사고)
 * - 2026-08-15 Claude: 기본 낭독을 edge-tts(사이드카 mp3)로 — 순서를 다시 뒤집었다.
 *   브라우저 합성기는 네트워크가 죽었을 때 되돌아갈 길로 남는다(speak 주석)
 * ------------------------------------------------------------------------
 */

import { API_BASE } from './apiBase';
import { MicCapture } from './audioCapture';
import {
  browserTtsAvailable, browserVoiceOptions, cancelBrowserSpeech,
  isWebVoiceId, speakBrowser, watchBrowserVoices,
} from './browserVoice';
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
  /**
   * 지금 마이크 단추를 누르고 있는가.
   *
   * [🔴 speaking 과 다르다] speaking 은 소리가 문턱을 넘었을 때만 true 다. 그것만으로
   *   단추를 칠하면, 누르고 숨을 고르는 동안 단추가 꺼져 보여 사람이 '안 눌렸나' 하고
   *   손을 뗀다. 누르고 있다는 사실 자체를 따로 들고 있어야 한다.
   */
  pressing: boolean;
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
  /**
   * **읽어 줄 수 있는가**(사이드카 기동 여부가 아니다).
   *
   * [🔴 의미가 바뀌었다 — 2026-08-15] 예전엔 '사이드카가 떴는가'였다. 그래서 사이드카가
   *   모델을 올리는 ~2분 동안 화면이 '준비 중'에 묶였고, 팝오버를 닫으면 그 값이 영영
   *   갱신되지 않아 고착됐다. 지금은 브라우저 합성기가 있으면 즉시 true — 사람이
   *   기다릴 이유가 없다. 사이드카 상태는 sttReady 로 따로 본다.
   */
  ready: boolean;
  /** 받아쓰기(사이드카 STT)가 준비됐는가. 낭독과 무관 — 둘은 수명이 다르다. */
  sttReady: boolean;
  /**
   * 사이드카가 **지금 합성할 수 있는가**(/status 의 ttsReady).
   *
   * [🔴 sttReady 와 갈라 둔 이유 — 2026-08-15] 예전엔 준비 상태가 하나뿐이라, 낭독이
   *   받아쓰기(whisper 로딩 수십 초)를 기다렸다. edge-tts 는 올릴 모델이 없어 즉시
   *   준비되는데도 그 수십 초 동안 브라우저 목소리로 읽혀, 사용자는 자기가 고른
   *   목소리가 안 먹는다고 판단했다.
   */
  ttsReady: boolean;
  /**
   * 인터넷 목소리(edge-tts)를 쓸 것인가 — **끄는 스위치**.
   *
   * [WHY 필요한가] edge 는 문장을 마이크로소프트 서버로 보낸다. 그 자체가 싫거나,
   *   회선이 느리거나, 오프라인으로 쓰는 사람이 있다. 끄면 목록에서 사라지고 낭독은
   *   브라우저 내장 합성기(이 PC 안의 Heami)로만 일어난다.
   * [🔴 이제 이 스위치가 곧 '사이드카를 쓰느냐'다 — 2026-08-15 엔진 정리] sherpa·SAPI
   *   어댑터를 걷어내 사이드카에 남은 낭독 엔진은 edge 하나뿐이다. 그래서 이걸 끄면
   *   낭독에 한해 사이드카를 아예 안 쓴다(받아쓰기는 그대로 사이드카가 한다 — 둘을
   *   묶어서 끄면 마이크가 같이 죽는다).
   */
  edgeOn: boolean;
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
// [WHY localStorage 인가] 목소리(VOICE_KEY)와 같은 이유다 — 회선·취향은 기기별이라
//   프로젝트 config 에 넣으면 다른 PC 의 설정까지 같이 바뀐다.
const EDGE_KEY = 'vibe.voice.edge';

/** 답을 다 읽은 뒤 이 시간 동안은 호출어 없이 바로 이어 말할 수 있다. */
const FOLLOW_MS = 12000;

/**
 * 손을 뗀 뒤 이 시간 안에 도착한 받아쓰기만 '누른 말'로 본다.
 *
 * [WHY 15초인가] 사이드카가 차가우면 첫 인식이 10초 넘게 걸린다(모델 로딩). 그보다
 *   짧게 잡으면 첫 발화가 배달되지 않고, 길게 잡으면 시효의 의미가 없어진다.
 */
const PRESS_GRACE_MS = 15000;

class VoiceBus {
  private state: VoiceState = {
    enabled: false,
    speaking: false,
    pressing: false,
    level: 0,
    busy: false,
    playing: false,
    ttsOn: (() => { try { return localStorage.getItem(TTS_KEY) !== '0'; } catch { return true; } })(),
    target: null,
    message: '',
    // 브라우저 합성기가 있으면 처음부터 말할 수 있다 — 물어보고 정할 것이 없다.
    ready: browserTtsAvailable(),
    sttReady: false,
    ttsReady: false,
    // 기본은 켜짐. [WHY] 오늘 실측에서 통과한 유일한 낭독이라 이게 곧 '보통 상태'다.
    edgeOn: (() => { try { return localStorage.getItem(EDGE_KEY) !== '0'; } catch { return true; } })(),
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
  /** 손을 뗀 뒤 받아쓰기 결과가 돌아올 때까지 대상을 붙들어 두는 자리(releaseToTalk 주석). */
  private pendingPress: string | null = null;
  /**
   * pendingPress 를 만든 시각.
   *
   * [🔴 시효가 없으면 엉뚱한 말이 옛 슬롯으로 간다] 누른 말이 너무 짧아 버려지면
   *   pendingPress 가 남는다. 그 뒤 상시 대기 상태에서 호출어 없이 들린 말이
   *   '누른 말'로 오인돼 배달된다 — 사용자는 부른 적도 누른 적도 없다.
   */
  private pendingPressAt = 0;
  /**
   * 직전 지시가 **음성으로** 들어왔는가.
   *
   * [🔴 이어 듣기의 유일한 근거 — 아픽스 실측] 답을 읽은 뒤 마이크를 여는 것은 되묻기
   *   편의다. 그런데 키보드로 친 지시의 답 뒤에도 열면, 사용자는 마이크가 열린 줄
   *   모르는 채 옆사람과 말하고 그게 지시가 된다. 음성으로 시작한 대화만 음성으로 잇는다.
   */
  private lastInputWasVoice = false;
  private followTimer: ReturnType<typeof setTimeout> | null = null;
  /** 누름 한 번을 가리키는 일련번호. 마이크가 열리기를 기다리는 동안 뗐는지 가른다. */
  private pressToken = 0;
  private pressWatchdog: ReturnType<typeof setTimeout> | null = null;
  /** 창이 숨어 마이크를 접었다 — 돌아오면 다시 열어야 하는가. */
  private reopenOnVisible = false;
  /** 사이드카가 준 목소리. 브라우저 목소리와 합쳐 state.voices 가 된다. */
  private serverVoices: VoiceOption[] = [];
  /** 사이드카가 /status 로 한 번이라도 답했는가. 저장된 목소리 판정의 전제. */
  private serverAnswered = false;
  /** 사이드카가 스스로 고른 기본 목소리(/status 의 voice). 아직 아무것도 안 고른 사람 몫. */
  private serverDefault = '';
  private statusTimer: ReturnType<typeof setTimeout> | null = null;
  private statusTries = 0;

  constructor() {
    // [🔴 여기서 사이드카를 부르지 않는다] 앱을 켜기만 해도 whisper 모델이 올라가면
    //   음성을 안 쓰는 사람이 CPU 를 낸다. 브라우저 목소리는 공짜라 미리 채워 두고,
    //   사이드카는 사용자가 음성을 만진 뒤에 ensureSidecar() 로 부른다.
    this.refreshVoices();
    watchBrowserVoices(() => this.refreshVoices());
    this.bindGuards();
  }

  /**
   * '켜진 채 잊히는 마이크'를 만들지 않기 위한 전역 안전장치.
   *
   * [🔴 왜 컴포넌트가 아니라 여기인가] 마이크를 소유한 것은 이 버스다. 단추 쪽에 걸면
   *   그 단추가 언마운트되는 순간(슬롯 전환·화면 이동) 감시가 같이 사라진다 — 정작
   *   마이크는 살아 있는데.
   * [🔴 blur 와 숨김을 나눠 다룬다] 다른 창을 클릭한 것(blur)은 '누르던 손이 떠났다'는
   *   뜻이므로 누름만 끝낸다. 창이 아예 숨은 것(visibilitychange)은 다르다 — 보이지도
   *   않는 창이 계속 듣고 있으면 안 되므로 장치를 접는다. 다시 보이면 되살린다.
   *   [WHY 체크를 끄지 않고 접기만 하나] 최소화했다고 사용자의 설정을 몰래 바꾸면,
   *   돌아왔을 때 왜 꺼졌는지 알 수 없다. 설정은 두고 장치만 접는다.
   */
  private bindGuards(): void {
    if (typeof window === 'undefined' || typeof document === 'undefined') return;

    window.addEventListener('blur', () => this.releaseToTalk());
    window.addEventListener('pagehide', () => this.releaseToTalk());

    document.addEventListener('visibilitychange', () => {
      if (document.hidden) {
        this.releaseToTalk();
        this.stopSpeaking();                    // 숨은 창이 혼자 떠들지 않게
        if (this.mic) {
          this.reopenOnVisible = this.state.enabled;
          this.mic.stop();
          this.mic = null;
          this.set({ speaking: false, level: 0 });
        }
        return;
      }
      if (this.reopenOnVisible && this.state.enabled) {
        this.reopenOnVisible = false;
        // [제약] 사용자 제스처 밖이지만 권한은 이미 받아 둔 출처라 다시 열린다.
        void this.openMic();
      }
    });
  }

  /**
   * 고를 수 있는 목소리 목록을 다시 만든다.
   *
   * [🔴 순서가 바뀌었다 — 2026-08-15] 예전엔 브라우저 목소리를 앞에 뒀다. 사이드카가
   *   모델을 올리는 ~2분 동안 고른 사람이 '기다려야 하는 쪽'을 집지 않게 하려는 것이었다.
   *   edge-tts 는 올릴 모델이 없어 그 기다림 자체가 사라졌고, 품질은 확연히 위다.
   *   그래서 edge → 브라우저(항상 되는 길) → 로컬 엔진 순으로 놓는다.
   * [🔴 스위치가 꺼져 있으면 edge 를 목록에서 통째로 뺀다] 목록에 두고 고르면 실패하는
   *   구조는 사용자가 '고장'으로 읽는다. 못 쓰는 것은 보여 주지 않는다.
   */
  private refreshVoices(): void {
    const web = browserVoiceOptions();
    const server = this.state.edgeOn
      ? this.serverVoices
      : this.serverVoices.filter((v) => v.engine !== 'edge');
    const edge = server.filter((v) => v.engine === 'edge');
    const local = server.filter((v) => v.engine !== 'edge');
    const voices = [...edge, ...web, ...local];

    // [🔴 저장된 목소리가 이 PC 에 없을 수 있다] 다른 PC 에서 쓰던 값이 남아 있거나
    //   음성이 제거된 경우다. 그대로 두면 낭독이 매번 실패한다 — 빈 값으로 되돌린다.
    // [🔴 사이드카 목소리는 사이드카가 답한 뒤에만 판정한다] 아직 안 뜬 상태에서
    //   판정하면 '목록에 없다'가 되어 사용자가 고른 값을 부팅 때마다 날린다.
    // [WHY 스위치를 끈 것도 여기서 걸리나] 위 server 에서 edge 를 뺐으므로, 고른 값이
    //   edge 였으면 자동으로 '없는 목소리'가 되어 풀린다 — 스위치 처리가 한 곳에 모인다.
    const cur = this.state.voice;
    const stale = !!cur && (isWebVoiceId(cur)
      ? web.length > 0 && !web.some((v) => v.id === cur)
      : this.serverAnswered && !server.some((v) => v.id === cur));
    let voice = stale ? '' : cur;

    // [🔴 화면에 칠한 것과 실제로 나는 소리가 같아야 한다] 아무것도 안 골랐을 때 화면은
    //   목록 첫 줄을 칠하는데, 낭독은 사이드카가 정한 기본값으로 나간다. 둘이 어긋나면
    //   사용자는 설정이 안 먹었다고 읽는다. 사이드카가 알려 준 기본값을 여기서 채운다.
    // [WHY localStorage 에 안 쓰나] 사람이 고른 적 없는 값이다. 저장하면 나중에 기본값이
    //   바뀌어도 옛 값에 묶인다.
    if (!voice && this.serverDefault && voices.some((v) => v.id === this.serverDefault)) {
      voice = this.serverDefault;
    }

    this.set({ voices, voice, ready: browserTtsAvailable() || this.state.ttsReady });
  }

  /**
   * 인터넷 목소리(edge-tts) 스위치.
   *
   * [🔴 끄면 즉시 되돌아간다] 다음 답부터가 아니라 지금 읽던 것도 멈춘다. 스위치를 끈
   *   사람은 '지금 이 소리를 그만'이라는 뜻으로 누른다.
   */
  setEdge(on: boolean): void {
    try { localStorage.setItem(EDGE_KEY, on ? '1' : '0'); } catch { /* 저장 실패는 무시 */ }
    if (!on) this.stopSpeaking();
    this.set({ edgeOn: on });
    this.refreshVoices();
    if (on) this.ensureSidecar();
  }

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

  /**
   * 지난번에 호출어 대기를 켜 뒀었는지.
   *
   * [🔴 이 값으로 자동으로 켜지 않는다 — 의도된 것] 앱을 켜자마자 마이크가 열리면
   *   오디오가 계속 들어오고(노트북은 배터리도) 사용자는 그 사실을 모른다. 상시 대기는
   *   **매번 사람이 켜는 것**이 기본이다. 이 값은 화면에 '지난번엔 켜 뒀었다'를
   *   알려 주는 용도로만 쓴다.
   */
  restore(): boolean {
    try { return localStorage.getItem(WAKE_ENABLED_KEY) === '1'; } catch { return false; }
  }

  /**
   * 마이크 장치를 실제로 연다. 이미 열려 있으면 아무것도 하지 않는다.
   *
   * [🔴 앱에 하나뿐이다] 누르고 말하기·상시 대기·이어 듣기 셋이 같은 장치를 쓴다.
   *   각자 열면 인식기 여럿이 같은 마이크를 잡고 전부 죽는다(audioCapture.ts 헤더).
   */
  private async openMic(): Promise<boolean> {
    if (this.mic) return true;
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
      this.set({ message: '마이크 권한이 필요합니다' });
      return false;
    }
    this.mic = mic;
    this.ensureSidecar();                       // 받아쓰기는 사이드카 몫 — 여기서 깨운다
    return true;
  }

  /**
   * 마이크를 닫는다. 단, **아직 쓸 사람이 있으면 닫지 않는다.**
   *
   * [🔴 세 주인이 한 장치를 공유한다] 상시 대기(enabled)·누르고 있는 손(pressSlot)·
   *   이어 듣기 창(followUntil). 하나가 끝났다고 닫으면 나머지가 조용히 먹통이 된다.
   */
  private closeMicIfIdle(): void {
    if (this.state.enabled || this.pressSlot) return;
    if (Date.now() < this.followUntil) return;
    this.mic?.stop();
    this.mic = null;
    this.set({ speaking: false, level: 0 });
  }

  /** 호출어 상시 대기를 켠다. [제약] 사용자 제스처 안에서 불러야 권한창이 뜬다. */
  async enable(): Promise<void> {
    const ok = await this.openMic();
    if (!ok) { this.set({ enabled: false }); return; }
    try { localStorage.setItem(WAKE_ENABLED_KEY, '1'); } catch { /* 저장 실패는 무시 */ }
    this.set({ enabled: true, message: '듣는 중…', error: '' });
    this.scheduleTurnPoll(1500);
  }

  disable(): void {
    this.pressSlot = null;
    this.followUntil = 0;
    try { localStorage.setItem(WAKE_ENABLED_KEY, '0'); } catch { /* 저장 실패는 무시 */ }
    // [🔴 enabled 를 먼저 내린다] closeMicIfIdle 이 이 값을 보고 닫을지 정한다.
    this.set({ enabled: false, speaking: false, level: 0, message: '' });
    this.closeMicIfIdle();
    // [WHY 낭독 폴링은 안 끈다] 답 듣기는 마이크와 독립이다(setTts 주석). 여기서 같이
    //   끄면 '손으로 치고 답은 귀로 듣는다'가 상시 대기를 끄는 순간 죽는다.
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
      // [🔴 낭독은 이걸 기다리지 않는다] 브라우저 합성기가 이미 읽는다. 사이드카는
      //   '더 나은 목소리'와 받아쓰기를 위해 뒤에서 데워 둘 뿐이다.
      this.ensureSidecar();
      this.scheduleTurnPoll(1500);
    } else if (this.turnTimer) {
      clearTimeout(this.turnTimer);
      this.turnTimer = null;
    }
  }

  /* ── 소유권 ──────────────────────────────────────────────────────────── */

  /**
   * 이 슬롯이 지금 마이크·스피커의 임자다.
   *
   * [🔴 물리적 제약을 먼저 인정한다] 터미널은 여럿인데 마이크와 스피커는 하나뿐이다.
   *   '완전히 따로'는 불가능하므로 규칙을 하나로 못 박는다 — **지금 활성 터미널이
   *   마이크·스피커를 소유한다.** 대화 내용과 '어디로 보낼지'는 슬롯별, 장치는 한 개.
   * [🔴 새 구조를 만들지 않는다] 임자는 이미 있던 state.target 그대로다. 여기서는
   *   '누가 임자인지 바뀌는 순간에 무엇을 정리하는가'만 정한다.
   * [🔴 바뀌면 읽던 것을 멈춘다] 안 멈추면 T1 을 떠났는데 T1 의 답이 계속 들린다 —
   *   사용자는 지금 화면(T2)과 들리는 말이 어긋나 무슨 말인지 알 수 없다.
   * [제약] 누르는 중에는 소유권을 넘기지 않는다. 그 손이 임자다.
   */
  claim(slotId: string): void {
    if (!slotId || this.pressSlot) return;
    if (this.state.target === slotId) return;
    this.stopSpeaking();
    this.followUntil = 0;
    this.lastInputWasVoice = false;
    this.pendingPress = null;                   // 앞 슬롯으로 가려던 말은 여기서 끊는다
    if (this.followTimer) { clearTimeout(this.followTimer); this.followTimer = null; }
    this.set({ target: slotId, message: '' });
  }

  /* ── 누르고 말하기 ───────────────────────────────────────────────────── */

  /**
   * 버튼을 누르는 동안만 듣는다. 그 슬롯이 무조건 대상이다(호출어 불필요).
   *
   * [🔴 여기서 상시 대기를 켜지 않는다] 예전에는 enable() 을 불러 마이크를 계속 열어
   *   뒀다. 한 번 눌렀다는 이유로 마이크가 영영 열려 있으면 사용자가 동의한 적 없는
   *   상시 청취가 된다. 누르는 동안만 열고, 떼면 닫는다(상시 대기가 켜져 있으면 유지).
   */
  async pressToTalk(slotId: string): Promise<void> {
    const token = ++this.pressToken;
    this.pressSlot = slotId;
    this.pendingPress = slotId;
    this.pendingPressAt = Date.now();
    // pressing 은 마이크가 열리기를 기다리는 동안에도 켜 둔다 — 사람은 누른 즉시 반응을 본다.
    this.set({ target: slotId, pressing: true, message: '듣는 중…' });
    this.armPressWatchdog();

    const ok = await this.openMic();

    // [🔴 기다리는 사이에 손을 뗐을 수 있다 — 이걸 안 보면 마이크가 열린 채 남는다]
    //   openMic 은 getUserMedia 를 기다린다(권한창이 뜨면 몇 초). 짧게 톡 누르면
    //   release 가 **먼저** 끝나고, 그 뒤에 여기가 이어져 beginHold 를 건다. 그러면
    //   아무도 뗀 적이 없는 hold 상태가 되어 계속 듣는다. 토큰으로 그 사이를 가른다.
    if (token !== this.pressToken || this.pressSlot !== slotId) {
      if (ok) { this.mic?.releaseHold(); this.closeMicIfIdle(); }
      this.set({ pressing: false });
      return;
    }
    if (!ok) {
      this.pressSlot = null;
      this.pendingPress = null;
      this.clearPressWatchdog();
      this.set({ pressing: false });
      return;
    }
    // [제약] 낭독 중이면 뮤트 상태다 — 사람이 버튼을 눌렀다는 것은 지금 말을 자르고
    //   자기가 말하겠다는 뜻이다. 읽던 것을 멈추고 귀를 연다.
    if (this.state.playing) this.stopSpeaking();
    this.mic?.setMuted(false);
    // [🔴 호출어 대기와 겹치지 않게 한다 — 보드의 stopWake() 자리] 이 앱은 인식기가
    //   하나라(MicCapture 싱글턴) 장치를 두고 다툴 일이 없다. 대신 VAD 가 이미 담고
    //   있던 조각을 beginHold 가 버린다 — 누르기 직전에 들린 주변 말이 내 지시 앞에
    //   붙는 것을 막는다. 뗀 뒤에는 자동으로 VAD 로 돌아간다.
    this.mic?.beginHold();
  }

  /**
   * 누른 채로 잊힌 단추에서 마이크를 되찾는다.
   *
   * [🔴 pointerup 이 영영 안 오는 경우가 있다] 창이 사라지거나, 포인터 캡처가 다른
   *   요소로 넘어가거나, 브라우저가 pointercancel 을 안 쏘는 경우다. 그때 사람은
   *   자기가 여전히 듣히고 있다는 것을 모른다. 30초면 어떤 정상 발화보다 길다.
   */
  private armPressWatchdog(): void {
    this.clearPressWatchdog();
    this.pressWatchdog = setTimeout(() => {
      this.pressWatchdog = null;
      if (this.pressSlot) this.releaseToTalk();
    }, 30000);
  }

  private clearPressWatchdog(): void {
    if (this.pressWatchdog) { clearTimeout(this.pressWatchdog); this.pressWatchdog = null; }
  }

  /**
   * 손을 뗐다 — **그대로 보낸다.**
   *
   * [🔴 확인 단추를 두지 않는다 — 아픽스 실측] 누르고 말한 사람은 이미 보낼 생각이었다.
   *   여기서 한 번 더 확인을 받으면 핸즈프리가 성립하지 않는다. 잘못 들었으면 입력창에
   *   남은 것을 고치면 된다.
   * [🔴 pressSlot 을 바로 비우되 대상은 pendingPress 로 넘긴다] releaseHold 가 발화를
   *   확정해도 받아쓰기는 서버 왕복이라 route() 는 한참 뒤에 돈다. pressSlot 만 보고
   *   판단하면 그 사이에 null 이 되어 '아무에게도 안 간 말'이 된다.
   */
  releaseToTalk(): void {
    if (!this.pressSlot) return;                // 누른 적 없는 뗌(권한 실패 등)은 무시
    this.pressToken++;                          // 아직 열리는 중인 press 를 무효로 만든다
    this.clearPressWatchdog();
    this.pendingPressAt = Date.now();           // 시효는 '뗀 순간'부터 센다
    this.mic?.releaseHold();                    // 여기서 발화가 확정돼 onUtterance 로 간다
    this.pressSlot = null;
    this.set({ pressing: false, speaking: false });
    this.closeMicIfIdle();
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
    // 누르는 중이거나, 방금 손을 뗀 그 말이다(pendingPress). 사람이 직접 지목한 것이 가장 세다.
    const fresh = Date.now() - this.pendingPressAt < PRESS_GRACE_MS;
    const forced = this.pressSlot ?? (fresh ? this.pendingPress : null);
    this.pendingPress = null;
    if (forced) {
      this.deliver(forced, text);
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
    this.lastInputWasVoice = true;              // 이 대화는 음성으로 시작됐다(onSpeechEnd 참조)
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
        // [🔴 서버를 다녀오는 사이에 임자가 바뀔 수 있다] 그때 그대로 읽으면, 방금 옮겨
        //   온 화면에서 이전 터미널의 답이 흘러나온다. 읽기 직전에 한 번 더 확인한다.
        // [제약] 여기서 return 하지 말 것 — 아래 재예약을 건너뛰면 낭독 폴링이 영영 멈춘다.
        if (this.state.target === slot) await this.speak(String(d?.text || ''));
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
    // [🔴 미리듣기 뒤에 귀를 열지 않는다 — 아픽스 실측] 일반 낭독은 끝나면 '이어 말하기'
    //   창을 연다. 목소리를 고르는 동안 그러면 고르는 소리·주변 말이 지시로 들어간다.
    await this.speak('안녕하세요. 이 목소리로 답을 읽어 드릴게요.',
                     { voice: id ?? this.state.voice, preview: true });
  }

  /**
   * 이 목소리를 사이드카(edge-tts / 로컬 엔진)로 읽을 것인가.
   *
   * [🔴 아무것도 안 골랐을 때만 '떴는가'를 따진다] 사용자가 사이드카 목소리를 직접
   *   골랐으면 그 값이 곧 의사표시다 — 아직 안 떴어도 한 번은 두드려 본다(실패하면
   *   호출부가 브라우저로 내려간다). 반대로 안 고른 사람에게 기본 경로를 태울 때는
   *   뜬 것이 확인된 뒤에만 간다. 안 그러면 매 낭독마다 502 를 한 번씩 맞고 시작한다.
   */
  private useSidecarFor(voiceId: string): boolean {
    if (isWebVoiceId(voiceId)) return false;
    if (!this.state.edgeOn && voiceId.startsWith('edge:')) return false;
    if (voiceId) return true;
    return this.state.edgeOn && this.state.ttsReady;
  }

  /**
   * 답을 소리로 읽는다.
   *
   * [🔴 순서가 뒤집혔다 — 2026-08-15 edge-tts 도입] 예전엔 브라우저 합성기가 먼저였다.
   *   사이드카가 첫 기동에 ~2분(whisper 모델)이 걸려 사람을 기다리게 했기 때문이다.
   *   edge-tts 는 올릴 모델이 없어 그 기다림이 사라졌고, 품질은 확연히 위다.
   *   그래서 지금은 사이드카가 먼저이고 브라우저가 되돌아갈 길이다.
   * [🔴 무음이 되면 안 된다 — 이 함수의 가장 중요한 계약] edge 는 네트워크에 기댄다.
   *   회선이 끊기거나 MS 가 막으면 실패한다. 그때 **조용히** 다음 길로 내려간다.
   *   사용자에게 실패를 알리는 것보다 소리가 나는 것이 먼저다 — 오류 문구는 error 에만
   *   남기고 화면 문구는 '읽는 중'을 유지한다.
   */
  async speak(markdown: string, opts: { voice?: string; preview?: boolean } = {}): Promise<void> {
    const text = toSpeech(markdown);
    if (!text) return;
    // [🔴 창이 숨어 있으면 읽지 않는다 — 아픽스 실측] 최소화해 둔 창이 혼자 떠드는 것은
    //   사고로 읽힌다. 사람이 직접 누른 미리듣기는 예외다.
    if (!opts.preview && typeof document !== 'undefined' && document.hidden) return;

    this.stopSpeaking();
    const wanted = opts.voice ?? this.state.voice;
    const sidecarFirst = this.useSidecarFor(wanted);

    // ① 사이드카(기본 = edge-tts mp3).
    if (sidecarFirst && await this.speakViaSidecar(text, wanted, opts.preview)) return;

    // ② 브라우저 내장 합성기 — 프로세스도 네트워크도 없어 이 길은 거의 안 죽는다.
    if (browserTtsAvailable()) {
      this.set({ busy: false, playing: true, message: '읽는 중…' });
      this.mic?.setMuted(true);                   // [불변식] 소리보다 먼저 귀를 닫는다
      const ok = await speakBrowser(text, { voiceId: wanted, speed: this.state.speed });
      if (ok) { this.onSpeechEnd(opts.preview); return; }
      this.set({ playing: false });
    }

    // ③ 브라우저까지 못 읽었다. 아직 사이드카를 안 써 봤다면 마지막으로 두드린다.
    if (!sidecarFirst && await this.speakViaSidecar(text, wanted, opts.preview)) return;

    // 모든 길이 막혔다 — 이때만 사람에게 알린다.
    this.set({ busy: false, playing: false, message: '낭독 실패' });
    this.onSpeechEnd(opts.preview);
  }

  /**
   * 사이드카로 합성해 재생한다. edge 면 mp3, 로컬 엔진이면 wav 가 온다.
   *
   * [🔴 형식을 우리가 정하지 않는다] Content-Type 을 그대로 담은 blob 을 Audio 에 준다.
   *   프론트가 wav 로 못 박으면 mp3 가 디코드에 실패하고, 그 실패는 소리만 안 나고
   *   오류도 안 뜨는 가장 찾기 나쁜 형태가 된다(voice_server.synthesize 주석과 짝).
   * [🔴 실패하면 onSpeechEnd 를 부르지 않고 false 만 돌려준다] 여기서 종료 처리를 하면
   *   호출부가 다음 길로 내려가는 것과 동시에 '이어 말하기' 창이 열려, 아직 답을 읽지도
   *   않았는데 마이크가 열린다.
   *
   * @returns 재생이 실제로 시작됐으면 true
   */
  private async speakViaSidecar(text: string, voice: string, preview?: boolean): Promise<boolean> {
    this.set({ busy: true, message: '읽는 중…' });
    // [불변식] 재생 전에 뮤트한다 — 순서를 바꾸면 첫 문장을 자기가 받아적는다.
    this.mic?.setMuted(true);
    let url = '';
    try {
      const res = await fetch(`${API_BASE}/api/voice/tts`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          // 사이드카에는 브라우저용 'web:' 이 아닌 것만 넘긴다 — 모르는 id 를 주면
          // 그쪽이 기본값으로 떨어져 사용자가 고른 것과 다른 목소리가 난다.
          text,
          voice: isWebVoiceId(voice) ? '' : voice,
          speed: this.state.speed,
        }),
      });
      if (!res.ok) throw new Error(`tts ${res.status}`);
      const blob = await res.blob();
      // [🔴 빈 응답을 성공으로 보면 무음이 된다] 길이 0 은 재생기가 조용히 삼킨다.
      if (!blob.size) throw new Error('tts empty');
      url = URL.createObjectURL(blob);
      const el = new Audio(url);
      // [🔴 종료 처리는 재생이 시작된 뒤에 건다] 먼저 걸면 디코드 실패(onerror)가
      //   '다 읽었다'로 처리돼, 폴백과 이어 말하기 창이 동시에 열린다.
      await el.play();
      this.audio = el;
      this.set({ busy: false, playing: true, error: '' });
      const done = () => { URL.revokeObjectURL(url); this.onSpeechEnd(preview); };
      el.onended = done;
      el.onerror = done;
      return true;
    } catch (e) {
      if (url) URL.revokeObjectURL(url);
      // [WHY message 를 안 건드리나] 아래 브라우저 경로가 이어서 읽는다. 여기서
      //   '낭독 실패'를 띄우면 소리는 정상으로 나는데 화면만 빨개진다.
      this.set({ busy: false, playing: false, error: String(e) });
      this.mic?.setMuted(false);
      return false;
    }
  }

  stopSpeaking(): void {
    const el = this.audio;
    this.audio = null;
    if (el) { try { el.pause(); } catch { /* 이미 멈춤 */ } }
    cancelBrowserSpeech();                        // 두 경로가 겹쳐 울지 않게 둘 다 끊는다
    if (this.state.playing) this.set({ playing: false });
    this.mic?.setMuted(false);
  }

  /**
   * 낭독이 끝났을 때.
   *
   * [WHY 여기서 이어 말하기 창을 여나] 답을 듣고 되묻는 것은 한 대화의 연속이다.
   *   매번 이름을 다시 부르게 하면 대화가 아니라 명령이 된다.
   */
  private onSpeechEnd(preview?: boolean): void {
    this.audio = null;
    this.mic?.setMuted(false);
    if (preview) {
      // [🔴 미리듣기는 대화가 아니다] 여기서 이어 말하기 창을 열면, 목소리를 여러 개
      //   들어 보는 동안 나온 주변 말이 곧바로 지시로 들어간다(아픽스에서 실제로 났다).
      this.set({ playing: false, busy: false });
      this.closeMicIfIdle();
      return;
    }
    if (!this.lastInputWasVoice) {
      // 키보드로 친 지시의 답이었다 — 읽어 주기만 하고 귀는 열지 않는다.
      this.set({ playing: false, busy: false, message: this.state.enabled ? '듣는 중…' : '' });
      this.closeMicIfIdle();
      return;
    }
    this.lastInputWasVoice = false;             // 한 번의 답에 한 번만 열린다
    this.openFollowWindow();
    this.set({ playing: false, busy: false, message: '이어서 말씀하세요' });
  }

  /**
   * 답을 다 읽은 뒤 잠깐 귀를 열어 둔다(되묻기).
   *
   * [🔴 상시 대기와 다른 스위치다] 호출어 대기가 꺼져 있어도 이 창은 열린다 — 방금
   *   음성으로 물어본 사람에게 "다시 눌러서 되물으세요"는 대화가 아니다. 대신 창이
   *   닫히면 마이크도 같이 닫는다. 열어 둔 채로 잊히는 것이 가장 나쁜 상태다.
   */
  private openFollowWindow(): void {
    this.followUntil = Date.now() + FOLLOW_MS;
    void this.openMic();
    if (this.followTimer) clearTimeout(this.followTimer);
    this.followTimer = setTimeout(() => {
      this.followTimer = null;
      if (!this.state.enabled) this.set({ message: '' });
      this.closeMicIfIdle();
    }, FOLLOW_MS + 200);
  }

  /* ── 서버 준비 상태 ──────────────────────────────────────────────────── */

  /**
   * 사이드카(받아쓰기·고급 목소리)를 깨우고, 준비될 때까지 **혼자** 다시 묻는다.
   *
   * [🔴 폴링을 화면에서 버스로 옮긴 이유 — 2026-08-15 고착 사고] 예전엔 '목소리' 팝오버가
   *   열려 있는 동안에만 3초마다 물었다. 예열(~2분)이 끝나기 전에 팝오버를 닫으면
   *   ready=true 를 받을 기회가 영영 사라져 화면이 '준비 중'에 굳었다. 상태를 소유한
   *   쪽이 갱신도 소유해야 한다 — 화면이 열려 있고 없고와 무관해야 한다.
   * [WHY 상한을 두나] 사이드카가 설치조차 안 된 PC 에서 무한히 두드리면 서버 로그만
   *   더럽힌다. 3분(45회)이면 예열은 끝난다 — 그 뒤엔 사용자가 다시 만질 때 재개된다.
   */
  ensureSidecar(): void {
    if (this.state.sttReady) return;
    this.statusTries = 0;
    if (this.statusTimer) { clearTimeout(this.statusTimer); this.statusTimer = null; }
    void this.checkReady();
  }

  private scheduleStatusPoll(): void {
    if (this.state.sttReady || this.statusTries++ > 45) return;
    if (this.statusTimer) clearTimeout(this.statusTimer);
    this.statusTimer = setTimeout(() => { void this.checkReady(); }, 4000);
  }

  async checkReady(): Promise<void> {
    try {
      const res = await fetch(`${API_BASE}/api/voice/status`, { cache: 'no-store' });
      const d = await res.json();
      this.serverAnswered = true;
      this.serverVoices = Array.isArray(d?.voices) ? d.voices : [];
      this.serverDefault = String(d?.voice || '');
      this.set({
        sttReady: !!d?.ready,
        // [🔴 낭독 준비는 받아쓰기와 따로 본다] edge 는 올릴 모델이 없어 기동 직후
        //   바로 true 가 된다. ready(=받아쓰기까지)를 기다리면 whisper 로딩 수십 초
        //   동안 고른 목소리 대신 브라우저 목소리가 난다.
        ttsReady: !!d?.ttsReady,
        // [🔴 여기서 error 를 채우지 않는다] 사이드카가 예열 중이라는 사실은 오류가
        //   아니다. 낭독은 브라우저가 이미 하고 있다 — 화면을 노랗게 만들 이유가 없다.
        error: '',
      });
      this.refreshVoices();
    } catch {
      this.set({ sttReady: false, ttsReady: false });
    }
    this.scheduleStatusPoll();
  }
}

/** 앱 전체에 하나. [🔴] 이 모듈을 여러 번 import 해도 인스턴스는 하나여야 한다. */
export const voiceBus = new VoiceBus();
