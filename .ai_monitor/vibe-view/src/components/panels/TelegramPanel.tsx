/**
 * FILE: TelegramPanel.tsx
 * DESCRIPTION: 텔레그램 브릿지 설정 패널. 이 PC의 이름(그룹방 표시용) · 봇 토큰 ·
 *              그룹 채팅 ID를 입력/저장하고, 브릿지 가동 상태를 표시한다.
 *
 * REVISION HISTORY:
 * - 2026-07-23 Claude: 다중 PC 대비 전면 개편.
 *   - PC 이름(TELEGRAM_PC_LABEL) 입력 신설 — 여러 PC가 한 그룹방에 발화할 때 출처 구분.
 *   - 그룹 채팅 ID 입력 신설 — 그룹방 필수값인데 UI에 없어 .env를 손으로 열어야 했음.
 *   - 봇 토큰을 "이 PC의 봇 1개" 중심으로 재배치. T2~T8은 고급 설정으로 접음
 *     (실사용이 PC당 2~3 터미널이고, 출처 표시가 메시지 기반이라 봇 1개로도 충분).
 * - 2026-03-23 Claude: 멀티봇 패턴으로 완전 재설계 (T1~T8 개별 봇 토큰)
 */

import { useState, useEffect } from 'react';
import { Save, CheckCircle2, AlertCircle, Smartphone, Bot, Monitor, Users, ChevronDown, ChevronRight } from 'lucide-react';
import { API_BASE } from '../../constants';

// 에이전트 이모지 + 색상 (T1~T8 고급 설정용)
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
  tokens: Record<string, string>;          // T1~T8 → bot token
  bot_statuses?: Record<string, string>;   // T1~T8 → "online"|"offline"
  pc_label: string;                        // 그룹방에서 이 PC를 부르는 이름
  group_chat_id: string;                   // 공유 그룹 채팅 ID
}

export default function TelegramPanel() {
  const [config, setConfig] = useState<TelegramConfig>({ tokens: {}, pc_label: '', group_chat_id: '' });
  const [saving, setSaving] = useState(false);
  const [msg, setMsg] = useState('');
  const [msgType, setMsgType] = useState<'success' | 'error'>('success');
  const [showAdvanced, setShowAdvanced] = useState(false);

  useEffect(() => {
    fetch(`${API_BASE}/api/config/telegram`)
      .then(r => r.json())
      .then(data => {
        setConfig({
          tokens: data.tokens || {},
          bot_statuses: data.bot_statuses || {},
          pc_label: data.pc_label || '',
          group_chat_id: data.group_chat_id || '',
        });
        // 저장된 토큰이 T1 외에도 있으면 고급 설정을 펼쳐 둔다(숨겨져 있으면
        // 사용자가 자기 설정을 못 찾는다).
        if (Object.keys(data.tokens || {}).some(k => k !== 'T1')) setShowAdvanced(true);
      })
      .catch(() => setMsg('서버 연결 실패'));
  }, []);

  const handleTokenChange = (tid: number, val: string) => {
    setConfig(prev => ({ ...prev, tokens: { ...prev.tokens, [`T${tid}`]: val } }));
  };

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
        setMsg('저장 완료 — 앱을 재시작하면 브릿지가 새 설정으로 연결됩니다.');
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

  const activeCount = Object.values(config.tokens).filter(t => t.trim()).length;
  const bridgeOnline = Object.values(config.bot_statuses || {}).some(s => s === 'online');
  const mainToken = config.tokens['T1'] || '';
  const groupReady = config.group_chat_id.trim().length > 0;

  return (
    <div className="h-full overflow-y-auto p-4 space-y-5">
      {/* 헤더 */}
      <div className="flex items-center gap-3">
        <Smartphone className="w-6 h-6 text-blue-400" />
        <h2 className="text-lg font-bold text-white">텔레그램 브릿지</h2>
        <span className={`text-xs px-2 py-0.5 rounded-full border ${
          bridgeOnline ? 'border-green-500/30 text-green-400' : 'border-gray-600 text-gray-500'}`}>
          {bridgeOnline ? '실행 중' : '중지됨'}
        </span>
      </div>

      {/* ── 이 PC 설정 ── */}
      <div className="space-y-3 p-3 rounded border border-[#333] bg-[#1e1e2e]">
        <div className="flex items-center gap-2">
          <Monitor className="w-4 h-4 text-blue-400" />
          <span className="text-sm font-medium text-gray-200">이 PC 설정</span>
        </div>

        {/* PC 이름 */}
        <div className="space-y-1">
          <label className="text-xs text-gray-400">PC 이름</label>
          <input
            type="text"
            value={config.pc_label}
            onChange={e => setConfig(p => ({ ...p, pc_label: e.target.value }))}
            placeholder="예: 데스크탑, 노트북, 회사PC"
            className="w-full px-2 py-1.5 bg-[#2d2d2d] border border-[#404040] rounded text-sm text-white
                       placeholder-gray-600 focus:border-blue-500 focus:outline-none"
          />
          <p className="text-[11px] text-gray-500">
            그룹방에서 <span className="text-gray-300">{config.pc_label || 'PC이름'}·T1(claude)</span> 형태로 표시됩니다.
            비워두면 표시하지 않습니다(PC 1대만 쓸 때).
          </p>
        </div>

        {/* 봇 토큰 */}
        <div className="space-y-1">
          <label className="text-xs text-gray-400">봇 토큰 <span className="text-gray-600">(이 PC 전용 1개)</span></label>
          <input
            type="password"
            value={mainToken}
            onChange={e => handleTokenChange(1, e.target.value)}
            placeholder="@BotFather에서 /newbot 으로 발급"
            className="w-full px-2 py-1.5 bg-[#2d2d2d] border border-[#404040] rounded text-sm text-white
                       placeholder-gray-600 focus:border-blue-500 focus:outline-none font-mono"
          />
          <p className="text-[11px] text-gray-500">
            PC마다 <span className="text-gray-300">서로 다른 봇</span>을 쓰세요. 같은 토큰을 두 PC에서 쓰면
            텔레그램이 한쪽 연결을 강제 종료합니다.
          </p>
        </div>

        {/* 그룹 채팅 ID */}
        <div className="space-y-1">
          <label className="text-xs text-gray-400">그룹 채팅 ID</label>
          <input
            type="text"
            value={config.group_chat_id}
            onChange={e => setConfig(p => ({ ...p, group_chat_id: e.target.value }))}
            placeholder="-1001234567890"
            className="w-full px-2 py-1.5 bg-[#2d2d2d] border border-[#404040] rounded text-sm text-white
                       placeholder-gray-600 focus:border-blue-500 focus:outline-none font-mono"
          />
          <p className="text-[11px] text-gray-500">
            모든 PC가 <span className="text-gray-300">같은 값</span>을 넣어야 한 방에 모입니다.
          </p>
        </div>
      </div>

      {/* ── 상태 ── */}
      <div className="space-y-2 p-3 rounded border border-[#333] bg-[#1e1e2e]">
        <div className="flex items-center gap-2">
          <Users className="w-4 h-4 text-blue-400" />
          <span className="text-sm font-medium text-gray-200">상태</span>
        </div>
        <div className="space-y-1 text-xs">
          <div className="flex items-center gap-2">
            <div className={`w-2 h-2 rounded-full ${bridgeOnline ? 'bg-green-400' : 'bg-gray-600'}`} />
            <span className="text-gray-400">브릿지</span>
            <span className={bridgeOnline ? 'text-green-400' : 'text-gray-500'}>
              {bridgeOnline ? '실행 중' : '중지됨 (앱 재시작 필요)'}
            </span>
          </div>
          <div className="flex items-center gap-2">
            <div className={`w-2 h-2 rounded-full ${activeCount ? 'bg-green-400' : 'bg-gray-600'}`} />
            <span className="text-gray-400">봇</span>
            <span className={activeCount ? 'text-green-400' : 'text-gray-500'}>{activeCount}개 설정됨</span>
          </div>
          <div className="flex items-center gap-2">
            <div className={`w-2 h-2 rounded-full ${groupReady ? 'bg-green-400' : 'bg-yellow-500'}`} />
            <span className="text-gray-400">그룹</span>
            <span className={groupReady ? 'text-green-400' : 'text-yellow-500'}>
              {groupReady ? '설정됨' : '미설정 — 그룹방 기능이 동작하지 않습니다'}
            </span>
          </div>
        </div>
        <p className="text-[11px] text-gray-500 border-t border-[#333] pt-2">
          다른 PC의 접속 여부는 <span className="text-gray-300">텔레그램 그룹방</span>에서 확인하세요 —
          각 PC가 켜지고 꺼질 때 🟢/🔴 메시지를 보냅니다.
        </p>
      </div>

      {/* ── 고급: 터미널별 봇 ── */}
      <div className="rounded border border-[#333] bg-[#1e1e2e]">
        <button
          onClick={() => setShowAdvanced(v => !v)}
          className="w-full flex items-center gap-2 p-3 text-left hover:bg-[#252535] transition-colors"
        >
          {showAdvanced ? <ChevronDown className="w-4 h-4 text-gray-400" /> : <ChevronRight className="w-4 h-4 text-gray-400" />}
          <Bot className="w-4 h-4 text-gray-400" />
          <span className="text-sm font-medium text-gray-300">고급 — 터미널별 봇 (선택)</span>
        </button>
        {showAdvanced && (
          <div className="px-3 pb-3 space-y-2">
            <p className="text-[11px] text-gray-500">
              터미널마다 다른 봇 아이콘으로 구분하고 싶을 때만 사용합니다. 대부분은 위의 봇 1개로 충분하며,
              메시지에 터미널 번호가 함께 표시됩니다.
            </p>
            {[2, 3, 4, 5, 6, 7, 8].map(tid => {
              const info = TERMINAL_INFO[tid];
              const val = config.tokens[`T${tid}`] || '';
              const hasToken = val.trim().length > 0;
              return (
                <div key={tid} className={`p-2 rounded border ${hasToken ? info.border : 'border-[#333]'} bg-[#252535] space-y-1`}>
                  <div className="flex items-center gap-2">
                    <div className={`w-2 h-2 rounded-full ${
                      config.bot_statuses?.[`T${tid}`] === 'online' ? 'bg-green-400' : hasToken ? 'bg-yellow-500' : 'bg-gray-600'}`} />
                    <span className={`text-xs font-bold font-mono ${info.color}`}>{info.emoji} T{tid}</span>
                    <span className="text-[11px] text-gray-500">{info.agent}</span>
                  </div>
                  <input
                    type="password"
                    value={val}
                    onChange={e => handleTokenChange(tid, e.target.value)}
                    placeholder={`T${tid} 봇 토큰`}
                    className="w-full px-2 py-1 bg-[#2d2d2d] border border-[#404040] rounded text-xs text-white
                               placeholder-gray-600 focus:border-blue-500 focus:outline-none font-mono"
                  />
                </div>
              );
            })}
          </div>
        )}
      </div>

      {/* 저장 */}
      <div className="flex gap-3">
        <button
          onClick={handleSave}
          disabled={saving}
          className="flex items-center gap-2 px-4 py-2 bg-blue-600 hover:bg-blue-500 disabled:bg-gray-700
                     disabled:text-gray-500 text-white text-sm rounded transition-colors"
        >
          <Save className="w-4 h-4" />
          {saving ? '저장 중...' : '저장'}
        </button>
      </div>

      {msg && (
        <div className={`flex items-center gap-2 px-3 py-2 rounded text-sm
          ${msgType === 'success' ? 'bg-green-500/10 text-green-400 border border-green-500/30' :
            'bg-red-500/10 text-red-400 border border-red-500/30'}`}
        >
          {msgType === 'success' ? <CheckCircle2 className="w-4 h-4" /> : <AlertCircle className="w-4 h-4" />}
          {msg}
        </div>
      )}

      {/* 도움말 */}
      <div className="p-3 bg-[#1a1a2e] rounded border border-[#333] text-xs text-gray-400 space-y-1">
        <p className="font-medium text-gray-300">📌 처음 설정하기</p>
        <p>1. 텔레그램에서 <span className="text-white">@BotFather</span> → /newbot 으로 이 PC용 봇 생성</p>
        <p>2. 발급 토큰을 <span className="text-white">봇 토큰</span>에 입력</p>
        <p>3. 텔레그램에 그룹을 만들고 그 봇을 초대 → 그룹 ID를 <span className="text-white">그룹 채팅 ID</span>에 입력</p>
        <p>4. <span className="text-white">PC 이름</span>을 알아보기 쉽게 지정 (PC 2대 이상일 때)</p>
        <p>5. 저장 후 앱 재시작 → 그룹방에 🟢 접속 메시지가 뜨면 성공</p>
        <p className="mt-2 text-gray-500 border-t border-[#333] pt-2">
          봇에게 <span className="text-white">/start</span>를 보내면 개인 채팅에서 1:1로 터미널을 조작할 수 있습니다.
        </p>
      </div>
    </div>
  );
}
