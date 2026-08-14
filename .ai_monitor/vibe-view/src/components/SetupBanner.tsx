/**
 * FILE: SetupBanner.tsx
 * DESCRIPTION: Setup Doctor 진단 결과를 상단 배너로 표시.
 *              자동 수리된 항목은 잠시 표시 후 사라지고,
 *              사용자 조치가 필요한 항목만 지속적으로 배너에 남는다.
 *              보여줄 게 하나도 없으면 배너 자체를 렌더링하지 않는다.
 *
 * REVISION HISTORY:
 * - 2026-08-14 Claude: "기본 설치팩"이 전부 설치된 뒤에도 계속 떠 있던 문제 —
 *                      미설치 도구가 있을 때만 표시하고, 표시할 게 없으면 배너를 안 그린다.
 *                      자동 설치 폴링에 상한(5분)을 둬 영원히 도는 것도 차단.
 * - 2026-07-29 Codex: Explain that installed AI CLIs require a first launch and login.
 * - 2026-07-29 Codex: Show and poll per-tool first-run installation progress.
 * - 2026-07-29 Codex: Stop treating missing project hooks as a missing Claude installation.
 * - 2026-07-29 Codex: Route every missing AI action through the full prerequisite-first installer.
 * - 2026-07-29 Codex: Make Claude and all-AI-CLI actions start installers instead of doing nothing.
 * - 2026-07-28 Codex: Start missing core dependency installation automatically on first run.
 * - 2026-07-28 Codex: Connect missing AI CLI action to the one-click install controls.
 * - 2026-03-27 Claude: 최초 작성. setup_doctor.py 연동 배너.
 */

import { useState, useEffect } from 'react';
import { AlertTriangle, CheckCircle, Wrench, X, Settings } from 'lucide-react';
import { API_BASE } from '../constants';

/* 진단 항목별 한글 라벨 */
const CHECK_LABELS: Record<string, string> = {
  pg_locale: 'PostgreSQL 로케일',
  pg_database: '프로젝트 DB',
  hooks: 'Claude Code 훅',
  cli_agents: 'CLI 에이전트',
};

/* 진단 항목별 조치 설명 */
const ACTION_LABELS: Record<string, string> = {
  install_claude: 'Claude Code를 설치하세요',
  install_cli: 'AI CLI 설치',
};

interface CheckResult {
  status: 'ok' | 'fixed' | 'missing' | 'error';
  message: string;
  auto_fixed?: boolean;
  action?: string;
}

interface SetupStatus {
  ready: boolean;
  checks: Record<string, CheckResult>;
  auto_fixed: string[];
  needs_action: string[];
  toolchain?: ToolchainItem[];
}

interface ToolchainItem {
  id: 'nodejs' | 'claude' | 'codex' | 'antigravity';
  name: string;
  installed: boolean;
  version?: string | null;
}

interface SetupBannerProps {
  onNavigate?: (tab: string) => void;
}

export default function SetupBanner({ onNavigate }: SetupBannerProps) {
  const [status, setStatus] = useState<SetupStatus | null>(null);
  const [dismissed, setDismissed] = useState(false);
  const [showFixed, setShowFixed] = useState(true);
  const [installingAction, setInstallingAction] = useState<string | null>(null);
  const [toolchainInstalling, setToolchainInstalling] = useState(false);

  useEffect(() => {
    /* 서버에서 진단 결과 가져오기 */
    fetch(`${API_BASE}/api/setup/status`)
      .then(r => r.json())
      .then((data: SetupStatus) => {
        setStatus(data);
        /* [WHY toolchain 기준] cli_agents 진단은 nodejs를 안 보고, 반대로 toolchain은
           네 도구의 실제 설치 상태다. 실제로 빠진 게 있을 때만 자동 설치를 부른다.
           서버가 자동 경로를 무창 + 총 3회로 제한하므로 여기서 또 막지 않는다. */
        const missing = (data.toolchain ?? []).filter(tool => !tool.installed);
        if (missing.length > 0) {
          fetch(`${API_BASE}/api/setup/auto-install`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: '{}',
          })
            .then(r => r.json())
            /* 실제로 설치가 시작됐을 때만 폴링 — exhausted/idle에 켜면 영원히 돈다 */
            .then(res => { if (res?.status === 'started' || res?.status === 'running') setToolchainInstalling(true); })
            .catch(() => { /* 설치 실패는 다음 실행의 진단 배너에서 다시 안내 */ });
        }
        /* 자동 수리 항목은 5초 후 숨김 */
        if ((data.auto_fixed?.length ?? 0) > 0 && (data.needs_action?.length ?? 0) === 0) {
          setTimeout(() => setShowFixed(false), 5000);
        }
      })
      .catch(() => { /* 서버 미실행 시 무시 */ });
  }, []);

  useEffect(() => {
    if (!toolchainInstalling) return;
    /* [상한] 설치가 끝내 완료되지 않아도 폴링은 5분에서 멈춘다. 무한 폴링은 앱이 켜져
       있는 내내 3초마다 setup_doctor 전체 진단(PATH 재병합 + which 호출)을 돌린다. */
    let ticks = 0;
    const poll = window.setInterval(() => {
      if (++ticks > 100) {
        setToolchainInstalling(false);
        setInstallingAction(null);
        return;
      }
      fetch(`${API_BASE}/api/setup/status`)
        .then(r => r.json())
        .then((data: SetupStatus) => {
          setStatus(data);
          if (data.toolchain?.length && data.toolchain.every(tool => tool.installed)) {
            setToolchainInstalling(false);
            setInstallingAction(null);
          }
        })
        .catch(() => undefined);
    }, 3000);
    return () => window.clearInterval(poll);
  }, [toolchainInstalling]);

  /* 렌더링 조건 */
  if (dismissed || !status) return null;

  /* [WHY] 예전엔 toolchain 배열이 오기만 하면 "기본 설치팩" 줄을 그렸다. 서버는 네 도구를
     설치 여부와 무관하게 **항상** 내려주므로, 설치가 다 끝난 PC에서도 배너가 영구히 남았다.
     남길 이유가 있는 건 '아직 안 깔린 도구'뿐이다. */
  const pendingTools = (status.toolchain ?? []).filter(tool => !tool.installed);
  const hasFixedToShow = showFixed && (status.auto_fixed?.length ?? 0) > 0;
  if (!hasFixedToShow && pendingTools.length === 0 && (status.needs_action?.length ?? 0) === 0) {
    return null;
  }

  const handleDismiss = () => {
    setDismissed(true);
  };

  const handleAction = async (action: string) => {
    if (action === 'install_claude' || action === 'install_cli') {
      setInstallingAction(action);
      setToolchainInstalling(true);
      try {
        /* [manual] 사람이 누른 설치 — 서버는 이때만 콘솔 창을 열고, 자동 3회 상한도 안 건다. */
        const response = await fetch(`${API_BASE}/api/setup/auto-install`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ manual: true }),
        });
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const result = await response.json();
        if (result.status === 'error') throw new Error(result.message || 'install failed');
      } catch {
        if (onNavigate) onNavigate('tools');
      } finally {
        window.setTimeout(() => setInstallingAction(null), 1500);
      }
    }
  };

  /* 배너 색상 결정 */
  const hasIssues = (status.needs_action?.length ?? 0) > 0 || pendingTools.length > 0;
  const bgColor = hasIssues
    ? 'bg-amber-900/80 border-amber-600/50'
    : 'bg-emerald-900/60 border-emerald-600/40';

  return (
    <div className={`${bgColor} border-b px-4 py-2 flex items-center gap-3 text-sm`}>
      {/* 아이콘 */}
      {hasIssues ? (
        <AlertTriangle className="w-4 h-4 text-amber-400 flex-shrink-0" />
      ) : (
        <CheckCircle className="w-4 h-4 text-emerald-400 flex-shrink-0" />
      )}

      {/* 메시지 */}
      <div className="flex-1 flex items-center gap-2 flex-wrap">
        {/* 자동 수리 완료 항목 */}
        {showFixed && status.auto_fixed.map(key => (
          <span key={key} className="inline-flex items-center gap-1 text-emerald-300">
            <Wrench className="w-3 h-3" />
            {CHECK_LABELS[key] || key} 자동 수리됨
          </span>
        ))}

        {/* 기본 설치팩 — 아직 안 깔린 도구만. 전부 설치되면 이 줄은 사라진다. */}
        {pendingTools.length > 0 && (
          <span className="inline-flex items-center gap-2 flex-wrap">
            <strong className="text-gray-100">기본 설치팩</strong>
            {pendingTools.map(tool => (
              <span
                key={tool.id}
                title={tool.version || undefined}
                className="inline-flex items-center gap-1 rounded px-2 py-0.5 text-xs bg-amber-950/70 text-amber-200"
              >
                <Wrench className="w-3 h-3 animate-pulse" />
                {tool.name}: {toolchainInstalling ? '확인·설치 중' : '설치 필요'}
              </span>
            ))}
          </span>
        )}

        {status.needs_action.map(key => {
          const check = status.checks[key];
          return (
            <span key={key} className="inline-flex items-center gap-2 text-amber-200">
              <span>{CHECK_LABELS[key] || key}: {check.message}</span>
              {check.action && (
                <button
                  onClick={() => handleAction(check.action!)}
                  disabled={installingAction === check.action}
                  className="px-2 py-0.5 bg-amber-700/60 hover:bg-amber-600/60 rounded text-xs text-amber-100 flex items-center gap-1"
                >
                  <Settings className="w-3 h-3" />
                  {installingAction === check.action
                    ? '설치 시작 중...'
                    : (ACTION_LABELS[check.action] || '설정하기')}
                </button>
              )}
            </span>
          );
        })}
      </div>

      {/* 닫기 버튼 */}
      <button
        onClick={handleDismiss}
        className="text-gray-400 hover:text-white flex-shrink-0"
        title="닫기"
      >
        <X className="w-4 h-4" />
      </button>
    </div>
  );
}
