/**
 * FILE: SetupBanner.tsx
 * DESCRIPTION: Setup Doctor 진단 결과를 상단 배너로 표시.
 *              자동 수리된 항목은 잠시 표시 후 사라지고,
 *              사용자 조치가 필요한 항목만 지속적으로 배너에 남는다.
 *              "닫기" 시 localStorage에 기록하여 재표시 방지.
 *
 * REVISION HISTORY:
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
  telegram: '텔레그램 봇',
};

/* 진단 항목별 조치 설명 */
const ACTION_LABELS: Record<string, string> = {
  open_telegram_panel: '텔레그램 설정으로 이동',
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
}

interface SetupBannerProps {
  onNavigate?: (tab: string) => void;
}

export default function SetupBanner({ onNavigate }: SetupBannerProps) {
  const [status, setStatus] = useState<SetupStatus | null>(null);
  const [dismissed, setDismissed] = useState(false);
  const [showFixed, setShowFixed] = useState(true);
  const [installingAction, setInstallingAction] = useState<string | null>(null);

  /* localStorage 키 — 사용자가 닫으면 다시 안 보임 */
  const DISMISS_KEY = 'setup_banner_dismissed';

  useEffect(() => {
    /* 이전에 닫았으면 표시 안 함 */
    const saved = localStorage.getItem(DISMISS_KEY);
    if (saved === 'true') {
      setDismissed(true);
    }

    /* 서버에서 진단 결과 가져오기 */
    fetch(`${API_BASE}/api/setup/status`)
      .then(r => r.json())
      .then((data: SetupStatus) => {
        setStatus(data);
        if (data.checks?.cli_agents?.status === 'missing') {
          fetch(`${API_BASE}/api/setup/auto-install`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: '{}',
          }).catch(() => { /* 설치 실패는 다음 실행의 진단 배너에서 다시 안내 */ });
        }
        /* 자동 수리 항목은 5초 후 숨김 */
        if ((data.auto_fixed?.length ?? 0) > 0 && (data.needs_action?.length ?? 0) === 0) {
          setTimeout(() => setShowFixed(false), 5000);
        }
      })
      .catch(() => { /* 서버 미실행 시 무시 */ });
  }, []);

  /* 렌더링 조건 */
  if (dismissed || !status) return null;
  if (status.ready && !showFixed) return null;
  if (status.ready && (status.auto_fixed?.length ?? 0) === 0) return null;

  const handleDismiss = () => {
    setDismissed(true);
    if ((status.needs_action?.length ?? 0) === 0) {
      localStorage.setItem(DISMISS_KEY, 'true');
    }
  };

  const handleAction = async (action: string) => {
    if (action === 'open_telegram_panel' && onNavigate) {
      onNavigate('telegram');
      return;
    }

    if (action === 'install_claude' || action === 'install_cli') {
      setInstallingAction(action);
      try {
        const response = await fetch(`${API_BASE}/api/setup/auto-install`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: '{}',
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
  const hasIssues = (status.needs_action?.length ?? 0) > 0;
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

        {/* 조치 필요 항목 */}
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
