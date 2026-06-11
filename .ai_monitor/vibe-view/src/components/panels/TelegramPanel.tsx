/**
 * FILE: TelegramPanel.tsx
 * DESCRIPTION: 텔레그램 멀티봇 브릿지 설정 패널.
 *              터미널당 1봇 (최대 8개) + 그룹채팅 ID를 입력/저장하는 UI 제공.
 *              각 봇의 연결 상태를 개별 표시합니다.
 *
 * REVISION HISTORY:
 * - 2026-03-23 Claude: 멀티봇 패턴으로 완전 재설계
 *   - 단일 토큰 → T1~T8 개별 봇 토큰 입력
 *   - 그룹 채팅 ID 입력 추가
 *   - 각 봇별 연결 상태 표시
 */

import { useState, useEffect } from 'react';
import { Save, RefreshCw, CheckCircle2, AlertCircle, Smartphone, Bot } from 'lucide-react';
import { API_BASE } from '../../constants';

// 에이전트 이모지 + 색상 + 이름
const TERMINAL_INFO: Record<number, { emoji: string; agent: string; color: string; border: string }> = {
  1: { emoji: '🤖', agent: 'Claude', color: 'text-purple-400', border: 'border-purple-500/30' },
  2: { emoji: '🟢', agent: 'Antigravity', color: 'text-emerald-400', border: 'border-emerald-500/30' },
  3: { emoji: '🤖', agent: 'Claude', color: 'text-purple-400', border: 'border-purple-500/30' },
  4: { emoji: '🟢', agent: 'Antigravity', color: 'text-emerald-400', border: 'border-emerald-500/30' },
  5: { emoji: '🔵', agent: 'Codex', color: 'text-cyan-400', border: 'border-cyan-500/30' },
  6: { emoji: '🤖', agent: 'Claude', color: 'text-purple-400', border: 'border-purple-500/30' },
  7: { emoji: '🟢', agent: 'Antigravity', color: 'text-emerald-400', border: 'border-emerald-500/30' },
  8: { emoji: '🔵', agent: 'Codex', color: 'text-cyan-400', border: 'border-cyan-500/30' },
};

interface TelegramConfig {
  tokens: Record<string, string>; // T1~T8 → bot token
  bot_statuses?: Record<string, string>; // T1~T8 → "online"|"offline"
}

export default function TelegramPanel() {
  const [config, setConfig] = useState<TelegramConfig>({ tokens: {} });
  const [saving, setSaving] = useState(false);
  const [msg, setMsg] = useState('');
  const [msgType, setMsgType] = useState<'success' | 'error'>('success');

  // 설정 로드
  useEffect(() => {
    fetch(`${API_BASE}/api/config/telegram`)
      .then(r => r.json())
      .then(data => {
        setConfig({
          tokens: data.tokens || {},
          bot_statuses: data.bot_statuses || {},
        });
      })
      .catch(() => setMsg('서버 연결 실패'));
  }, []);

  // 봇 토큰 변경
  const handleTokenChange = (tid: number, val: string) => {
    setConfig(prev => ({
      ...prev,
      tokens: { ...prev.tokens, [`T${tid}`]: val },
    }));
  };

  // 저장
  const handleSave = async () => {
    setSaving(true);
    setMsg('');
    try {
      const res = await fetch(`${API_BASE}/api/config/telegram`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(config),
      });
      const data = await res.json();
      if (data.status === 'saved') {
        setMsg('저장 완료! 서버를 재시작하면 봇들이 자동 연결됩니다.');
        setMsgType('success');
      } else {
        setMsg(data.error || '저장 실패');
        setMsgType('error');
      }
    } catch {
      setMsg('서버 연결 실패');
      setMsgType('error');
    }
    setSaving(false);
  };

  // 활성 봇 수 계산
  const activeCount = Object.values(config.tokens).filter(t => t.trim()).length;

  return (
    <div className="h-full overflow-y-auto p-4 space-y-6">
      {/* 헤더 */}
      <div className="flex items-center gap-3">
        <Smartphone className="w-6 h-6 text-blue-400" />
        <h2 className="text-lg font-bold text-white">Telegram Multi-Bot Bridge</h2>
        <span className="text-xs px-2 py-0.5 rounded-full border border-blue-500/30 text-blue-400">
          {activeCount}봇 설정됨
        </span>
      </div>

      <p className="text-sm text-gray-400">
        각 터미널이 독립된 텔레그램 봇으로 존재합니다. 개인 채팅에서 1:1 모니터링합니다.
      </p>

      {/* T1~T8 봇 토큰 */}
      <div className="space-y-2">
        <div className="flex items-center gap-2">
          <Bot className="w-4 h-4 text-gray-400" />
          <label className="text-sm font-medium text-gray-300">터미널별 봇 토큰</label>
        </div>
        <p className="text-xs text-gray-500">
          @BotFather에서 /newbot으로 각 터미널용 봇 생성 후 토큰 입력
        </p>
        <div className="space-y-2">
          {[1, 2, 3, 4, 5, 6, 7, 8].map(tid => {
            const info = TERMINAL_INFO[tid];
            const val = config.tokens[`T${tid}`] || '';
            const status = config.bot_statuses?.[`T${tid}`];
            const isOnline = status === 'online';
            const hasToken = val.trim().length > 0;

            return (
              <div
                key={tid}
                className={`p-2.5 rounded border ${hasToken ? info.border : 'border-[#333]'} bg-[#1e1e2e] space-y-1.5`}
              >
                <div className="flex items-center gap-2">
                  {/* 상태 표시등 */}
                  <div className={`w-2 h-2 rounded-full ${isOnline ? 'bg-green-400' : hasToken ? 'bg-yellow-500' : 'bg-gray-600'}`} />
                  <span className={`text-sm font-bold font-mono ${info.color}`}>
                    {info.emoji} T{tid}
                  </span>
                  <span className="text-xs text-gray-500">{info.agent}</span>
                  {isOnline && (
                    <span className="text-xs text-green-400 ml-auto">online</span>
                  )}
                </div>
                <input
                  type="password"
                  value={val}
                  onChange={e => handleTokenChange(tid, e.target.value)}
                  placeholder={`T${tid} 봇 토큰 (BotFather에서 발급)`}
                  className="w-full px-2 py-1.5 bg-[#2d2d2d] border border-[#404040] rounded text-xs text-white
                             placeholder-gray-600 focus:border-blue-500 focus:outline-none font-mono"
                />
              </div>
            );
          })}
        </div>
      </div>

      {/* 저장 버튼 */}
      <div className="flex gap-3">
        <button
          onClick={handleSave}
          disabled={saving || activeCount === 0}
          className="flex items-center gap-2 px-4 py-2 bg-blue-600 hover:bg-blue-500 disabled:bg-gray-700
                     disabled:text-gray-500 text-white text-sm rounded transition-colors"
        >
          <Save className="w-4 h-4" />
          {saving ? '저장 중...' : '저장'}
        </button>
      </div>

      {/* 메시지 */}
      {msg && (
        <div className={`flex items-center gap-2 px-3 py-2 rounded text-sm
          ${msgType === 'success' ? 'bg-green-500/10 text-green-400 border border-green-500/30' :
            'bg-red-500/10 text-red-400 border border-red-500/30'}`}
        >
          {msgType === 'success' ? <CheckCircle2 className="w-4 h-4" /> : <AlertCircle className="w-4 h-4" />}
          {msg}
        </div>
      )}

      {/* 도움말: 봇 생성 */}
      <div className="mt-4 p-3 bg-[#1a1a2e] rounded border border-[#333] text-xs text-gray-400 space-y-1">
        <p className="font-medium text-gray-300">📌 Step 1: 봇 생성 (터미널당 1개)</p>
        <p>1. 텔레그램에서 <span className="text-white">@BotFather</span> 검색 → /newbot 전송</p>
        <p>2. 봇 이름 예: <span className="text-white">VibeCoding_T1</span>, VibeCoding_T2, ...</p>
        <p>3. 발급받은 토큰을 위 T{'{N}'} 필드에 입력</p>
        <p>4. 사용할 터미널 수만큼 반복 (최대 8개)</p>
      </div>

      {/* 도움말: 개인 채팅 */}
      <div className="p-3 bg-[#1a1a2e] rounded border border-[#333] text-xs text-gray-400 space-y-1">
        <p className="font-medium text-gray-300">📌 Step 2: 개인 채팅 (1:1 모니터링)</p>
        <p>1. 생성한 봇(예: @VibeCoding_T1_bot)에게 텔레그램에서 <span className="text-white">/start</span> 전송</p>
        <p>2. 그러면 해당 터미널의 PTY 출력이 실시간으로 이 채팅에 스트리밍됩니다</p>
        <p>3. 채팅에 텍스트를 보내면 해당 터미널에 명령이 입력됩니다</p>
      </div>

      {/* 도움말: 저장 및 실행 */}
      <div className="p-3 bg-[#1a1a2e] rounded border border-[#333] text-xs text-gray-400 space-y-1">
        <p className="font-medium text-gray-300">📌 Step 4: 저장 및 실행</p>
        <p>1. 위 내용 모두 입력 후 <span className="text-white">저장</span> 클릭 → .env에 자동 기록</p>
        <p>2. 서버 재시작하면 봇들이 자동 연결됩니다</p>
        <p className="mt-2 text-gray-500 border-t border-[#333] pt-2">
          <span className="text-blue-400">개인 채팅:</span> 각 봇에게 /start → 해당 터미널의 PTY 출력을 실시간 수신
        </p>
      </div>
    </div>
  );
}
