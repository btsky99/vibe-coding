/**
 * ------------------------------------------------------------------------
 * 📄 파일명: xtermSelection.ts
 * 📝 설명: 터미널 클립보드 복사 + xterm 선택(하이라이트) 유지 유틸.
 *          TerminalSlot.tsx가 1500줄 제한을 넘겨 도메인 단위(클립보드/선택)로 분리.
 * REVISION HISTORY:
 * - 2026-07-05 Claude: TerminalSlot.tsx에서 copyTextToClipboard + 선택 좌표 캡처 로직 분리 신설.
 * ------------------------------------------------------------------------
 */
import type { Terminal as XTerm } from '@xterm/xterm';

// [WHY] 클립보드 쓰기 공용 헬퍼 — navigator.clipboard 실패 시 execCommand 폴백.
// WebView2(PyWebView)에서 writeText가 포커스/권한 사유로 거부될 수 있어 폴백 필수.
// xterm getSelection()은 Windows에서 이미 \r\n으로 join되므로 CRLF 재정규화 불필요.
export async function copyTextToClipboard(text: string): Promise<void> {
  try {
    await navigator.clipboard.writeText(text);
  } catch {
    const ta = document.createElement('textarea');
    ta.value = text;
    ta.style.position = 'fixed';
    ta.style.left = '-9999px';
    document.body.appendChild(ta);
    ta.select();
    document.execCommand('copy');
    document.body.removeChild(ta);
  }
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
