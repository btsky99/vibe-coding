/**
 * FILE: lib/folderPicker.ts
 * DESCRIPTION: 시스템 폴더 선택 다이얼로그 공유 헬퍼 — pywebview 네이티브 → HTTP API 순 시도.
 *
 * [WHY] window.prompt는 mac WKWebView(pywebview mac 백엔드)에서 신뢰성 문제가 있고 경로 검증이
 *   전무하다(오타·미존재 경로가 그대로 PTY cwd로 흘러감). FileExplorer.openFolder가 쓰는 검증된
 *   네이티브 다이얼로그 경로를 공유해, 실제 존재하는 폴더만 받도록 한다.
 *
 * REVISION HISTORY:
 * - 2026-07-24 Claude: 슬롯별 프로젝트 '변경' 버튼이 window.prompt를 재발명한 것을 코드리뷰에서 지적받아
 *   FileExplorer.openFolder(174행)와 동일한 네이티브 다이얼로그 폴백을 공유 헬퍼로 추출.
 */
import { API_BASE } from '../constants';

/**
 * 폴더 선택 다이얼로그를 띄우고 선택된 절대 경로를 반환.
 * 취소하거나 다이얼로그를 띄울 수 없으면(브라우저 모드 등) null.
 * [폴백 순서] ① pywebview 네이티브 API → ② HTTP /api/select-folder(네이티브 스레드 다이얼로그).
 */
export async function pickFolderDialog(): Promise<string | null> {
  try {
    const nativeApi = (window as any).pywebview?.api?.select_folder;
    if (nativeApi) {
      const data = await nativeApi();
      if (data?.status === 'success' && data.path) return data.path;
      if (data?.status === 'cancelled') return null;
    }
    const res = await fetch(`${API_BASE}/api/select-folder`, { method: 'POST' });
    const data = await res.json();
    if (data?.status === 'success' && data.path) return data.path;
    return null;
  } catch {
    return null;
  }
}
