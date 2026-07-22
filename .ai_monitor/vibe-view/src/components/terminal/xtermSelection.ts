/**
 * ------------------------------------------------------------------------
 * 📄 파일명: xtermSelection.ts
 * 📝 설명: 터미널 클립보드 복사 + xterm 선택(하이라이트) 유지 유틸.
 *          TerminalSlot.tsx가 1500줄 제한을 넘겨 도메인 단위(클립보드/선택)로 분리.
 * REVISION HISTORY:
 * - 2026-07-22 Claude: 클립보드 I/O를 lib/clipboard.ts(pywebview NSPasteboard 브리지 폴백)로 위임 —
 *   맥 WKWebView가 navigator.clipboard를 조용히 거부해 복붙 전멸하던 문제.
 * - 2026-07-22 Claude: installClipboardShortcuts 신설 — 맥 ⌘C/⌘V + 윈도우 Ctrl+Shift+C/V 터미널 복붙 지원.
 * - 2026-07-05 Claude: TerminalSlot.tsx에서 copyTextToClipboard + 선택 좌표 캡처 로직 분리 신설.
 * ------------------------------------------------------------------------
 */
import type { Terminal as XTerm } from '@xterm/xterm';
import { readClipboardText, writeClipboardText } from '../../lib/clipboard';

// [WHY] navigator.platform은 deprecated지만 WKWebView/WebView2 양쪽에서 여전히 유효.
// userAgent 폴백 병행 — 맥 판정이 틀리면 ⌘ 단축키가 통째로 죽으므로 이중 검사.
const IS_MAC = /Mac/i.test(navigator.platform) || /Macintosh/i.test(navigator.userAgent);

// [호환] 기존 호출부(TerminalSlot 등)가 쓰는 이름 유지 — 구현은 lib/clipboard로 위임.
// xterm getSelection()은 Windows에서 이미 \r\n으로 join되므로 CRLF 재정규화 불필요.
export async function copyTextToClipboard(text: string): Promise<void> {
  return writeClipboardText(text);
}

// [WHY] 터미널 키보드 복붙 단축키 설치 — 맥/윈도우 관례가 달라서 플랫폼 분기 필수.
//   맥: ⌘C 복사 / ⌘V 붙여넣기 (Ctrl+C는 SIGINT라 건드리지 않음)
//   윈도우/리눅스: Ctrl+Shift+C 복사 / Ctrl+Shift+V 붙여넣기 (터미널 표준 관례).
//     일반 Ctrl+V는 WebView2가 네이티브 paste 이벤트를 쏴줘서 이미 동작 — 개입하면 이중 붙여넣기.
//
// [맥 WKWebView 함정 — 이 함수가 존재하는 이유]
//   1) xterm 선택은 캔버스 오버레이(DOM 선택 아님) → 네이티브 Edit 메뉴의 copy:가 빈 값을 복사.
//      → document 'copy' 이벤트를 가로채 clipboardData에 터미널 선택/캐시를 직접 주입.
//   2) Edit 메뉴가 keyEquivalent를 소비하면 keydown이 JS에 안 오고, 메뉴가 죽어 있으면 keydown만 온다.
//      두 경로가 상호배타적이지 않은 환경(브라우저 dev 모드 등)이 있어 붙여넣기는 이중 실행 위험 —
//      keydown 경로를 140ms 지연 실행하고, 네이티브 paste 이벤트가 먼저 도착하면 지연분을 취소해 단일화.
// [불변식] 붙여넣기는 반드시 term.paste() 경유 — ws.send 직송은 bracketed paste 모드를 우회해
//   TUI(claude CLI)에서 멀티라인 붙여넣기가 줄 단위로 즉시 실행되는 사고로 이어진다.
export function installClipboardShortcuts(
  term: XTerm,
  getCachedSelection: () => string,
  onPasteDenied: () => void,
): void {
  let pendingPaste: ReturnType<typeof setTimeout> | null = null;

  const doPaste = () => {
    readClipboardText()
      .then(text => { if (text) term.paste(text); })
      .catch(() => onPasteDenied());
  };

  term.attachCustomKeyEventHandler((ev: KeyboardEvent) => {
    if (ev.type !== 'keydown') return true;
    const key = ev.key.toLowerCase();
    const copyCombo = IS_MAC
      ? (ev.metaKey && !ev.ctrlKey && !ev.altKey && !ev.shiftKey && key === 'c')
      : (ev.ctrlKey && ev.shiftKey && key === 'c');
    const pasteCombo = IS_MAC
      ? (ev.metaKey && !ev.ctrlKey && !ev.altKey && !ev.shiftKey && key === 'v')
      : (ev.ctrlKey && ev.shiftKey && key === 'v');
    if (copyCombo) {
      // 복사는 같은 텍스트를 두 번 써도 무해 → 지연 없이 즉시. 선택이 이미 지워졌으면 캐시 폴백.
      const sel = (term.hasSelection() ? term.getSelection() : '') || getCachedSelection();
      if (sel) copyTextToClipboard(sel);
      ev.preventDefault();
      return false;
    }
    if (pasteCombo) {
      if (pendingPaste) clearTimeout(pendingPaste);
      pendingPaste = setTimeout(() => { pendingPaste = null; doPaste(); }, 140);
      ev.preventDefault();
      return false;
    }
    return true;
  });

  // 네이티브 paste 이벤트가 도착 = 메뉴/브라우저 경로가 살아 있음 → keydown 지연분 취소 (이중 방지).
  // xterm 자체 paste 핸들러가 이 이벤트를 처리해 PTY로 보내므로 여기선 취소만 한다.
  term.textarea?.addEventListener('paste', () => {
    if (pendingPaste) { clearTimeout(pendingPaste); pendingPaste = null; }
  }, true);

  // 네이티브 copy: 액션(맥 Edit 메뉴 경유)이 터미널 위에서 발화하면 빈 복사가 되는 문제 보정 —
  // clipboardData에 터미널 선택/캐시를 직접 주입. 터미널 밖(입력창 등)의 copy는 건드리지 않는다.
  term.textarea?.addEventListener('copy', (e: ClipboardEvent) => {
    const sel = (term.hasSelection() ? term.getSelection() : '') || getCachedSelection();
    if (sel && e.clipboardData) {
      e.clipboardData.setData('text/plain', sel);
      e.preventDefault();
    }
  }, true);
}

// [WHY] 현재 선택을 나중에 term.select()로 재적용하기 위한 좌표 스냅샷.
// getSelectionPosition은 버퍼 절대 좌표(0-based col, 스크롤백 포함 row)를 주고, start/end가
// 역방향(위로 드래그)일 수 있어 읽기 순서로 정규화한다. len = (행 차 × cols) + 열 차 —
// select()가 length를 cols에서 wrap시키는 규칙의 역산이라 멀티라인 선택도 한 번에 복원된다.
export function captureSelectRestore(term: XTerm): { col: number; row: number; len: number } | null {
  const pos = term.getSelectionPosition();
  if (!pos) return null;
  const cols = term.cols;
  const fwd = pos.start.y < pos.end.y || (pos.start.y === pos.end.y && pos.start.x <= pos.end.x);
  const a = fwd ? pos.start : pos.end;
  const b = fwd ? pos.end : pos.start;
  const len = (b.y - a.y) * cols + (b.x - a.x);
  return len > 0 ? { col: a.x, row: a.y, len } : null;
}
