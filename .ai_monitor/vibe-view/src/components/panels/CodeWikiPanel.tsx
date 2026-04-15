/**
 * FILE: components/panels/CodeWikiPanel.tsx
 * DESCRIPTION: LLM 위키 패널 — 파일 트리 + 마크다운 뷰어/편집기.
 *   코드 인텔리전스 Phase 3. 에이전트가 생성한 코드 위키를 조회/편집.
 * REVISION HISTORY:
 *   2026-04-15 — 초기 구현. 파일트리 + react-markdown 뷰어
 */
import { useState, useEffect, useCallback } from 'react';
import Markdown from 'react-markdown';
import remarkGfm from 'remark-gfm';

// ── 타입 ──
interface CodeProject {
  id: number;
  name: string;
  root_path: string;
}

interface TreeItem {
  path: string;
  type: 'file' | 'directory';
  has_wiki: boolean;
  wikis: { wiki_type: string; generated_at: string }[];
}

interface WikiEntry {
  id: number;
  project_id: number;
  file_path: string;
  title: string;
  content: string;
  source_hash: string;
  wiki_type: string;
  node_id: number | null;
  generated_at: string;
}

const API = '';

export default function CodeWikiPanel() {
  const [projects, setProjects] = useState<CodeProject[]>([]);
  const [selectedProject, setSelectedProject] = useState<number | null>(null);
  const [tree, setTree] = useState<TreeItem[]>([]);
  const [selectedPath, setSelectedPath] = useState<string>('');
  const [wiki, setWiki] = useState<WikiEntry | null>(null);
  const [editing, setEditing] = useState(false);
  const [editContent, setEditContent] = useState('');
  const [generating, setGenerating] = useState(false);
  const [generatingAll, setGeneratingAll] = useState(false);
  const [collapsedDirs, setCollapsedDirs] = useState<Set<string>>(new Set());
  const [totalFiles, setTotalFiles] = useState(0);

  // 프로젝트 목록
  useEffect(() => {
    fetch(`${API}/api/codegraph/projects`)
      .then(r => r.json())
      .then(setProjects)
      .catch(() => {});
  }, []);

  // 위키 트리 로드
  const loadTree = useCallback(() => {
    if (!selectedProject) return;
    fetch(`${API}/api/codegraph/wiki/tree?project_id=${selectedProject}`)
      .then(r => r.json())
      .then(data => {
        setTree(data.tree || []);
        setTotalFiles(data.total_files || 0);
      })
      .catch(() => {});
  }, [selectedProject]);

  useEffect(() => { loadTree(); }, [loadTree]);

  // 위키 조회
  const loadWiki = useCallback((filePath: string) => {
    if (!selectedProject) return;
    setSelectedPath(filePath);
    fetch(`${API}/api/codegraph/wiki?project_id=${selectedProject}&file_path=${encodeURIComponent(filePath)}&wiki_type=file`)
      .then(r => r.json())
      .then((data: WikiEntry[]) => {
        if (data.length > 0) {
          setWiki(data[0]);
          setEditContent(data[0].content);
        } else {
          setWiki(null);
          setEditContent('');
        }
        setEditing(false);
      })
      .catch(() => {});
  }, [selectedProject]);

  // 위키 생성
  const handleGenerate = useCallback((targetType: string, targetPath: string) => {
    if (!selectedProject) return;
    setGenerating(true);
    fetch(`${API}/api/codegraph/wiki/generate`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        project_id: selectedProject,
        target_type: targetType,
        target_path: targetPath,
      }),
    })
      .then(r => r.json())
      .then(() => {
        setGenerating(false);
        loadTree();
      })
      .catch(() => setGenerating(false));
  }, [selectedProject, loadTree]);

  // 전체 생성
  const handleGenerateAll = useCallback(() => {
    if (!selectedProject) return;
    setGeneratingAll(true);
    fetch(`${API}/api/codegraph/wiki/generate`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ project_id: selectedProject, target_type: 'all' }),
    })
      .then(r => r.json())
      .then(() => {
        setGeneratingAll(false);
        loadTree();
      })
      .catch(() => setGeneratingAll(false));
  }, [selectedProject, loadTree]);

  // 위키 저장
  const handleSave = useCallback(() => {
    if (!selectedProject || !selectedPath) return;
    fetch(`${API}/api/codegraph/wiki`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        project_id: selectedProject,
        file_path: selectedPath,
        wiki_type: 'file',
        content: editContent,
        title: selectedPath.split('/').pop() || '',
      }),
    })
      .then(r => r.json())
      .then(() => {
        setEditing(false);
        loadWiki(selectedPath);
        loadTree();
      })
      .catch(() => {});
  }, [selectedProject, selectedPath, editContent, loadWiki, loadTree]);

  // 폴더 토글
  const toggleDir = (dir: string) => {
    setCollapsedDirs(prev => {
      const next = new Set(prev);
      if (next.has(dir)) next.delete(dir); else next.add(dir);
      return next;
    });
  };

  // 트리에서 보이는 항목 필터
  const visibleTree = tree.filter(item => {
    if (item.type === 'directory') return true;
    // 상위 디렉토리가 접혀있으면 숨기기
    for (const dir of collapsedDirs) {
      if (item.path.startsWith(dir + '/')) return false;
    }
    return true;
  }).filter(item => {
    // 접힌 하위 디렉토리도 숨기기
    if (item.type === 'directory') {
      for (const dir of collapsedDirs) {
        if (item.path.startsWith(dir + '/') && item.path !== dir) return false;
      }
    }
    return true;
  });

  const wikiCount = tree.filter(t => t.type === 'file' && t.has_wiki).length;

  return (
    <div className="flex flex-col h-full bg-[#1e1e2e] text-gray-200">
      {/* 상단 툴바 */}
      <div className="flex items-center gap-2 px-3 py-2 bg-[#181825] border-b border-[#313244]">
        <select
          className="bg-[#313244] text-sm rounded px-2 py-1 border border-[#45475a] flex-1 max-w-[200px]"
          value={selectedProject || ''}
          onChange={e => {
            setSelectedProject(Number(e.target.value) || null);
            setSelectedPath('');
            setWiki(null);
          }}
        >
          <option value="">프로젝트 선택</option>
          {projects.map(p => (
            <option key={p.id} value={p.id}>{p.name}</option>
          ))}
        </select>

        {selectedProject && (
          <>
            <span className="text-xs text-gray-500">
              {wikiCount}/{totalFiles} 파일
            </span>
            <button
              className="px-3 py-1 text-xs rounded bg-[#89b4fa] text-[#1e1e2e] font-medium hover:bg-[#74c7ec] disabled:opacity-50"
              onClick={handleGenerateAll}
              disabled={generatingAll || !selectedProject}
            >
              {generatingAll ? '생성 중...' : '전체 위키 생성'}
            </button>
          </>
        )}
      </div>

      {/* 메인 영역 */}
      <div className="flex flex-1 overflow-hidden">
        {/* 좌측: 파일 트리 */}
        <div className="w-1/3 min-w-[200px] max-w-[320px] border-r border-[#313244] overflow-y-auto">
          {!selectedProject ? (
            <div className="p-4 text-sm text-gray-500 text-center">
              프로젝트를 선택하세요
            </div>
          ) : tree.length === 0 ? (
            <div className="p-4 text-sm text-gray-500 text-center">
              인덱싱된 파일이 없습니다.<br />
              코드 그래프 탭에서 먼저 인덱싱하세요.
            </div>
          ) : (
            <div className="py-1">
              {visibleTree.map(item => {
                const depth = item.path.split('/').length - 1;
                const isDir = item.type === 'directory';
                const isCollapsed = collapsedDirs.has(item.path);
                const isSelected = item.path === selectedPath;
                const name = item.path.split('/').pop() || item.path;

                return (
                  <div
                    key={item.path}
                    className={`flex items-center gap-1 px-2 py-0.5 cursor-pointer text-sm hover:bg-[#313244] ${
                      isSelected ? 'bg-[#313244] text-[#89b4fa]' : ''
                    }`}
                    style={{ paddingLeft: `${depth * 16 + 8}px` }}
                    onClick={() => {
                      if (isDir) {
                        toggleDir(item.path);
                      } else {
                        loadWiki(item.path);
                      }
                    }}
                  >
                    {isDir ? (
                      <span className="w-4 text-center text-gray-500">
                        {isCollapsed ? '▸' : '▾'}
                      </span>
                    ) : (
                      <span className="w-4 text-center">
                        {item.has_wiki ? '✅' : '➕'}
                      </span>
                    )}
                    <span className={isDir ? 'font-medium text-[#f9e2af]' : ''}>
                      {isDir ? `${name}/` : name}
                    </span>
                  </div>
                );
              })}
            </div>
          )}
        </div>

        {/* 우측: 위키 콘텐츠 */}
        <div className="flex-1 flex flex-col overflow-hidden">
          {!selectedPath ? (
            <div className="flex-1 flex items-center justify-center text-gray-500 text-sm">
              좌측 트리에서 파일을 선택하세요
            </div>
          ) : (
            <>
              {/* 파일 경로 헤더 */}
              <div className="flex items-center gap-2 px-4 py-2 bg-[#181825] border-b border-[#313244]">
                <span className="text-sm font-mono text-[#cdd6f4] flex-1 truncate">
                  {selectedPath}
                </span>
                <div className="flex gap-1">
                  {!wiki ? (
                    <button
                      className="px-2 py-1 text-xs rounded bg-[#a6e3a1] text-[#1e1e2e] font-medium hover:bg-[#94e2d5] disabled:opacity-50"
                      onClick={() => handleGenerate('file', selectedPath)}
                      disabled={generating}
                    >
                      {generating ? '생성 중...' : '위키 생성'}
                    </button>
                  ) : (
                    <>
                      {!editing ? (
                        <>
                          <button
                            className="px-2 py-1 text-xs rounded bg-[#313244] text-gray-300 hover:bg-[#45475a]"
                            onClick={() => { setEditing(true); setEditContent(wiki.content); }}
                          >
                            편집
                          </button>
                          <button
                            className="px-2 py-1 text-xs rounded bg-[#fab387] text-[#1e1e2e] font-medium hover:bg-[#f9e2af] disabled:opacity-50"
                            onClick={() => handleGenerate('file', selectedPath)}
                            disabled={generating}
                          >
                            {generating ? '생성 중...' : '재생성'}
                          </button>
                        </>
                      ) : (
                        <>
                          <button
                            className="px-2 py-1 text-xs rounded bg-[#a6e3a1] text-[#1e1e2e] font-medium hover:bg-[#94e2d5]"
                            onClick={handleSave}
                          >
                            저장
                          </button>
                          <button
                            className="px-2 py-1 text-xs rounded bg-[#313244] text-gray-300 hover:bg-[#45475a]"
                            onClick={() => setEditing(false)}
                          >
                            취소
                          </button>
                        </>
                      )}
                    </>
                  )}
                </div>
              </div>

              {/* 콘텐츠 영역 */}
              <div className="flex-1 overflow-y-auto">
                {!wiki && !editing ? (
                  <div className="flex flex-col items-center justify-center h-full text-gray-500 gap-3">
                    <span className="text-4xl">📝</span>
                    <span className="text-sm">아직 위키가 생성되지 않았습니다</span>
                    <span className="text-xs text-gray-600">
                      "위키 생성" 버튼을 누르면 에이전트가 위키를 작성합니다
                    </span>
                  </div>
                ) : editing ? (
                  <textarea
                    className="w-full h-full p-4 bg-[#1e1e2e] text-gray-200 font-mono text-sm resize-none focus:outline-none"
                    value={editContent}
                    onChange={e => setEditContent(e.target.value)}
                    placeholder="마크다운으로 위키를 작성하세요..."
                  />
                ) : (
                  <div className="p-4 prose prose-invert prose-sm max-w-none
                    prose-headings:text-[#cdd6f4] prose-p:text-gray-300
                    prose-a:text-[#89b4fa] prose-code:text-[#f38ba8]
                    prose-pre:bg-[#181825] prose-pre:border prose-pre:border-[#313244]
                    prose-strong:text-[#cdd6f4]
                    prose-li:text-gray-300
                    prose-th:text-[#cdd6f4] prose-td:text-gray-300
                  ">
                    <Markdown remarkPlugins={[remarkGfm]}>
                      {wiki?.content || ''}
                    </Markdown>
                    {wiki?.generated_at && (
                      <div className="mt-6 pt-3 border-t border-[#313244] text-xs text-gray-600">
                        생성일: {new Date(wiki.generated_at).toLocaleString('ko-KR')}
                      </div>
                    )}
                  </div>
                )}
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
