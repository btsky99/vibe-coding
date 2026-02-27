/**
 * 📄 파일명: ThoughtTrace.tsx
 * 📝 설명: AI의 사고 과정(Chain of Thought)을 실시간으로 시각화하는 패널.
 *
 * REVISION HISTORY:
 * - 2026-02-27 Claude: 벡터 DB/ChromaDB 탭 제거 — 사고 추적 전용으로 단순화
 * - 2026-02-26 Claude: 탭 구조 추가 + 벡터 메모리 검색 UI 구현
 * - 2026-02-26 Gemini-1: 초기 Thought Trace 시각화 컴포넌트 생성
 */

import React, { useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { Brain, Zap, ChevronLeft, ChevronRight } from 'lucide-react';
import { ThoughtLog } from '../types';

interface ThoughtTraceProps {
  thoughts: ThoughtLog[];
}

export const ThoughtTrace: React.FC<ThoughtTraceProps> = ({ thoughts }) => {
  const [isOpen, setIsOpen] = useState(false);

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

      {/* 헤더 */}
      <div className={`shrink-0 border-b border-white/5 bg-white/2 ${!isOpen && 'justify-center px-0'}`}>
        <div className={`flex items-center gap-2 px-4 py-2.5 ${!isOpen && 'justify-center px-0'}`}>
          <Brain className={`w-4 h-4 text-primary shrink-0 ${!isOpen && 'animate-pulse'}`} />
          {isOpen && (
            <>
              <span className="text-xs font-bold text-white/80 flex-1 truncate">사고 추적</span>
              <span className="text-[10px] bg-primary/20 text-primary px-1.5 py-0.5 rounded-full font-mono">v5.0</span>
            </>
          )}
        </div>
      </div>

      {/* 사고 타임라인 */}
      <div className={`flex-1 overflow-y-auto p-4 space-y-4 scrollbar-hide ${!isOpen && 'opacity-0 pointer-events-none'}`}>
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

      {/* 하단 상태바 */}
      {isOpen && (
        <div className="px-4 py-2 bg-black/20 border-t border-white/5 shrink-0">
          <div className="flex items-center gap-2">
            <div className="w-1.5 h-1.5 rounded-full animate-pulse bg-success" />
            <span className="text-[9px] text-white/40">실시간 사고 스트림 활성</span>
          </div>
        </div>
      )}
    </motion.div>
  );
};
