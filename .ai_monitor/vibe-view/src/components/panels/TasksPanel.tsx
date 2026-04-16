/**
 * FILE: TasksPanel.tsx
 * DESCRIPTION: 에이전트 간 태스크 보드 패널 컴포넌트.
 *              태스크 목록 폴링, 상태 필터(전체/할 일/진행/완료), 새 작업 추가 폼을 담당합니다.
 *              Paperclip 스타일 코멘트 인라인 뷰 — 태스크 클릭 시 코멘트 로드/작성 가능.
 *
 * REVISION HISTORY:
 * - 2026-03-31 Claude: 코멘트 인라인 뷰 추가 (Paperclip 스타일 비동기 통신)
 * - 2026-03-01 Claude: App.tsx에서 분리 — 독립 컴포넌트화
 */

import { useState, useEffect, useCallback } from 'react';
import { ClipboardList, Plus, MessageSquare, Send } from 'lucide-react';
import { Task } from '../../types';
import { API_BASE } from '../../constants';

// ─── 코멘트 타입 ──────────────────────────────────────────────────────────────
interface TaskComment {
  id: number;
  task_id: string;
  author: string;
  content: string;
  created_at: string;
}

// ─── Props 타입 정의 ───────────────────────────────────────────────────────────
interface TasksPanelProps {
  /** 활성(미완료) 작업 수 변경 시 부모에게 알리는 콜백 */
  onActiveCount: (count: number) => void;
}

// ─── 상태 필터 타입 ────────────────────────────────────────────────────────────
type TaskFilterType = 'all' | 'pending' | 'in_progress' | 'done';

/**
 * TasksPanel
 * 에이전트 간 작업 큐(태스크 보드) 패널.
 * - 4초 간격으로 /api/tasks 폴링하여 최신 작업 목록 유지
 * - 상태 필터(전체 / 할 일 / 진행 / 완료)로 필터링된 목록 표시
 * - 새 작업 추가 폼 (제목 필수, 설명·담당자·우선순위 선택)
 * - 각 작업 카드에서 시작 / 완료 / 되돌리기 / 삭제 인라인 조작 가능
 */
// React.FC 대신 명시적 타입으로 선언 — React import 없이 사용 가능
const TasksPanel = ({ onActiveCount }: TasksPanelProps) => {
  // ─── 작업 목록 상태 ──────────────────────────────────────────────────────────
  const [tasks, setTasks] = useState<Task[]>([]);

  // ─── 필터 상태 ───────────────────────────────────────────────────────────────
  const [taskFilter, setTaskFilter] = useState<TaskFilterType>('all');

  // ─── 코멘트 인라인 뷰 상태 ───────────────────────────────────────────────────
  const [expandedTaskId, setExpandedTaskId] = useState<string | null>(null);
  const [comments, setComments] = useState<TaskComment[]>([]);
  const [newComment, setNewComment] = useState('');
  const [loadingComments, setLoadingComments] = useState(false);

  // 코멘트 로드
  const loadComments = useCallback(async (taskId: string) => {
    setLoadingComments(true);
    try {
      const res = await fetch(`${API_BASE}/api/tasks/${taskId}/comments`);
      if (res.ok) {
        const data = await res.json();
        setComments(Array.isArray(data) ? data : []);
      }
    } catch { /* 무시 */ }
    setLoadingComments(false);
  }, []);

  // 태스크 클릭 → 코멘트 토글
  const toggleComments = (taskId: string) => {
    if (expandedTaskId === taskId) {
      setExpandedTaskId(null);
      setComments([]);
    } else {
      setExpandedTaskId(taskId);
      loadComments(taskId);
    }
  };

  // 코멘트 추가
  const addComment = async (taskId: string) => {
    if (!newComment.trim()) return;
    try {
      await fetch(`${API_BASE}/api/tasks/${taskId}/comments`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ author: 'user', content: newComment.trim() }),
      });
      setNewComment('');
      loadComments(taskId);
    } catch { /* 무시 */ }
  };

  // ─── 새 작업 추가 폼 상태 ────────────────────────────────────────────────────
  const [showTaskForm, setShowTaskForm] = useState(false);
  const [newTaskTitle, setNewTaskTitle]     = useState('');
  const [newTaskDesc, setNewTaskDesc]       = useState('');
  const [newTaskAssignee, setNewTaskAssignee] = useState('all');
  const [newTaskPriority, setNewTaskPriority] = useState<'high' | 'medium' | 'low'>('medium');

  // ─── 태스크 폴링 (4초 간격) ───────────────────────────────────────────────────
  useEffect(() => {
    const fetchTasks = () => {
      fetch(`${API_BASE}/api/tasks`)
        .then(res => res.json())
        .then((data: Task[]) => {
          const list = Array.isArray(data) ? data : [];
          setTasks(list);

          // done을 제외한 활성 작업 수를 부모에게 보고합니다.
          const activeCount = list.filter(t => t.status !== 'done').length;
          onActiveCount(activeCount);
        })
        .catch((err) => console.error('[TasksPanel] fetch error:', err));
    };

    fetchTasks();
    const interval = setInterval(fetchTasks, 4000);
    return () => clearInterval(interval);
  // onActiveCount 레퍼런스는 매 렌더마다 변경될 수 있으므로 의존성 제외
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // ─── 새 작업 생성 ─────────────────────────────────────────────────────────────
  const createTask = () => {
    if (!newTaskTitle.trim()) return;

    fetch(`${API_BASE}/api/tasks`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        title: newTaskTitle,
        description: newTaskDesc,
        assigned_to: newTaskAssignee,
        priority: newTaskPriority,
        created_by: 'user',
      }),
    })
      .then(res => res.json())
      .then(() => {
        // 폼 초기화 및 목록 즉시 갱신
        setNewTaskTitle('');
        setNewTaskDesc('');
        setShowTaskForm(false);
        return fetch(`${API_BASE}/api/tasks`);
      })
      .then(res => res.json())
      .then((data: Task[]) => setTasks(Array.isArray(data) ? data : []))
      .catch((err) => console.error('[TasksPanel] fetch error:', err));
  };

  // ─── 작업 상태/필드 업데이트 ──────────────────────────────────────────────────
  const updateTask = (id: string, fields: Partial<Task>) => {
    fetch(`${API_BASE}/api/tasks/update`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ id, ...fields }),
    })
      .then(res => res.json())
      .then(() => fetch(`${API_BASE}/api/tasks`))
      .then(res => res.json())
      .then((data: Task[]) => setTasks(Array.isArray(data) ? data : []))
      .catch((err) => console.error('[TasksPanel] fetch error:', err));
  };

  // ─── 작업 삭제 ────────────────────────────────────────────────────────────────
  const deleteTask = (id: string) => {
    fetch(`${API_BASE}/api/tasks/delete`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ id }),
    })
      .then(res => res.json())
      .then(() => fetch(`${API_BASE}/api/tasks`))
      .then(res => res.json())
      .then((data: Task[]) => setTasks(Array.isArray(data) ? data : []))
      .catch((err) => console.error('[TasksPanel] fetch error:', err));
  };

  // ─── 필터 탭 메타 정보 ────────────────────────────────────────────────────────
  const filterTabs: { key: TaskFilterType; label: string }[] = [
    { key: 'all',         label: '전체' },
    { key: 'pending',     label: '할 일' },
    { key: 'in_progress', label: '진행' },
    { key: 'done',        label: '완료' },
  ];

  // ─── 현재 필터에 맞는 작업 목록 (최신순 역순 정렬) ───────────────────────────
  const filteredTasks = tasks
    .filter(t => taskFilter === 'all' || t.status === taskFilter)
    .slice()
    .reverse();

  // ─── 렌더링 ───────────────────────────────────────────────────────────────────
  return (
    <div className="flex-1 flex flex-col overflow-hidden gap-2">
      {/* 상태 필터 탭 */}
      <div className="flex gap-1 shrink-0">
        {filterTabs.map(({ key, label }) => {
          const count = key === 'all'
            ? tasks.length
            : tasks.filter(t => t.status === key).length;
          return (
            <button
              key={key}
              onClick={() => setTaskFilter(key)}
              className={`flex-1 py-1 rounded text-[9px] font-bold transition-colors ${
                taskFilter === key
                  ? 'bg-primary text-white'
                  : 'bg-white/5 text-[#858585] hover:text-white'
              }`}
            >
              {label}{count > 0 && ` (${count})`}
            </button>
          );
        })}
      </div>

      {/* 작업 목록 */}
      <div className="flex-1 overflow-y-auto space-y-1.5 custom-scrollbar">
        {filteredTasks.length === 0 ? (
          <div className="text-center text-[#858585] text-xs py-10 flex flex-col items-center gap-2 italic">
            <ClipboardList className="w-7 h-7 opacity-20" />
            작업이 없습니다
          </div>
        ) : (
          filteredTasks.map(task => {
            // 우선순위별 색상 도트 (이모지 활용)
            const priorityDot =
              task.priority === 'high'   ? '🔴' :
              task.priority === 'medium' ? '🟡' : '🟢';

            // 상태별 한글 레이블
            const statusLabel =
              task.status === 'pending'     ? '할 일' :
              task.status === 'in_progress' ? '진행 중' : '완료';

            return (
              <div
                key={task.id}
                className={`p-2 rounded border text-[10px] transition-colors ${
                  task.status === 'done'
                    ? 'border-white/5 opacity-50'
                    : 'border-white/10 hover:border-white/20'
                }`}
              >
                {/* 제목 + 우선순위 */}
                <div className="flex items-start gap-1.5 mb-1">
                  <span className="text-[11px] shrink-0">{priorityDot}</span>
                  <span
                    className={`font-bold flex-1 break-words leading-tight ${
                      task.status === 'done'
                        ? 'line-through text-[#858585]'
                        : 'text-[#cccccc]'
                    }`}
                  >
                    {task.title}
                  </span>
                </div>

                {/* 설명 (있을 경우에만 렌더링) */}
                {task.description && (
                  <p className="text-[#858585] text-[9px] mb-1.5 leading-relaxed pl-4">
                    {task.description}
                  </p>
                )}

                {/* 담당자 배지 + 상태 배지 */}
                <div className="flex items-center justify-between pl-4 mb-1.5">
                  <span
                    className={`px-1.5 py-0.5 rounded text-[8px] font-bold font-mono ${
                      task.assigned_to === 'claude'
                        ? 'bg-green-500/15 text-green-400' :
                      task.assigned_to === 'gemini'
                        ? 'bg-blue-500/15 text-blue-400' :
                      task.assigned_to === 'codex'
                        ? 'bg-orange-500/15 text-orange-400' :
                      task.assigned_to === 'all'
                        ? 'bg-yellow-500/15 text-yellow-400 border border-yellow-500/30' :
                      'bg-white/10 text-white/50'
                    }`}
                  >
                    {task.assigned_to}
                  </span>
                  <span
                    className={`text-[8px] font-bold px-1.5 py-0.5 rounded ${
                      task.status === 'pending'
                        ? 'bg-white/10 text-[#858585]' :
                      task.status === 'in_progress'
                        ? 'bg-primary/20 text-primary' :
                      'bg-green-500/20 text-green-400'
                    }`}
                  >
                    {statusLabel}
                  </span>
                </div>

                {/* 인라인 액션 버튼 */}
                <div className="flex gap-1 pl-4">
                  {/* 할 일 → 진행 시작 */}
                  {task.status === 'pending' && (
                    <button
                      onClick={() => updateTask(task.id, { status: 'in_progress' })}
                      className="flex-1 py-0.5 bg-primary/20 hover:bg-primary/40 text-primary rounded text-[9px] font-bold transition-colors"
                    >
                      ▶ 시작
                    </button>
                  )}

                  {/* 진행 중 → 완료 / 되돌리기 */}
                  {task.status === 'in_progress' && (
                    <>
                      <button
                        onClick={() => updateTask(task.id, { status: 'done' })}
                        className="flex-1 py-0.5 bg-green-500/20 hover:bg-green-500/40 text-green-400 rounded text-[9px] font-bold transition-colors"
                      >
                        ✅ 완료
                      </button>
                      <button
                        onClick={() => updateTask(task.id, { status: 'pending' })}
                        className="px-1.5 py-0.5 bg-white/5 hover:bg-white/10 text-[#858585] rounded text-[9px] transition-colors"
                      >
                        ↩
                      </button>
                    </>
                  )}

                  {/* 완료 → 다시 할 일로 */}
                  {task.status === 'done' && (
                    <button
                      onClick={() => updateTask(task.id, { status: 'pending' })}
                      className="flex-1 py-0.5 bg-white/5 hover:bg-white/10 text-[#858585] rounded text-[9px] transition-colors"
                    >
                      ↩ 다시
                    </button>
                  )}

                  {/* 코멘트 토글 버튼 */}
                  <button
                    onClick={() => toggleComments(task.id)}
                    className={`px-1.5 py-0.5 rounded text-[9px] transition-colors flex items-center gap-0.5 ${
                      expandedTaskId === task.id
                        ? 'bg-primary/20 text-primary'
                        : 'bg-white/5 hover:bg-white/10 text-[#858585]'
                    }`}
                    title="코멘트"
                  >
                    <MessageSquare className="w-2.5 h-2.5" />
                  </button>

                  {/* 삭제 버튼 (항상 표시) */}
                  <button
                    onClick={() => deleteTask(task.id)}
                    className="px-1.5 py-0.5 bg-red-500/10 hover:bg-red-500/25 text-red-400 rounded text-[9px] transition-colors"
                    title="삭제"
                  >
                    🗑️
                  </button>
                </div>

                {/* 코멘트 인라인 뷰 */}
                {expandedTaskId === task.id && (
                  <div className="mt-2 ml-4 border-l-2 border-primary/20 pl-2">
                    {loadingComments ? (
                      <p className="text-[9px] text-white/30 py-1">로딩...</p>
                    ) : comments.length === 0 ? (
                      <p className="text-[9px] text-white/25 py-1 italic">코멘트 없음</p>
                    ) : (
                      <div className="space-y-1 max-h-32 overflow-y-auto custom-scrollbar">
                        {comments.map(c => (
                          <div key={c.id} className="text-[9px]">
                            <span className={`font-bold ${
                              c.author.includes('claude') ? 'text-green-400' :
                              c.author.includes('gemini') ? 'text-blue-400' :
                              c.author.includes('codex') ? 'text-orange-400' :
                              'text-primary'
                            }`}>
                              {c.author}
                            </span>
                            <span className="text-white/20 ml-1">
                              {c.created_at?.split('T')[1]?.substring(0, 5) ?? ''}
                            </span>
                            <p className="text-white/60 leading-snug mt-0.5 whitespace-pre-wrap">
                              {c.content}
                            </p>
                          </div>
                        ))}
                      </div>
                    )}
                    {/* 코멘트 작성 */}
                    <div className="flex gap-1 mt-1">
                      <input
                        type="text"
                        value={newComment}
                        onChange={e => setNewComment(e.target.value)}
                        onKeyDown={e => { if (e.key === 'Enter') addComment(task.id); }}
                        placeholder="코멘트 작성..."
                        className="flex-1 bg-[#1e1e1e] border border-white/10 rounded px-1.5 py-0.5 text-[9px] focus:outline-none focus:border-primary text-white"
                      />
                      <button
                        onClick={() => addComment(task.id)}
                        disabled={!newComment.trim()}
                        className="px-1.5 py-0.5 bg-primary/20 hover:bg-primary/40 text-primary rounded text-[9px] disabled:opacity-30 transition-colors"
                      >
                        <Send className="w-2.5 h-2.5" />
                      </button>
                    </div>
                  </div>
                )}
              </div>
            );
          })
        )}
      </div>

      {/* 새 작업 추가 영역 */}
      {showTaskForm ? (
        <div className="border-t border-white/5 pt-2 flex flex-col gap-1.5 shrink-0">
          {/* 작업 제목 입력 (필수) */}
          <input
            type="text"
            value={newTaskTitle}
            onChange={e => setNewTaskTitle(e.target.value)}
            onKeyDown={e => {
              if (e.key === 'Enter') createTask();
              if (e.key === 'Escape') setShowTaskForm(false);
            }}
            placeholder="작업 제목 (필수)"
            autoFocus
            className="w-full bg-[#1e1e1e] border border-white/10 hover:border-white/30 rounded px-2 py-1.5 text-[10px] focus:outline-none focus:border-primary text-white transition-colors"
          />

          {/* 상세 설명 입력 (선택) */}
          <input
            type="text"
            value={newTaskDesc}
            onChange={e => setNewTaskDesc(e.target.value)}
            placeholder="상세 설명 (선택)"
            className="w-full bg-[#1e1e1e] border border-white/10 hover:border-white/30 rounded px-2 py-1.5 text-[10px] focus:outline-none focus:border-primary text-white transition-colors"
          />

          {/* 담당자 + 우선순위 선택 */}
          <div className="flex gap-1">
            <select
              value={newTaskAssignee}
              onChange={e => setNewTaskAssignee(e.target.value)}
              className="flex-1 bg-[#3c3c3c] border border-white/5 rounded px-1 py-1 text-[10px] focus:outline-none cursor-pointer"
            >
              <option value="all">All</option>
              <option value="claude">Claude</option>
              <option value="gemini">Gemini</option>
            </select>
            <select
              value={newTaskPriority}
              onChange={e => setNewTaskPriority(e.target.value as 'high' | 'medium' | 'low')}
              className="flex-1 bg-[#3c3c3c] border border-white/5 rounded px-1 py-1 text-[10px] focus:outline-none cursor-pointer"
            >
              <option value="high">🔴 높음</option>
              <option value="medium">🟡 보통</option>
              <option value="low">🟢 낮음</option>
            </select>
          </div>

          {/* 추가 / 취소 버튼 */}
          <div className="flex gap-1">
            <button
              onClick={createTask}
              disabled={!newTaskTitle.trim()}
              className="flex-1 py-1.5 bg-primary/80 hover:bg-primary disabled:opacity-30 text-white rounded text-[10px] font-bold transition-colors"
            >
              추가
            </button>
            <button
              onClick={() => setShowTaskForm(false)}
              className="px-3 py-1.5 bg-white/5 hover:bg-white/10 text-[#858585] rounded text-[10px] transition-colors"
            >
              취소
            </button>
          </div>
        </div>
      ) : (
        /* 폼이 닫힌 상태: 새 작업 추가 트리거 버튼 */
        <button
          onClick={() => setShowTaskForm(true)}
          className="shrink-0 w-full py-1.5 border border-dashed border-white/15 hover:border-primary/40 hover:bg-primary/5 rounded text-[10px] text-[#858585] hover:text-primary transition-colors flex items-center justify-center gap-1.5"
        >
          <Plus className="w-3 h-3" /> 새 작업 추가
        </button>
      )}
    </div>
  );
};

export default TasksPanel;
