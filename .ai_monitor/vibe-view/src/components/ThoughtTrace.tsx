/**
 * 📄 파일명: ThoughtTrace.tsx
 * 📝 설명: AI의 사고 과정(Chain of Thought)과 벡터 메모리 검색을 하나의 패널에서 제공합니다.
 *         [🧠 사고] 탭: 실시간 Thought Trace 타임라인
 *         [🔍 메모리] 탭: ChromaDB 벡터 DB 시맨틱 검색 UI
 *
 * REVISION HISTORY:
 * - 2026-02-26 Claude: 탭 구조 추가 + 벡터 메모리 검색 UI 구현
 * - 2026-02-26 Gemini-1: 초기 Thought Trace 시각화 컴포넌트 생성
 */

import React, { useState, useRef } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { Brain, Zap, ChevronLeft, ChevronRight, Search, Database, Loader2, Tag, ChevronDown, ChevronUp } from 'lucide-react';
import { ThoughtLog } from '../types';

// 서버 API 기본 URL — App.tsx와 동일한 방식으로 현재 페이지 포트 사용
const API_BASE = `http://${window.location.hostname}:${window.location.port}`;

// 벡터 검색 결과 단일 항목 타입
interface VectorResult {
  id: string;
  content: string;
  metadata: Record<string, string>;
  distance: number;
}

// 유사도 점수(distance)를 % 문자열로 변환 (distance 0 = 100%, 1 = 0%)
function similarityPct(distance: number): number {
  return Math.round((1 - distance) * 100);
}

// 유사도 % 값에 따른 색상 클래스 반환
// 70% 이상: 초록, 50~70: 노랑, 그 이하: 회색
function similarityColor(pct: number): string {
  if (pct >= 70) return 'bg-green-500/20 text-green-400 border-green-500/30';
  if (pct >= 50) return 'bg-yellow-500/20 text-yellow-400 border-yellow-500/30';
  return 'bg-white/10 text-white/40 border-white/10';
}

// 결과 카드 단일 컴포넌트 — 클릭 시 전체 내용 expand/collapse
const VectorResultCard: React.FC<{ result: VectorResult }> = ({ result }) => {
  const [expanded, setExpanded] = useState(false);
  const pct = similarityPct(result.distance);
  const colorClass = similarityColor(pct);
  // 미리보기: 최대 100자
  const preview = result.content.slice(0, 100);
  const hasMore = result.content.length > 100;

  // 메타데이터에서 표시할 태그 목록 (type, agent 우선)
  const metaTags = Object.entries(result.metadata).slice(0, 3);

  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      className="bg-white/5 border border-white/8 rounded-lg overflow-hidden hover:border-white/15 transition-colors"
    >
      {/* 카드 헤더: id + 유사도 배지 */}
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full text-left px-3 py-2 flex items-start justify-between gap-2"
      >
        <div className="flex-1 min-w-0">
          {/* 메모리 ID */}
          <p className="text-[10px] font-mono text-primary/70 truncate mb-1">{result.id}</p>
          {/* 내용 미리보기 */}
          <p className="text-[11px] text-white/70 leading-relaxed line-clamp-2">
            {preview}{hasMore && !expanded ? '…' : ''}
          </p>
        </div>
        <div className="flex flex-col items-end gap-1 shrink-0">
          {/* 유사도 배지 */}
          <span className={`text-[10px] font-bold px-1.5 py-0.5 rounded border ${colorClass}`}>
            {pct}%
          </span>
          {/* expand/collapse 아이콘 */}
          {hasMore && (
            expanded
              ? <ChevronUp className="w-3 h-3 text-white/30" />
              : <ChevronDown className="w-3 h-3 text-white/30" />
          )}
        </div>
      </button>

      {/* 확장된 전체 내용 */}
      <AnimatePresence initial={false}>
        {expanded && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.2 }}
            className="overflow-hidden"
          >
            <div className="px-3 pb-3 border-t border-white/5 pt-2">
              {/* 전체 내용 */}
              <p className="text-[11px] text-white/80 leading-relaxed whitespace-pre-wrap mb-2">
                {result.content}
              </p>
              {/* 메타데이터 태그 */}
              {metaTags.length > 0 && (
                <div className="flex flex-wrap gap-1">
                  {metaTags.map(([k, v]) => (
                    <span key={k} className="flex items-center gap-1 text-[9px] bg-white/8 text-white/40 px-1.5 py-0.5 rounded">
                      <Tag className="w-2 h-2" />
                      <span className="text-white/60">{k}:</span> {String(v).slice(0, 20)}
                    </span>
                  ))}
                </div>
              )}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </motion.div>
  );
};

interface ThoughtTraceProps {
  thoughts: ThoughtLog[];
}

export const ThoughtTrace: React.FC<ThoughtTraceProps> = ({ thoughts }) => {
  const [isOpen, setIsOpen] = useState(false);
  // 현재 활성 탭: 사고 과정 or 벡터 메모리 검색
  const [activeTab, setActiveTab] = useState<'thoughts' | 'vector'>('thoughts');

  // 벡터 검색 관련 상태
  const [vectorQuery, setVectorQuery] = useState('');
  const [vectorResults, setVectorResults] = useState<VectorResult[]>([]);
  const [isSearching, setIsSearching] = useState(false);
  const [searchError, setSearchError] = useState('');
  const [hasSearched, setHasSearched] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  // 벡터 검색 실행 — /api/vector/search POST 호출
  const handleSearch = async () => {
    const q = vectorQuery.trim();
    if (!q) return;
    setIsSearching(true);
    setSearchError('');
    setHasSearched(true);
    try {
      const res = await fetch(`${API_BASE}/api/vector/search`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ query: q, n: 5 }),
      });
      const data = await res.json();
      if (data.error) {
        setSearchError(data.error);
        setVectorResults([]);
      } else {
        setVectorResults(data.results || []);
      }
    } catch {
      setSearchError('서버 연결 실패 — 서버가 실행 중인지 확인하세요');
      setVectorResults([]);
    } finally {
      setIsSearching(false);
    }
  };

  // Enter 키 검색 처리
  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter') handleSearch();
  };

  return (
    <motion.div
      initial={false}
      animate={{ width: isOpen ? 320 : 36 }}
      className="flex flex-col h-full bg-[#1e1e1e] border-l border-white/5 shrink-0 overflow-hidden relative shadow-2xl"
    >
      {/* 접기/펴기 핸들 버튼 (세로로 길게 배치) */}
      <button
        onClick={() => setIsOpen(!isOpen)}
        className="absolute left-0 top-1/2 -translate-y-1/2 w-8 h-24 bg-primary/20 hover:bg-primary/40 border-y border-r border-white/10 rounded-r-md flex items-center justify-center transition-colors z-20 group"
        title={isOpen ? "패널 숨기기" : "AI 인사이트 보기"}
      >
        {isOpen
          ? <ChevronRight className="w-4 h-4 text-primary" />
          : <ChevronLeft className="w-4 h-4 text-primary group-hover:scale-125 transition-transform" />
        }
      </button>

      {/* 헤더 + 탭 */}
      <div className={`shrink-0 border-b border-white/5 bg-white/2 ${!isOpen && 'justify-center px-0'}`}>
        {/* 상단 타이틀 행 */}
        <div className={`flex items-center gap-2 px-4 py-2.5 ${!isOpen && 'justify-center px-0'}`}>
          {activeTab === 'thoughts'
            ? <Brain className={`w-4 h-4 text-primary shrink-0 ${!isOpen && 'animate-pulse'}`} />
            : <Database className={`w-4 h-4 text-cyan-400 shrink-0 ${!isOpen && 'animate-pulse'}`} />
          }
          {isOpen && (
            <>
              <span className="text-xs font-bold text-white/80 flex-1 truncate">
                {activeTab === 'thoughts' ? 'Thought Trace' : 'Vector Memory'}
              </span>
              <span className="text-[10px] bg-primary/20 text-primary px-1.5 py-0.5 rounded-full font-mono">v5.0</span>
            </>
          )}
        </div>

        {/* 탭 버튼 행 — 패널이 열려있을 때만 표시 */}
        {isOpen && (
          <div className="flex border-t border-white/5">
            <button
              onClick={() => setActiveTab('thoughts')}
              className={`flex-1 flex items-center justify-center gap-1.5 py-2 text-[11px] font-medium transition-colors ${
                activeTab === 'thoughts'
                  ? 'text-primary border-b-2 border-primary bg-primary/5'
                  : 'text-white/40 hover:text-white/70'
              }`}
            >
              <Brain className="w-3 h-3" /> 사고
            </button>
            <button
              onClick={() => { setActiveTab('vector'); setTimeout(() => inputRef.current?.focus(), 100); }}
              className={`flex-1 flex items-center justify-center gap-1.5 py-2 text-[11px] font-medium transition-colors ${
                activeTab === 'vector'
                  ? 'text-cyan-400 border-b-2 border-cyan-400 bg-cyan-400/5'
                  : 'text-white/40 hover:text-white/70'
              }`}
            >
              <Search className="w-3 h-3" /> 메모리
            </button>
          </div>
        )}
      </div>

      {/* ── 탭 내용 영역 ── */}
      <div className={`flex-1 overflow-hidden flex flex-col ${!isOpen && 'opacity-0 pointer-events-none'}`}>

        {/* ── [🧠 사고] 탭 ── */}
        {activeTab === 'thoughts' && (
          <div className="flex-1 overflow-y-auto p-4 space-y-4 scrollbar-hide">
            <AnimatePresence initial={false}>
              {thoughts.length === 0 ? (
                <div className="flex flex-col items-center justify-center h-full opacity-20 text-center pt-16">
                  <Brain className="w-12 h-12 mb-2" />
                  <p className="text-[10px]">대기 중...</p>
                </div>
              ) : (
                thoughts.map((t, idx) => (
                  <motion.div
                    key={idx + t.timestamp}
                    initial={{ opacity: 0, x: 20 }}
                    animate={{ opacity: 1, x: 0 }}
                    className="relative pl-6 pb-2 border-l border-white/10 last:border-0"
                  >
                    {/* 타임라인 점 */}
                    <div className="absolute left-[-5px] top-1 w-2.5 h-2.5 rounded-full bg-primary/40 border border-primary flex items-center justify-center">
                      <div className="w-1 h-1 rounded-full bg-primary" />
                    </div>
                    <div className="flex flex-col gap-1">
                      <div className="flex items-center justify-between">
                        <span className="text-[9px] font-mono text-primary/60">{t.agent}</span>
                        <span className="text-[8px] text-white/30">
                          {new Date(t.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })}
                        </span>
                      </div>
                      <div className="bg-white/5 rounded p-2 border border-white/5 hover:bg-white/8 transition-colors">
                        {t.tool && (
                          <div className="flex items-center gap-1.5 mb-1 opacity-80">
                            <Zap className="w-3 h-3 text-yellow-500" />
                            <span className="text-[10px] font-bold text-yellow-500/80 uppercase">{t.tool}</span>
                          </div>
                        )}
                        <p className="text-[11px] leading-relaxed text-white/80 whitespace-pre-wrap">{t.thought}</p>
                      </div>
                    </div>
                  </motion.div>
                ))
              )}
            </AnimatePresence>
          </div>
        )}

        {/* ── [🔍 메모리] 탭 ── */}
        {activeTab === 'vector' && (
          <div className="flex-1 overflow-hidden flex flex-col">
            {/* 검색 입력 영역 */}
            <div className="px-3 py-3 border-b border-white/5 shrink-0">
              <div className="flex gap-2 items-center bg-black/30 border border-white/10 rounded-lg px-3 py-2 focus-within:border-cyan-400/40 transition-colors">
                <Search className="w-3.5 h-3.5 text-white/30 shrink-0" />
                <input
                  ref={inputRef}
                  type="text"
                  value={vectorQuery}
                  onChange={e => setVectorQuery(e.target.value)}
                  onKeyDown={handleKeyDown}
                  placeholder="기억 검색... (Enter)"
                  className="flex-1 bg-transparent text-[12px] text-white/80 placeholder:text-white/25 outline-none"
                />
                {vectorQuery && (
                  <button
                    onClick={handleSearch}
                    disabled={isSearching}
                    className="text-[10px] text-cyan-400 hover:text-cyan-300 font-medium shrink-0 disabled:opacity-40"
                  >
                    검색
                  </button>
                )}
              </div>
            </div>

            {/* 결과 영역 */}
            <div className="flex-1 overflow-y-auto p-3 space-y-2 scrollbar-hide">
              {/* 로딩 중 */}
              {isSearching && (
                <div className="flex items-center justify-center py-12 gap-2 text-white/30">
                  <Loader2 className="w-4 h-4 animate-spin" />
                  <span className="text-[11px]">검색 중...</span>
                </div>
              )}

              {/* 에러 메시지 */}
              {!isSearching && searchError && (
                <div className="text-center py-8">
                  <p className="text-[11px] text-red-400/70">{searchError}</p>
                </div>
              )}

              {/* 검색 전 초기 상태 */}
              {!isSearching && !searchError && !hasSearched && (
                <div className="flex flex-col items-center justify-center py-12 opacity-25 text-center">
                  <Database className="w-10 h-10 mb-3" />
                  <p className="text-[11px] font-medium mb-1">벡터 메모리 검색</p>
                  <p className="text-[10px] text-white/60 leading-relaxed">
                    의미적으로 유사한 기억을<br />찾아드립니다
                  </p>
                </div>
              )}

              {/* 결과 없음 */}
              {!isSearching && !searchError && hasSearched && vectorResults.length === 0 && (
                <div className="flex flex-col items-center justify-center py-12 opacity-30 text-center">
                  <Database className="w-8 h-8 mb-2" />
                  <p className="text-[11px]">결과 없음</p>
                  <p className="text-[10px] text-white/50 mt-1">다른 키워드로 검색해보세요</p>
                </div>
              )}

              {/* 결과 카드 목록 */}
              {!isSearching && vectorResults.length > 0 && (
                <AnimatePresence>
                  {vectorResults.map((r, i) => (
                    <motion.div
                      key={r.id + i}
                      initial={{ opacity: 0, y: 6 }}
                      animate={{ opacity: 1, y: 0 }}
                      transition={{ delay: i * 0.05 }}
                    >
                      <VectorResultCard result={r} />
                    </motion.div>
                  ))}
                </AnimatePresence>
              )}
            </div>
          </div>
        )}
      </div>

      {/* 하단 상태바 */}
      {isOpen && (
        <div className="px-4 py-2 bg-black/20 border-t border-white/5 shrink-0">
          <div className="flex items-center gap-2">
            <div className={`w-1.5 h-1.5 rounded-full animate-pulse ${activeTab === 'thoughts' ? 'bg-success' : 'bg-cyan-400'}`} />
            <span className="text-[9px] text-white/40">
              {activeTab === 'thoughts' ? 'Real-time Insight Active' : `Vector DB · ${vectorResults.length > 0 ? vectorResults.length + '개 결과' : '준비 완료'}`}
            </span>
          </div>
        </div>
      )}
    </motion.div>
  );
};
