/**
 * ------------------------------------------------------------------------
 * 📄 파일명: FileExplorer.tsx
 * 📝 설명: 파일 탐색기 사이드바 패널 컴포넌트.
 *          트리 뷰 / 플랫 뷰 전환, 드라이브 선택, 최근 프로젝트 드롭다운,
 *          파일/폴더 생성·이름변경·삭제, 경로 복사, 컨텍스트 메뉴 등을 포함합니다.
 *          모든 파일시스템 상태를 내부에서 관리하며, currentPath / onPathChange /
 *          onOpenFile 세 가지 인터페이스로 App.tsx와 연결됩니다.
 * REVISION HISTORY:
 * - 2026-03-01 Claude: App.tsx에서 독립 컴포넌트로 분리.
 *                      파일시스템 관련 상태(drives, items, treeMode 등) 내부 이동.
 * ------------------------------------------------------------------------
 */

import { useState, useEffect } from 'react';
import { ChevronLeft, Plus, Trash2, Edit3, ClipboardList } from 'lucide-react';
import { VscFolder, VscFolderOpened, VscNewFolder, VscFile, VscTrash } from 'react-icons/vsc';
import { API_BASE, TreeItem, getFileIcon } from '../constants';
import FileTreeNode from './FileTreeNode';

interface FileExplorerProps {
  // 현재 탐색 중인 경로 — App 레벨에서 관리 (GitPanel, TerminalSlot 등도 사용)
  currentPath: string;
  // 경로 변경 시 App에 알림 (폴더 이동 / 드라이브 전환)
  onPathChange: (path: string) => void;
  // 파일 클릭 시 FloatingWindow 열기 요청 (App에서 openFiles 상태 관리)
  onOpenFile: (item: TreeItem) => void;
  // 외부에서 파일 목록 강제 새로고침 트리거 (헤더 새로고침 버튼용)
  refreshKey?: number;
}

export default function FileExplorer({ currentPath, onPathChange, onOpenFile, refreshKey = 0 }: FileExplorerProps) {

  // ─── 드라이브 / 디렉토리 목록 상태 ────────────────────────────────────
  const [drives, setDrives] = useState<string[]>([]);
  const [items, setItems] = useState<TreeItem[]>([]);
  const [recentProjects, setRecentProjects] = useState<string[]>([]);
  const [initialConfigLoaded, setInitialConfigLoaded] = useState(false);

  // ─── 트리 뷰 상태 ─────────────────────────────────────────────────────
  const [treeMode, setTreeMode] = useState(true);
  const [treeExpanded, setTreeExpanded] = useState<Record<string, boolean>>({});
  const [treeChildren, setTreeChildren] = useState<Record<string, TreeItem[]>>({});

  // ─── 선택 / 편집 상태 ─────────────────────────────────────────────────
  const [selectedPath, setSelectedPath] = useState<string | null>(null);
  const [editingPath, setEditingPath] = useState<string | null>(null);
  const [editValue, setEditValue] = useState('');

  // ─── 컨텍스트 메뉴 상태 ───────────────────────────────────────────────
  const [contextMenu, setContextMenu] = useState<{
    x: number; y: number; path: string; isDir: boolean
  } | null>(null);

  // 초기 설정 로드 (마지막 경로, 드라이브 목록, 최근 프로젝트)
  useEffect(() => {
    fetch(`${API_BASE}/api/drives`)
      .then(res => res.json())
      .then(data => setDrives(data))
      .catch(() => {});

    fetch(`${API_BASE}/api/projects`)
      .then(res => res.json())
      .then(data => { if (Array.isArray(data)) setRecentProjects(data); })
      .catch(() => {});

    fetch(`${API_BASE}/api/config`)
      .then(res => res.json())
      .then(data => {
        if (data.last_path) onPathChange(data.last_path);
        setInitialConfigLoaded(true);
      })
      .catch(() => setInitialConfigLoaded(true));
  }, []);

  // 경로 변경 시 config 저장 + 최근 프로젝트 목록 갱신 + 트리 초기화
  useEffect(() => {
    if (!initialConfigLoaded || !currentPath) return;

    // 마지막 경로 config에 저장
    fetch(`${API_BASE}/api/config/update`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ last_path: currentPath })
    }).catch(() => {});

    // 드라이브 루트가 아닌 실제 프로젝트 경로만 최근 목록에 저장
    const isDriveRoot = /^[A-Za-z]:\/+$/.test(currentPath);
    if (!isDriveRoot) {
      fetch(`${API_BASE}/api/projects`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ path: currentPath })
      })
        .then(res => res.json())
        .then(data => { if (Array.isArray(data.projects)) setRecentProjects(data.projects); })
        .catch(() => {});
    }

    // 경로 변경 시 트리 접힘 초기화
    setTreeExpanded({});
    setTreeChildren({});
  }, [currentPath, initialConfigLoaded]);

  // 현재 경로의 파일/폴더 목록 새로고침
  const refreshItems = () => {
    fetch(`${API_BASE}/api/files?path=${encodeURIComponent(currentPath || '')}`)
      .then(res => res.json())
      .then(data => setItems(Array.isArray(data) ? data : []))
      .catch(() => setItems([]));
  };

  // 특정 폴더 하위 트리 데이터 새로고침
  const refreshTree = (parentPath: string) => {
    fetch(`${API_BASE}/api/files?path=${encodeURIComponent(parentPath)}`)
      .then(res => res.json())
      .then(data => {
        if (Array.isArray(data)) setTreeChildren(prev => ({ ...prev, [parentPath]: data }));
      })
      .catch(() => {});
  };

  // currentPath 변경 또는 외부 refreshKey 증가 시 항목 목록 재요청
  useEffect(() => { refreshItems(); }, [currentPath, refreshKey]);

  // ─── 파일/폴더 조작 함수들 ────────────────────────────────────────────

  // 시스템 폴더 선택 대화상자 열기
  const openFolder = () => {
    fetch(`${API_BASE}/api/select-folder`, { method: 'POST' })
      .then(res => res.json())
      .then(data => { if (data.status === 'success' && data.path) onPathChange(data.path); })
      .catch(err => alert('폴더 선택 오류: ' + err));
  };

  // 상위 폴더로 이동
  const goUp = () => {
    const parts = currentPath.replace(/\\/g, '/').split('/').filter(Boolean);
    if (parts.length > 1) {
      parts.pop();
      let parentPath = parts.join('/');
      if (parts.length === 1 && parts[0].includes(':')) parentPath += '/';
      onPathChange(parentPath);
    }
  };

  // 트리 노드 열기/닫기 토글
  const handleTreeToggle = (path: string) => {
    if (treeExpanded[path]) {
      setTreeExpanded(prev => ({ ...prev, [path]: false }));
    } else {
      setTreeExpanded(prev => ({ ...prev, [path]: true }));
      if (!treeChildren[path]) {
        fetch(`${API_BASE}/api/files?path=${encodeURIComponent(path)}`)
          .then(res => res.json())
          .then(data => {
            if (Array.isArray(data)) setTreeChildren(prev => ({ ...prev, [path]: data }));
          })
          .catch(() => {});
      }
    }
  };

  // 파일 클릭 — 폴더면 경로 이동, 파일이면 FloatingWindow 열기
  const handleFileClick = (item: TreeItem) => {
    setSelectedPath(item.path);
    if (item.isDir) {
      onPathChange(item.path);
    } else {
      onOpenFile(item);
    }
  };

  // 파일 생성
  const createFile = (parentPath: string) => {
    const name = prompt('새 파일 이름:');
    if (!name) return;
    fetch(`${API_BASE}/api/files/create`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ path: `${parentPath}/${name}`, is_dir: false })
    }).then(() => refreshTree(parentPath));
  };

  // 폴더 생성
  const createFolder = (parentPath: string) => {
    const name = prompt('새 폴더 이름:');
    if (!name) return;
    fetch(`${API_BASE}/api/files/create`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ path: `${parentPath}/${name}`, is_dir: true })
    }).then(() => refreshTree(parentPath));
  };

  // 파일/폴더 삭제
  const deleteFile = (path: string, isDir: boolean) => {
    if (!confirm(`${isDir ? '폴더' : '파일'}을(를) 삭제하시겠습니까?\n${path}`)) return;
    const parentPath = path.split(/[\\\/]/).slice(0, -1).join('/');
    fetch(`${API_BASE}/api/files/delete`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ path })
    }).then(() => {
      if (parentPath) refreshTree(parentPath);
      else refreshItems();
    });
  };

  // 파일/폴더 이름 변경
  const renameFile = (src: string, dest: string): Promise<boolean> => {
    return fetch(`${API_BASE}/api/file-rename`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ src, dest })
    })
      .then(res => res.json())
      .then(data => {
        if (data.status === 'success') {
          const parentPath = src.split(/[\\\/]/).slice(0, -1).join('/');
          if (parentPath) refreshTree(parentPath);
          else refreshItems();
          return true;
        } else {
          alert('이름 변경 오류: ' + data.message);
          return false;
        }
      })
      .catch(err => { alert('이름 변경 오류: ' + err); return false; });
  };

  return (
    <>
      {/* 드라이브 선택 + 트리/플랫 토글 */}
      <div className="flex items-center gap-1 mb-2">
        <button
          onClick={openFolder}
          className="p-1.5 bg-[#3c3c3c] border border-white/5 hover:border-white/20 rounded text-[#dcb67a] transition-all shrink-0"
          title="프로젝트 폴더 열기"
        >
          <VscFolderOpened className="w-4 h-4" />
        </button>
        {/* 최근 프로젝트 + 드라이브 드롭다운 */}
        <select
          value={
            recentProjects.find(p => currentPath === p || currentPath.startsWith(p + '/') || currentPath.startsWith(p + '\\'))
              || drives.find(d => currentPath.startsWith(d))
              || currentPath
          }
          onChange={(e) => onPathChange(e.target.value)}
          className="flex-1 bg-[#3c3c3c] border border-white/5 hover:border-white/20 rounded px-2 py-1.5 text-xs focus:outline-none transition-all cursor-pointer"
        >
          {recentProjects.length > 0 && (
            <optgroup label="📁 최근 프로젝트">
              {recentProjects.map(p => (
                <option key={p} value={p}>
                  {p.split(/[\\\/]/).filter(Boolean).pop() || p} — {p}
                </option>
              ))}
            </optgroup>
          )}
          <optgroup label="💾 드라이브">
            {drives.map(drive => <option key={drive} value={drive}>{drive}</option>)}
          </optgroup>
        </select>
        {/* 트리 ↔ 플랫 뷰 토글 버튼 */}
        <button
          onClick={() => setTreeMode(v => !v)}
          className={`p-1.5 rounded border text-[10px] font-bold transition-all shrink-0 ${treeMode ? 'bg-primary/20 border-primary/40 text-primary' : 'bg-[#3c3c3c] border-white/10 text-[#858585] hover:text-white'}`}
          title={treeMode ? '플랫 뷰로 전환' : '트리 뷰로 전환'}
        >
          {treeMode ? '≡' : '⊞'}
        </button>
      </div>

      {/* 파일 목록 컨테이너 — 상하/좌우 스크롤 허용 */}
      <div className="flex-1 overflow-auto custom-scrollbar border-t border-white/5 pt-2">
        {/* min-w-max: 파일명이 길면 가로 확장 */}
        <div className="min-w-max space-y-0.5">
          {/* 상위 폴더 이동 버튼 */}
          <button
            onClick={goUp}
            className="w-full flex items-center gap-2 px-2 py-1 hover:bg-[#2a2d2e] rounded text-xs transition-colors group"
          >
            <ChevronLeft className="w-4 h-4 text-[#3794ef] group-hover:-translate-x-1 transition-transform" /> ..
          </button>

          {treeMode ? (
            /* ── 트리 뷰 ── */
            items.length > 0 ? (
              items.map(item => (
                <FileTreeNode
                  key={item.path}
                  item={item}
                  depth={0}
                  expanded={treeExpanded}
                  treeChildren={treeChildren}
                  onToggle={handleTreeToggle}
                  onFileOpen={handleFileClick}
                  onContextMenu={(e, it) => setContextMenu({ x: e.clientX, y: e.clientY, path: it.path, isDir: it.isDir })}
                  onRename={renameFile}
                  onDelete={deleteFile}
                  onCreateFile={createFile}
                  onCreateFolder={createFolder}
                  editingPath={editingPath}
                  setEditingPath={setEditingPath}
                  editValue={editValue}
                  setEditValue={setEditValue}
                />
              ))
            ) : (
              <div className="py-10 text-center text-[10px] text-[#858585] italic animate-pulse">
                파일을 불러오는 중이거나 폴더가 비어 있습니다.
              </div>
            )
          ) : (
            /* ── 플랫 뷰 ── */
            items.length > 0 ? (
              items.map(item => (
                <div
                  key={item.path}
                  className={`group flex items-center gap-0 px-2 py-0.5 rounded text-xs transition-colors relative ${selectedPath === item.path ? 'bg-primary/20 border-l-2 border-primary' : 'hover:bg-[#2a2d2e]'}`}
                >
                  <button
                    onClick={() => handleFileClick(item)}
                    onContextMenu={(e) => {
                      e.preventDefault();
                      setContextMenu({ x: e.clientX, y: e.clientY, path: item.path, isDir: item.isDir });
                    }}
                    className={`flex items-center gap-2 py-1 ${item.isDir ? 'text-[#cccccc]' : 'text-[#ffffff] font-medium'}`}
                  >
                    {item.isDir
                      ? <VscFolder className="w-4 h-4 text-[#dcb67a] shrink-0" />
                      : getFileIcon(item.name)}
                    {editingPath === item.path ? (
                      <input
                        autoFocus
                        value={editValue}
                        onChange={e => setEditValue(e.target.value)}
                        onKeyDown={async e => {
                          if (e.key === 'Enter') {
                            if (editValue && editValue !== item.name) {
                              const parentPath = item.path.split(/[\\\/]/).slice(0, -1).join('/');
                              const dest = parentPath ? `${parentPath}/${editValue}` : editValue;
                              await renameFile(item.path, dest);
                            }
                            setEditingPath(null);
                          }
                          if (e.key === 'Escape') setEditingPath(null);
                        }}
                        onBlur={async () => {
                          if (editValue && editValue !== item.name) {
                            const parentPath = item.path.split(/[\\\/]/).slice(0, -1).join('/');
                            const dest = parentPath ? `${parentPath}/${editValue}` : editValue;
                            await renameFile(item.path, dest);
                          }
                          setEditingPath(null);
                        }}
                        onClick={e => e.stopPropagation()}
                        className="flex-1 bg-[#1e1e1e] border border-primary outline-none px-1 text-xs text-white rounded"
                      />
                    ) : (
                      <span className="whitespace-nowrap">{item.name}</span>
                    )}
                  </button>

                  {/* 호버 액션 버튼 그룹 */}
                  {editingPath !== item.path && (
                    <div className="opacity-0 group-hover:opacity-100 flex items-center gap-0.5 ml-auto shrink-0 pr-1 transition-all">
                      {item.isDir && (
                        <>
                          <button onClick={(e) => { e.stopPropagation(); createFile(item.path); }} className="p-1 hover:bg-white/10 rounded text-[#858585] hover:text-white" title="새 파일">
                            <Plus className="w-3 h-3" />
                          </button>
                          <button onClick={(e) => { e.stopPropagation(); createFolder(item.path); }} className="p-1 hover:bg-white/10 rounded text-[#858585] hover:text-white" title="새 폴더">
                            <VscNewFolder className="w-3 h-3" />
                          </button>
                        </>
                      )}
                      {/* 경로 복사 버튼 */}
                      <button
                        onClick={(e) => {
                          e.stopPropagation();
                          fetch(`${API_BASE}/api/copy-path?path=${encodeURIComponent(item.path)}`)
                            .then(res => res.json())
                            .then(data => {
                              if (data.status === 'success') {
                                const btn = e.currentTarget;
                                const originalHtml = btn.innerHTML;
                                btn.innerHTML = '<span class="text-[8px] text-green-400">Copied!</span>';
                                setTimeout(() => btn.innerHTML = originalHtml, 1500);
                              }
                            });
                        }}
                        className="p-1 hover:bg-white/10 rounded text-[#858585] hover:text-primary transition-all"
                        title="경로 복사"
                      >
                        <ClipboardList className="w-3 h-3" />
                      </button>
                      {/* 이름 변경 버튼 */}
                      <button
                        onClick={(e) => { e.stopPropagation(); setEditingPath(item.path); setEditValue(item.name); }}
                        className="p-1 hover:bg-white/10 rounded text-[#858585] hover:text-primary transition-all"
                        title="이름 변경"
                      >
                        <Edit3 className="w-3 h-3" />
                      </button>
                      {/* 삭제 버튼 */}
                      <button
                        onClick={(e) => { e.stopPropagation(); deleteFile(item.path, item.isDir); }}
                        className="p-1 hover:bg-red-500/20 rounded text-[#858585] hover:text-red-400 transition-all"
                        title="삭제"
                      >
                        <Trash2 className="w-3 h-3" />
                      </button>
                    </div>
                  )}
                </div>
              ))
            ) : (
              <div className="py-10 text-center text-[10px] text-[#858585] italic">
                표시할 파일이 없습니다.
              </div>
            )
          )}
        </div>
      </div>

      {/* ── 컨텍스트 메뉴 — portal 없이 position:fixed로 표시 ── */}
      {contextMenu && (
        <div
          className="fixed z-[9999] bg-[#252526] border border-white/10 rounded shadow-2xl py-1 min-w-[150px] animate-in fade-in zoom-in duration-100"
          style={{ left: contextMenu.x, top: contextMenu.y }}
          onClick={() => setContextMenu(null)}
        >
          {contextMenu.isDir && (
            <>
              <button onClick={() => { createFile(contextMenu.path); setContextMenu(null); }} className="w-full text-left px-3 py-1.5 text-xs text-[#cccccc] hover:bg-primary hover:text-white transition-colors flex items-center gap-2">
                <VscFile className="w-3.5 h-3.5" /> 새 파일...
              </button>
              <button onClick={() => { createFolder(contextMenu.path); setContextMenu(null); }} className="w-full text-left px-3 py-1.5 text-xs text-[#cccccc] hover:bg-primary hover:text-white transition-colors flex items-center gap-2">
                <VscFolder className="w-3.5 h-3.5" /> 새 폴더...
              </button>
              <div className="h-[1px] bg-white/5 my-1" />
            </>
          )}
          <button
            onClick={() => { fetch(`${API_BASE}/api/copy-path?path=${encodeURIComponent(contextMenu.path)}`); setContextMenu(null); }}
            className="w-full text-left px-3 py-1.5 text-xs text-[#cccccc] hover:bg-primary hover:text-white transition-colors flex items-center gap-2"
          >
            <ClipboardList className="w-3.5 h-3.5" /> 경로 복사
          </button>
          <button
            onClick={() => { setEditingPath(contextMenu.path); setEditValue(contextMenu.path.split(/[\\\/]/).pop() || ''); setContextMenu(null); }}
            className="w-full text-left px-3 py-1.5 text-xs text-[#cccccc] hover:bg-primary hover:text-white transition-colors flex items-center gap-2"
          >
            <Edit3 className="w-3.5 h-3.5" /> 이름 변경...
          </button>
          <div className="h-[1px] bg-white/5 my-1" />
          <button onClick={() => { deleteFile(contextMenu.path, contextMenu.isDir); setContextMenu(null); }} className="w-full text-left px-3 py-1.5 text-xs text-red-400 hover:bg-red-500/20 transition-colors flex items-center gap-2">
            <VscTrash className="w-3.5 h-3.5" /> 삭제
          </button>
          <button onClick={() => setContextMenu(null)} className="w-full text-left px-3 py-1.5 text-xs text-[#858585] hover:bg-white/5 transition-colors">
            취소
          </button>
        </div>
      )}
    </>
  );
}
