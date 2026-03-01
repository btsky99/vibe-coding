/**
 * FILE: McpPanel.tsx
 * DESCRIPTION: MCP(Model Context Protocol) 관리자 패널.
 *              Claude Code / Gemini CLI 에 MCP 서버를 설치·제거하는 UI를 제공한다.
 *              내장 카탈로그(8개)와 Smithery 검색을 지원한다.
 *
 * REVISION HISTORY:
 * - 2026-03-01 Claude: App.tsx에서 분리 — 독립 컴포넌트화, 상태 내부 관리
 */

import { useState, useEffect } from 'react';
import { Package, CheckCircle2, Circle, Search } from 'lucide-react';
import { McpEntry, SmitheryServer } from '../../types';

// 현재 접속 포트 기반으로 API 주소 자동 결정
const API_BASE = `http://${window.location.hostname}:${window.location.port}`;

// Props 없음 — 완전 독립 패널 컴포넌트
export default function McpPanel() {
  // ── 카탈로그 / 설치 현황 상태 ──────────────────────────────────
  const [mcpCatalog, setMcpCatalog] = useState<McpEntry[]>([]);
  const [mcpInstalled, setMcpInstalled] = useState<string[]>([]);
  const [mcpTool, setMcpTool] = useState<'claude' | 'gemini'>('claude');
  const [mcpScope, setMcpScope] = useState<'global' | 'project'>('global');
  const [mcpLoading, setMcpLoading] = useState<Record<string, boolean>>({});
  const [mcpMsg, setMcpMsg] = useState('');

  // ── Smithery 검색 상태 ─────────────────────────────────────────
  const [mcpSubTab, setMcpSubTab] = useState<'catalog' | 'smithery'>('catalog');
  const [smitheryQuery, setSmitheryQuery] = useState('');
  const [smitheryResults, setSmitheryResults] = useState<SmitheryServer[]>([]);
  const [smitheryPage, setSmitheryPage] = useState(1);
  const [smitheryLoading, setSmitheryLoading] = useState(false);
  const [smitheryApiKey, setSmitheryApiKey] = useState('');
  const [smitheryApiKeyInput, setSmitheryApiKeyInput] = useState('');
  const [smitheryApiKeySaved, setSmitheryApiKeySaved] = useState(false);

  // 카탈로그는 최초 1회만 로드
  useEffect(() => {
    fetch(`${API_BASE}/api/mcp/catalog`)
      .then(res => res.json())
      .then((data: McpEntry[]) => setMcpCatalog(Array.isArray(data) ? data : []))
      .catch(() => {});
  }, []);

  // Smithery API 키 로드
  useEffect(() => {
    fetch(`${API_BASE}/api/mcp/apikey`)
      .then(res => res.json())
      .then(data => {
        if (data.apikey) {
          setSmitheryApiKey(data.apikey);
          setSmitheryApiKeyInput(data.apikey);
        }
      })
      .catch(() => {});
  }, []);

  // 설치 현황 폴링 (5초 간격 — 도구·범위 변경 시 즉시 재조회)
  const fetchMcpInstalled = () => {
    fetch(`${API_BASE}/api/mcp/installed?tool=${mcpTool}&scope=${mcpScope}`)
      .then(res => res.json())
      .then(data => setMcpInstalled(data.installed ?? []))
      .catch(() => {});
  };

  useEffect(() => {
    fetchMcpInstalled();
    const interval = setInterval(fetchMcpInstalled, 5000);
    return () => clearInterval(interval);
  }, [mcpTool, mcpScope]);

  // MCP 설치 핸들러
  const installMcp = (entry: McpEntry) => {
    setMcpLoading(prev => ({ ...prev, [entry.name]: true }));
    fetch(`${API_BASE}/api/mcp/install`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        tool: mcpTool, scope: mcpScope,
        name: entry.name, package: entry.package,
        requiresEnv: entry.requiresEnv ?? [],
      }),
    })
      .then(res => res.json())
      .then(data => { setMcpMsg(data.message ?? ''); fetchMcpInstalled(); })
      .catch(() => {})
      .finally(() => setMcpLoading(prev => ({ ...prev, [entry.name]: false })));
  };

  // MCP 제거 핸들러
  const uninstallMcp = (name: string) => {
    setMcpLoading(prev => ({ ...prev, [name]: true }));
    fetch(`${API_BASE}/api/mcp/uninstall`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ tool: mcpTool, scope: mcpScope, name }),
    })
      .then(res => res.json())
      .then(data => { setMcpMsg(data.message ?? ''); fetchMcpInstalled(); })
      .catch(() => {})
      .finally(() => setMcpLoading(prev => ({ ...prev, [name]: false })));
  };

  // Smithery API 키 저장
  const saveSmitheryApiKey = () => {
    fetch(`${API_BASE}/api/mcp/apikey`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ apikey: smitheryApiKeyInput }),
    })
      .then(res => res.json())
      .then(() => {
        setSmitheryApiKey(smitheryApiKeyInput);
        setSmitheryApiKeySaved(true);
        setTimeout(() => setSmitheryApiKeySaved(false), 2000);
      })
      .catch(() => {});
  };

  // Smithery 검색
  const searchSmithery = (page = 1) => {
    if (!smitheryQuery.trim()) return;
    setSmitheryLoading(true);
    const url = `${API_BASE}/api/mcp/search?q=${encodeURIComponent(smitheryQuery)}&page=${page}&pageSize=10`;
    fetch(url)
      .then(res => res.json())
      .then(data => {
        setSmitheryResults(Array.isArray(data.servers) ? data.servers : []);
        setSmitheryPage(page);
      })
      .catch(() => {})
      .finally(() => setSmitheryLoading(false));
  };

  // 카테고리별 배지 색상
  const catColor: Record<string, string> = {
    '문서': 'bg-blue-500/20 text-blue-300',
    '개발': 'bg-orange-500/20 text-orange-300',
    '검색': 'bg-yellow-500/20 text-yellow-300',
    'AI':   'bg-purple-500/20 text-purple-300',
    '브라우저': 'bg-green-500/20 text-green-300',
    'DB':   'bg-red-500/20 text-red-300',
  };

  return (
    <div className="flex-1 flex flex-col overflow-hidden gap-2">
      {/* 도구 탭 선택: Claude Code / Gemini CLI */}
      <div className="flex gap-1 shrink-0">
        {(['claude', 'gemini'] as const).map(t => (
          <button
            key={t}
            onClick={() => setMcpTool(t)}
            className={`flex-1 py-1 text-[10px] font-bold rounded transition-colors ${mcpTool === t ? 'bg-primary text-white' : 'bg-white/5 text-[#858585] hover:text-white'}`}
          >
            {t === 'claude' ? 'Claude Code' : 'Gemini CLI'}
          </button>
        ))}
      </div>

      {/* 범위 탭 선택: 전역 / 프로젝트 */}
      <div className="flex gap-1 shrink-0">
        {(['global', 'project'] as const).map(s => (
          <button
            key={s}
            onClick={() => setMcpScope(s)}
            className={`flex-1 py-1 text-[10px] font-bold rounded transition-colors ${mcpScope === s ? 'bg-accent/80 text-white' : 'bg-white/5 text-[#858585] hover:text-white'}`}
          >
            {s === 'global' ? '전역 (Global)' : '프로젝트'}
          </button>
        ))}
      </div>

      {/* 카탈로그 / Smithery 탭 전환 */}
      <div className="flex gap-1 shrink-0">
        <button
          onClick={() => setMcpSubTab('catalog')}
          className={`flex-1 py-1 text-[9px] font-bold rounded transition-colors ${mcpSubTab === 'catalog' ? 'bg-white/15 text-white' : 'bg-white/3 text-[#858585] hover:text-white'}`}
        >
          내장 카탈로그
        </button>
        <button
          onClick={() => setMcpSubTab('smithery')}
          className={`flex-1 py-1 text-[9px] font-bold rounded transition-colors ${mcpSubTab === 'smithery' ? 'bg-white/15 text-white' : 'bg-white/3 text-[#858585] hover:text-white'}`}
        >
          Smithery 검색
        </button>
      </div>

      {/* 마지막 작업 결과 메시지 */}
      {mcpMsg && (
        <div className="text-[9px] text-green-400 bg-green-500/10 border border-green-500/20 rounded px-2 py-1 font-mono truncate shrink-0" title={mcpMsg}>
          {mcpMsg}
        </div>
      )}

      {mcpSubTab === 'catalog' ? (
        /* ── 내장 카탈로그 목록 ── */
        <div className="flex-1 overflow-y-auto custom-scrollbar space-y-1.5">
          {mcpCatalog.length === 0 ? (
            <div className="text-center text-[#858585] text-xs py-10 flex flex-col items-center gap-2 italic">
              <Package className="w-7 h-7 opacity-20" />
              카탈로그 로딩 중...
            </div>
          ) : (
            mcpCatalog.map(entry => {
              const isInstalled = mcpInstalled.includes(entry.name);
              const isLoading = mcpLoading[entry.name] ?? false;
              return (
                <div key={entry.name} className={`p-2 rounded border transition-colors ${isInstalled ? 'border-green-500/30 bg-green-500/5' : 'border-white/10 bg-white/2 hover:border-white/20'}`}>
                  {/* 이름 + 카테고리 배지 + 설치 상태 아이콘 */}
                  <div className="flex items-center gap-1.5 mb-0.5">
                    {isInstalled
                      ? <CheckCircle2 className="w-3.5 h-3.5 text-green-400 shrink-0" />
                      : <Circle className="w-3.5 h-3.5 text-[#555] shrink-0" />
                    }
                    <span className="text-[11px] font-bold text-white flex-1 truncate">{entry.name}</span>
                    <span className={`text-[8px] font-bold px-1 py-0.5 rounded ${catColor[entry.category] ?? 'bg-white/10 text-white/50'}`}>
                      {entry.category}
                    </span>
                  </div>
                  {/* 설명 */}
                  <p className="text-[9px] text-[#858585] pl-5 mb-1.5 leading-tight">{entry.description}</p>
                  {/* 필수 환경변수 안내 */}
                  {entry.requiresEnv && entry.requiresEnv.length > 0 && (
                    <p className="text-[8px] text-yellow-400/70 pl-5 mb-1.5 font-mono">
                      ENV: {entry.requiresEnv.join(', ')}
                    </p>
                  )}
                  {/* 설치 / 제거 버튼 */}
                  <div className="pl-5">
                    {isInstalled ? (
                      <button
                        onClick={() => uninstallMcp(entry.name)}
                        disabled={isLoading}
                        className="text-[9px] font-bold px-2 py-0.5 rounded bg-red-500/20 text-red-400 hover:bg-red-500/30 disabled:opacity-50 transition-colors"
                      >
                        {isLoading ? '처리 중...' : '제거'}
                      </button>
                    ) : (
                      <button
                        onClick={() => installMcp(entry)}
                        disabled={isLoading}
                        className="text-[9px] font-bold px-2 py-0.5 rounded bg-primary/20 text-primary hover:bg-primary/30 disabled:opacity-50 transition-colors"
                      >
                        {isLoading ? '처리 중...' : '설치'}
                      </button>
                    )}
                  </div>
                </div>
              );
            })
          )}
        </div>
      ) : (
        /* ── Smithery 레지스트리 검색 ── */
        <div className="flex-1 flex flex-col overflow-hidden gap-2">
          {/* API 키 입력 */}
          <div className="flex gap-1 shrink-0">
            <input
              type="password"
              value={smitheryApiKeyInput}
              onChange={e => setSmitheryApiKeyInput(e.target.value)}
              placeholder="Smithery API 키 입력..."
              className="flex-1 bg-[#1e1e1e] border border-white/10 rounded px-2 py-1 text-[10px] focus:outline-none focus:border-primary text-white"
            />
            <button
              onClick={saveSmitheryApiKey}
              className={`px-2 py-1 rounded text-[9px] font-bold transition-colors ${smitheryApiKeySaved ? 'bg-green-500/30 text-green-400' : 'bg-white/10 text-white hover:bg-white/20'}`}
            >
              {smitheryApiKeySaved ? '저장됨 ✓' : '저장'}
            </button>
          </div>

          {/* 검색창 */}
          <div className="flex gap-1 shrink-0">
            <input
              type="text"
              value={smitheryQuery}
              onChange={e => setSmitheryQuery(e.target.value)}
              onKeyDown={e => e.key === 'Enter' && searchSmithery(1)}
              placeholder="MCP 서버 검색..."
              className="flex-1 bg-[#1e1e1e] border border-white/10 rounded px-2 py-1 text-[10px] focus:outline-none focus:border-primary text-white"
            />
            <button
              onClick={() => searchSmithery(1)}
              disabled={smitheryLoading || !smitheryApiKey}
              className="px-2 py-1 rounded bg-primary/20 text-primary hover:bg-primary/30 disabled:opacity-40 transition-colors"
            >
              <Search className="w-3.5 h-3.5" />
            </button>
          </div>

          {/* 검색 결과 */}
          <div className="flex-1 overflow-y-auto custom-scrollbar space-y-1.5">
            {smitheryLoading ? (
              <div className="text-center text-[#858585] text-xs py-6 italic">검색 중...</div>
            ) : smitheryResults.length === 0 ? (
              <div className="text-center text-[#858585] text-xs py-6 italic">
                {smitheryApiKey ? '검색어를 입력하세요' : 'API 키를 먼저 저장하세요'}
              </div>
            ) : (
              smitheryResults.map(srv => (
                <div key={srv.qualifiedName} className="p-2 rounded border border-white/10 bg-white/2 hover:border-white/20 transition-colors">
                  <div className="flex items-center gap-1.5 mb-0.5">
                    <span className="text-[11px] font-bold text-white flex-1 truncate">{srv.displayName}</span>
                    {srv.verified && (
                      <span className="text-[8px] font-bold px-1 py-0.5 rounded bg-blue-500/20 text-blue-300">검증됨</span>
                    )}
                  </div>
                  <p className="text-[9px] text-[#858585] mb-1 leading-tight">{srv.description}</p>
                  <div className="flex items-center justify-between">
                    <span className="text-[8px] text-[#555] font-mono">{srv.qualifiedName}</span>
                    <span className="text-[8px] text-[#555]">사용 {srv.useCount.toLocaleString()}회</span>
                  </div>
                </div>
              ))
            )}
          </div>

          {/* 페이지네이션 */}
          {smitheryResults.length > 0 && (
            <div className="flex gap-1 justify-center shrink-0">
              <button
                onClick={() => searchSmithery(smitheryPage - 1)}
                disabled={smitheryPage <= 1}
                className="px-2 py-0.5 text-[9px] rounded bg-white/5 hover:bg-white/10 disabled:opacity-30 transition-colors"
              >
                이전
              </button>
              <span className="text-[9px] text-[#858585] self-center">{smitheryPage}페이지</span>
              <button
                onClick={() => searchSmithery(smitheryPage + 1)}
                disabled={smitheryResults.length < 10}
                className="px-2 py-0.5 text-[9px] rounded bg-white/5 hover:bg-white/10 disabled:opacity-30 transition-colors"
              >
                다음
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
