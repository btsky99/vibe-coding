/**
 * 📄 파일명: ThoughtTrace.tsx
 * 📝 설명: AI의 사고 과정(Chain of Thought)을 시각화하는 컴포넌트입니다.
 */

import React from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { Brain, Zap } from 'lucide-react';
import { ThoughtLog } from '../types';

interface ThoughtTraceProps {
  thoughts: ThoughtLog[];
}

export const ThoughtTrace: React.FC<ThoughtTraceProps> = ({ thoughts }) => {
  return (
    <div className="flex flex-col h-full bg-[#1e1e1e] border-l border-white/5 w-80 shrink-0 overflow-hidden">
      <div className="flex items-center gap-2 px-4 py-3 border-b border-white/5 bg-white/2">
        <Brain className="w-4 h-4 text-primary" />
        <span className="text-xs font-bold text-white/80">Thought Trace (v5.0)</span>
      </div>
      
      <div className="flex-1 overflow-y-auto p-4 space-y-4 scrollbar-hide">
        <AnimatePresence initial={false}>
          {thoughts.length === 0 ? (
            <div className="flex flex-col items-center justify-center h-full opacity-20 text-center">
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
                    <span className="text-[9px] font-mono text-primary/60">
                      {t.agent}
                    </span>
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
                    <p className="text-[11px] leading-relaxed text-white/80 whitespace-pre-wrap">
                      {t.thought}
                    </p>
                  </div>
                </div>
              </motion.div>
            ))
          )}
        </AnimatePresence>
      </div>
      
      {/* 하단 상태바 */}
      <div className="px-4 py-2 bg-black/20 border-t border-white/5">
        <div className="flex items-center gap-2">
          <div className="w-1.5 h-1.5 rounded-full bg-success animate-pulse" />
          <span className="text-[9px] text-white/40">Real-time Insight Active</span>
        </div>
      </div>
    </div>
  );
};
