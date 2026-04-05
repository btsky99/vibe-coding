/*
 * FILE: panels/ToolsPanel.tsx
 * DESCRIPTION: AI 개발 도구 설치 관리 패널.
 *              TOOL_REGISTRY(tools_api.py)에 등록된 도구의 설치 상태를
 *              시각적으로 표시하고, 원클릭 설치를 지원한다.
 * REVISION HISTORY:
 * - 2026-04-05 Claude Opus 4.6: 최초 생성 — 도구 목록 + 설치 상태 + 카테고리 필터
 */

import { useState, useEffect, useCallback } from 'react';
import {
  Package, CheckCircle, XCircle, Download, ExternalLink,
  RefreshCw, Filter,
} from 'lucide-react';
import { API_BASE } from '../../constants';

/* ── 타입 ──────────────────────────────────────────────────────────── */

interface ToolInfo {
  id: string;
  name: string;
  description: string;
  installed: boolean;
  version: string | null;
  install_url: string;
  install_hint: string;
  category: string;
  can_auto_install: boolean;
}

interface ToolsSummary {
  installed: number;
  total: number;
  all_ready: boolean;
}

/* ── 카테고리 라벨 매핑 ─────────────────────────────────────────────── */

const CATEGORY_LABELS: Record<string, string> = {
  'all': '전체',
  'ai-agent': 'AI 에이전트',
  'runtime': '런타임',
  'vcs': '버전 관리',
  'database': '데이터베이스',
  'testing': '테스트',
  'code-quality': '코드 품질',
  'build': '빌드',
  'frontend': '프론트엔드',
  'package-manager': '패키지 관리',
  'image': '이미지',
  'git': 'Git',
};

/* ── 컴포넌트 ──────────────────────────────────────────────────────── */

const ToolsPanel = () => {
  const [tools, setTools] = useState<ToolInfo[]>([]);
  const [summary, setSummary] = useState<ToolsSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [installing, setInstalling] = useState<string | null>(null);
  const [selectedCategory, setSelectedCategory] = useState('all');

  /* ── 데이터 조회 ── */
  const fetchTools = useCallback(() => {
    setLoading(true);
    fetch(`${API_BASE}/api/tools/status`)
      .then(res => res.json())
      .then(data => {
        setTools(data.tools || []);
        setSummary(data.summary || null);
      })
      .catch(err => console.error('[ToolsPanel] fetch error:', err))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    fetchTools();
  }, [fetchTools]);

  /* ── 도구 설치 ── */
  const handleInstall = (toolId: string) => {
    setInstalling(toolId);
    fetch(`${API_BASE}/api/tools/install`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ tool: toolId }),
    })
      .then(res => res.json())
      .then(data => {
        if (data.status === 'manual') {
          // 수동 설치 안내
          const msg = `${data.message}\n\n${data.install_hint || ''}`;
          if (data.install_url) {
            const doOpen = confirm(`${msg}\n\n[확인]을 누르면 다운로드 페이지를 엽니다.`);
            if (doOpen) window.open(data.install_url, '_blank');
          } else {
            alert(msg);
          }
        } else if (data.status === 'success') {
          // 설치 콘솔 창이 열림 — 10초 후 자동 새로고침
          setTimeout(fetchTools, 10000);
        } else if (data.status === 'error') {
          alert(`설치 실패: ${data.message}`);
        }
      })
      .catch(err => alert(`설치 요청 실패: ${err}`))
      .finally(() => setInstalling(null));
  };

  /* ── 카테고리 추출 ── */
  const categories = ['all', ...Array.from(new Set(tools.map(t => t.category).filter(Boolean)))];

  /* ── 필터링 ── */
  const filtered = selectedCategory === 'all'
    ? tools
    : tools.filter(t => t.category === selectedCategory);

  const installedCount = filtered.filter(t => t.installed).length;

  /* ── 렌더링 ── */
  return (
    <div className="flex-1 flex flex-col overflow-hidden text-[13px]">
      {/* 헤더 */}
      <div className="flex items-center justify-between px-3 py-2 border-b border-white/5 shrink-0">
        <div className="flex items-center gap-2">
          <Package className="w-4 h-4 text-primary" />
          <span className="font-semibold text-[#cccccc] uppercase text-[11px] tracking-wide">
            개발 도구
          </span>
          {summary && (
            <span className={`text-[10px] px-1.5 py-0.5 rounded-full ${
              summary.all_ready
                ? 'bg-green-500/20 text-green-400'
                : 'bg-yellow-500/20 text-yellow-400'
            }`}>
              {summary.installed}/{summary.total}
            </span>
          )}
        </div>
        <button
          onClick={fetchTools}
          disabled={loading}
          className="p-1 text-[#969696] hover:text-white transition-colors disabled:opacity-50"
          title="새로고침"
        >
          <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} />
        </button>
      </div>

      {/* 카테고리 필터 */}
      <div className="flex items-center gap-1 px-3 py-1.5 border-b border-white/5 shrink-0 overflow-x-auto no-scrollbar">
        <Filter className="w-3 h-3 text-[#969696] shrink-0" />
        {categories.map(cat => (
          <button
            key={cat}
            onClick={() => setSelectedCategory(cat)}
            className={`px-2 py-0.5 rounded text-[10px] whitespace-nowrap transition-colors ${
              selectedCategory === cat
                ? 'bg-primary/20 text-primary border border-primary/30'
                : 'text-[#969696] hover:text-white hover:bg-white/5'
            }`}
          >
            {CATEGORY_LABELS[cat] || cat}
          </button>
        ))}
      </div>

      {/* 필터 결과 카운트 */}
      <div className="px-3 py-1 text-[10px] text-[#969696] border-b border-white/5 shrink-0">
        {installedCount}/{filtered.length}개 설치됨
      </div>

      {/* 도구 목록 */}
      <div className="flex-1 overflow-y-auto">
        {loading && tools.length === 0 ? (
          <div className="flex items-center justify-center h-32 text-[#969696]">
            <RefreshCw className="w-4 h-4 animate-spin mr-2" />
            도구 상태 확인 중...
          </div>
        ) : filtered.length === 0 ? (
          <div className="flex items-center justify-center h-32 text-[#969696]">
            등록된 도구가 없습니다
          </div>
        ) : (
          <div className="divide-y divide-white/5">
            {filtered.map(tool => (
              <div
                key={tool.id}
                className="px-3 py-2 hover:bg-white/[0.03] transition-colors group"
              >
                <div className="flex items-start justify-between gap-2">
                  {/* 좌측: 상태 아이콘 + 이름 */}
                  <div className="flex items-start gap-2 min-w-0 flex-1">
                    {tool.installed ? (
                      <CheckCircle className="w-4 h-4 text-green-500 shrink-0 mt-0.5" />
                    ) : (
                      <XCircle className="w-4 h-4 text-red-400 shrink-0 mt-0.5" />
                    )}
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-1.5">
                        <span className="font-medium text-[#cccccc] truncate">
                          {tool.name}
                        </span>
                        {tool.version && (
                          <span className="text-[10px] text-[#969696] shrink-0">
                            {tool.version.length > 30
                              ? tool.version.slice(0, 30) + '…'
                              : tool.version}
                          </span>
                        )}
                      </div>
                      <p className="text-[11px] text-[#969696] mt-0.5 leading-snug">
                        {tool.description}
                      </p>
                      {!tool.installed && tool.install_hint && (
                        <code className="block text-[10px] text-yellow-400/70 bg-yellow-400/5 px-1.5 py-0.5 rounded mt-1 font-mono">
                          {tool.install_hint}
                        </code>
                      )}
                    </div>
                  </div>

                  {/* 우측: 액션 버튼 */}
                  <div className="flex items-center gap-1 shrink-0 opacity-0 group-hover:opacity-100 transition-opacity">
                    {!tool.installed && tool.can_auto_install && (
                      <button
                        onClick={() => handleInstall(tool.id)}
                        disabled={installing === tool.id}
                        className="flex items-center gap-1 px-2 py-1 rounded text-[10px] bg-primary/20 text-primary hover:bg-primary/30 disabled:opacity-50 transition-colors"
                        title="자동 설치"
                      >
                        <Download className={`w-3 h-3 ${installing === tool.id ? 'animate-bounce' : ''}`} />
                        설치
                      </button>
                    )}
                    {!tool.installed && !tool.can_auto_install && tool.install_url && (
                      <a
                        href={tool.install_url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="flex items-center gap-1 px-2 py-1 rounded text-[10px] bg-white/5 text-[#969696] hover:text-white hover:bg-white/10 transition-colors"
                        title="다운로드 페이지"
                      >
                        <ExternalLink className="w-3 h-3" />
                        수동
                      </a>
                    )}
                    {tool.installed && tool.install_url && (
                      <a
                        href={tool.install_url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="p-1 text-[#969696] hover:text-white transition-colors"
                        title="공식 문서"
                      >
                        <ExternalLink className="w-3 h-3" />
                      </a>
                    )}
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
};

export default ToolsPanel;
