/**
 * FILE: MemoryPanel.tsx
 * DESCRIPTION: 에이전트 간 공유 메모리(SQLite) 패널 — 검색, CRUD, 폴링 로직을 포함한 독립 컴포넌트
 * REVISION HISTORY:
 * - 2026-03-01 Claude: DB 정보 표시 + APPDATA→로컬 동기화 버튼 추가
 *                      배포 버전에서 어떤 DB를 사용 중인지 표시하고 수동 동기화 지원
 * - 2026-03-01 Claude: App.tsx에서 분리 — 독립 컴포넌트화
 */

import { useState, useEffect } from 'react';
import { Search, Brain, Plus, RefreshCw, Database } from 'lucide-react';
import { MemoryEntry } from '../../types';
import { API_BASE } from '../../constants';

// ─── Props 타입 ─────────────────────────────────────────────────────────────
interface MemoryPanelProps {
  currentProjectName?: string; // 현재 열린 프로젝트 이름 (프로젝트 필터링용, 선택)
}

/**
 * MemoryPanel
 * - 에이전트(Claude / Gemini / User)가 작성한 공유 지식 항목을 조회·추가·수정·삭제
 * - 검색어 기반 실시간 필터링 + 5초 폴링으로 최신 상태 유지
 * - memShowAll 상태로 전체 보기 / 현재 프로젝트만 보기 토글 지원
 */
export default function MemoryPanel({ currentProjectName }: MemoryPanelProps) {
  // ─── 메모리 목록 및 검색 상태 ─────────────────────────────────────────
  const [memory, setMemory] = useState<MemoryEntry[]>([]);
  const [memSearch, setMemSearch] = useState('');

  // 전체 보기(true) vs 현재 프로젝트만(false) 토글
  const [memShowAll, setMemShowAll] = useState(true);

  // B.2 — 작성자 필터 (예: 'claude', 'gemini'). 빈값이면 전체.
  const [memAuthorFilter, setMemAuthorFilter] = useState('');

  // C.1 — 제텔카스텐(zettel_notes) 지식 포함 여부. 기본 on으로 에이전트가
  // 놓치던 234건을 바로 활용하도록 유도.
  const [includeZettel, setIncludeZettel] = useState(true);

  // ─── 폼 상태 (신규 추가 / 수정) ──────────────────────────────────────
  const [showMemForm, setShowMemForm] = useState(false);
  const [editingMemKey, setEditingMemKey] = useState<string | null>(null);
  const [memKey, setMemKey] = useState('');
  const [memTitle, setMemTitle] = useState('');
  const [memContent, setMemContent] = useState('');
  const [memTags, setMemTags] = useState('');
  const [memAuthor, setMemAuthor] = useState('claude');

  // ─── 데이터 페칭 ────────────────────────────────────────────────────────
  // 검색어/작성자/지식포함 파라미터를 쿼리스트링으로 전달.
  const fetchMemory = (q = '', author = '', withZettel = false) => {
    const params = new URLSearchParams();
    if (q) params.set('q', q);
    if (author) params.set('author', author);
    if (withZettel) params.set('include_zettel', 'true');
    const url = params.toString()
      ? `${API_BASE}/api/memory?${params.toString()}`
      : `${API_BASE}/api/memory`;
    fetch(url)
      .then(res => res.json())
      .then(data => setMemory(Array.isArray(data) ? data : []))
      .catch((err) => console.error('[MemoryPanel] fetch error:', err));
  };

  // 검색어/작성자/지식포함 변경 시 즉시 재조회 + 5초 폴링 유지
  useEffect(() => {
    fetchMemory(memSearch, memAuthorFilter, includeZettel);
    const interval = setInterval(
      () => fetchMemory(memSearch, memAuthorFilter, includeZettel),
      5000,
    );
    return () => clearInterval(interval);
  }, [memSearch, memAuthorFilter, includeZettel]);

  // ─── DB 정보 상태 ────────────────────────────────────────────────────────
  const [dbInfo, setDbInfo] = useState<{ db_path?: string; is_local?: boolean; count?: number } | null>(null);
  const [syncMsg, setSyncMsg] = useState('');
  const [syncing, setSyncing] = useState(false);

  // DB 정보 로드 (마운트 시 1회)
  useEffect(() => {
    fetch(`${API_BASE}/api/memory/db-info`)
      .then(res => res.json())
      .then(data => setDbInfo(data))
      .catch((err) => console.error('[MemoryPanel] fetch error:', err));
  }, [memory]); // memory 갱신 시마다 DB 정보도 갱신

  // APPDATA→로컬 DB 동기화 핸들러
  const syncMemory = () => {
    setSyncing(true);
    setSyncMsg('');
    fetch(`${API_BASE}/api/memory/sync`, { method: 'POST' })
      .then(res => res.json())
      .then(data => {
        setSyncMsg(data.message || '완료');
        fetchMemory(memSearch, memAuthorFilter, includeZettel); // 목록 즉시 갱신
      })
      .catch(() => setSyncMsg('동기화 실패'))
      .finally(() => setSyncing(false));
  };

  // ─── 표시할 목록 계산 ──────────────────────────────────────────────────
  // memShowAll=false이고 currentProjectName이 있으면 프로젝트 필터 적용
  const displayedMemory = memShowAll || !currentProjectName
    ? memory
    : memory.filter(entry => entry.project_id === currentProjectName);

  // ─── CRUD 핸들러 ────────────────────────────────────────────────────────

  // 신규 추가 또는 수정 저장 (key 기준 UPSERT)
  const saveMemory = () => {
    if (!memKey.trim() || !memContent.trim()) return;
    fetch(`${API_BASE}/api/memory/set`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        key:     memKey.trim(),
        title:   memTitle.trim() || memKey.trim(),
        content: memContent.trim(),
        tags:    memTags.split(',').map(t => t.trim()).filter(Boolean),
        author:  memAuthor,
      }),
    })
      .then(() => {
        // 저장 후 폼 초기화 및 목록 갱신
        setMemKey(''); setMemTitle(''); setMemContent('');
        setMemTags(''); setShowMemForm(false); setEditingMemKey(null);
        fetchMemory(memSearch, memAuthorFilter, includeZettel);
      })
      .catch((err) => console.error('[MemoryPanel] fetch error:', err));
  };

  // 항목 삭제 — key를 서버에 전달하여 SQLite 레코드 제거
  const deleteMemory = (key: string) => {
    fetch(`${API_BASE}/api/memory/delete`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ key }),
    }).then(() => fetchMemory(memSearch, memAuthorFilter, includeZettel)).catch((err) => console.error('[MemoryPanel] fetch error:', err));
  };

  // C.3 — hive_memory 항목을 zettel_notes로 승격 (원본 유지).
  // 태그 기반 note_type 자동 판정. 실패 시 alert.
  const promoteMemory = (key: string) => {
    if (!confirm(`"${key}" 을(를) 정제 지식(zettel_notes)으로 승격할까요?\n원본은 유지됩니다.`)) return;
    fetch(`${API_BASE}/api/memory/promote`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ key }),
    })
      .then(res => res.json())
      .then(data => {
        if (data.status !== 'success') alert(data.message || '승격 실패');
        fetchMemory(memSearch, memAuthorFilter, includeZettel);
      })
      .catch((err) => console.error('[MemoryPanel] promote error:', err));
  };

  // 수정 폼 열기 — 기존 항목 데이터를 상태에 주입하여 편집 가능하게 함
  const startEditMemory = (entry: MemoryEntry) => {
    setMemKey(entry.key);
    setMemTitle(entry.title);
    setMemContent(entry.content);
    setMemTags(entry.tags.join(', '));
    setMemAuthor(entry.author);
    setEditingMemKey(entry.key);
    setShowMemForm(true);
  };

  // 폼 취소 — 모든 입력 상태 초기화
  const cancelForm = () => {
    setShowMemForm(false);
    setEditingMemKey(null);
    setMemKey('');
    setMemTitle('');
    setMemContent('');
    setMemTags('');
  };

  // ─── 렌더링 ─────────────────────────────────────────────────────────────
  return (
    <div className="flex-1 flex flex-col overflow-hidden gap-2">
      {/* 검색 입력 */}
      <div className="relative shrink-0">
        <Search className="absolute left-2 top-1/2 -translate-y-1/2 w-3 h-3 text-[#858585]" />
        <input
          type="text"
          value={memSearch}
          onChange={e => setMemSearch(e.target.value)}
          placeholder="키 / 내용 / 태그 검색..."
          className="w-full bg-[#1e1e1e] border border-white/10 rounded pl-6 pr-2 py-1.5 text-[10px] focus:outline-none focus:border-primary text-white transition-colors"
        />
      </div>

      {/* 항목 수 요약 + 지식 포함 + 작성자 필터 + 전체/현재 프로젝트 토글 */}
      <div className="flex items-center justify-between shrink-0 px-0.5 gap-1">
        <span className="text-[9px] text-[#858585] shrink-0">
          총 {displayedMemory.length}개{memSearch && ` (검색)`}
          {memAuthorFilter && ` (by ${memAuthorFilter})`}
        </span>
        <div className="flex items-center gap-1">
          {/* C.1 — 제텔카스텐 지식 포함 토글 */}
          <button
            onClick={() => setIncludeZettel(prev => !prev)}
            className={`text-[8px] px-1.5 py-0.5 rounded transition-colors ${
              includeZettel
                ? 'bg-purple-500/20 text-purple-300 border border-purple-500/30'
                : 'bg-white/5 text-[#858585] hover:text-white border border-white/10'
            }`}
            title="zettel_notes 지식 포함 여부"
          >
            {includeZettel ? '🧠 지식 on' : '🧠 지식 off'}
          </button>
          {/* B.2 — 작성자 필터 드롭다운 (prefix 매칭: 'claude' → claude-*) */}
          <select
            value={memAuthorFilter}
            onChange={e => setMemAuthorFilter(e.target.value)}
            className="text-[8px] bg-[#3c3c3c] border border-white/5 rounded px-1 py-0.5 focus:outline-none cursor-pointer text-white"
            title="작성자 필터"
          >
            <option value="">작성자: 전체</option>
            <option value="claude">claude 계열</option>
            <option value="gemini">gemini 계열</option>
            <option value="codex">codex 계열</option>
            <option value="user">user</option>
            <option value="unknown">unknown</option>
            <option value="legacy">legacy</option>
          </select>
          {/* 프로젝트 필터 토글 — currentProjectName이 있을 때만 표시 */}
          {currentProjectName && (
            <button
              onClick={() => setMemShowAll(prev => !prev)}
              className={`text-[8px] px-1.5 py-0.5 rounded transition-colors ${
                memShowAll
                  ? 'bg-white/5 text-[#858585] hover:text-white'
                  : 'bg-cyan-500/15 text-cyan-400'
              }`}
            >
              {memShowAll ? '전체' : currentProjectName}
            </button>
          )}
        </div>
      </div>

      {/* 메모리 항목 목록 */}
      <div className="flex-1 overflow-y-auto space-y-1.5 custom-scrollbar">
        {displayedMemory.length === 0 ? (
          <div className="text-center text-[#858585] text-xs py-10 flex flex-col items-center gap-2 italic">
            <Brain className="w-7 h-7 opacity-20" />
            {memSearch ? '검색 결과 없음' : '저장된 메모리 없음'}
          </div>
        ) : (
          displayedMemory.map(entry => (
            <div
              key={entry.key}
              className="p-2 rounded border border-white/10 bg-white/2 text-[10px] hover:border-white/20 transition-colors group"
            >
              {/* 키 + 소스 배지 + 액션 버튼 */}
              <div className="flex items-start justify-between gap-1 mb-1">
                <div className="flex items-start gap-1 min-w-0 flex-1">
                  {/* C.1 — source 배지. zettel은 note_type까지 표시해 정제 단계 구분. */}
                  {entry.source === 'zettel' ? (
                    <span
                      className={`px-1 py-0.5 rounded text-[7px] font-bold shrink-0 leading-tight ${
                        entry.note_type === 'permanent'
                          ? 'bg-purple-500/25 text-purple-200'
                          : entry.note_type === 'literature'
                          ? 'bg-indigo-500/20 text-indigo-300'
                          : 'bg-purple-500/10 text-purple-400/80'
                      }`}
                      title={`zettel ${entry.note_type || 'fleeting'} · access ${entry.access_count ?? 0}`}
                    >
                      🧠 {entry.note_type || 'fleeting'}
                    </span>
                  ) : (
                    <span
                      className="px-1 py-0.5 rounded text-[7px] font-bold shrink-0 leading-tight bg-white/5 text-[#888]"
                      title="hive_memory (작업 흔적)"
                    >
                      💾 hive
                    </span>
                  )}
                  <span className="font-mono font-bold text-cyan-400 text-[10px] break-all leading-tight min-w-0">
                    {entry.key}
                  </span>
                </div>
                <div className="flex gap-0.5 shrink-0 opacity-0 group-hover:opacity-100 transition-opacity">
                  {/* zettel은 별도 API(zettelkasten.py)가 관리 — 여기선 hive_memory 편집만 허용 */}
                  {entry.source !== 'zettel' && (
                    <>
                      {/* C.3 — 정제 지식(zettel)로 승격. hive 항목에만 노출. */}
                      <button
                        onClick={() => promoteMemory(entry.key)}
                        className="px-1.5 py-0.5 bg-white/5 hover:bg-purple-500/20 rounded text-[9px] text-[#858585] hover:text-purple-300 transition-colors"
                        title="정제 지식(zettel)로 승격"
                      >
                        🧠
                      </button>
                      <button
                        onClick={() => startEditMemory(entry)}
                        className="px-1.5 py-0.5 bg-white/5 hover:bg-primary/20 rounded text-[9px] text-[#858585] hover:text-primary transition-colors"
                      >
                        ✏️
                      </button>
                      <button
                        onClick={() => deleteMemory(entry.key)}
                        className="px-1.5 py-0.5 bg-white/5 hover:bg-red-500/20 rounded text-[9px] text-[#858585] hover:text-red-400 transition-colors"
                      >
                        🗑️
                      </button>
                    </>
                  )}
                </div>
              </div>

              {/* 제목 (키와 다를 경우만 표시) */}
              {entry.title && entry.title !== entry.key && (
                <p className="text-[#cccccc] font-semibold text-[10px] mb-0.5">{entry.title}</p>
              )}

              {/* 내용 미리보기 (2줄 클램프) */}
              <p className="text-[#969696] text-[9px] leading-relaxed line-clamp-2 break-words">
                {entry.content}
              </p>

              {/* 태그 + 작성자 배지 + 수정 날짜 */}
              <div className="flex items-center flex-wrap gap-1 mt-1.5">
                {entry.tags.map(tag => (
                  <span
                    key={tag}
                    onClick={() => setMemSearch(tag)}
                    className="px-1 py-0.5 bg-cyan-500/10 text-cyan-400 rounded text-[8px] font-mono cursor-pointer hover:bg-cyan-500/20 transition-colors"
                  >
                    #{tag}
                  </span>
                ))}
                {/* 작성자별 색상 구분 */}
                <span
                  className={`px-1.5 py-0.5 rounded text-[8px] font-bold ml-auto ${
                    entry.author === 'claude'
                      ? 'bg-green-500/15 text-green-400'
                      : entry.author === 'gemini'
                      ? 'bg-blue-500/15 text-blue-400'
                      : 'bg-white/10 text-white/50'
                  }`}
                >
                  {entry.author}
                </span>
                <span className="text-[#858585] text-[8px] font-mono">
                  {entry.updated_at.slice(5, 16).replace('T', ' ')}
                </span>
              </div>
            </div>
          ))
        )}
      </div>

      {/* 저장 폼 또는 추가 버튼 */}
      {showMemForm ? (
        <div className="border-t border-white/5 pt-2 flex flex-col gap-1.5 shrink-0">
          {/* 폼 헤더 — 신규/수정 여부 표시 */}
          <div className="text-[9px] text-[#858585] font-bold uppercase tracking-wider">
            {editingMemKey ? `✏️ 수정: ${editingMemKey}` : '+ 새 메모리 항목'}
          </div>

          {/* 키 입력 — 수정 시 잠금 (primary key) */}
          <input
            type="text"
            value={memKey}
            onChange={e => setMemKey(e.target.value)}
            placeholder="키 (예: db_schema, auth_method)"
            disabled={!!editingMemKey}
            className="w-full bg-[#1e1e1e] border border-white/10 rounded px-2 py-1.5 text-[10px] focus:outline-none focus:border-cyan-500 text-white transition-colors disabled:opacity-50 disabled:cursor-not-allowed font-mono"
          />

          {/* 제목 — 비워두면 키 값을 대신 사용 */}
          <input
            type="text"
            value={memTitle}
            onChange={e => setMemTitle(e.target.value)}
            placeholder="제목 (선택, 비워두면 키 사용)"
            className="w-full bg-[#1e1e1e] border border-white/10 rounded px-2 py-1.5 text-[10px] focus:outline-none focus:border-cyan-500 text-white transition-colors"
          />

          {/* 내용 — 에이전트 간 공유할 핵심 정보 */}
          <textarea
            value={memContent}
            onChange={e => setMemContent(e.target.value)}
            placeholder="내용 (에이전트가 공유할 정보)"
            rows={4}
            className="w-full bg-[#1e1e1e] border border-white/10 hover:border-white/30 rounded px-2 py-1.5 text-[10px] focus:outline-none focus:border-cyan-500 text-white transition-colors resize-none"
          />

          {/* 태그 + 작성자 선택 한 줄 배치 */}
          <div className="flex gap-1">
            <input
              type="text"
              value={memTags}
              onChange={e => setMemTags(e.target.value)}
              placeholder="태그 (쉼표 구분)"
              className="flex-1 bg-[#1e1e1e] border border-white/10 rounded px-2 py-1.5 text-[10px] focus:outline-none focus:border-cyan-500 text-white transition-colors"
            />
            <select
              value={memAuthor}
              onChange={e => setMemAuthor(e.target.value)}
              className="bg-[#3c3c3c] border border-white/5 rounded px-1 py-1 text-[10px] focus:outline-none cursor-pointer"
            >
              <option value="claude">Claude</option>
              <option value="gemini">Gemini</option>
              <option value="user">User</option>
            </select>
          </div>

          {/* 저장 / 취소 버튼 */}
          <div className="flex gap-1">
            <button
              onClick={saveMemory}
              disabled={!memKey.trim() || !memContent.trim()}
              className="flex-1 py-1.5 bg-cyan-500/80 hover:bg-cyan-500 disabled:opacity-30 text-black rounded text-[10px] font-black transition-colors"
            >
              저장
            </button>
            <button
              onClick={cancelForm}
              className="px-3 py-1.5 bg-white/5 hover:bg-white/10 text-[#858585] rounded text-[10px] transition-colors"
            >
              취소
            </button>
          </div>
        </div>
      ) : (
        /* 폼이 닫혔을 때 — 추가 버튼 */
        <button
          onClick={() => setShowMemForm(true)}
          className="shrink-0 w-full py-1.5 border border-dashed border-white/15 hover:border-cyan-500/40 hover:bg-cyan-500/5 rounded text-[10px] text-[#858585] hover:text-cyan-400 transition-colors flex items-center justify-center gap-1.5"
        >
          <Plus className="w-3 h-3" /> 새 메모리 항목 추가
        </button>
      )}

      {/* ── DB 정보 + 동기화 버튼 ─────────────────────────────────────────── */}
      {/* 배포 버전에서 현재 어떤 DB를 바라보는지 표시하고, APPDATA→로컬 동기화 제공 */}
      {dbInfo && (
        <div className="shrink-0 p-2 rounded border border-white/10 bg-black/20 flex flex-col gap-1.5">
          <div className="flex items-center gap-1.5">
            <Database className="w-3 h-3 text-[#666] shrink-0" />
            <span className={`text-[8px] font-mono truncate flex-1 ${dbInfo.is_local ? 'text-green-400/70' : 'text-yellow-400/70'}`}
                  title={dbInfo.db_path}>
              {dbInfo.is_local ? '📂 로컬 DB' : '🌐 APPDATA DB'} ({dbInfo.count ?? 0}개)
            </span>
            <button
              onClick={syncMemory}
              disabled={syncing}
              className="flex items-center gap-0.5 px-1.5 py-0.5 rounded border border-white/10 bg-white/5 hover:bg-cyan-500/10 hover:border-cyan-500/30 text-[8px] text-[#858585] hover:text-cyan-400 transition-colors disabled:opacity-40 shrink-0"
              title="APPDATA DB → 로컬 DB 동기화"
            >
              <RefreshCw className={`w-2.5 h-2.5 ${syncing ? 'animate-spin' : ''}`} />
              동기화
            </button>
          </div>
          {syncMsg && (
            <div className="text-[8px] text-cyan-400/80 font-mono truncate">{syncMsg}</div>
          )}
        </div>
      )}
    </div>
  );
}
