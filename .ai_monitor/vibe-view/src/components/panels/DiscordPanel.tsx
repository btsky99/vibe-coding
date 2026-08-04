/**
 * FILE: components/panels/DiscordPanel.tsx
 * DESCRIPTION: Discord 공용 봇 토큰과 현재 PC의 터미널별 채널 binding을 저장한다.
 *
 * REVISION HISTORY:
 * - 2026-08-04 Codex: 설정 패널 하단에 Bot Token과 서버·사용자·채널 ID 발급 안내 추가.
 * - 2026-08-03 Codex: 다중 Discord API 키 입력·추가·저장 UI 최초 구현.
 * - 2026-08-03 Codex: 공용 봇 1개 + Node ID + T1~T9 채널 ID 구조로 재설계.
 */
import { useEffect, useMemo, useState } from 'react';
import { AlertCircle, Bot, CheckCircle2, CirclePlus, Save, ShieldCheck, Trash2 } from 'lucide-react';
import { API_BASE } from '../../constants';

const DEFAULT_SLOTS = ['T1', 'T2', 'T3'];

const csv = (value: string) => value.split(',').map(item => item.trim()).filter(Boolean);

export default function DiscordPanel() {
  const [slots, setSlots] = useState<string[]>(DEFAULT_SLOTS);
  const [token, setToken] = useState('');
  const [tokenConfigured, setTokenConfigured] = useState(false);
  const [nodeId, setNodeId] = useState('');
  const [guildIds, setGuildIds] = useState('');
  const [userIds, setUserIds] = useState('');
  const [channels, setChannels] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState('');
  const [isError, setIsError] = useState(false);

  useEffect(() => {
    fetch(`${API_BASE}/api/config/discord`)
      .then(response => response.json())
      .then(data => {
        const savedChannels = data.channels && typeof data.channels === 'object' ? data.channels : {};
        setSlots(Array.from(new Set([...DEFAULT_SLOTS, ...Object.keys(savedChannels)]))
          .sort((a, b) => Number(a.slice(1)) - Number(b.slice(1))));
        setTokenConfigured(Boolean(data.token_configured));
        setNodeId(data.node_id || '');
        setGuildIds(Array.isArray(data.guild_ids) ? data.guild_ids.join(', ') : '');
        setUserIds(Array.isArray(data.user_ids) ? data.user_ids.join(', ') : '');
        setChannels(savedChannels);
      })
      .catch(() => { setMessage('Discord 설정을 불러오지 못했습니다.'); setIsError(true); });
  }, []);

  const nextSlot = useMemo(() => {
    for (let id = 4; id <= 9; id += 1) if (!slots.includes(`T${id}`)) return `T${id}`;
    return null;
  }, [slots]);

  const removeSlot = (slot: string) => {
    setSlots(previous => previous.filter(value => value !== slot));
    setChannels(previous => { const next = { ...previous }; delete next[slot]; return next; });
  };

  const save = async () => {
    setSaving(true); setMessage(''); setIsError(false);
    try {
      const activeChannels = Object.fromEntries(
        slots.map(slot => [slot, (channels[slot] || '').trim()]).filter(([, value]) => value),
      );
      const response = await fetch(`${API_BASE}/api/config/discord`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          token, node_id: nodeId.trim(), guild_ids: csv(guildIds), user_ids: csv(userIds),
          channels: activeChannels,
        }),
      });
      const data = await response.json();
      if (!response.ok || data.status !== 'saved') throw new Error(data.error || '저장 실패');
      setTokenConfigured(Boolean(data.token_configured)); setToken('');
      setChannels(data.channels || {});
      setMessage('저장 완료 — 앱을 재시작하면 공용 Discord Gateway가 시작됩니다.');
    } catch (error) {
      setIsError(true); setMessage(error instanceof Error ? error.message : '저장 실패');
    } finally { setSaving(false); }
  };

  return (
    <div className="h-full overflow-y-auto p-4 space-y-4">
      <div className="flex items-center gap-2">
        <Bot className="w-6 h-6 text-indigo-400" />
        <h2 className="text-lg font-bold text-white">Discord 연결 설정</h2>
      </div>
      <div className="flex gap-2 rounded border border-indigo-500/20 bg-indigo-500/5 p-3 text-xs text-gray-400">
        <ShieldCheck className="w-4 h-4 shrink-0 text-green-400" />
        봇은 전체에서 하나만 사용하고, 이 PC의 각 터미널을 Discord 채널 ID로 구분합니다.
        토큰은 Windows 사용자 계정으로 암호화되며 다시 표시되지 않습니다.
      </div>

      <section className="space-y-3 rounded border border-[#3a3a3a] bg-[#252535] p-3">
        <label className="block text-xs text-gray-400">공용 Bot Token</label>
        <div className="flex items-center gap-2">
          <input type="password" value={token} onChange={event => setToken(event.target.value)}
            placeholder={tokenConfigured ? '새 토큰을 입력하면 교체됩니다' : 'Discord Bot Token'}
            autoComplete="new-password"
            className="min-w-0 flex-1 rounded border border-[#454545] bg-[#1e1e1e] px-2 py-1.5 font-mono text-xs text-white placeholder-gray-600 focus:border-indigo-500 focus:outline-none" />
          <span className={`shrink-0 text-[11px] ${tokenConfigured ? 'text-green-400' : 'text-gray-500'}`}>
            {tokenConfigured ? '● 저장됨' : '○ 미설정'}
          </span>
        </div>
        <label className="block text-xs text-gray-400">PC 이름 (Node ID)</label>
        <input value={nodeId} onChange={event => setNodeId(event.target.value)} placeholder="예: pc1, desktop-a"
          className="w-full rounded border border-[#454545] bg-[#1e1e1e] px-2 py-1.5 font-mono text-xs text-white focus:border-indigo-500 focus:outline-none" />
        <label className="block text-xs text-gray-400">Discord 서버 ID</label>
        <input value={guildIds} onChange={event => setGuildIds(event.target.value)} placeholder="여러 개면 쉼표로 구분"
          className="w-full rounded border border-[#454545] bg-[#1e1e1e] px-2 py-1.5 font-mono text-xs text-white focus:border-indigo-500 focus:outline-none" />
        <label className="block text-xs text-gray-400">허용할 내 Discord 사용자 ID</label>
        <input value={userIds} onChange={event => setUserIds(event.target.value)} placeholder="여러 명이면 쉼표로 구분"
          className="w-full rounded border border-[#454545] bg-[#1e1e1e] px-2 py-1.5 font-mono text-xs text-white focus:border-indigo-500 focus:outline-none" />
      </section>

      <section className="space-y-2">
        <h3 className="text-sm font-semibold text-gray-200">터미널별 Discord 채널 ID</h3>
        {slots.map(slot => (
          <div key={slot} className="flex items-center gap-2 rounded border border-[#3a3a3a] bg-[#252535] p-3">
            <span className="w-8 font-mono text-sm font-bold text-indigo-300">{slot}</span>
            <input value={channels[slot] || ''}
              onChange={event => setChannels(previous => ({ ...previous, [slot]: event.target.value }))}
              placeholder={`${slot}에 연결할 채널 ID`}
              className="min-w-0 flex-1 rounded border border-[#454545] bg-[#1e1e1e] px-2 py-1.5 font-mono text-xs text-white placeholder-gray-600 focus:border-indigo-500 focus:outline-none" />
            {Number(slot.slice(1)) >= 4 && (
              <button onClick={() => removeSlot(slot)} className="p-1 text-gray-500 hover:text-red-400" title={`${slot} 제거`}>
                <Trash2 className="w-4 h-4" />
              </button>
            )}
          </div>
        ))}
      </section>

      <div className="flex gap-2">
        {nextSlot && <button onClick={() => setSlots(previous => [...previous, nextSlot])}
          className="flex items-center gap-2 rounded border border-[#444] px-3 py-2 text-sm text-gray-300 hover:bg-white/5">
          <CirclePlus className="w-4 h-4" /> {nextSlot} 추가
        </button>}
        <button onClick={save} disabled={saving}
          className="flex items-center gap-2 rounded bg-indigo-600 px-4 py-2 text-sm text-white hover:bg-indigo-500 disabled:bg-gray-700">
          <Save className="w-4 h-4" /> {saving ? '저장 중…' : '저장'}
        </button>
      </div>
      {message && <div className={`flex items-center gap-2 rounded border p-3 text-sm ${isError ? 'border-red-500/30 bg-red-500/10 text-red-400' : 'border-green-500/30 bg-green-500/10 text-green-400'}`}>
        {isError ? <AlertCircle className="w-4 h-4" /> : <CheckCircle2 className="w-4 h-4" />}{message}
      </div>}

      <section className="space-y-3 rounded border border-indigo-500/20 bg-indigo-500/5 p-4 text-xs leading-relaxed text-gray-300">
        <h3 className="text-sm font-bold text-white">Discord 값 만드는 방법</h3>
        <ol className="list-decimal space-y-3 pl-5">
          <li>
            <span className="font-semibold text-indigo-300">공용 Bot Token</span>
            <div className="mt-1 text-gray-400">
              <a href="https://discord.com/developers/applications" target="_blank" rel="noreferrer"
                className="text-indigo-300 underline hover:text-indigo-200">Discord Developer Portal</a>
              에서 <b>New Application</b> → 이름 입력 → <b>Bot</b> → <b>Reset Token</b>을 누르고 나온 값을 복사합니다.
              같은 Bot 화면에서 <b>Message Content Intent</b>도 켭니다. 토큰은 비밀번호이므로 다른 사람에게 보내거나 화면에 공개하지 마세요.
            </div>
          </li>
          <li>
            <span className="font-semibold text-indigo-300">봇을 서버에 초대</span>
            <div className="mt-1 text-gray-400">
              Developer Portal의 <b>OAuth2 → URL Generator</b>에서 <b>bot</b>을 선택하고
              <b>View Channels, Send Messages, Read Message History</b> 권한을 선택한 뒤 생성된 주소를 열어 서버에 추가합니다.
            </div>
          </li>
          <li>
            <span className="font-semibold text-indigo-300">개발자 모드 켜기</span>
            <div className="mt-1 text-gray-400">
              Discord의 <b>사용자 설정 → 고급 → 개발자 모드</b>를 켭니다. 아래 ID 복사 메뉴는 개발자 모드를 켜야 나타납니다.
            </div>
          </li>
          <li>
            <span className="font-semibold text-indigo-300">서버 ID</span>
            <div className="mt-1 text-gray-400">왼쪽 서버 아이콘을 우클릭 → <b>서버 ID 복사</b>.</div>
          </li>
          <li>
            <span className="font-semibold text-indigo-300">사용자 ID</span>
            <div className="mt-1 text-gray-400">내 프로필이나 사용자 이름을 우클릭 → <b>사용자 ID 복사</b>.</div>
          </li>
          <li>
            <span className="font-semibold text-indigo-300">채널 ID</span>
            <div className="mt-1 text-gray-400">
              연결할 텍스트 채널을 우클릭 → <b>채널 ID 복사</b>. T1, T2, T3 입력칸에 서로 다른 채널 ID를 넣으면 각 터미널과 분리됩니다.
            </div>
          </li>
        </ol>
        <div className="rounded border border-amber-500/20 bg-amber-500/5 p-2 text-amber-200/80">
          모두 입력한 뒤 <b>저장</b>하고 Vibe Coding 앱을 재시작해야 Discord Gateway가 연결됩니다.
        </div>
      </section>
    </div>
  );
}
