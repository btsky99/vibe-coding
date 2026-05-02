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

import { memo, useState, useRef, useEffect } from 'react';
import {
  Menu, Terminal, RotateCw, Monitor,
  X, Zap, Cpu, Info, ShieldCheck,
  Trash2, LayoutDashboard, ClipboardCheck, FileText, Copy, Check, RefreshCw,
  Settings, Wrench, Database, Shield, BookOpen, FileCode
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
  onOpenHelpDoc: (topic: string, title: string) => void;
  onClearLogs: () => void;
  // 프로젝트 전환 시 App의 currentPath 업데이트
  currentPath?: string;
  onSwitchProject?: (path: string) => void;
}

// ── 서버 로그 뷰어 모달 — 서버/PG/태스크 로그를 탭으로 전환하며 확인 + 클립보드 복사 ──
function LogViewerModal({ isOpen, onClose }: { isOpen: boolean; onClose: () => void }) {
  const [logType, setLogType] = useState<'server' | 'pgsql' | 'task'>('server');
  const [lines, setLines] = useState<string[]>([]);
  const [logPath, setLogPath] = useState('');
  const [copied, setCopied] = useState(false);
  const [loading, setLoading] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);

  const fetchLogs = () => {
    setLoading(true);
    fetch(`${API_BASE}/api/server-logs?type=${logType}&lines=300`)
      .then(r => r.json())
      .then(d => {
        setLines(d.lines || []);
        setLogPath(d.path || '');
        // 스크롤을 맨 아래로 이동 (최신 로그 확인)
        setTimeout(() => bottomRef.current?.scrollIntoView({ behavior: 'smooth' }), 100);
      })
      .catch(() => setLines(['(로그 로드 실패)']))
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    if (isOpen) fetchLogs();
  }, [isOpen, logType]);

  // 5초 자동 갱신
  useEffect(() => {
    if (!isOpen) return;
    const iv = setInterval(fetchLogs, 5000);
    return () => clearInterval(iv);
  }, [isOpen, logType]);

  const handleCopy = () => {
    navigator.clipboard.writeText(lines.join('\n')).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    });
  };

  if (!isOpen) return null;

  const tabs: { key: 'server' | 'pgsql' | 'task'; label: string }[] = [
    { key: 'server', label: '서버 로그' },
    { key: 'pgsql', label: 'PostgreSQL' },
    { key: 'task', label: '태스크 로그' },
  ];

  return (
    <div className="fixed inset-0 z-[9999] flex items-center justify-center bg-black/50 backdrop-blur-sm">
      <div className="w-[85vw] max-w-[1200px] h-[75vh] bg-[#1e1e1e] border border-white/10 rounded-xl shadow-2xl flex flex-col overflow-hidden">
        {/* 헤더 */}
        <div className="h-10 bg-[#252526] border-b border-white/5 flex items-center justify-between px-4 shrink-0">
          <div className="flex items-center gap-2 text-sm font-semibold text-white/80">
            <FileText className="w-4 h-4 text-primary" />
            서버 로그 뷰어
            {logPath && <span className="text-[10px] text-white/30 font-mono ml-2">{logPath}</span>}
          </div>
          <div className="flex items-center gap-1">
            <button onClick={fetchLogs} className="p-1.5 hover:bg-white/10 rounded text-white/40 hover:text-white/80" title="새로고침">
              <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} />
            </button>
            <button onClick={handleCopy} className="p-1.5 hover:bg-white/10 rounded text-white/40 hover:text-green-400 flex items-center gap-1" title="전체 복사">
              {copied ? <Check className="w-3.5 h-3.5 text-green-400" /> : <Copy className="w-3.5 h-3.5" />}
              <span className="text-[10px]">{copied ? '복사됨!' : '복사'}</span>
            </button>
            <div className="w-px h-4 bg-white/10 mx-1" />
            <button onClick={onClose} className="p-1.5 hover:bg-red-500/20 rounded text-white/40 hover:text-red-400">
              <X className="w-4 h-4" />
            </button>
          </div>
        </div>
        {/* 탭 바 */}
        <div className="flex border-b border-white/5 bg-[#2d2d2d] px-2 gap-0.5">
          {tabs.map(tab => (
            <button
              key={tab.key}
              onClick={() => setLogType(tab.key)}
              className={`px-3 py-1.5 text-xs font-medium transition-colors rounded-t ${
                logType === tab.key
                  ? 'bg-[#1e1e1e] text-primary border-t-2 border-primary'
                  : 'text-white/40 hover:text-white/70 hover:bg-white/5'
              }`}
            >
              {tab.label}
            </button>
          ))}
          <span className="ml-auto text-[10px] text-white/20 self-center">{lines.length}줄 | 5초 자동 갱신</span>
        </div>
        {/* 로그 내용 */}
        <div className="flex-1 overflow-auto p-3 font-mono text-[11px] leading-relaxed custom-scrollbar">
          {lines.length === 0 ? (
            <div className="text-white/20 text-center py-10">로그가 비어있습니다</div>
          ) : (
            lines.map((line, i) => (
              <div
                key={i}
                className={`px-2 py-0.5 rounded hover:bg-white/5 whitespace-pre-wrap break-all ${
                  line.includes('ERROR') || line.includes('error') || line.includes('FATAL')
                    ? 'text-red-400 bg-red-500/5'
                    : line.includes('WARNING') || line.includes('warning')
                    ? 'text-yellow-400'
                    : line.includes('INFO') || line.includes('info')
                    ? 'text-white/60'
                    : 'text-white/40'
                }`}
              >
                <span className="text-white/15 mr-2 select-none">{(i + 1).toString().padStart(4)}</span>
                {line}
              </div>
            ))
          )}
          <div ref={bottomRef} />
        </div>
      </div>
    </div>
  );
}

// 상단 메뉴 바 — 메뉴가 닫힌 상태에서 다른 상태 변경 시 리렌더 방지
const TopMenuBar = memo(function TopMenuBar({
  activeMenu, setActiveMenu,
  isSidebarOpen, setIsSidebarOpen,
  setLayoutMode,
  appVersion,
  updateReady, updateApplying, updateChecking,
  onApplyUpdate, onTriggerUpdateCheck,
  onOpenFolder, onInstallSkills, onOpenHelpDoc, onClearLogs,
  currentPath: propCurrentPath,
  onSwitchProject,
}: TopMenuBarProps) {
  const [isLogViewerOpen, setIsLogViewerOpen] = useState(false);

  // ── 프로젝트 스위칭 상태 ──────────────────────────────────────────────
  const [projects, setProjects] = useState<Record<string, string>>({});
  const [currentPath, setCurrentPath] = useState('');

  useEffect(() => {
    fetch(`${API_BASE}/api/config`)
      .then(r => r.json())
      .then(cfg => {
        setProjects(cfg.projects || {});
        setCurrentPath(propCurrentPath || cfg.last_path || cfg.path || '');
      })
      .catch(() => {});
  }, [propCurrentPath]);

  const switchProject = (_name: string, path: string) => {
    fetch(`${API_BASE}/api/config/update`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ last_path: path }),
    })
      .then(() => {
        setCurrentPath(path);
        // App의 currentPath도 업데이트 (파일 탐색기 연동)
        if (onSwitchProject) onSwitchProject(path);
      })
      .catch(() => {});
  };

  // 메뉴 항목 목록 — 순서가 곧 표시 순서
  const menus = ['파일', '편집', '보기', 'AI 도구', '도움말', '프로젝트 세팅'];

  // 프로젝트 세팅 프롬프트 목록 (도움말 옆 별도 메뉴)
  const [setupPrompts, setSetupPrompts] = useState<{id: string; agent: string; category: string; description: string; prompt: string}[]>([]);
  const [copiedPromptId, setCopiedPromptId] = useState<string | null>(null);
  const [vaultDir, setVaultDir] = useState('');
  const [vaultSaved, setVaultSaved] = useState(false);

  useEffect(() => {
    if (activeMenu === '프로젝트 세팅') {
      if (setupPrompts.length === 0) {
        fetch(`${API_BASE}/api/tools/rule-prompts`)
          .then(r => r.json())
          .then(d => setSetupPrompts(d.prompts || []))
          .catch(() => {});
      }
      fetch(`${API_BASE}/api/config`)
        .then(r => r.json())
        .then(d => setVaultDir(d.vault_dir || ''))
        .catch(() => {});
    }
  }, [activeMenu]);

  const handleBrowseVault = () => {
    fetch(`${API_BASE}/api/browse-folder`)
      .then(r => r.json())
      .then(d => {
        if (d.path) {
          setVaultDir(d.path);
          fetch(`${API_BASE}/api/config/update`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ vault_dir: d.path }),
          }).then(() => {
            setVaultSaved(true);
            setTimeout(() => setVaultSaved(false), 2000);
          });
        }
      })
      .catch(() => {});
  };

  const handleCopyPrompt = (id: string, prompt: string) => {
    navigator.clipboard.writeText(prompt).then(() => {
      setCopiedPromptId(id);
      setTimeout(() => setCopiedPromptId(null), 2000);
    });
  };

  // 카테고리별 아이콘 매핑
  const promptIcon = (id: string) => {
    if (id === 'dev-tools') return <Wrench className="w-3.5 h-3.5 text-[#e8a87c]" />;
    if (id === 'db-hive') return <Database className="w-3.5 h-3.5 text-accent" />;
    if (id === 'harness') return <Shield className="w-3.5 h-3.5 text-primary" />;
    if (id === 'zettelkasten') return <BookOpen className="w-3.5 h-3.5 text-success" />;
    return <FileCode className="w-3.5 h-3.5 text-white/50" />;
  };

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
            <div className="absolute top-full left-0 w-48 max-h-[80vh] overflow-y-auto bg-[#252526] border border-black/40 shadow-2xl rounded-b z-[100] py-1 animate-in fade-in slide-in-from-top-1 custom-scrollbar">
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
              <div className="h-px bg-white/5 my-1 mx-2"></div>
              <div className="px-3 py-1 text-[10px] text-textMuted font-bold uppercase tracking-wider opacity-60">진단</div>
              <button
                onClick={() => { setIsLogViewerOpen(true); setActiveMenu(null); }}
                className="w-full text-left px-4 py-1.5 hover:bg-white/10 flex items-center gap-2"
              >
                <FileText className="w-3.5 h-3.5 text-[#e8a87c]" /> 서버 로그 보기
              </button>
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
              <div className="px-3 py-1 text-[10px] text-textMuted font-bold uppercase tracking-wider opacity-60">스킬 관리</div>
              <button
                onClick={() => {
                  fetch(`${API_BASE}/api/eval-review/launch`, { method: 'POST' })
                    .then(r => r.json())
                    .then(d => { if (d.status === 'error') alert(d.message); })
                    .catch(err => console.error('[TopMenuBar] eval-review launch error:', err));
                  setActiveMenu(null);
                }}
                className="w-full text-left px-4 py-1.5 hover:bg-primary/20 flex items-center gap-2"
              >
                <ClipboardCheck className="w-3.5 h-3.5 text-[#a78bfa]" />
                <span>스킬 평가 리뷰어 열기</span>
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
              <button
                onClick={() => onOpenHelpDoc('codex', '코덱스(Codex) 사용 설명서')}
                className="w-full text-left px-4 py-1.5 hover:bg-white/10 flex items-center gap-2"
              >
                <Zap className="w-3.5 h-3.5 text-yellow-400" /> 코덱스(Codex) 사용법
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

          {/* ── 프로젝트 세팅 메뉴 (도움말 옆) ── */}
          {activeMenu === menu && menu === '프로젝트 세팅' && (
            <div className="absolute top-full left-0 w-80 bg-[#252526] border border-black/40 shadow-2xl rounded-b z-[100] py-1 animate-in fade-in slide-in-from-top-1">
              <div className="px-3 py-1 text-[10px] text-textMuted font-bold uppercase tracking-wider opacity-60">환경 설치 프롬프트</div>
              <div className="px-3 py-1.5 text-[10px] text-white/30">클릭하면 프롬프트가 클립보드에 복사됩니다. AI 에이전트에 붙여넣기 하세요.</div>
              <div className="h-px bg-white/5 my-1 mx-2"></div>
              {setupPrompts.filter(p => p.category === 'setup').map(p => (
                <button
                  key={p.id}
                  onClick={() => { handleCopyPrompt(p.id, p.prompt); }}
                  className="w-full text-left px-4 py-2 hover:bg-primary/10 flex items-center gap-2.5 group"
                >
                  {promptIcon(p.id)}
                  <div className="flex-1 min-w-0">
                    <div className="text-[11px] text-white/80 group-hover:text-white truncate">{p.description}</div>
                    <div className="text-[9px] text-white/30">{p.agent}</div>
                  </div>
                  {copiedPromptId === p.id
                    ? <Check className="w-3.5 h-3.5 text-green-400 shrink-0" />
                    : <Copy className="w-3 h-3 text-white/20 group-hover:text-white/50 shrink-0" />}
                </button>
              ))}
              {setupPrompts.filter(p => p.category === 'rules').length > 0 && (
                <>
                  <div className="h-px bg-white/5 my-1 mx-2"></div>
                  <div className="px-3 py-1 text-[10px] text-textMuted font-bold uppercase tracking-wider opacity-60">규칙 파일 생성</div>
                  {setupPrompts.filter(p => p.category === 'rules').map(p => (
                    <button
                      key={p.id}
                      onClick={() => { handleCopyPrompt(p.id, p.prompt); }}
                      className="w-full text-left px-4 py-2 hover:bg-primary/10 flex items-center gap-2.5 group"
                    >
                      {promptIcon(p.id)}
                      <div className="flex-1 min-w-0">
                        <div className="text-[11px] text-white/80 group-hover:text-white truncate">{p.description}</div>
                        <div className="text-[9px] text-white/30">{p.agent}</div>
                      </div>
                      {copiedPromptId === p.id
                        ? <Check className="w-3.5 h-3.5 text-green-400 shrink-0" />
                        : <Copy className="w-3 h-3 text-white/20 group-hover:text-white/50 shrink-0" />}
                    </button>
                  ))}
                </>
              )}
              {setupPrompts.length === 0 && (
                <div className="px-4 py-3 text-[11px] text-white/30 text-center">프롬프트 로딩 중...</div>
              )}
              {/* ── 옵시디언 Vault 경로 설정 ── */}
              <div className="h-px bg-white/5 my-1 mx-2"></div>
              <div className="px-3 py-1 text-[10px] text-textMuted font-bold uppercase tracking-wider opacity-60">옵시디언 Vault 경로</div>
              <div className="px-3 py-2 flex items-center gap-2">
                <div className="flex-1 min-w-0 bg-[#1e1e1e] rounded px-2 py-1 text-[10px] text-white/60 truncate border border-white/10" title={vaultDir}>
                  {vaultDir || '(기본 경로)'}
                </div>
                <button
                  onClick={handleBrowseVault}
                  className="shrink-0 px-2 py-1 text-[10px] rounded bg-primary/20 text-primary hover:bg-primary/30 transition-colors flex items-center gap-1"
                >
                  <VscFolderOpened className="w-3 h-3" />
                  변경
                </button>
                {vaultSaved && <Check className="w-3.5 h-3.5 text-green-400 shrink-0" />}
              </div>
            </div>
          )}
        </div>
      ))}

      {/* ── 우측 — 업데이트 버튼 + 버전 배지 ── */}
      <div className="ml-auto flex items-center gap-2 text-[11px] text-[#969696] px-2 font-mono overflow-hidden">
        {/* 📂 프로젝트 탭 — 항상 표시 (Phase 2-5.1) */}
        {Object.keys(projects).length > 1 && (
          <div className="flex items-center gap-1 shrink-0">
            {Object.entries(projects).map(([name, path]) => {
              const isCurrent = path.replace(/\\/g, '/') === currentPath.replace(/\\/g, '/');
              return (
                <button
                  key={name}
                  onClick={() => !isCurrent && switchProject(name, path)}
                  className={`flex items-center gap-1.5 px-2 py-0.5 rounded border transition-all ${
                    isCurrent
                      ? 'bg-primary/15 border-primary/40 text-primary cursor-default'
                      : 'bg-white/5 border-white/10 text-white/50 hover:text-white/80 hover:border-white/30'
                  }`}
                  title={path}
                >
                  <VscFolderOpened className="w-3.5 h-3.5 shrink-0" />
                  <span className="text-[9px] font-bold max-w-[100px] truncate">{name}</span>
                </button>
              );
            })}
          </div>
        )}

        {/* 중앙 통제실 버튼 제거 — 사용자 요청 (2026-04-16) */}

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

      {/* 로그 뷰어 모달 — 보기 메뉴에서 열림 */}
      <LogViewerModal isOpen={isLogViewerOpen} onClose={() => setIsLogViewerOpen(false)} />
    </div>
  );
});

export default TopMenuBar;
