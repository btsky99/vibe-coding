/**
 * ------------------------------------------------------------------------
 * 📄 파일명: lib/speech.ts
 * 📝 설명: 음성 입출력의 순수 로직 — 마크다운→낭독문 변환, 문장 쪼개기, 톤 프리셋,
 *          목소리 점수, 웨이크워드 패턴. DOM·상태를 만지지 않으므로 테스트 가능하다.
 *          엔진(마이크·합성기)은 lib/voiceBus.ts 가 소유한다.
 *
 *          아픽스(D:/apix board/app.js 음성 섹션)에서 이식. 그쪽 값들은 귀로 듣고
 *          맞춘 실측치라 임의로 바꾸면 체감이 곧바로 나빠진다.
 *
 * REVISION HISTORY:
 * - 2026-08-15 Claude: 최초 작성 — 아픽스 음성 기능 이식(순수 로직 분리)
 * ------------------------------------------------------------------------
 */

/* ── 호출어 ───────────────────────────────────────────────────────────────── */

/**
 * 인식된 문장에서 어느 슬롯을 부른 것인지 가려낸다.
 *
 * [WHY 고정 정규식이 아닌가] 아픽스는 호출어가 "아픽스" 하나여서 변형까지 정규식에
 *   박아 둘 수 있었다. 여기는 슬롯마다 사용자가 직접 정한다 — 미리 알 수 없는 말이라
 *   패턴을 손으로 못 쓴다. 그래서 정규화 후 부분일치로 찾는다.
 *
 * [🔴 조사를 잘라 내야 한다] 사람은 "클로드"라고 안 부르고 "클로드야", "클로드가"라고
 *   부른다. 호출어 뒤에 붙은 조사는 지시문이 아니므로 떼어 낸다. 안 그러면 입력창에
 *   "야 테스트 돌려줘"가 들어간다.
 *
 * [🔴 가장 앞에 나온 슬롯이 이긴다] 두 호출어가 한 문장에 다 들어 있을 때
 *   ("클로드한테 코덱스 얘기 전해줘") 뒤엣것을 고르면 엉뚱한 슬롯이 받는다.
 *
 * @param text  인식 결과 문장
 * @param words 슬롯ID → 호출어 (예: {T1: '클로드', T2: '코덱스'})
 * @returns 매칭된 슬롯과, 호출어를 걷어낸 나머지 지시문. 없으면 null.
 */
export function matchWakeWord(
  text: string,
  words: Record<string, string>,
): { slot: string; rest: string } | null {
  const norm = normalizeForWake(text);
  if (!norm) return null;

  let best: { slot: string; at: number; end: number } | null = null;
  for (const [slot, raw] of Object.entries(words)) {
    const w = normalizeForWake(raw);
    if (w.length < 2) continue;          // 한 글자 호출어는 오인식이 너무 많다
    const at = norm.indexOf(w);
    if (at < 0) continue;
    // [🔴 문장 앞쪽만 호출로 인정한다] 말 중간에 우연히 나온 단어까지 받으면
    //   대화하다가 아무 때나 슬롯이 깨어난다. 부르는 말은 앞에 온다.
    if (at > 6) continue;
    if (!best || at < best.at) best = { slot, at, end: at + w.length };
  }
  if (!best) return null;

  // 원문에서 잘라야 띄어쓰기·문장부호가 살아 있는 지시문이 남는다. 정규화 문자열의
  // 인덱스는 원문과 어긋나므로, 원문에서 다시 찾아 자른다.
  const rest = cutAfterWake(text, words[best.slot]);
  return { slot: best.slot, rest };
}

/** 비교용 정규화 — 공백·문장부호를 지우고 소문자로. 인식기가 띄어쓰기를 자주 흘린다. */
function normalizeForWake(s: string): string {
  return String(s || '')
    .toLowerCase()
    .replace(/[\s,.!?~…·'"'"()[\]{}]/g, '');
}

/** 원문에서 호출어(와 뒤에 붙은 조사)를 걷어낸 나머지. */
function cutAfterWake(text: string, wake: string): string {
  const cleanWake = normalizeForWake(wake);
  const chars = [...String(text)];
  let acc = '';
  let endIdx = -1;
  for (let i = 0; i < chars.length; i++) {
    if (!/[\s,.!?~…·'"'"()[\]{}]/.test(chars[i])) acc += chars[i].toLowerCase();
    if (acc.endsWith(cleanWake)) { endIdx = i + 1; break; }
  }
  if (endIdx < 0) return String(text).trim();

  let rest = chars.slice(endIdx).join('');
  // 호출어에 붙은 조사·감탄사만 제거. [제약] 목록을 넓히면 진짜 지시문의 첫 낱말을
  // 먹는다 — "클로드 야마존 API" 같은 경우가 생기므로 짧고 확실한 것만 둔다.
  rest = rest.replace(/^\s*(아|야|이|가|은|는|님|씨|한테|에게|더러)?\s*[,.!?~]*\s*/, '');
  return rest.trim();
}

/**
 * 느낌 프리셋.
 *
 * [🔴 '부드럽게'는 한 값으로 안 나온다] 속도·높이·크기가 함께 움직여야 한다.
 *   조금 느리고, 조금 높고, 조금 작게 — 셋이 같이 가야 몰아붙이지 않는 느낌이 된다.
 *   사람에게 슬라이더 셋을 각각 맞추라고 하면 아무도 안 맞춘다.
 * [WHY gap 도 프리셋인가] 부드러움은 목소리만의 문제가 아니다. 천천히 말해도 문장
 *   사이가 짧으면 여전히 몰아붙인다. 느리게 말하는 사람은 사이도 길게 둔다.
 */
export type ToneName = 'verysoft' | 'soft' | 'normal' | 'clear';

export interface Tone { rate: number; pitch: number; vol: number; gap: number }

export const TONES: Record<ToneName, Tone> = {
  verysoft: { rate: 0.85, pitch: 1.30, vol: 0.72, gap: 300 },
  soft:     { rate: 0.92, pitch: 1.20, vol: 0.85, gap: 180 },
  normal:   { rate: 1.00, pitch: 1.00, vol: 1.00, gap: 140 },
  clear:    { rate: 1.05, pitch: 0.95, vol: 1.00, gap: 120 },
};

export const TONE_LABELS: Record<ToneName, string> = {
  verysoft: '아주 부드럽게',
  soft: '부드럽게',
  normal: '보통',
  clear: '또렷하게',
};

/** 낭독 길이 상한. [WHY] 2천 자를 다 읽으면 3분이 넘는다. 요지만 읽고 나머지는 눈으로. */
const MAX_SPEECH = 700;

/**
 * 마크다운을 귀로 들을 수 있는 문장으로 바꾼다.
 *
 * [🔴 왜 필요한가] 턴 채널의 text 는 사람이 눈으로 읽을 마크다운이다. 그대로 읽히면
 *   "별표 별표 판정 별표 별표", 표는 "파이프 파이프 파이프"가 된다. 코드 블록은
 *   통째로 읽으면 몇 분씩 간다.
 * [WHY 표·코드를 버리나] 귀로 표를 따라갈 수 없다. 눈으로 볼 것은 화면에 이미 있으니,
 *   소리는 '무엇이 있었는지'만 알리고 넘어가는 편이 낫다.
 */
export function toSpeech(md: string): string {
  let s = String(md || '');
  let codes = 0;
  s = s.replace(/```[\s\S]*?```/g, () => { codes++; return ' '; });

  const kept: string[] = [];
  let tables = 0;
  for (const line of s.split('\n')) {
    const t = line.trim();
    if (/^\|.*\|$/.test(t) || (/^[|\s:-]+$/.test(t) && t.includes('|'))) { tables++; continue; }
    kept.push(line);
  }
  s = kept.join('\n');

  s = s.replace(/^#{1,6}\s*/gm, '')                 // 제목 표시
    .replace(/\[([^\]]+)\]\([^)]*\)/g, '$1')        // 링크는 글자만
    .replace(/[*_~`]/g, '')                         // 강조·인라인코드 표시
    .replace(/^\s*[-•]\s+/gm, '')                   // 목록 기호
    .replace(/^\s*>\s?/gm, '')                      // 인용
    // [🔴 경로·파일명은 소리에서 뺀다] "슬래시 에이피아이 슬래시"는 귀로 못 따라가고
    //   그 구간에서 낭독이 유난히 딱딱해진다. 화면에 이미 있다.
    // [🔴 지우지 말고 낱말로 바꾼다 — 아픽스 실측] 그냥 지웠더니 조사가 붕 떴다:
    //   "읽을 문장은 에서 옵니다". 문장이 무너지면 안 들린다.
    // [🔴 경로를 먼저] 파일 규칙을 먼저 돌리면 src/App.tsx 가 'src/해당 파일'이 되고,
    //   이어서 경로 규칙이 앞부분만 먹어 '해당 경로 파일'이 된다(실측).
    .replace(/\S*\/\S+/g, '해당 경로')
    .replace(/\b[\w.-]+\.(js|jsx|ts|tsx|py|json|html|css|sh|ps1|log|md|sql|yml|yaml)\b/gi, '해당 파일')
    // 줄표는 쉼표로. [WHY] 쉼표가 있어야 합성기가 그 자리에서 숨을 쉰다.
    .replace(/\s*[—–]\s*/g, ', ')
    .replace(/\n{2,}/g, '. ')
    .replace(/\s+/g, ' ')
    .replace(/\s+([,.])/g, '$1')
    // 걷어낸 자리에 남은 겹친 마침표·쉼표를 하나로. 안 그러면 "둘뿐입니다..."처럼
    // 읽혀 문장이 끝났는지 귀로 알 수 없다.
    .replace(/([,.])[\s,.]*\1*/g, '$1 ')
    .replace(/\s+/g, ' ')
    .trim();

  const tail: string[] = [];
  if (codes) tail.push(`코드 블록 ${codes}개 생략`);
  if (tables) tail.push('표 생략');

  if (s.length > MAX_SPEECH) {
    const cut = s.slice(0, MAX_SPEECH);
    const at = Math.max(cut.lastIndexOf('. '), cut.lastIndexOf('다 '));
    s = (at > 200 ? cut.slice(0, at + 1) : cut) + ' 이하 생략. 화면에서 확인하세요.';
  }
  if (tail.length) s += ' ' + tail.join(', ') + '.';
  return s;
}

// [🔴 눈에 안 보이는 구분자를 소스에 박지 않는다] 제어문자를 그대로 넣으면 편집기·
//   린터가 조용히 지워도 아무도 못 알아채고, 그날부터 낭독이 한 덩어리로 돌아간다.
const SPLIT = '\u0001';

/**
 * 문장 단위로 쪼갠다.
 *
 * [🔴 이것이 '기계 같음'의 진짜 원인] 같은 목소리라도 두 문장을 쉼 없이 이어 붙이면
 *   딱딱하게 들린다. 사람은 문장 사이에서 숨을 쉰다. 목소리를 바꾸는 것 다음으로
 *   체감이 큰 지렛대다.
 */
export function chunkSentences(input: string): string[] {
  const parts = String(input)
    .replace(/([.!?])\s+/g, '$1' + SPLIT)
    // 한국어는 마침표 없이 끝나는 문장이 흔하다 — 종결어미에서도 자른다.
    .replace(/(다|요|죠|까|네)\s*[.!?]?\s+/g, '$1' + SPLIT)
    .split(SPLIT)
    .map((t) => t.trim())
    .filter(Boolean);

  // 너무 짧은 조각은 앞에 붙인다 — "네." 하나만 따로 말하면 되레 뚝뚝 끊긴다.
  const out: string[] = [];
  for (const p of parts) {
    if (out.length && (p.length < 12 || out[out.length - 1].length < 12)) {
      out[out.length - 1] += ' ' + p;
    } else out.push(p);
  }
  return out.length ? out : [String(input)];
}

/**
 * 설치된 목소리 중 '덜 기계적인' 순으로 점수를 매긴다.
 *
 * [🔴 기기마다 목록이 다르다] 이름 하나를 못 박으면 그 목소리가 없는 PC 에서는
 *   아무거나 걸린다. 점수만 매기고 **최종 선택은 사람에게 넘긴다.**
 *
 * [실측 2026-08-15 — 이 앱의 제약] 브라우저와 달리 WebView2 에는 한국어 목소리가
 *   Microsoft Heami 하나뿐이다(Edge 가 노출하는 Natural/Neural 계열은 안 보인다).
 *   그래서 이 앱에서는 목소리 선택보다 톤 프리셋·문장 쪼개기가 체감을 좌우한다.
 */
export function scoreVoice(v: SpeechSynthesisVoice): number {
  const n = (v.name || '') + ' ' + (v.voiceURI || '');
  let s = 0;
  if (/^ko/i.test(v.lang)) s += 100;            // 한국어가 아니면 애초에 후보가 아니다
  if (/natural|neural/i.test(n)) s += 40;       // 신경망 합성 — 가장 큰 차이
  if (/sunhi|선희/i.test(n)) s += 12;
  if (/yuna|유나/i.test(n)) s += 10;            // macOS 한국어 여성
  if (/heami|해미/i.test(n)) s += 8;
  if (/google/i.test(n)) s += 6;
  if (/male(?!.*female)|남성/i.test(n)) s -= 15;
  if (v.localService === false) s += 3;          // 온라인 목소리가 대체로 낫다
  return s;
}

/** 한국어 우선 + 점수순 정렬. 한국어가 하나도 없으면 전체를 준다(있는 걸로라도 읽는다). */
export function sortVoices(all: SpeechSynthesisVoice[]): SpeechSynthesisVoice[] {
  const ko = all.filter((v) => /^ko/i.test(v.lang));
  return (ko.length ? ko : all).slice().sort((a, b) => scoreVoice(b) - scoreVoice(a));
}
