/**
 * FILE: components/panels/CodeSearchPanel.tsx
 * DESCRIPTION: 코드 인텔리전스 BM25 검색 패널.
 *   PostgreSQL FTS 기반으로 함수/클래스/코드를 검색하고 결과를 표시.
 * REVISION HISTORY:
 *   2026-04-14 — 초기 구현. MindVault 영감 기반 코드 검색 UI
 */
import { useState, useEffect, useCallback, useRef } from 'react';

interface SearchResult {
  id: number;
  file_path: string;
  name: string;
  node_type: string;
  signature: string;
  snippet: string;
  score: number;
  project_id: number;
  line_start: number;
  line_end: number;
}

interface CodeProject {
  id: number;
  name: string;
  node_count: number;
}

const NODE_TYPE_ICONS: Record<string, string> = {
  function: 'fn',
  class: 'Cl',
  import: '->',
};

const NODE_TYPE_COLORS: Record<string, string> = {
  function: 'text-blue-400',
  class: 'text-green-400',
  import: 'text-purple-400',
};

const API = '';

export default function CodeSearchPanel() {
  const [query, setQuery] = useState('');
  const [results, setResults] = useState<SearchResult[]>([]);
  const [projects, setProjects] = useState<CodeProject[]>([]);
  const [selectedProject, setSelectedProject] = useState<string>('');
  const [nodeTypeFilter, setNodeTypeFilter] = useState<string>('');
  const [loading, setLoading] = useState(false);
  const [selectedResult, setSelectedResult] = useState<SearchResult | null>(null);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // 프로젝트 목록 로드
  useEffect(() => {
    fetch(`${API}/api/codegraph/projects`)
      .then(r => r.json())
      .then(setProjects)
      .catch(() => {});
  }, []);

  // 검색 실행 (debounce 300ms)
  const doSearch = useCallback((q: string) => {
    if (!q.trim()) {
      setResults([]);
      return;
    }
    setLoading(true);
    const params = new URLSearchParams({ q: q.trim(), limit: '50' });
    if (selectedProject) params.set('project_id', selectedProject);
    if (nodeTypeFilter) params.set('node_type', nodeTypeFilter);

    fetch(`${API}/api/codegraph/search?${params}`)
      .then(r => r.json())
      .then(data => {
        setResults(Array.isArray(data) ? data : []);
        setLoading(false);
      })
      .catch(() => setLoading(false));
  }, [selectedProject, nodeTypeFilter]);

  // 입력 핸들러 (debounce)
  const handleInput = useCallback((value: string) => {
    setQuery(value);
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => doSearch(value), 300);
  }, [doSearch]);

  // 필터 변경 시 재검색
  useEffect(() => {
    if (query.trim()) doSearch(query);
  }, [selectedProject, nodeTypeFilter]);

  return (
    <div className="h-full flex flex-col gap-2 text-sm">
      {/* 검색 바 */}
      <div className="flex items-center gap-2">
        <div className="relative flex-1">
          <input
            className="w-full bg-zinc-800 border border-zinc-700 rounded px-3 py-1.5 text-xs
                       placeholder-zinc-500 focus:border-blue-500 focus:outline-none"
            placeholder="함수명, 클래스명, 코드 검색..."
            value={query}
            onChange={e => handleInput(e.target.value)}
            autoFocus
          />
          {loading && (
            <span className="absolute right-2 top-1/2 -translate-y-1/2 text-zinc-500 text-xs animate-pulse">
              ...
            </span>
          )}
        </div>

        <select
          className="bg-zinc-800 border border-zinc-700 rounded px-2 py-1.5 text-xs"
          value={selectedProject}
          onChange={e => setSelectedProject(e.target.value)}
        >
          <option value="">All Projects</option>
          {projects.map(p => (
            <option key={p.id} value={p.id}>{p.name}</option>
          ))}
        </select>

        <select
          className="bg-zinc-800 border border-zinc-700 rounded px-2 py-1.5 text-xs"
          value={nodeTypeFilter}
          onChange={e => setNodeTypeFilter(e.target.value)}
        >
          <option value="">All Types</option>
          <option value="function">Functions</option>
          <option value="class">Classes</option>
          <option value="import">Imports</option>
        </select>
      </div>

      {/* 결과 수 */}
      {results.length > 0 && (
        <div className="text-xs text-zinc-500">
          {results.length} results found
        </div>
      )}

      {/* 결과 + 상세 */}
      <div className="flex-1 flex gap-2 min-h-0">
        {/* 결과 리스트 */}
        <div className="flex-1 overflow-y-auto space-y-1">
          {results.length === 0 && query.trim() && !loading && (
            <div className="text-zinc-500 text-xs text-center py-8">
              검색 결과 없음
            </div>
          )}

          {results.map(r => (
            <button
              key={r.id}
              className={`w-full text-left p-2 rounded border text-xs transition-colors
                ${selectedResult?.id === r.id
                  ? 'bg-zinc-800 border-blue-500'
                  : 'bg-zinc-900 border-zinc-800 hover:border-zinc-700'}`}
              onClick={() => setSelectedResult(r)}
            >
              <div className="flex items-center gap-2">
                <span className={`font-mono font-bold ${NODE_TYPE_COLORS[r.node_type] || 'text-zinc-400'}`}>
                  {NODE_TYPE_ICONS[r.node_type] || '??'}
                </span>
                <span className="font-semibold text-white truncate">{r.name}</span>
                <span className="ml-auto text-zinc-600 text-[10px]">
                  {typeof r.score === 'number' ? r.score.toFixed(2) : r.score}
                </span>
              </div>
              <div className="text-zinc-500 truncate mt-0.5">
                {r.file_path}:{r.line_start}
              </div>
            </button>
          ))}
        </div>

        {/* 상세 패널 */}
        {selectedResult && (
          <div className="w-80 bg-zinc-900 rounded border border-zinc-800 p-3 overflow-y-auto">
            <div className="flex items-center gap-2 mb-2">
              <span className={`font-mono font-bold text-lg ${NODE_TYPE_COLORS[selectedResult.node_type]}`}>
                {NODE_TYPE_ICONS[selectedResult.node_type]}
              </span>
              <h3 className="font-bold text-white">{selectedResult.name}</h3>
            </div>

            <div className="text-xs space-y-2">
              <div>
                <span className="text-zinc-500">File: </span>
                <span className="text-zinc-300">{selectedResult.file_path}</span>
              </div>
              <div>
                <span className="text-zinc-500">Lines: </span>
                <span className="text-zinc-300">{selectedResult.line_start} - {selectedResult.line_end}</span>
              </div>
              <div>
                <span className="text-zinc-500">Type: </span>
                <span className={NODE_TYPE_COLORS[selectedResult.node_type]}>
                  {selectedResult.node_type}
                </span>
              </div>

              {selectedResult.signature && (
                <div>
                  <span className="text-zinc-500 block mb-1">Signature:</span>
                  <pre className="font-mono text-[10px] bg-zinc-800 p-2 rounded overflow-x-auto text-zinc-300">
                    {selectedResult.signature}
                  </pre>
                </div>
              )}

              {selectedResult.snippet && (
                <div>
                  <span className="text-zinc-500 block mb-1">Preview:</span>
                  <pre className="font-mono text-[10px] bg-zinc-800 p-2 rounded overflow-x-auto text-zinc-300 max-h-48">
                    {selectedResult.snippet}
                  </pre>
                </div>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
