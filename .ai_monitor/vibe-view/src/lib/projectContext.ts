/**
 * ------------------------------------------------------------------------
 * 📄 파일명: lib/projectContext.ts
 * 📝 설명: 프론트엔드 프로젝트 컨텍스트 헬퍼 (Phase 2-5.2).
 *          백엔드 infra/project_context.py의 slugify와 동일 규칙으로
 *          현재 프로젝트 경로 → project_id 슬러그 변환.
 *          API 호출 URL에 ?project_id=를 자동 첨부하는 withProjectId 제공.
 *          멀티 윈도우/탭 전환 직후 race window 차단 목적.
 * REVISION HISTORY:
 * - 2026-05-02 Claude: 최초 작성 — Phase 2-5.2
 * ------------------------------------------------------------------------
 */

/**
 * 프로젝트 경로를 백엔드와 동일한 규칙으로 슬러그화.
 * 예: 'D:/vibe-coding' → 'D--vibe-coding'
 * 백엔드 기준: infra/project_context.py::slugify
 */
export function slugifyProjectPath(path: string): string {
  if (!path) return '';
  return path
    .replace(/\\/g, '/')
    .replace(/:/g, '')
    .replace(/\//g, '--')
    .replace(/^-+/, '');
}

/**
 * URL에 ?project_id= 쿼리를 첨부. currentPath가 비면 원본 반환.
 * 이미 쿼리 있으면 &로 이어붙인다.
 */
export function withProjectId(url: string, currentPath?: string): string {
  if (!currentPath) return url;
  const pid = slugifyProjectPath(currentPath);
  if (!pid) return url;
  const sep = url.includes('?') ? '&' : '?';
  return `${url}${sep}project_id=${encodeURIComponent(pid)}`;
}
