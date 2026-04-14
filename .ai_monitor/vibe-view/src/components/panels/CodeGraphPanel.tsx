/**
 * FILE: components/panels/CodeGraphPanel.tsx
 * DESCRIPTION: 코드 인텔리전스 그래프 시각화 패널.
 *   react-force-graph-2d로 함수/클래스/모듈 간 의존관계를 인터랙티브 그래프로 표시.
 * REVISION HISTORY:
 *   2026-04-14 — 초기 구현. MindVault 영감 기반 코드 그래프 시각화
 */
import { useState, useEffect, useCallback, useRef } from 'react';
import ForceGraph2D from 'react-force-graph-2d';

// ── 타입 ──
interface CodeProject {
  id: number;
  name: string;
  root_path: string;
  language: string;
  file_count: number;
  node_count: number;
  last_indexed_at: string | null;
}

interface GraphNode {
  id: number;
  name: string;
  node_type: string;
  file_path: string;
  line_start: number;
  signature?: string;
}

interface GraphEdge {
  source: number;
  target: number;
  edge_type: string;
}

interface GraphData {
  nodes: GraphNode[];
  edges: GraphEdge[];
  stats: Record<string, number>;
}

// ── 색상 매핑 ──
const NODE_COLORS: Record<string, string> = {
  function: '#3b82f6',   // 파랑
  class: '#10b981',      // 초록
  module: '#f59e0b',     // 주황
  import: '#8b5cf6',     // 보라
  variable: '#6b7280',   // 회색
};

const API = '';

export default function CodeGraphPanel() {
  const [projects, setProjects] = useState<CodeProject[]>([]);
  const [selectedProject, setSelectedProject] = useState<number | null>(null);
  const [graphData, setGraphData] = useState<{ nodes: any[]; links: any[] }>({ nodes: [], links: [] });
  const [stats, setStats] = useState<Record<string, number>>({});
  const [selectedNode, setSelectedNode] = useState<GraphNode | null>(null);
  const [impactNodes, setImpactNodes] = useState<any[]>([]);
  const [indexing, setIndexing] = useState(false);
  const [registerPath, setRegisterPath] = useState('');
  const graphRef = useRef<any>(null);

  // 프로젝트 목록 로드
  useEffect(() => {
    fetch(`${API}/api/codegraph/projects`)
      .then(r => r.json())
      .then(setProjects)
      .catch(() => {});
  }, []);

  // 그래프 데이터 로드
  useEffect(() => {
    if (!selectedProject) return;
    fetch(`${API}/api/codegraph/graph?project_id=${selectedProject}`)
      .then(r => r.json())
      .then((data: GraphData) => {
        // react-force-graph 형식으로 변환
        const nodeSet = new Set(data.nodes.map(n => n.id));
        setGraphData({
          nodes: data.nodes.map(n => ({
            ...n,
            val: n.node_type === 'class' ? 3 : 1,
          })),
          links: data.edges
            .filter(e => nodeSet.has(e.source) && nodeSet.has(e.target))
            .map(e => ({
              source: e.source,
              target: e.target,
              type: e.edge_type,
            })),
        });
        setStats(data.stats);
      })
      .catch(() => {});
  }, [selectedProject]);

  // 프로젝트 등록
  const handleRegister = useCallback(() => {
    if (!registerPath.trim()) return;
    fetch(`${API}/api/codegraph/register`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ root_path: registerPath.trim() }),
    })
      .then(r => r.json())
      .then(res => {
        if (res.project_id) {
          setSelectedProject(res.project_id);
          setRegisterPath('');
          // 프로젝트 목록 갱신
          fetch(`${API}/api/codegraph/projects`).then(r => r.json()).then(setProjects);
        }
      })
      .catch(() => {});
  }, [registerPath]);

  // 인덱싱 실행
  const handleIndex = useCallback(() => {
    if (!selectedProject) return;
    setIndexing(true);
    fetch(`${API}/api/codegraph/index`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ project_id: selectedProject }),
    })
      .then(r => r.json())
      .then(() => {
        // 폴링으로 완료 확인
        const poll = setInterval(() => {
          fetch(`${API}/api/codegraph/status?project_id=${selectedProject}`)
            .then(r => r.json())
            .then(s => {
              if (s.status === 'done' || !s.status) {
                clearInterval(poll);
                setIndexing(false);
                // 그래프 데이터 다시 로드
                setSelectedProject(prev => prev); // trigger re-fetch
                fetch(`${API}/api/codegraph/projects`).then(r => r.json()).then(setProjects);
                fetch(`${API}/api/codegraph/graph?project_id=${selectedProject}`)
                  .then(r => r.json())
                  .then((data: GraphData) => {
                    const nodeSet = new Set(data.nodes.map(n => n.id));
                    setGraphData({
                      nodes: data.nodes.map(n => ({ ...n, val: n.node_type === 'class' ? 3 : 1 })),
                      links: data.edges
                        .filter(e => nodeSet.has(e.source) && nodeSet.has(e.target))
                        .map(e => ({ source: e.source, target: e.target, type: e.edge_type })),
                    });
                    setStats(data.stats);
                  });
              }
            });
        }, 2000);
      })
      .catch(() => setIndexing(false));
  }, [selectedProject]);

  // 노드 클릭 → 영향 분석
  const handleNodeClick = useCallback((node: any) => {
    setSelectedNode(node);
    fetch(`${API}/api/codegraph/impact?node_id=${node.id}`)
      .then(r => r.json())
      .then(data => setImpactNodes(data.affected || []))
      .catch(() => {});
  }, []);

  // 노드 렌더링 커스텀
  const paintNode = useCallback((node: any, ctx: CanvasRenderingContext2D) => {
    const color = NODE_COLORS[node.node_type] || '#6b7280';
    const size = node.node_type === 'class' ? 6 : 4;
    const isSelected = selectedNode?.id === node.id;
    const isImpacted = impactNodes.some((n: any) => n.id === node.id);

    ctx.beginPath();
    ctx.arc(node.x, node.y, size, 0, 2 * Math.PI);
    ctx.fillStyle = isSelected ? '#ef4444' : isImpacted ? '#f97316' : color;
    ctx.fill();

    if (isSelected || isImpacted) {
      ctx.strokeStyle = '#fff';
      ctx.lineWidth = 1.5;
      ctx.stroke();
    }

    // 이름 라벨
    ctx.fillStyle = '#d1d5db';
    ctx.font = `${isSelected ? 'bold ' : ''}3px sans-serif`;
    ctx.textAlign = 'center';
    ctx.fillText(node.name, node.x, node.y + size + 4);
  }, [selectedNode, impactNodes]);

  return (
    <div className="h-full flex flex-col gap-2 text-sm">
      {/* 상단 바 */}
      <div className="flex items-center gap-2 flex-wrap">
        <select
          className="bg-zinc-800 border border-zinc-700 rounded px-2 py-1 text-xs"
          value={selectedProject || ''}
          onChange={e => setSelectedProject(Number(e.target.value) || null)}
        >
          <option value="">프로젝트 선택</option>
          {projects.map(p => (
            <option key={p.id} value={p.id}>
              {p.name} ({p.node_count} nodes)
            </option>
          ))}
        </select>

        {selectedProject && (
          <button
            className="px-2 py-1 bg-blue-600 hover:bg-blue-700 rounded text-xs disabled:opacity-50"
            onClick={handleIndex}
            disabled={indexing}
          >
            {indexing ? 'Indexing...' : 'Re-index'}
          </button>
        )}

        {/* 간이 등록 */}
        <input
          className="bg-zinc-800 border border-zinc-700 rounded px-2 py-1 text-xs flex-1 min-w-[200px]"
          placeholder="프로젝트 경로 입력 (예: D:\my-project)"
          value={registerPath}
          onChange={e => setRegisterPath(e.target.value)}
          onKeyDown={e => e.key === 'Enter' && handleRegister()}
        />
        <button
          className="px-2 py-1 bg-green-600 hover:bg-green-700 rounded text-xs"
          onClick={handleRegister}
        >
          Register
        </button>
      </div>

      {/* 통계 바 */}
      {Object.keys(stats).length > 0 && (
        <div className="flex gap-3 text-xs text-zinc-400">
          {stats.function && <span className="text-blue-400">{stats.function} functions</span>}
          {stats.class && <span className="text-green-400">{stats.class} classes</span>}
          {stats.import && <span className="text-purple-400">{stats.import} imports</span>}
          {stats.files && <span className="text-zinc-300">{stats.files} files</span>}
        </div>
      )}

      {/* 그래프 + 상세 패널 */}
      <div className="flex-1 flex gap-2 min-h-0">
        {/* 그래프 영역 */}
        <div className="flex-1 bg-zinc-900 rounded border border-zinc-800 overflow-hidden">
          {graphData.nodes.length > 0 ? (
            <ForceGraph2D
              ref={graphRef}
              graphData={graphData}
              nodeId="id"
              nodeCanvasObject={paintNode}
              linkColor={() => 'rgba(100,100,100,0.3)'}
              linkDirectionalArrowLength={3}
              linkDirectionalArrowRelPos={1}
              onNodeClick={handleNodeClick}
              backgroundColor="#09090b"
              width={undefined}
              height={undefined}
            />
          ) : (
            <div className="h-full flex items-center justify-center text-zinc-500 text-xs">
              {selectedProject ? 'Re-index로 그래프 데이터를 생성하세요' : '프로젝트를 선택하세요'}
            </div>
          )}
        </div>

        {/* 상세 사이드바 */}
        {selectedNode && (
          <div className="w-64 bg-zinc-900 rounded border border-zinc-800 p-3 overflow-y-auto">
            <h3 className="font-bold text-white mb-2">{selectedNode.name}</h3>
            <div className="text-xs text-zinc-400 space-y-1">
              <p><span className="text-zinc-500">Type:</span> <span className={`text-${selectedNode.node_type === 'function' ? 'blue' : 'green'}-400`}>{selectedNode.node_type}</span></p>
              <p><span className="text-zinc-500">File:</span> {selectedNode.file_path}</p>
              <p><span className="text-zinc-500">Line:</span> {selectedNode.line_start}</p>
              {selectedNode.signature && (
                <p className="font-mono text-[10px] bg-zinc-800 p-1 rounded break-all">{selectedNode.signature}</p>
              )}
            </div>

            {impactNodes.length > 0 && (
              <div className="mt-3">
                <h4 className="text-xs font-semibold text-orange-400 mb-1">
                  Impact ({impactNodes.length})
                </h4>
                <ul className="text-xs text-zinc-400 space-y-1">
                  {impactNodes.map((n: any, i: number) => (
                    <li key={i} className="flex items-center gap-1">
                      <span className="w-1.5 h-1.5 rounded-full bg-orange-400 inline-block" />
                      <span className="truncate">{n.name}</span>
                      <span className="text-zinc-600 ml-auto">L{n.distance}</span>
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
