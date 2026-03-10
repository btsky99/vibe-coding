/**
 * FILE: KnowledgeGraphPanel.tsx
 * DESCRIPTION: 하이브 지식 그래프 시각화 패널.
 *              /api/hive/knowledge-graph 에서 노드·링크 데이터를 받아
 *              react-force-graph-2d 기반 인터랙티브 그래프로 렌더링합니다.
 *              노드 색상: 에이전트별 구분 (claude=보라, gemini=파랑, codex=주황)
 *              엣지: parent_id → child 계보 연결선
 * REVISION HISTORY:
 * - 2026-03-10 Claude: 신규 구현 — Task 17 지식 그래프 시각화 (A안 + react-force-graph-2d)
 */

import { useState, useEffect, useRef, useCallback } from 'react';
import ForceGraph2D from 'react-force-graph-2d';
import { Network, RefreshCw, ZoomIn, ZoomOut, Maximize2, Info } from 'lucide-react';

// 현재 포트 기반 API 주소
const API_BASE = `http://${window.location.hostname}:${window.location.port}`;

// ── 타입 정의 ───────────────────────────────────────────────────────────────
interface GraphNode {
  id: number;
  label: string;
  agent: string;
  skill: string;
  type: string;
  // force-graph 내부에서 채워지는 좌표 (선택적)
  x?: number;
  y?: number;
}

interface GraphLink {
  source: number;
  target: number;
}

interface GraphData {
  nodes: GraphNode[];
  links: GraphLink[];
}

// ── 에이전트별 색상 팔레트 ────────────────────────────────────────────────
const AGENT_COLORS: Record<string, string> = {
  claude:  '#7c6ee3',  // 보라
  gemini:  '#4a9eff',  // 파랑
  codex:   '#f97316',  // 주황
  user:    '#34d399',  // 초록
  agent:   '#e879f9',  // 핑크
};

const getAgentColor = (agent: string): string =>
  AGENT_COLORS[agent?.toLowerCase()] ?? '#8b8b8b';

// ── 노드 타입별 형태 ─────────────────────────────────────────────────────
const NODE_RADIUS: Record<string, number> = {
  decision: 9,
  memory:   7,
  log:      5,
  default:  6,
};

/**
 * KnowledgeGraphPanel
 *
 * 하이브 마인드의 pg_thoughts 기반 지식 계보를 force-directed 그래프로 시각화.
 * 노드 클릭 시 상세 정보(에이전트, 스킬, 타입)를 우측 인포 패널에 표시.
 */
export default function KnowledgeGraphPanel() {
  // 그래프 데이터
  const [graphData, setGraphData] = useState<GraphData>({ nodes: [], links: [] });
  // 로딩 / 오류 상태
  const [loading, setLoading] = useState(true);
  const [error, setError]     = useState('');
  // 선택된 노드 상세 정보
  const [selectedNode, setSelectedNode] = useState<GraphNode | null>(null);
  // 컨테이너 크기 (force-graph에 width/height 전달)
  const containerRef = useRef<HTMLDivElement>(null);
  const [dimensions, setDimensions] = useState({ w: 600, h: 500 });
  // 그래프 인스턴스 ref — zoomToFit, zoom 제어에 사용
  const fgRef = useRef<any>(null);
  // 마지막 갱신 시각
  const [lastUpdated, setLastUpdated] = useState('');

  // ── 컨테이너 크기 감지 (ResizeObserver) ────────────────────────────────
  useEffect(() => {
    if (!containerRef.current) return;
    const ro = new ResizeObserver(entries => {
      const { width, height } = entries[0].contentRect;
      setDimensions({ w: Math.floor(width), h: Math.floor(height) });
    });
    ro.observe(containerRef.current);
    return () => ro.disconnect();
  }, []);

  // ── API 데이터 로드 ──────────────────────────────────────────────────────
  const fetchGraph = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const res  = await fetch(`${API_BASE}/api/hive/knowledge-graph`);
      const data = await res.json();
      if (data.error) throw new Error(data.error);
      setGraphData(data);
      setLastUpdated(new Date().toLocaleTimeString());
    } catch (e: any) {
      setError(e.message ?? '데이터 로드 실패');
    } finally {
      setLoading(false);
    }
  }, []);

  // 마운트 시 1회 + 60초 자동 갱신
  useEffect(() => {
    fetchGraph();
    const iv = setInterval(fetchGraph, 60_000);
    return () => clearInterval(iv);
  }, [fetchGraph]);

  // ── 데이터 로드 후 그래프 자동 맞춤 ────────────────────────────────────
  useEffect(() => {
    if (!loading && fgRef.current) {
      setTimeout(() => fgRef.current?.zoomToFit(400, 40), 300);
    }
  }, [loading]);

  // ── 노드 캔버스 커스텀 렌더러 ──────────────────────────────────────────
  const paintNode = useCallback((node: any, ctx: CanvasRenderingContext2D) => {
    const r     = NODE_RADIUS[node.type] ?? NODE_RADIUS.default;
    const color = getAgentColor(node.agent);
    const isSelected = selectedNode?.id === node.id;

    // 선택 시 글로우 효과
    if (isSelected) {
      ctx.beginPath();
      ctx.arc(node.x, node.y, r + 5, 0, 2 * Math.PI);
      ctx.fillStyle = color + '40';
      ctx.fill();
    }

    // 노드 원
    ctx.beginPath();
    ctx.arc(node.x, node.y, r, 0, 2 * Math.PI);
    ctx.fillStyle = color;
    ctx.fill();
    // 테두리
    ctx.strokeStyle = isSelected ? '#ffffff' : color + 'aa';
    ctx.lineWidth   = isSelected ? 2 : 1;
    ctx.stroke();

    // 라벨 (짧게 truncate)
    const label = node.label?.length > 12 ? node.label.slice(0, 12) + '…' : node.label;
    ctx.fillStyle    = '#cccccc';
    ctx.font         = `${Math.max(8, r * 1.2)}px monospace`;
    ctx.textAlign    = 'center';
    ctx.textBaseline = 'middle';
    ctx.fillText(label, node.x, node.y + r + 8);
  }, [selectedNode]);

  // ── 통계 요약 ───────────────────────────────────────────────────────────
  const agentCounts = graphData.nodes.reduce<Record<string, number>>((acc, n) => {
    acc[n.agent] = (acc[n.agent] ?? 0) + 1;
    return acc;
  }, {});

  return (
    <div className="flex-1 flex flex-col overflow-hidden gap-0 h-full">

      {/* ── 헤더 툴바 ─────────────────────────────────────────────────────── */}
      <div className="shrink-0 flex items-center justify-between px-3 py-2 border-b border-white/10 bg-black/20">
        <div className="flex items-center gap-2">
          <Network className="w-4 h-4 text-primary" />
          <span className="text-xs font-bold text-[#ccc] uppercase tracking-wider">지식 그래프</span>
          <span className="text-[10px] text-[#555] ml-1">
            {graphData.nodes.length}노드 · {graphData.links.length}링크
          </span>
        </div>

        <div className="flex items-center gap-1">
          {/* 줌 인 */}
          <button
            onClick={() => fgRef.current?.zoom(fgRef.current.zoom() * 1.3, 200)}
            className="p-1 hover:bg-white/10 rounded text-[#858585] hover:text-white transition-colors"
            title="줌 인"
          >
            <ZoomIn className="w-3.5 h-3.5" />
          </button>
          {/* 줌 아웃 */}
          <button
            onClick={() => fgRef.current?.zoom(fgRef.current.zoom() * 0.7, 200)}
            className="p-1 hover:bg-white/10 rounded text-[#858585] hover:text-white transition-colors"
            title="줌 아웃"
          >
            <ZoomOut className="w-3.5 h-3.5" />
          </button>
          {/* 전체 맞춤 */}
          <button
            onClick={() => fgRef.current?.zoomToFit(400, 40)}
            className="p-1 hover:bg-white/10 rounded text-[#858585] hover:text-white transition-colors"
            title="전체 보기"
          >
            <Maximize2 className="w-3.5 h-3.5" />
          </button>
          {/* 새로고침 */}
          <button
            onClick={fetchGraph}
            className={`p-1 hover:bg-white/10 rounded text-[#858585] hover:text-white transition-colors ${loading ? 'animate-spin' : ''}`}
            title="새로고침"
          >
            <RefreshCw className="w-3.5 h-3.5" />
          </button>
        </div>
      </div>

      {/* ── 본문: 그래프 + 사이드 정보 ──────────────────────────────────────── */}
      <div className="flex-1 flex overflow-hidden">

        {/* 그래프 캔버스 영역 */}
        <div ref={containerRef} className="flex-1 relative overflow-hidden bg-[#0d0d0d]">

          {/* 로딩 오버레이 */}
          {loading && (
            <div className="absolute inset-0 flex items-center justify-center bg-black/60 z-10">
              <div className="flex flex-col items-center gap-3">
                <div className="w-8 h-8 border-2 border-primary border-t-transparent rounded-full animate-spin" />
                <span className="text-xs text-[#858585]">지식 그래프 로딩 중...</span>
              </div>
            </div>
          )}

          {/* 에러 메시지 */}
          {error && !loading && (
            <div className="absolute inset-0 flex items-center justify-center">
              <div className="text-center text-red-400 text-xs px-6">
                <Network className="w-10 h-10 mx-auto mb-3 opacity-30" />
                <p className="font-bold mb-1">데이터 로드 실패</p>
                <p className="text-[#555] mb-3">{error}</p>
                <button onClick={fetchGraph} className="px-3 py-1 bg-primary/20 text-primary rounded text-xs hover:bg-primary/30">
                  다시 시도
                </button>
              </div>
            </div>
          )}

          {/* 노드 없을 때 빈 상태 */}
          {!loading && !error && graphData.nodes.length === 0 && (
            <div className="absolute inset-0 flex items-center justify-center">
              <div className="text-center text-[#555] text-xs">
                <Network className="w-10 h-10 mx-auto mb-3 opacity-20" />
                <p>pg_thoughts 데이터가 없습니다.</p>
                <p className="mt-1 text-[10px]">에이전트가 작업하면 노드가 생성됩니다.</p>
              </div>
            </div>
          )}

          {/* force-graph 렌더링 */}
          {!loading && !error && graphData.nodes.length > 0 && (
            <ForceGraph2D
              ref={fgRef}
              width={dimensions.w}
              height={dimensions.h}
              graphData={graphData}
              nodeId="id"
              linkSource="source"
              linkTarget="target"
              // 노드 커스텀 렌더
              nodeCanvasObject={paintNode}
              nodeCanvasObjectMode={() => 'replace'}
              // 링크 스타일
              linkColor={() => '#ffffff18'}
              linkWidth={1}
              linkDirectionalArrowLength={4}
              linkDirectionalArrowRelPos={1}
              linkDirectionalArrowColor={() => '#ffffff30'}
              // 배경
              backgroundColor="#0d0d0d"
              // 클릭 인터랙션
              onNodeClick={(node: any) => setSelectedNode(node as GraphNode)}
              onBackgroundClick={() => setSelectedNode(null)}
              // 툴팁
              nodeLabel={(node: any) => `${node.agent} · ${node.skill || ''}\n${node.label}`}
              // 노드 포스 설정 (넓게 퍼지도록)
              d3VelocityDecay={0.3}
              d3AlphaDecay={0.01}
              cooldownTime={3000}
            />
          )}

          {/* 마지막 갱신 표시 */}
          {lastUpdated && (
            <div className="absolute bottom-2 left-2 text-[10px] text-[#333] pointer-events-none">
              갱신: {lastUpdated}
            </div>
          )}
        </div>

        {/* ── 우측 정보 패널 ─────────────────────────────────────────────── */}
        <div className="w-48 shrink-0 border-l border-white/10 bg-black/30 flex flex-col overflow-hidden">

          {/* 에이전트 범례 */}
          <div className="p-3 border-b border-white/10">
            <div className="text-[10px] font-bold text-[#666] mb-2 uppercase tracking-wider">에이전트</div>
            <div className="flex flex-col gap-1.5">
              {Object.entries(AGENT_COLORS).map(([agent, color]) => (
                <div key={agent} className="flex items-center justify-between">
                  <div className="flex items-center gap-1.5">
                    <div className="w-2.5 h-2.5 rounded-full" style={{ backgroundColor: color }} />
                    <span className="text-[11px] text-[#aaa] capitalize">{agent}</span>
                  </div>
                  <span className="text-[10px] text-[#555] font-mono">
                    {agentCounts[agent] ?? 0}
                  </span>
                </div>
              ))}
            </div>
          </div>

          {/* 선택된 노드 상세 */}
          <div className="p-3 flex-1 overflow-y-auto">
            {selectedNode ? (
              <div className="flex flex-col gap-2">
                <div className="flex items-center gap-1.5 text-[10px] font-bold text-[#969696] uppercase tracking-wider">
                  <Info className="w-3 h-3" /> 노드 상세
                </div>
                {/* 색상 인디케이터 */}
                <div
                  className="w-full h-1 rounded-full"
                  style={{ backgroundColor: getAgentColor(selectedNode.agent) }}
                />
                <div className="flex flex-col gap-1.5 mt-1">
                  <div>
                    <div className="text-[9px] text-[#555] mb-0.5">ID</div>
                    <div className="text-[11px] text-[#ccc] font-mono">#{selectedNode.id}</div>
                  </div>
                  <div>
                    <div className="text-[9px] text-[#555] mb-0.5">라벨</div>
                    <div className="text-[11px] text-[#ccc] break-words leading-snug">{selectedNode.label}</div>
                  </div>
                  <div>
                    <div className="text-[9px] text-[#555] mb-0.5">에이전트</div>
                    <div className="text-[11px] font-bold capitalize" style={{ color: getAgentColor(selectedNode.agent) }}>
                      {selectedNode.agent}
                    </div>
                  </div>
                  <div>
                    <div className="text-[9px] text-[#555] mb-0.5">스킬</div>
                    <div className="text-[11px] text-[#aaa] font-mono">{selectedNode.skill || '—'}</div>
                  </div>
                  <div>
                    <div className="text-[9px] text-[#555] mb-0.5">타입</div>
                    <div className="text-[11px] text-[#aaa]">{selectedNode.type || '—'}</div>
                  </div>
                </div>
              </div>
            ) : (
              <div className="text-[10px] text-[#444] italic text-center mt-6">
                노드를 클릭하면<br />상세 정보가 표시됩니다
              </div>
            )}
          </div>

          {/* 전체 통계 */}
          <div className="p-3 border-t border-white/10">
            <div className="text-[10px] font-bold text-[#666] mb-1.5 uppercase tracking-wider">전체 통계</div>
            <div className="flex justify-between text-[11px]">
              <span className="text-[#777]">노드</span>
              <span className="text-primary font-mono font-bold">{graphData.nodes.length}</span>
            </div>
            <div className="flex justify-between text-[11px]">
              <span className="text-[#777]">연결</span>
              <span className="text-cyan-400 font-mono font-bold">{graphData.links.length}</span>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
