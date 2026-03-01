/**
 * FILE: GitPanel.tsx
 * DESCRIPTION: Git 저장소 실시간 감시 패널 — 브랜치 상태, 파일 변경, 커밋 로그를 5초 폴링으로 표시
 * REVISION HISTORY:
 * - 2026-03-01 Claude: App.tsx에서 분리 — 독립 컴포넌트화
 */

import { useState, useEffect } from 'react';
import {
  GitBranch,
  AlertTriangle,
  GitCommit as GitCommitIcon,
  ArrowUp,
  ArrowDown,
} from 'lucide-react';
import { GitStatus, GitCommit } from '../../types';

// 현재 접속 포트 기반으로 API 주소 자동 결정 (App.tsx와 동일한 방식)
const API_BASE = `http://${window.location.hostname}:${window.location.port}`;

// ─── Props 타입 ─────────────────────────────────────────────────────────────
interface GitPanelProps {
  /** 모니터링할 Git 저장소의 절대 경로 (부모 컴포넌트의 currentPath와 동기화) */
  currentPath: string;
  /**
   * 변경 파일 수 및 충돌 수 콜백 — 부모가 Activity Bar 배지를 갱신하는 데 사용
   * @param count     staged + unstaged + untracked 합계
   * @param conflicts 충돌 파일 수
   */
  onChangesCount: (count: number, conflicts: number) => void;
}

/**
 * GitPanel
 * - gitPath 상태로 경로 편집 가능 (입력 blur 시 currentPath로 복귀 처리)
 * - 5초 간격 폴링으로 git status / git log 갱신
 * - staged, unstaged, untracked, conflicts 파일 목록 시각화
 * - 최근 커밋 로그 8개 표시
 */
export default function GitPanel({ currentPath, onChangesCount }: GitPanelProps) {
  // ─── 내부 상태 ────────────────────────────────────────────────────────
  const [gitStatus, setGitStatus] = useState<GitStatus | null>(null);
  const [gitLog, setGitLog] = useState<GitCommit[]>([]);

  // 경로 입력 필드 — 기본값은 부모로부터 받은 currentPath
  // 사용자가 직접 수정하여 다른 저장소를 모니터링할 수 있음
  const [gitPath, setGitPath] = useState(currentPath);

  // currentPath prop이 바뀌면(부모 디렉토리 이동) 내부 gitPath도 동기화
  useEffect(() => {
    setGitPath(currentPath);
  }, [currentPath]);

  // ─── Git 상태 폴링 ─────────────────────────────────────────────────────
  useEffect(() => {
    // 경로가 비어있으면 API 호출 생략 (초기 로드 전 안전장치)
    if (!gitPath) return;

    const fetchGit = () => {
      const encodedPath = encodeURIComponent(gitPath);

      // git status: 브랜치, staged/unstaged/untracked/conflicts 파일 목록
      fetch(`${API_BASE}/api/git/status?path=${encodedPath}`)
        .then(res => res.json())
        .then((data: GitStatus) => {
          setGitStatus(data);
          // 부모에게 배지용 숫자 전달 (충돌은 별도 집계)
          const total =
            (data.staged?.length ?? 0) +
            (data.unstaged?.length ?? 0) +
            (data.untracked?.length ?? 0);
          onChangesCount(total, data.conflicts?.length ?? 0);
        })
        .catch(() => {});

      // git log: 최근 15개 커밋 (표시는 8개만, 나머지는 여유분)
      fetch(`${API_BASE}/api/git/log?path=${encodedPath}&n=15`)
        .then(res => res.json())
        .then((data: GitCommit[]) => setGitLog(Array.isArray(data) ? data : []))
        .catch(() => {});
    };

    fetchGit(); // 마운트 또는 경로 변경 시 즉시 실행
    const interval = setInterval(fetchGit, 5000);
    return () => clearInterval(interval);
  }, [gitPath, onChangesCount]);

  // ─── 렌더링 ─────────────────────────────────────────────────────────────
  return (
    <div className="flex-1 flex flex-col overflow-hidden gap-2">
      {/* 경로 입력 — blur 시 빈 값이면 currentPath로 복귀 */}
      <input
        type="text"
        value={gitPath}
        onChange={e => setGitPath(e.target.value)}
        onBlur={() => setGitPath(gitPath.trim() || currentPath)}
        placeholder="Git 저장소 경로..."
        className="w-full bg-[#1e1e1e] border border-white/10 rounded px-2 py-1.5 text-[10px] focus:outline-none focus:border-primary text-white transition-colors font-mono shrink-0"
      />

      {/* Git 저장소가 아닌 경우 안내 메시지 */}
      {!gitStatus || !gitStatus.is_git_repo ? (
        <div className="text-center text-[#858585] text-xs py-10 flex flex-col items-center gap-2 italic">
          <GitBranch className="w-7 h-7 opacity-20" />
          {gitStatus?.error ? gitStatus.error : 'Git 저장소가 아닙니다'}
        </div>
      ) : (
        <div className="flex-1 overflow-y-auto custom-scrollbar flex flex-col gap-3">

          {/* ── 브랜치 + ahead/behind 요약 카드 ─────────────────────────── */}
          <div className="p-2 rounded border border-white/10 bg-white/2">
            <div className="flex items-center gap-2 mb-1.5">
              <GitBranch className="w-3.5 h-3.5 text-primary shrink-0" />
              <span className="text-[11px] font-bold text-primary font-mono">
                {gitStatus.branch}
              </span>
              {/* 로컬이 리모트보다 앞선 경우 — 푸시 필요 */}
              {gitStatus.ahead > 0 && (
                <span className="flex items-center gap-0.5 text-[9px] text-green-400 font-bold ml-auto">
                  <ArrowUp className="w-3 h-3" />{gitStatus.ahead}
                </span>
              )}
              {/* 리모트가 앞선 경우 — 풀 필요 */}
              {gitStatus.behind > 0 && (
                <span className="flex items-center gap-0.5 text-[9px] text-orange-400 font-bold ml-auto">
                  <ArrowDown className="w-3 h-3" />{gitStatus.behind}
                </span>
              )}
            </div>
            {/* 파일 수 요약 통계 행 */}
            <div className="flex gap-2 text-[9px] font-mono">
              <span className="text-green-400">S:{gitStatus.staged.length}</span>
              <span className="text-yellow-400">M:{gitStatus.unstaged.length}</span>
              <span className="text-[#858585]">?:{gitStatus.untracked.length}</span>
              {gitStatus.conflicts.length > 0 && (
                <span className="text-red-400 font-black animate-pulse">
                  ⚠ C:{gitStatus.conflicts.length}
                </span>
              )}
            </div>
          </div>

          {/* ── 충돌 파일 목록 (최우선 경고 — 빨간 테두리) ─────────────── */}
          {gitStatus.conflicts.length > 0 && (
            <div className="p-2 rounded border border-red-500/40 bg-red-500/5">
              <div className="flex items-center gap-1.5 mb-1 text-[10px] font-bold text-red-400">
                <AlertTriangle className="w-3.5 h-3.5" />
                충돌 파일 ({gitStatus.conflicts.length})
              </div>
              {gitStatus.conflicts.map(f => (
                <div key={f} className="text-[9px] font-mono text-red-300 pl-4 py-0.5 truncate">
                  {f}
                </div>
              ))}
            </div>
          )}

          {/* ── 스테이징된 파일 목록 (초록 테두리) ──────────────────────── */}
          {gitStatus.staged.length > 0 && (
            <div className="p-2 rounded border border-green-500/20 bg-green-500/3">
              <div className="text-[9px] font-bold text-green-400 mb-1">
                스테이징됨 ({gitStatus.staged.length})
              </div>
              {gitStatus.staged.slice(0, 8).map(f => (
                <div key={f} className="text-[9px] font-mono text-green-300/70 pl-2 py-0.5 truncate">
                  +{f}
                </div>
              ))}
              {gitStatus.staged.length > 8 && (
                <div className="text-[8px] text-green-400/50 pl-2">
                  ... +{gitStatus.staged.length - 8}개 더
                </div>
              )}
            </div>
          )}

          {/* ── 수정됨 (unstaged) 목록 (노란 테두리) ─────────────────────── */}
          {gitStatus.unstaged.length > 0 && (
            <div className="p-2 rounded border border-yellow-500/20 bg-yellow-500/3">
              <div className="text-[9px] font-bold text-yellow-400 mb-1">
                수정됨 (unstaged) ({gitStatus.unstaged.length})
              </div>
              {gitStatus.unstaged.slice(0, 8).map(f => (
                <div key={f} className="text-[9px] font-mono text-yellow-300/70 pl-2 py-0.5 truncate">
                  ~{f}
                </div>
              ))}
              {gitStatus.unstaged.length > 8 && (
                <div className="text-[8px] text-yellow-400/50 pl-2">
                  ... +{gitStatus.unstaged.length - 8}개 더
                </div>
              )}
            </div>
          )}

          {/* ── 미추적 파일 목록 (회색 테두리) ──────────────────────────── */}
          {gitStatus.untracked.length > 0 && (
            <div className="p-2 rounded border border-white/10">
              <div className="text-[9px] font-bold text-[#858585] mb-1">
                미추적 ({gitStatus.untracked.length})
              </div>
              {gitStatus.untracked.slice(0, 5).map(f => (
                <div key={f} className="text-[9px] font-mono text-[#858585] pl-2 py-0.5 truncate">
                  ?{f}
                </div>
              ))}
              {gitStatus.untracked.length > 5 && (
                <div className="text-[8px] text-[#858585]/50 pl-2">
                  ... +{gitStatus.untracked.length - 5}개 더
                </div>
              )}
            </div>
          )}

          {/* ── 최근 커밋 로그 (최대 8개) ────────────────────────────────── */}
          {gitLog.length > 0 && (
            <div className="p-2 rounded border border-white/10">
              <div className="flex items-center gap-1.5 mb-1.5 text-[9px] font-bold text-[#969696]">
                <GitCommitIcon className="w-3 h-3" /> 최근 커밋
              </div>
              {gitLog.slice(0, 8).map(commit => (
                <div
                  key={commit.hash}
                  className="flex items-start gap-1.5 py-0.5 hover:bg-white/3 rounded px-1 transition-colors"
                >
                  {/* 짧은 해시 */}
                  <span className="font-mono text-[8px] text-primary shrink-0 mt-0.5">
                    {commit.hash}
                  </span>
                  {/* 커밋 메시지 (한 줄 잘림) */}
                  <span className="text-[9px] text-[#cccccc] flex-1 truncate leading-tight">
                    {commit.message}
                  </span>
                  {/* 상대적 날짜 (" ago" 접미사 제거) */}
                  <span className="text-[8px] text-[#858585] shrink-0 font-mono">
                    {commit.date.replace(' ago', '')}
                  </span>
                </div>
              ))}
            </div>
          )}

        </div>
      )}
    </div>
  );
}
