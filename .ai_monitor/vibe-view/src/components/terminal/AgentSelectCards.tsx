/**
 * ------------------------------------------------------------------------
 * 📄 파일명: AgentSelectCards.tsx
 * 📝 설명: 터미널 미실행 슬롯의 에이전트 선택 카드 3장(Claude/Antigravity/Codex)
 *          + 배경 로그 표시(블러). 카드 버튼이 onLaunch(agent, yolo)를 호출.
 * REVISION HISTORY:
 * - 2026-07-15 Claude: TerminalSlot.tsx 1500줄 상한 도달로 분리 (로직 무변경 이동,
 *                      배경 로그 자동 스크롤 effect는 이 뷰 전용이라 함께 이동)
 * - 2026-03-08 Claude: (TerminalSlot 내) Codex CLI 카드 추가
 * ------------------------------------------------------------------------
 */
import { useEffect, useRef } from 'react';
import { motion } from 'framer-motion';
import { Cpu, Zap, Code2, Orbit } from 'lucide-react';
import { API_BASE } from '../../constants';
import { LogRecord } from '../../types';

export default function AgentSelectCards({ logs, onLaunch }: {
  logs: LogRecord[];
  onLaunch: (agent: string, yolo: boolean) => void;
}) {
  const scrollRef = useRef<HTMLDivElement>(null);

  // 새 로그 도착 시 자동 스크롤
  useEffect(() => {
    if (scrollRef.current) scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
  }, [logs.length]);

  return (
    <div className="flex-1 flex flex-col relative overflow-hidden bg-[#1a1a1a]">
      {/* 중앙 에이전트 선택 카드 UI */}
      <div className="absolute inset-0 flex items-center justify-center p-6 z-10 bg-black/20 backdrop-blur-[2px]">
        <div className="flex flex-col md:flex-row gap-6 max-w-4xl w-full">

          {/* Claude Card */}
          <motion.div
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            whileHover={{ scale: 1.02, translateY: -5 }}
            className="flex-1 bg-[#252526] border border-white/10 rounded-2xl p-6 shadow-2xl flex flex-col items-center gap-4 transition-all hover:border-success/50 group relative overflow-hidden"
          >
            <div className="absolute top-0 right-0 p-3 opacity-10 group-hover:opacity-20 transition-opacity">
              <Cpu className="w-12 h-12 text-success" />
            </div>
            <div className="w-16 h-16 rounded-2xl bg-success/10 flex items-center justify-center mb-2 group-hover:bg-success/20 transition-colors shadow-inner">
              <Cpu className="w-8 h-8 text-success" />
            </div>
            <div className="text-center">
              <h3 className="text-xl font-black text-white tracking-tighter mb-1">CLAUDE CODE</h3>
              <p className="text-[10px] text-success font-bold uppercase tracking-widest opacity-60">High Precision Agent</p>
            </div>
            <p className="text-xs text-[#969696] text-center leading-relaxed h-12 flex items-center">
              Anthropic의 최신 모델을 기반으로 한 정밀 코딩 도구.<br/>복잡한 리팩토링과 설계에 최적화되어 있습니다.
            </p>
            <div className="flex flex-col w-full gap-2 mt-4">
              <button
                onClick={() => onLaunch('claude', false)}
                className="w-full py-2.5 bg-[#3c3c3c] hover:bg-white/10 rounded-xl text-[11px] font-bold transition-all border border-white/5 flex items-center justify-center gap-2 group/btn"
              >
                Claude 일반 모드
              </button>
              <button
                onClick={() => onLaunch('claude', true)}
                className="w-full py-2.5 bg-primary/20 hover:bg-primary/40 text-primary rounded-xl text-[11px] font-black transition-all border border-primary/30 flex items-center justify-center gap-2 shadow-lg shadow-primary/10"
              >
                <Zap className="w-3.5 h-3.5 fill-current" /> Claude 욜로(YOLO)
              </button>
            </div>
          </motion.div>

          {/* Antigravity Card (식별자 'gemini'는 Phase 1 alias 정책으로 유지) */}
          <motion.div
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.1 }}
            whileHover={{ scale: 1.02, translateY: -5 }}
            className="flex-1 bg-[#252526] border border-white/10 rounded-2xl p-6 shadow-2xl flex flex-col items-center gap-4 transition-all hover:border-indigo-400/50 group relative overflow-hidden"
          >
            <div className="absolute top-0 right-0 p-3 opacity-10 group-hover:opacity-20 transition-opacity">
              <Orbit className="w-12 h-12 text-indigo-400" />
            </div>
            <div className="w-16 h-16 rounded-2xl bg-indigo-400/10 flex items-center justify-center mb-2 group-hover:bg-indigo-400/20 transition-colors shadow-inner">
              <Orbit className="w-8 h-8 text-indigo-400" />
            </div>
            <div className="text-center">
              <h3 className="text-xl font-black text-white tracking-tighter mb-1">ANTIGRAVITY</h3>
              <p className="text-[10px] text-indigo-400 font-bold uppercase tracking-widest opacity-60">Agentic Code Pilot</p>
            </div>
            <p className="text-xs text-[#969696] text-center leading-relaxed h-12 flex items-center">
              Google의 차세대 에이전트 CLI.<br/>비대화형 실행과 멀티스텝 자동화에 최적화됐습니다.
            </p>
            <div className="flex flex-col w-full gap-2 mt-4">
              <button
                onClick={() => onLaunch('antigravity', false)}
                className="w-full py-2.5 bg-[#3c3c3c] hover:bg-white/10 rounded-xl text-[11px] font-bold transition-all border border-white/5 flex items-center justify-center gap-2 group/btn"
              >
                Antigravity 일반 모드
              </button>
              <button
                onClick={() => onLaunch('antigravity', true)}
                className="w-full py-2.5 bg-indigo-400/20 hover:bg-indigo-400/40 text-indigo-300 rounded-xl text-[11px] font-black transition-all border border-indigo-400/30 flex items-center justify-center gap-2 shadow-lg shadow-indigo-400/10"
              >
                <Zap className="w-3.5 h-3.5 fill-current" /> Antigravity 욜로(YOLO)
              </button>
            </div>
          </motion.div>

          {/* Codex Card */}
          <motion.div
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.2 }}
            whileHover={{ scale: 1.02, translateY: -5 }}
            className="flex-1 bg-[#252526] border border-white/10 rounded-2xl p-6 shadow-2xl flex flex-col items-center gap-4 transition-all hover:border-orange-400/50 group relative overflow-hidden"
          >
            <div className="absolute top-0 right-0 p-3 opacity-10 group-hover:opacity-20 transition-opacity">
              <Code2 className="w-12 h-12 text-orange-400" />
            </div>
            <div className="w-16 h-16 rounded-2xl bg-orange-400/10 flex items-center justify-center mb-2 group-hover:bg-orange-400/20 transition-colors shadow-inner">
              <Code2 className="w-8 h-8 text-orange-400" />
            </div>
            <div className="text-center">
              <h3 className="text-xl font-black text-white tracking-tighter mb-1">CODEX CLI</h3>
              <p className="text-[10px] text-orange-400 font-bold uppercase tracking-widest opacity-60">OpenAI Agentic Coder</p>
            </div>
            <p className="text-xs text-[#969696] text-center leading-relaxed h-12 flex items-center">
              OpenAI의 자율 코딩 에이전트.<br/>코드 생성·수정·실행을 자동으로 처리합니다.
            </p>
            <div className="flex flex-col w-full gap-2 mt-4">
              <button
                onClick={() => onLaunch('codex', false)}
                className="w-full py-2.5 bg-[#3c3c3c] hover:bg-white/10 rounded-xl text-[11px] font-bold transition-all border border-white/5 flex items-center justify-center gap-2 group/btn"
              >
                Codex 일반 모드
              </button>
              <button
                onClick={() => onLaunch('codex', true)}
                className="w-full py-2.5 bg-orange-400/20 hover:bg-orange-400/40 text-orange-400 rounded-xl text-[11px] font-black transition-all border border-orange-400/30 flex items-center justify-center gap-2 shadow-lg shadow-orange-400/10"
              >
                <Zap className="w-3.5 h-3.5 fill-current" /> Codex 욜로(YOLO)
              </button>
              {/* Codex CLI 미설치 시 npm 전역 설치 버튼 */}
              <button
                onClick={() => fetch(`${API_BASE}/api/install-codex-cli`, { method: 'POST' })}
                className="w-full py-1.5 bg-transparent hover:bg-white/5 rounded-xl text-[10px] font-bold transition-all border border-white/5 text-[#555] hover:text-[#888] flex items-center justify-center gap-1.5"
              >
                <Code2 className="w-3 h-3" /> Codex CLI 설치 (npm)
              </button>
            </div>
          </motion.div>

        </div>
      </div>

      {/* 배경 로그 (블러 처리하여 생동감 부여) */}
      <div ref={scrollRef} className="flex-1 p-3 overflow-y-auto font-mono text-[11px] space-y-1 custom-scrollbar opacity-20">
        {logs.slice(-30).map((log, idx) => (
          <div key={idx} className="flex items-start gap-2 border-l border-primary/20 pl-2 py-0.5">
            <span className="text-primary/60 font-bold whitespace-nowrap">[{log.agent}]</span>
            <span className="flex-1 text-[#aaaaaa] break-all leading-relaxed whitespace-pre-wrap">{log.trigger}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
