/**
 * ------------------------------------------------------------------------
 * 📄 파일명: MissionControlPanel.tsx
 * 📝 설명: AI의 사고 과정(Thought Stream)과 마이크로 플랜을 시각화하는 패널.
 *          사이드바의 'Mission Control' 탭에서 렌더링됩니다.
 * REVISION HISTORY:
 * - 2026-03-04 Gemini: 초기 생성.
 * ------------------------------------------------------------------------
 */

import React, { useState, useEffect, useRef } from 'react';
import { Terminal, CheckCircle2, Circle, Clock, Brain } from 'lucide-react';

export default function MissionControlPanel() {
  const [thoughts, setThoughts] = useState<any[]>([]);
  const [planSteps, setPlanSteps] = useState<any[]>([]);
  const thoughtEndRef = useRef<HTMLDivElement>(null);

  // 사고 과정(Thought Stream) 더미 데이터 및 로딩 로직 (추후 API 연동)
  useEffect(() => {
    // 임시 데이터
    const mockThoughts = [
      { id: 1, time: '19:45:10', agent: 'Gemini', text: '프로젝트 구조 분석을 시작합니다...' },
      { id: 2, time: '19:45:12', agent: 'Gemini', text: '오케스트레이터의 UI 연동 상태를 확인했습니다.' },
      { id: 3, time: '19:45:15', agent: 'Gemini', text: '사이드바 버튼 추가를 위한 ActivityBar.tsx 수정을 계획합니다.' },
    ];
    setThoughts(mockThoughts);

    // 플랜 데이터 파싱 로직 (추후 ai_monitor_plan.md 연동)
    const mockPlan = [
      { id: 1, title: 'orchestrator.py 고도화', status: 'done' },
      { id: 2, title: 'Sidebar 버튼 추가', status: 'running' },
      { id: 3, title: 'Mission Control 패널 구현', status: 'pending' },
    ];
    setPlanSteps(mockPlan);
  }, []);

  useEffect(() => {
    thoughtEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [thoughts]);

  return (
    <div className="flex flex-col h-full gap-4 overflow-hidden">
      {/* 🚀 AI 마이크로 플랜 섹션 */}
      <div className="flex flex-col gap-2 shrink-0">
        <div className="flex items-center gap-2 text-[11px] font-bold text-primary uppercase tracking-tighter">
          <CheckCircle2 className="w-3.5 h-3.5" /> Live Micro-Plan
        </div>
        <div className="bg-black/20 rounded border border-white/5 p-2 flex flex-col gap-1.5">
          {planSteps.map(step => (
            <div key={step.id} className="flex items-center gap-2 text-[11px]">
              {step.status === 'done' ? (
                <CheckCircle2 className="w-3.5 h-3.5 text-green-500" />
              ) : step.status === 'running' ? (
                <div className="w-3.5 h-3.5 rounded-full border-2 border-primary border-t-transparent animate-spin" />
              ) : (
                <Circle className="w-3.5 h-3.5 text-white/20" />
              )}
              <span className={step.status === 'done' ? 'text-white/40 line-through' : 'text-white/80'}>
                {step.title}
              </span>
            </div>
          ))}
        </div>
      </div>

      {/* 🧠 사고 흐름 (Thought Stream) 섹션 */}
      <div className="flex flex-col flex-1 gap-2 overflow-hidden">
        <div className="flex items-center gap-2 text-[11px] font-bold text-cyan-400 uppercase tracking-tighter">
          <Brain className="w-3.5 h-3.5" /> AI Thought Stream
        </div>
        <div className="flex-1 bg-black/40 rounded border border-white/5 p-2 font-mono text-[10px] overflow-y-auto custom-scrollbar flex flex-col gap-2">
          {thoughts.map(thought => (
            <div key={thought.id} className="flex flex-col gap-0.5 border-l border-white/10 pl-2">
              <div className="flex items-center gap-2">
                <span className="text-white/30">[{thought.time}]</span>
                <span className="text-primary font-bold">{thought.agent}</span>
              </div>
              <div className="text-white/70 leading-relaxed whitespace-pre-wrap">
                {thought.text}
              </div>
            </div>
          ))}
          <div ref={thoughtEndRef} />
        </div>
      </div>

      {/* 🛠️ 작업 도구 상태 */}
      <div className="bg-primary/10 rounded border border-primary/20 p-2 shrink-0">
        <div className="flex items-center justify-between text-[10px]">
          <span className="text-white/60">Active Skill:</span>
          <span className="text-primary font-bold uppercase tracking-widest">Brainstorming</span>
        </div>
      </div>
    </div>
  );
}
