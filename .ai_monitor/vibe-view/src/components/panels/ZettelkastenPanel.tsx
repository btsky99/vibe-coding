/**
 * FILE: ZettelkastenPanel.tsx
 * DESCRIPTION: Hive Zettelkasten 패널 — 카파시 + 루만 융합 메모 시스템 UI.
 *              원자 노트 CRUD, 그래프 시각화, 중력 침강/rescue, 통계 대시보드.
 * REVISION HISTORY:
 *   2026-04-05 — 초기 구현
 */

import { useState, useEffect, useCallback } from 'react';
import {
  Search, Plus, RefreshCw, BookOpen, Link2, ArrowUp,
  Archive, BarChart3, Network, Trash2, Edit3, Save, X,
  ChevronDown, ChevronRight, Eye
} from 'lucide-react';
import { ZettelNote, ZettelStats } from '../../types';
import { API_BASE } from '../../constants';

// ─── 상수 ────────────────────────────────────────────────────────────────
const NOTE_TYPE_LABELS: Record<string, string> = {
  fleeting: '일시',
  literature: '문헌',
  permanent: '영구',
};
const NOTE_TYPE_COLORS: Record<string, string> = {
  fleeting: 'bg-gray-500/20 text-gray-300',
  literature: 'bg-blue-500/20 text-blue-300',
  permanent: 'bg-green-500/20 text-green-300',
};
const LINK_TYPE_LABELS: Record<string, string> = {
  relates_to: '관련',
  extends: '확장',
  contradicts: '반박',
  implements: '구현',
};

type ViewMode = 'list' | 'stats';

export default function ZettelkastenPanel() {
  // ─── 상태 ──────────────────────────────────────────────────────────────
  const [notes, setNotes] = useState<ZettelNote[]>([]);
  const [stats, setStats] = useState<ZettelStats | null>(null);
  const [search, setSearch] = useState('');
  const [typeFilter, setTypeFilter] = useState('');
  const [viewMode, setViewMode] = useState<ViewMode>('list');
  const [selectedNote, setSelectedNote] = useState<ZettelNote | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [editingNote, setEditingNote] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  // 폼 상태
  const [formTitle, setFormTitle] = useState('');
  const [formContent, setFormContent] = useState('');
  const [formType, setFormType] = useState<string>('fleeting');
  const [formTags, setFormTags] = useState('');
  const [formParentId, setFormParentId] = useState('');
  const [formSourceRef, setFormSourceRef] = useState('');

  // ─── 데이터 페칭 ────────────────────────────────────────────────────────
  const fetchNotes = useCallback(() => {
    const params = new URLSearchParams();
    if (search) params.set('q', search);
    if (typeFilter) params.set('type', typeFilter);
    params.set('limit', '100');
    fetch(`${API_BASE}/api/zettel/notes?${params}`)
      .then(r => r.json())
      .then(data => { if (Array.isArray(data)) setNotes(data); })
      .catch(() => {});
  }, [search, typeFilter]);

  const fetchStats = useCallback(() => {
    fetch(`${API_BASE}/api/zettel/stats`)
      .then(r => r.json())
      .then(data => { if (data && typeof data.total_notes === 'number') setStats(data); })
      .catch(() => {});
  }, []);

  useEffect(() => {
    fetchNotes();
    fetchStats();
    const interval = setInterval(() => { fetchNotes(); fetchStats(); }, 10000);
    return () => clearInterval(interval);
  }, [fetchNotes, fetchStats]);

  // ─── CRUD ────────────────────────────────────────────────────────────────
  const handleCreate = async () => {
    if (!formTitle.trim()) return;
    setLoading(true);
    try {
      const res = await fetch(`${API_BASE}/api/zettel/notes`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          title: formTitle,
          content: formContent,
          note_type: formType,
          tags: formTags.split(',').map(t => t.trim()).filter(Boolean),
          parent_id: formParentId,
          source_ref: formSourceRef,
          author: 'user',
        }),
      });
      if (res.ok) {
        resetForm();
        fetchNotes();
        fetchStats();
      }
    } catch { /* 무시 */ }
    setLoading(false);
  };

  const handleUpdate = async (noteId: string) => {
    setLoading(true);
    try {
      await fetch(`${API_BASE}/api/zettel/note/${noteId}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          title: formTitle,
          content: formContent,
          note_type: formType,
          tags: formTags.split(',').map(t => t.trim()).filter(Boolean),
          source_ref: formSourceRef,
        }),
      });
      setEditingNote(null);
      resetForm();
      fetchNotes();
    } catch { /* 무시 */ }
    setLoading(false);
  };

  const handleDelete = async (noteId: string) => {
    if (!confirm(`노트 "${noteId}"를 삭제하시겠습니까?`)) return;
    await fetch(`${API_BASE}/api/zettel/note/${noteId}/delete`, { method: 'POST' });
    setSelectedNote(null);
    fetchNotes();
    fetchStats();
  };

  const handleRescue = async (noteId: string) => {
    await fetch(`${API_BASE}/api/zettel/note/${noteId}/rescue`, { method: 'POST' });
    fetchNotes();
  };

  const startEdit = (note: ZettelNote) => {
    setEditingNote(note.id);
    setFormTitle(note.title);
    setFormContent(note.content);
    setFormType(note.note_type);
    setFormTags((note.tags || []).join(', '));
    setFormSourceRef(note.source_ref || '');
    setShowForm(true);
  };

  const resetForm = () => {
    setShowForm(false);
    setEditingNote(null);
    setFormTitle('');
    setFormContent('');
    setFormType('fleeting');
    setFormTags('');
    setFormParentId('');
    setFormSourceRef('');
  };

  // ─── 노트 상세 보기 ────────────────────────────────────────────────────
  const viewNote = async (noteId: string) => {
    try {
      const res = await fetch(`${API_BASE}/api/zettel/note/${noteId}`);
      const data = await res.json();
      if (data && data.id) setSelectedNote(data);
    } catch { /* 무시 */ }
  };

  // ─── 렌더링 ─────────────────────────────────────────────────────────────
  return (
    <div className="h-full flex flex-col text-sm overflow-hidden">
      {/* 헤더 */}
      <div className="flex items-center gap-2 p-2 border-b border-[#333]">
        <BookOpen className="w-4 h-4 text-green-400" />
        <span className="font-semibold text-white">Zettelkasten</span>
        {stats && (
          <span className="text-xs text-gray-500 ml-1">
            {stats.total_notes}개 노트 · {stats.total_links}개 링크
          </span>
        )}
        <div className="flex-1" />
        <button onClick={() => setViewMode(viewMode === 'list' ? 'stats' : 'list')}
          className="p-1 hover:bg-[#333] rounded" title="통계/목록 전환">
          {viewMode === 'list' ? <BarChart3 className="w-4 h-4" /> : <BookOpen className="w-4 h-4" />}
        </button>
        <button onClick={() => { setShowForm(!showForm); setEditingNote(null); }}
          className="p-1 hover:bg-[#333] rounded text-green-400" title="새 노트">
          <Plus className="w-4 h-4" />
        </button>
        <button onClick={() => { fetchNotes(); fetchStats(); }}
          className="p-1 hover:bg-[#333] rounded" title="새로고침">
          <RefreshCw className="w-3.5 h-3.5" />
        </button>
      </div>

      {/* 검색 + 필터 */}
      <div className="flex gap-1 p-2 border-b border-[#333]">
        <div className="flex-1 flex items-center bg-[#1e1e1e] border border-[#444] rounded px-2">
          <Search className="w-3.5 h-3.5 text-gray-500" />
          <input
            className="flex-1 bg-transparent text-white text-xs px-1 py-1 outline-none"
            placeholder="노트 검색..."
            value={search}
            onChange={e => setSearch(e.target.value)}
          />
        </div>
        <select
          className="bg-[#1e1e1e] border border-[#444] rounded text-xs text-gray-300 px-1"
          value={typeFilter}
          onChange={e => setTypeFilter(e.target.value)}
        >
          <option value="">전체</option>
          <option value="fleeting">일시</option>
          <option value="literature">문헌</option>
          <option value="permanent">영구</option>
        </select>
      </div>

      {/* 생성/수정 폼 */}
      {showForm && (
        <div className="p-2 border-b border-[#333] bg-[#1a1a2e] space-y-1.5">
          <input
            className="w-full bg-[#1e1e1e] border border-[#444] rounded px-2 py-1 text-xs text-white"
            placeholder="제목 *"
            value={formTitle}
            onChange={e => setFormTitle(e.target.value)}
          />
          <textarea
            className="w-full bg-[#1e1e1e] border border-[#444] rounded px-2 py-1 text-xs text-white h-20 resize-none"
            placeholder="내용 (마크다운 지원)"
            value={formContent}
            onChange={e => setFormContent(e.target.value)}
          />
          <div className="flex gap-1">
            <select
              className="bg-[#1e1e1e] border border-[#444] rounded text-xs text-gray-300 px-1 py-1"
              value={formType}
              onChange={e => setFormType(e.target.value)}
            >
              <option value="fleeting">일시 노트</option>
              <option value="literature">문헌 노트</option>
              <option value="permanent">영구 노트</option>
            </select>
            <input
              className="flex-1 bg-[#1e1e1e] border border-[#444] rounded px-2 py-1 text-xs text-white"
              placeholder="태그 (쉼표 구분)"
              value={formTags}
              onChange={e => setFormTags(e.target.value)}
            />
          </div>
          <div className="flex gap-1">
            {!editingNote && (
              <input
                className="flex-1 bg-[#1e1e1e] border border-[#444] rounded px-2 py-1 text-xs text-white"
                placeholder="부모 노트 ID (선택)"
                value={formParentId}
                onChange={e => setFormParentId(e.target.value)}
              />
            )}
            <input
              className="flex-1 bg-[#1e1e1e] border border-[#444] rounded px-2 py-1 text-xs text-white"
              placeholder="출처 URL/참조 (선택)"
              value={formSourceRef}
              onChange={e => setFormSourceRef(e.target.value)}
            />
          </div>
          <div className="flex gap-1 justify-end">
            <button onClick={resetForm}
              className="px-2 py-1 text-xs text-gray-400 hover:text-white">
              <X className="w-3 h-3 inline mr-1" />취소
            </button>
            <button
              onClick={() => editingNote ? handleUpdate(editingNote) : handleCreate()}
              disabled={loading || !formTitle.trim()}
              className="px-3 py-1 text-xs bg-green-600 hover:bg-green-500 text-white rounded disabled:opacity-50"
            >
              <Save className="w-3 h-3 inline mr-1" />
              {editingNote ? '수정' : '생성'}
            </button>
          </div>
        </div>
      )}

      {/* 메인 콘텐츠 */}
      <div className="flex-1 overflow-auto">
        {viewMode === 'stats' ? (
          <StatsView stats={stats} />
        ) : selectedNote ? (
          <NoteDetail
            note={selectedNote}
            onBack={() => setSelectedNote(null)}
            onEdit={startEdit}
            onDelete={handleDelete}
            onRescue={handleRescue}
            onViewNote={viewNote}
          />
        ) : (
          <NoteList
            notes={notes}
            onSelect={viewNote}
            onRescue={handleRescue}
            onDelete={handleDelete}
          />
        )}
      </div>
    </div>
  );
}

// ─── 노트 목록 ──────────────────────────────────────────────────────────────
function NoteList({ notes, onSelect, onRescue, onDelete }: {
  notes: ZettelNote[];
  onSelect: (id: string) => void;
  onRescue: (id: string) => void;
  onDelete: (id: string) => void;
}) {
  if (!notes.length) {
    return (
      <div className="p-4 text-center text-gray-500 text-xs">
        <BookOpen className="w-8 h-8 mx-auto mb-2 opacity-30" />
        노트가 없습니다. + 버튼으로 첫 번째 노트를 작성하세요.
      </div>
    );
  }
  return (
    <div className="divide-y divide-[#333]">
      {notes.map(note => (
        <div key={note.id}
          className="px-3 py-2 hover:bg-[#2a2a3a] cursor-pointer group transition-colors"
          onClick={() => onSelect(note.id)}
        >
          <div className="flex items-center gap-2">
            <span className="text-[10px] text-gray-500 font-mono min-w-[30px]">{note.id}</span>
            <span className={`text-[10px] px-1.5 py-0.5 rounded ${NOTE_TYPE_COLORS[note.note_type] || NOTE_TYPE_COLORS.fleeting}`}>
              {NOTE_TYPE_LABELS[note.note_type] || note.note_type}
            </span>
            <span className="text-xs text-white truncate flex-1">{note.title}</span>
            <span className="text-[10px] text-gray-600">{note.access_count}회</span>
            <div className="hidden group-hover:flex gap-0.5">
              <button onClick={e => { e.stopPropagation(); onRescue(note.id); }}
                className="p-0.5 hover:bg-green-500/20 rounded" title="Rescue (재부상)">
                <ArrowUp className="w-3 h-3 text-green-400" />
              </button>
              <button onClick={e => { e.stopPropagation(); onDelete(note.id); }}
                className="p-0.5 hover:bg-red-500/20 rounded" title="삭제">
                <Trash2 className="w-3 h-3 text-red-400" />
              </button>
            </div>
          </div>
          {note.tags && note.tags.length > 0 && (
            <div className="flex gap-1 mt-0.5 ml-8">
              {note.tags.slice(0, 5).map((tag, i) => (
                <span key={i} className="text-[10px] text-gray-500">#{tag}</span>
              ))}
            </div>
          )}
        </div>
      ))}
    </div>
  );
}

// ─── 노트 상세 ──────────────────────────────────────────────────────────────
function NoteDetail({ note, onBack, onEdit, onDelete, onRescue, onViewNote }: {
  note: ZettelNote;
  onBack: () => void;
  onEdit: (note: ZettelNote) => void;
  onDelete: (id: string) => void;
  onRescue: (id: string) => void;
  onViewNote: (id: string) => void;
}) {
  return (
    <div className="p-3 space-y-3">
      {/* 네비게이션 */}
      <div className="flex items-center gap-2">
        <button onClick={onBack} className="text-xs text-blue-400 hover:underline">
          &larr; 목록
        </button>
        <div className="flex-1" />
        <button onClick={() => onRescue(note.id)}
          className="p-1 hover:bg-green-500/20 rounded" title="Rescue">
          <ArrowUp className="w-3.5 h-3.5 text-green-400" />
        </button>
        <button onClick={() => onEdit(note)}
          className="p-1 hover:bg-blue-500/20 rounded" title="수정">
          <Edit3 className="w-3.5 h-3.5 text-blue-400" />
        </button>
        <button onClick={() => onDelete(note.id)}
          className="p-1 hover:bg-red-500/20 rounded" title="삭제">
          <Trash2 className="w-3.5 h-3.5 text-red-400" />
        </button>
      </div>

      {/* 제목 + 메타 */}
      <div>
        <div className="flex items-center gap-2 mb-1">
          <span className="text-xs text-gray-500 font-mono">{note.id}</span>
          <span className={`text-[10px] px-1.5 py-0.5 rounded ${NOTE_TYPE_COLORS[note.note_type] || ''}`}>
            {NOTE_TYPE_LABELS[note.note_type] || note.note_type}
          </span>
          {note.archived && <span className="text-[10px] px-1 py-0.5 bg-yellow-500/20 text-yellow-300 rounded">아카이브</span>}
        </div>
        <h2 className="text-base font-semibold text-white">{note.title}</h2>
        <div className="flex gap-3 mt-1 text-[10px] text-gray-500">
          <span>작성: {note.author}</span>
          <span>조회: {note.access_count}회</span>
          <span>수정: {note.updated_at?.slice(0, 16)}</span>
          {note.last_rescued_at && <span className="text-green-400">Rescue: {note.last_rescued_at.slice(0, 16)}</span>}
        </div>
      </div>

      {/* 태그 */}
      {note.tags && note.tags.length > 0 && (
        <div className="flex gap-1 flex-wrap">
          {note.tags.map((tag, i) => (
            <span key={i} className="text-[10px] px-1.5 py-0.5 bg-[#333] text-gray-300 rounded">#{tag}</span>
          ))}
        </div>
      )}

      {/* 내용 */}
      <div className="bg-[#1e1e1e] border border-[#333] rounded p-2 text-xs text-gray-300 whitespace-pre-wrap min-h-[60px]">
        {note.content || '(내용 없음)'}
      </div>

      {/* 출처 */}
      {note.source_ref && (
        <div className="text-[10px] text-gray-500">
          출처: <span className="text-blue-400">{note.source_ref}</span>
        </div>
      )}

      {/* 링크 / 백링크 */}
      {note.links && note.links.length > 0 && (
        <div>
          <h3 className="text-xs text-gray-400 mb-1 flex items-center gap-1">
            <Link2 className="w-3 h-3" /> 연결된 노트 ({note.links.length})
          </h3>
          <div className="space-y-0.5">
            {note.links.map((l, i) => (
              <div key={i} className="flex items-center gap-2 px-2 py-0.5 hover:bg-[#333] rounded cursor-pointer"
                onClick={() => onViewNote(l.id)}>
                <span className="text-[10px] text-gray-500 font-mono">{l.id}</span>
                <span className="text-xs text-white">{l.title}</span>
                <span className="text-[10px] text-gray-600">{LINK_TYPE_LABELS[l.link_type] || l.link_type}</span>
              </div>
            ))}
          </div>
        </div>
      )}
      {note.backlinks && note.backlinks.length > 0 && (
        <div>
          <h3 className="text-xs text-gray-400 mb-1 flex items-center gap-1">
            <Network className="w-3 h-3" /> 백링크 ({note.backlinks.length})
          </h3>
          <div className="space-y-0.5">
            {note.backlinks.map((l, i) => (
              <div key={i} className="flex items-center gap-2 px-2 py-0.5 hover:bg-[#333] rounded cursor-pointer"
                onClick={() => onViewNote(l.id)}>
                <span className="text-[10px] text-gray-500 font-mono">{l.id}</span>
                <span className="text-xs text-white">{l.title}</span>
                <span className="text-[10px] text-gray-600">{LINK_TYPE_LABELS[l.link_type] || l.link_type}</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

// ─── 통계 뷰 ─────────────────────────────────────────────────────────────────
function StatsView({ stats }: { stats: ZettelStats | null }) {
  if (!stats) {
    return <div className="p-4 text-center text-gray-500 text-xs">통계 로딩 중...</div>;
  }
  return (
    <div className="p-3 space-y-3">
      {/* 전체 수치 */}
      <div className="grid grid-cols-2 gap-2">
        <div className="bg-[#1a1a2e] border border-[#333] rounded p-2 text-center">
          <div className="text-lg font-bold text-white">{stats.total_notes}</div>
          <div className="text-[10px] text-gray-500">전체 노트</div>
        </div>
        <div className="bg-[#1a1a2e] border border-[#333] rounded p-2 text-center">
          <div className="text-lg font-bold text-blue-400">{stats.total_links}</div>
          <div className="text-[10px] text-gray-500">전체 링크</div>
        </div>
      </div>

      {/* 유형별 분포 */}
      <div>
        <h3 className="text-xs text-gray-400 mb-1">유형별 분포</h3>
        <div className="space-y-1">
          {stats.by_type.map((t, i) => (
            <div key={i} className="flex items-center gap-2">
              <span className={`text-[10px] px-1.5 py-0.5 rounded min-w-[32px] text-center ${NOTE_TYPE_COLORS[t.note_type] || 'bg-gray-500/20 text-gray-300'}`}>
                {NOTE_TYPE_LABELS[t.note_type] || t.note_type}
              </span>
              <div className="flex-1 bg-[#333] rounded-full h-2">
                <div
                  className="h-2 rounded-full bg-green-500/60"
                  style={{ width: `${stats.total_notes ? (t.cnt / stats.total_notes * 100) : 0}%` }}
                />
              </div>
              <span className="text-xs text-gray-400 min-w-[24px] text-right">{t.cnt}</span>
            </div>
          ))}
        </div>
      </div>

      {/* 허브 노트 (가장 많이 연결된) */}
      {stats.top_hubs && stats.top_hubs.length > 0 && (
        <div>
          <h3 className="text-xs text-gray-400 mb-1 flex items-center gap-1">
            <Network className="w-3 h-3" /> 허브 노트 (최다 연결)
          </h3>
          <div className="space-y-0.5">
            {stats.top_hubs.map((h, i) => (
              <div key={i} className="flex items-center gap-2 px-2 py-1 bg-[#1e1e1e] rounded">
                <span className="text-[10px] text-gray-500 font-mono">{h.id}</span>
                <span className="text-xs text-white flex-1 truncate">{h.title}</span>
                <span className="text-[10px] text-blue-400">{h.link_cnt} links</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
