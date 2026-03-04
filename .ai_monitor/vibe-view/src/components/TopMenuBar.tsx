/**
 * ------------------------------------------------------------------------
 * 📄 파일명: TopMenuBar.tsx
 * 📝 설명: VS Code 스타일 상단 메뉴바 컴포넌트.
 *          파일 / 편집 / 보기 / AI 도구 / 도움말 드롭다운 메뉴와
 *          업데이트 확인 버튼 및 버전 배지를 포함합니다.
 *          App.tsx에서 분리되어 단독 파일로 관리됩니다.
 * REVISION HISTORY:
 * - 2026-03-01 Claude: App.tsx에서 독립 컴포넌트로 분리.
 * ------------------------------------------------------------------------
 */

import {
  Menu, Terminal, RotateCw,
  X, Zap, Cpu, Info,
  Trash2, LayoutDashboard
} from 'lucide-react';
import { API_BASE } from '../constants';
import { VscFolderOpened } from 'react-icons/vsc';

// 레이아웃 모드 타입 — App.tsx와 동일하게 유지
type LayoutMode = '1' | '2' | '3' | '4' | '2x2' | '6' | '8';

interface TopMenuBarProps {
  // 메뉴 열림 상태 — 루트 div 클릭으로 닫기 위해 App에서 관리
  activeMenu: string | null;
  setActiveMenu: (menu: string | null) => void;
  // 사이드바 / 레이아웃
  isSidebarOpen: boolean;
  setIsSidebarOpen: (open: boolean) => void;
  // layoutMode는 보기 메뉴에서 선택만 가능 (현재 모드 표시 없음)
  setLayoutMode: (mode: LayoutMode) => void;
  // 앱 버전 및 업데이트 상태
  appVersion: string;
  updateReady: { version: string } | null;
  updateApplying: boolean;
  updateChecking: boolean;
  onApplyUpdate: () => void;
  onTriggerUpdateCheck: () => void;
  // 파일 / 도구 작업 콜백
  onOpenFolder: () => void;
  onInstallSkills: () => void;
  onInstallTool: (tool: string) => void;
  onOpenHelpDoc: (topic: string, title: string) => void;
  onClearLogs: () => void;
  // 자율 주행 버튼 → 중앙 통제실(mission-control) 탭으로 이동
  onOpenMissionControl: () => void;
}

export default function TopMenuBar({
  activeMenu, setActiveMenu,
  isSidebarOpen, setIsSidebarOpen,
  setLayoutMode,
  appVersion,
  updateReady, updateApplying, updateChecking,
  onApplyUpdate, onTriggerUpdateCheck,
  onOpenFolder, onInstallSkills, onInstallTool, onOpenHelpDoc, onClearLogs,
  onOpenMissionControl,
}: TopMenuBarProps) {

  // 메뉴 항목 목록 — 순서가 곧 표시 순서
  const menus = ['파일', '편집', '보기', 'AI 도구', '도움말'];

  return (
    <div className="h-7 bg-[#323233] flex items-center px-2 gap-0.5 text-[12px] border-b border-black/30 shrink-0 z-50 shadow-lg">
      {menus.map(menu => (
        <div key={menu} className="relative">
          {/* 메뉴 버튼 — 클릭 시 드롭다운 토글, 다른 메뉴가 열려 있을 때 호버만으로도 전환 */}
          <button
            onClick={(e) => { e.stopPropagation(); setActiveMenu(activeMenu === menu ? null : menu); }}
            onMouseEnter={() => activeMenu && setActiveMenu(menu)}
            className={`px-2 py-0.5 rounded transition-colors ${activeMenu === menu ? 'bg-[#444444] text-white' : 'hover:bg-white/10'}`}
          >
            {menu}
          </button>

          {/* ── 파일 메뉴 ── */}
          {activeMenu === menu && menu === '파일' && (
            <div className="absolute top-full left-0 w-48 bg-[#252526] border border-black/40 shadow-2xl rounded-b z-[100] py-1 animate-in fade-in slide-in-from-top-1">
              <button
                onClick={() => { onOpenFolder(); setActiveMenu(null); }}
                className="w-full text-left px-4 py-1.5 hover:bg-white/10 flex items-center gap-2"
              >
                <VscFolderOpened className="w-3.5 h-3.5 text-[#dcb67a]" /> 폴더 열기...
              </button>
              <div className="h-px bg-white/5 my-1 mx-2"></div>
              <button
                onClick={() => {
                  if (confirm("시스템을 완전히 종료하시겠습니까? (백그라운드 서버도 종료됩니다)")) {
                    fetch(`${API_BASE}/api/shutdown`)
                      .then(() => { alert("서버가 종료되었습니다. 창을 닫아주세요."); window.close(); })
                      .catch(() => { alert("서버 종료 신호 전송 실패"); });
                  }
                  setActiveMenu(null);
                }}
                className="w-full text-left px-4 py-1.5 hover:bg-red-500/20 text-red-400 flex items-center gap-2"
              >
                <X className="w-3.5 h-3.5" /> 시스템 완전 종료
              </button>
            </div>
          )}

          {/* ── 편집 메뉴 ── */}
          {activeMenu === menu && menu === '편집' && (
            <div className="absolute top-full left-0 w-48 bg-[#252526] border border-black/40 shadow-2xl rounded-b z-[100] py-1 animate-in fade-in slide-in-from-top-1">
              <button
                onClick={() => { onClearLogs(); setActiveMenu(null); }}
                className="w-full text-left px-4 py-1.5 hover:bg-white/10 flex items-center gap-2"
              >
                <Trash2 className="w-3.5 h-3.5 text-[#e8a87c]" /> 로그 비우기
              </button>
            </div>
          )}

          {/* ── 보기 메뉴 — 사이드바 토글 + 레이아웃 선택 ── */}
          {activeMenu === menu && menu === '보기' && (
            <div className="absolute top-full left-0 w-48 bg-[#252526] border border-black/40 shadow-2xl rounded-b z-[100] py-1 animate-in fade-in slide-in-from-top-1">
              <button
                onClick={() => { setIsSidebarOpen(!isSidebarOpen); setActiveMenu(null); }}
                className="w-full text-left px-4 py-1.5 hover:bg-white/10 flex items-center gap-2"
              >
                <Menu className="w-3.5 h-3.5 text-[#3794ef]" /> 사이드바 {isSidebarOpen ? '숨기기' : '보이기'}
              </button>
              <div className="h-px bg-white/5 my-1 mx-2"></div>
              {/* 레이아웃 섹션 헤더 */}
              <div className="px-3 py-1 text-[10px] text-textMuted font-bold uppercase tracking-wider opacity-60">터미널 레이아웃</div>
              {(['1', '2', '3', '4', '2x2', '6', '8'] as const).map(mode => (
                <button
                  key={mode}
                  onClick={() => { setLayoutMode(mode); setActiveMenu(null); }}
                  className="w-full text-left px-4 py-1.5 hover:bg-white/10 flex items-center gap-2"
                >
                  <LayoutDashboard className="w-3.5 h-3.5 text-[#cccccc]" />
                  {mode === '1' ? '1 분할 뷰' : mode === '2' ? '2 분할 뷰' : mode === '3' ? '3 분할 뷰' :
                   mode === '4' ? '4 분할 (가로 4열)' : mode === '2x2' ? '4 분할 (2×2 격자)' :
                   mode === '6' ? '6 분할 (3×2 격자)' : '8 분할 (4×2 격자)'}
                </button>
              ))}
            </div>
          )}

          {/* ── AI 도구 메뉴 ── */}
          {activeMenu === menu && menu === 'AI 도구' && (
            <div className="absolute top-full left-0 w-64 bg-[#252526] border border-black/40 shadow-2xl rounded-b z-[100] py-1 animate-in fade-in slide-in-from-top-1">
              <div className="px-3 py-1 text-[10px] text-textMuted font-bold uppercase tracking-wider opacity-60">하이브 마인드 코어</div>
              <button
                onClick={onInstallSkills}
                className="w-full text-left px-4 py-1.5 hover:bg-primary/20 flex items-center justify-between group"
              >
                <div className="flex items-center gap-2">
                  <Zap className="w-3.5 h-3.5 text-primary" />
                  <span>하이브 스킬 설치 (현재 프로젝트)</span>
                </div>
                <span className="text-[9px] text-white/30 group-hover:text-white/60 font-mono italic">Recommended</span>
              </button>
              <div className="h-px bg-white/5 my-1 mx-2"></div>
              <div className="px-3 py-1 text-[10px] text-textMuted font-bold uppercase tracking-wider opacity-60">글로벌 CLI 도구</div>
              <button
                onClick={() => onInstallTool('gemini')}
                className="w-full text-left px-4 py-1.5 hover:bg-primary/20 flex items-center gap-2"
              >
                <Terminal className="w-3.5 h-3.5 text-accent" />
                <span>Gemini CLI 설치 (npm -g)</span>
              </button>
              <button
                onClick={() => onInstallTool('claude')}
                className="w-full text-left px-4 py-1.5 hover:bg-primary/20 flex items-center gap-2"
              >
                <Cpu className="w-3.5 h-3.5 text-success" />
                <span>Claude Code 설치 (npm -g)</span>
              </button>
              <div className="h-px bg-white/5 my-1 mx-2"></div>
              <button
                onClick={() => window.location.reload()}
                className="w-full text-left px-4 py-1.5 hover:bg-primary/20 flex items-center gap-2"
              >
                <RotateCw className="w-3.5 h-3.5 text-[#3794ef]" />
                <span>대시보드 새로고침</span>
              </button>
            </div>
          )}

          {/* ── 도움말 메뉴 ── */}
          {activeMenu === menu && menu === '도움말' && (
            <div className="absolute top-full left-0 w-56 bg-[#252526] border border-black/40 shadow-2xl rounded-b z-[100] py-1 animate-in fade-in slide-in-from-top-1">
              <div className="px-3 py-1 text-[10px] text-textMuted font-bold uppercase tracking-wider opacity-60">사용 설명서</div>
              <button
                onClick={() => onOpenHelpDoc('claude-code', 'Claude Code 사용 설명서')}
                className="w-full text-left px-4 py-1.5 hover:bg-white/10 flex items-center gap-2"
              >
                <Cpu className="w-3.5 h-3.5 text-success" /> Claude Code 사용법
              </button>
              <button
                onClick={() => onOpenHelpDoc('gemini-cli', 'Gemini CLI 사용 설명서')}
                className="w-full text-left px-4 py-1.5 hover:bg-white/10 flex items-center gap-2"
              >
                <Terminal className="w-3.5 h-3.5 text-accent" /> Gemini CLI 사용법
              </button>
              <div className="h-px bg-white/5 my-1 mx-2"></div>
              <button
                onClick={() => { alert("바이브 코딩(Vibe Coding)\n하이브 마인드 중앙 지휘소"); setActiveMenu(null); }}
                className="w-full text-left px-4 py-1.5 hover:bg-white/10 flex items-center gap-2"
              >
                <Info className="w-3.5 h-3.5 text-[#3794ef]" /> 버전 정보
              </button>
            </div>
          )}
        </div>
      ))}

      {/* ── 우측 — 업데이트 버튼 + 버전 배지 ── */}
      <div className="ml-auto flex items-center gap-2 text-[11px] text-[#969696] px-2 font-mono overflow-hidden">
        {/* 🧠 중앙 통제실(Mission Control) 탭으로 이동 — 자율 에이전트 + 오케스트레이터 통합 뷰 */}
        <button
          onClick={onOpenMissionControl}
          className="shrink-0 flex items-center gap-1.5 px-2 py-0.5 rounded border transition-all bg-white/5 border-white/10 text-white/40 hover:text-white/70 hover:border-white/30"
          title="중앙 통제실 열기 (자율 에이전트 + 오케스트레이터)"
        >
          <Cpu className="w-3.5 h-3.5" />
          <span className="text-[9px] font-black uppercase tracking-tighter">중앙 통제실</span>
        </button>

        {/* 업데이트 즉시 적용 버튼 — updateReady 상태일 때만 표시 */}
        {updateReady && (
          <button
            onClick={onApplyUpdate}
            disabled={updateApplying}
            className="shrink-0 text-[9px] font-bold px-2 py-0.5 rounded bg-primary text-white hover:bg-primary/80 disabled:opacity-50 transition-colors animate-pulse"
            title={`새 버전 ${updateReady.version} 업데이트 준비 완료`}
          >
            {updateApplying ? '적용 중...' : `↑ ${updateReady.version}`}
          </button>
        )}
        {/* 수동 업데이트 확인 버튼 */}
        <button
          onClick={onTriggerUpdateCheck}
          disabled={updateChecking || !!updateReady}
          className="shrink-0 text-[9px] px-1.5 py-0.5 rounded border border-white/10 text-white/40 hover:text-white/70 hover:border-white/30 disabled:opacity-30 transition-colors"
          title="업데이트 확인"
        >
          {updateChecking ? '확인 중...' : '업데이트 확인'}
        </button>
        {/* 버전 배지 — 서버 동적 로드 */}
        <span className="shrink-0 text-[9px] bg-primary/20 text-primary px-1.5 py-0.5 rounded border border-primary/30 font-mono">
          v{appVersion}
        </span>
      </div>

    </div>
  );
}
