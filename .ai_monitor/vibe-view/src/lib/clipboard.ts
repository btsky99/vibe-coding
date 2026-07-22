/**
 * ------------------------------------------------------------------------
 * 📄 파일명: clipboard.ts
 * 📝 설명: 클립보드 읽기/쓰기 공용 헬퍼 — pywebview 네이티브 브리지 우선, navigator.clipboard 폴백.
 *          우클릭 메뉴/단축키/복사 버튼 등 프론트 전체가 이 모듈만 사용한다.
 * REVISION HISTORY:
 * - 2026-07-22 Claude: 신설 — 맥 WKWebView가 navigator.clipboard.readText를 권한 UI 없이
 *   조용히 거부해(NotAllowedError) 우클릭 복사/붙여넣기가 전멸하던 문제의 근본 수정.
 * ------------------------------------------------------------------------
 */

// [WHY] 맥 WKWebView는 async Clipboard API의 권한 프롬프트를 구현하지 않아 readText가 조용히
// 거부된다(윈도우 WebView2는 허용 → "윈도우만 되던" 원인). app_boot.py의 _ClipboardBridge가
// NSPasteboard로 구현한 js_api(clip_read/clip_write)를 우선 사용하고, 브리지가 없거나(브라우저
// dev 모드) 비지원 플랫폼(null/false 반환)이면 navigator.clipboard로 폴백한다.
type PywebviewClipApi = {
  clip_read?: () => Promise<string | null>;
  clip_write?: (text: string) => Promise<boolean>;
};

function bridge(): PywebviewClipApi | undefined {
  return (window as unknown as { pywebview?: { api?: PywebviewClipApi } }).pywebview?.api;
}

// [제약] 브리지 우선 순서 고정 — 브리지는 포커스/권한/사용자 제스처와 무관하게 결정적이지만
// navigator 쪽은 WebView 백엔드 재량이라 결과가 갈린다. 둘 다 실패 시 reject — 호출부가 안내 표시.
export async function readClipboardText(): Promise<string> {
  const api = bridge();
  if (api?.clip_read) {
    try {
      const t = await api.clip_read();
      if (typeof t === 'string') return t; // null = 비지원 플랫폼 → navigator 폴백
    } catch {
      /* navigator 폴백 */
    }
  }
  return navigator.clipboard.readText();
}

export async function writeClipboardText(text: string): Promise<void> {
  const api = bridge();
  if (api?.clip_write) {
    try {
      if (await api.clip_write(text)) return;
    } catch {
      /* navigator 폴백 */
    }
  }
  try {
    await navigator.clipboard.writeText(text);
  } catch {
    // [WHY] execCommand 최후 폴백 — async 체인 뒤라 사용자 제스처가 만료됐을 수 있지만
    // WebView2 구버전에서 이 경로만 통하던 사례가 있어 유지.
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
