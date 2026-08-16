/**
 * ------------------------------------------------------------------------
 * 📄 파일명: lib/audioCapture.ts
 * 📝 설명: 마이크 → 16kHz mono PCM → WAV. 말이 시작되고 끝나는 지점을 스스로
 *          판정(VAD)해 '한 발화'만 잘라 낸다. 인식은 서버(faster-whisper)가 한다.
 *
 *          [WHY 브라우저 SpeechRecognition 을 안 쓰나] 그 API 는 오디오를 구글 서버로
 *          보내 인식한다. 로컬 오픈소스로 간다는 결정(2026-08-15)의 핵심이 그 전송을
 *          없애는 것이라, 인식기를 바꾸면 캡처도 우리가 해야 한다.
 *
 *          [🔴 16kHz mono 로 고정하는 이유] whisper 계열은 16k mono 를 전제로 학습됐다.
 *          44.1k 를 그대로 보내면 서버가 리샘플링하느라 지연이 늘고, 채널이 둘이면
 *          앞 채널만 쓰이거나 섞여 인식률이 떨어진다. 보내기 전에 여기서 맞춘다.
 *
 *          [🔴 WAV 로 보내는 이유] MediaRecorder 의 webm/opus 는 서버에서 ffmpeg 디코딩이
 *          필요하다. 의존성을 하나 늘리는 대신, PCM 을 직접 받아 44바이트 헤더만 붙인다.
 *
 * REVISION HISTORY:
 * - 2026-08-15 Claude: 최초 작성 — 로컬 STT 전환에 따른 자체 캡처
 * - 2026-08-15 Claude: '누르고 말하기' 모드 추가(beginHold/releaseHold) — 누르는 동안은
 *   VAD 문턱·무음 판정을 우회하고, 손을 떼는 순간 그 자리에서 발화를 확정한다
 * ------------------------------------------------------------------------
 */

/** 인식기가 기대하는 샘플레이트. 바꾸면 서버 쪽 전처리도 같이 바꿔야 한다. */
export const TARGET_RATE = 16000;

export interface VadOptions {
  /** 이 값을 넘으면 '말이 있다'로 본다. 0~1 RMS. 조용한 방 기준 0.01 근처가 바닥. */
  threshold?: number;
  /** 말이 멈춘 뒤 이만큼 조용하면 한 발화가 끝난 것으로 본다(ms). */
  silenceMs?: number;
  /** 이보다 짧은 소리는 발화로 치지 않는다(ms). 기침·클릭 제거. */
  minSpeechMs?: number;
  /** 아무리 길어도 여기서 끊는다(ms). 마이크가 열린 채 남는 것이 가장 나쁜 상태다. */
  maxSpeechMs?: number;
}

const DEFAULTS: Required<VadOptions> = {
  threshold: 0.018,
  silenceMs: 900,
  minSpeechMs: 350,
  maxSpeechMs: 20000,
};

export interface CaptureHandlers {
  /** 한 발화가 끝났다. wav 는 16k mono 16bit. */
  onUtterance: (wav: Blob, meta: { ms: number; peak: number }) => void;
  /** 말이 시작/끝났다는 신호 — 화면 표시용. */
  onSpeechState?: (speaking: boolean) => void;
  /** 입력 레벨(0~1) — 마이크가 살아 있음을 사람이 눈으로 확인하는 유일한 수단. */
  onLevel?: (level: number) => void;
  onError?: (e: unknown) => void;
  /**
   * 담고 있던 것을 **버렸다**. 왜 버렸는지 사람이 읽을 문장으로 준다.
   *
   * [🔴 왜 이 통로가 생겼나 — 2026-08-17 사장 신고] "마이크 누르고 말해도 입력칸에
   *   아무것도 안 뜬다." 그런데 서버 칸은 멀쩡했다(사이드카 /stt 2.6초·앱 프록시
   *   /api/voice/stt 2.5초, 둘 다 글자까지 정상). 즉 소리가 **여기서** 버려졌는데
   *   버리는 자리 두 곳이 전부 조용한 `return` 이라 화면에 아무 흔적도 안 남았다.
   *   원인을 못 좁힌 이유가 바로 그 침묵이다 — 이 저장소가 이미 같은 교훈을 적어 뒀다
   *   ("서버가 옳은 말을 해도 화면이 버리면 없는 말이다", voice_api 헤더).
   * [불변식] 버리는 return 을 새로 만들면 **여기도 같이 부른다.** 안 부르면 그 자리는
   *   다시 '아무 일도 안 일어난 것'처럼 보인다.
   */
  onDropped?: (why: string, meta: { ms: number; peak: number }) => void;
}

/**
 * 마이크 세션 하나.
 *
 * [🔴 전역에 하나만 만든다] 터미널 슬롯마다 만들면 인식기 여럿이 같은 마이크를 잡고
 *   전부 죽는다. 소유자는 lib/voiceBus.ts 이고, 이 클래스를 직접 new 하지 말 것.
 */
export class MicCapture {
  private ctx: AudioContext | null = null;
  private stream: MediaStream | null = null;
  private node: ScriptProcessorNode | null = null;
  private source: MediaStreamAudioSourceNode | null = null;

  private buf: Float32Array[] = [];      // 현재 발화의 PCM 조각들(리샘플 후)
  private speaking = false;
  private silenceRun = 0;                // 무음이 이어진 샘플 수
  private speechSamples = 0;
  private peak = 0;
  private opts: Required<VadOptions>;

  constructor(private handlers: CaptureHandlers, opts: VadOptions = {}) {
    this.opts = { ...DEFAULTS, ...opts };
  }

  get running(): boolean { return !!this.ctx; }

  async start(): Promise<void> {
    if (this.ctx) return;
    try {
      this.stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          channelCount: 1,
          // [WHY 브라우저 처리를 켜 두나] 끄면 스피커로 나간 낭독이 마이크로 되돌아와
          //   자기 목소리를 지시로 받아적는다. 에코 제거는 그 1차 방어선이다.
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
        },
      });
    } catch (e) {
      this.handlers.onError?.(e);
      throw e;
    }

    const Ctor: typeof AudioContext =
      window.AudioContext || (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext;
    this.ctx = new Ctor();
    this.source = this.ctx.createMediaStreamSource(this.stream);

    // [WHY AudioWorklet 이 아니라 ScriptProcessor 인가] Worklet 은 별도 모듈 파일을
    //   addModule 로 불러와야 하는데, 이 앱은 Vite 번들 + WebView2 라 그 URL 을
    //   맞추는 데 배포 경로 함정이 하나 더 생긴다. 이 용도(음성 한 줄)에는 deprecated
    //   경로가 실용적으로 안전하다. 끊김이 생기면 그때 Worklet 으로 옮길 것.
    this.node = this.ctx.createScriptProcessor(4096, 1, 1);
    this.node.onaudioprocess = (ev) => this.onAudio(ev.inputBuffer);
    this.source.connect(this.node);
    // [🔴 destination 에 연결해야 콜백이 돈다] 크롬은 목적지에 닿지 않은 그래프를
    //   돌리지 않는다. 소리가 나가면 안 되므로 볼륨 0 게인을 사이에 둔다.
    const mute = this.ctx.createGain();
    mute.gain.value = 0;
    this.node.connect(mute);
    mute.connect(this.ctx.destination);
  }

  stop(): void {
    try { this.node?.disconnect(); } catch { /* 이미 끊김 */ }
    try { this.source?.disconnect(); } catch { /* 이미 끊김 */ }
    try { this.stream?.getTracks().forEach((t) => t.stop()); } catch { /* 이미 끝남 */ }
    try { void this.ctx?.close(); } catch { /* 이미 닫힘 */ }
    this.node = null; this.source = null; this.stream = null; this.ctx = null;
    this.hold = false;
    this.reset();
  }

  /** 낭독 중에는 받아적지 않는다 — 자기 목소리를 지시로 먹는 사고를 막는 2차 방어선. */
  private muted = false;
  setMuted(v: boolean): void {
    this.muted = v;
    if (v) this.reset();
  }

  /**
   * '누르고 말하기' 모드.
   *
   * [🔴 왜 VAD 를 통째로 우회하나] 버튼을 누르고 있는 동안은 사람이 이미 '지금부터
   *   말한다'고 선언한 것이다. 그런데 VAD 문턱(threshold)은 조용히 말하는 첫 음절을
   *   자주 흘리고, 말 도중 잠깐 뜸을 들이면 silenceMs 로 발화를 끊어 문장을 두 동강
   *   낸다. 누르고 있는 동안은 전부 담고, 손을 떼는 순간이 곧 '끝'이다.
   * [제약] maxSpeechMs 는 그대로 산다 — 버튼이 눌린 채 잊히면 마이크가 영영 열린다.
   */
  private hold = false;
  beginHold(): void {
    this.hold = true;
    this.reset();
  }

  /**
   * 손을 뗐다 — 담고 있던 것을 **그 자리에서** 발화로 확정한다.
   *
   * [🔴 무음을 기다리지 않는다] 기다리면 손을 뗀 뒤 900ms 동안 들어온 주변 소리가
   *   같은 발화에 붙는다. 그리고 사용자는 그 사이를 '먹통'으로 읽는다.
   */
  releaseHold(): void {
    this.hold = false;
    if (!this.speaking) {
      // [🔴 여기에 오면 마이크에서 소리 조각이 **한 번도** 안 왔다는 뜻이다]
      //   홀드 중에는 문턱(threshold)을 아예 안 보고 첫 콜백에서 speaking 을 켠다
      //   (onAudio 의 hold 가지). 그러니 speaking 이 거짓인 채로 손을 뗐다면 볼륨이
      //   작아서가 아니라 **오디오 콜백 자체가 안 돈 것**이다 — WebView2 마이크 권한이
      //   허용도 거부도 아닌 채 매달리면 정확히 이 모양이 된다(pywebview 6.1 함정).
      //   예전에는 조용히 reset() 만 하고 끝나 화면에 아무 말도 안 남았다.
      this.handlers.onDropped?.('마이크에서 소리가 들어오지 않았습니다(권한/장치 확인)',
                                { ms: 0, peak: this.peak });
      this.reset();
      return;
    }
    // 누르고 말한 것은 짧아도 버리지 않는다("네", "응"). 대신 헛클릭(120ms 미만)은 버린다.
    this.flush(this.currentMs(), 120);
  }

  private currentMs(): number {
    return (this.speechSamples / TARGET_RATE) * 1000;
  }

  private reset(): void {
    this.buf = [];
    this.speaking = false;
    this.silenceRun = 0;
    this.speechSamples = 0;
    this.peak = 0;
  }

  private onAudio(input: AudioBuffer): void {
    if (this.muted) return;
    const src = input.getChannelData(0);

    let sum = 0;
    for (let i = 0; i < src.length; i++) sum += src[i] * src[i];
    const rms = Math.sqrt(sum / src.length);
    this.handlers.onLevel?.(Math.min(1, rms * 8));
    if (rms > this.peak) this.peak = rms;

    const rate = input.sampleRate;
    const loud = rms >= this.opts.threshold;

    if (this.hold) {
      // 누르고 있는 동안은 문턱·무음 판정을 보지 않는다(beginHold 주석 참조).
      if (!this.speaking) {
        this.speaking = true;
        this.speechSamples = 0;
        this.buf = [];
        this.handlers.onSpeechState?.(true);
      }
      this.buf.push(downsample(src, rate, TARGET_RATE));
      this.speechSamples += Math.round((src.length / rate) * TARGET_RATE);
      if (this.currentMs() >= this.opts.maxSpeechMs) {
        this.hold = false;                       // 눌린 채 잊힌 버튼에서 마이크를 되찾는다
        this.flush(this.currentMs(), 120);
      }
      return;
    }

    if (!this.speaking) {
      if (!loud) return;
      this.speaking = true;
      this.silenceRun = 0;
      this.speechSamples = 0;
      this.buf = [];
      this.handlers.onSpeechState?.(true);
    }

    this.buf.push(downsample(src, rate, TARGET_RATE));
    this.speechSamples += Math.round((src.length / rate) * TARGET_RATE);
    this.silenceRun = loud ? 0 : this.silenceRun + Math.round((src.length / rate) * 1000);

    const ms = (this.speechSamples / TARGET_RATE) * 1000;
    if (this.silenceRun >= this.opts.silenceMs || ms >= this.opts.maxSpeechMs) {
      this.flush(ms);
    }
  }

  private flush(ms: number, minMs = this.opts.minSpeechMs): void {
    const chunks = this.buf;
    const peak = this.peak;
    this.speaking = false;
    this.buf = [];
    this.speechSamples = 0;
    this.silenceRun = 0;
    this.peak = 0;
    this.handlers.onSpeechState?.(false);

    // 너무 짧으면 버린다. [WHY] 문 닫는 소리·마우스 클릭이 매번 서버로 나가면
    //   인식기가 헛돌고, 그 결과 "말한 적 없는 문장"이 입력창에 꽂힌다.
    // [제약] 기준은 호출부가 낮출 수 있다 — 누르고 말하기는 사람이 이미 의도를 밝혔다.
    if (ms < minMs) {
      // 헛클릭·기침을 거르는 정상 동작이지만, **왜 안 갔는지는 말해 준다.**
      // 누르고 말했는데 매번 여기로 떨어지면 그건 거름이 아니라 고장이다.
      this.handlers.onDropped?.(`너무 짧아 보내지 않았습니다(${Math.round(ms)}ms)`,
                                { ms, peak });
      return;
    }

    const total = chunks.reduce((n, c) => n + c.length, 0);
    const pcm = new Float32Array(total);
    let at = 0;
    for (const c of chunks) { pcm.set(c, at); at += c.length; }
    this.handlers.onUtterance(encodeWav(pcm, TARGET_RATE), { ms, peak });
  }
}

/**
 * 선형 보간 다운샘플.
 *
 * [제약] 저역 통과 필터가 없어 이론상 에일리어싱이 생긴다. 음성 인식용으로는
 *   실측상 문제가 되지 않았고, 필터를 넣으면 이 파일이 DSP 코드가 된다.
 *   인식률이 의심되면 여기부터 의심할 것.
 */
function downsample(src: Float32Array, from: number, to: number): Float32Array {
  if (from === to) return src.slice();
  const ratio = from / to;
  const out = new Float32Array(Math.floor(src.length / ratio));
  for (let i = 0; i < out.length; i++) {
    const pos = i * ratio;
    const i0 = Math.floor(pos);
    const i1 = Math.min(i0 + 1, src.length - 1);
    const t = pos - i0;
    out[i] = src[i0] * (1 - t) + src[i1] * t;
  }
  return out;
}

/** float32 PCM → 16bit WAV Blob. 헤더 44바이트가 전부다. */
export function encodeWav(pcm: Float32Array, rate: number): Blob {
  const buf = new ArrayBuffer(44 + pcm.length * 2);
  const view = new DataView(buf);
  const w = (off: number, s: string) => { for (let i = 0; i < s.length; i++) view.setUint8(off + i, s.charCodeAt(i)); };

  w(0, 'RIFF');
  view.setUint32(4, 36 + pcm.length * 2, true);
  w(8, 'WAVE');
  w(12, 'fmt ');
  view.setUint32(16, 16, true);
  view.setUint16(20, 1, true);          // PCM
  view.setUint16(22, 1, true);          // mono
  view.setUint32(24, rate, true);
  view.setUint32(28, rate * 2, true);   // byte rate
  view.setUint16(32, 2, true);          // block align
  view.setUint16(34, 16, true);         // bits
  w(36, 'data');
  view.setUint32(40, pcm.length * 2, true);

  let off = 44;
  for (let i = 0; i < pcm.length; i++, off += 2) {
    const s = Math.max(-1, Math.min(1, pcm[i]));
    view.setInt16(off, s < 0 ? s * 0x8000 : s * 0x7fff, true);
  }
  return new Blob([buf], { type: 'audio/wav' });
}
