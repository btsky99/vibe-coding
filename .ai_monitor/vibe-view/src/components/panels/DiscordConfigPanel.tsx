import React, { useState, useEffect } from 'react';
import { Save, RefreshCw, MessageSquare, ShieldCheck, Hash } from 'lucide-react';
import { API_BASE } from '../../constants';

interface DiscordConfig {
  token: string;
  channels: { [key: string]: string };
}

const DiscordConfigPanel: React.FC = () => {
  const [config, setConfig] = useState<DiscordConfig>({
    token: '',
    channels: Object.fromEntries(Array.from({ length: 8 }, (_, i) => [`T${i + 1}`, '']))
  });
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState<{ type: 'success' | 'error', text: string } | null>(null);

  useEffect(() => {
    fetchConfig();
  }, []);

  const fetchConfig = async () => {
    try {
      const response = await fetch(`${API_BASE}/api/config/discord`);
      if (response.ok) {
        const data = await response.json();
        // T1~T8만 필터링
        const filteredChannels: { [key: string]: string } = {};
        for (let i = 1; i <= 8; i++) {
          const key = `T${i}`;
          filteredChannels[key] = data.channels[key] || '';
        }
        setConfig({ token: data.token || '', channels: filteredChannels });
      }
    } catch (error) {
      console.error('Failed to fetch discord config:', error);
    } finally {
      setLoading(false);
    }
  };

  const handleSave = async () => {
    setSaving(true);
    setMessage(null);
    try {
      const response = await fetch(`${API_BASE}/api/config/discord`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(config),
      });
      if (response.ok) {
        setMessage({ type: 'success', text: '디스코드 설정이 성공적으로 저장되었습니다.' });
      } else {
        setMessage({ type: 'error', text: '설정 저장 중 오류가 발생했습니다.' });
      }
    } catch (error) {
      setMessage({ type: 'error', text: '서버와 통신할 수 없습니다.' });
    } finally {
      setSaving(false);
    }
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <RefreshCw className="w-8 h-8 animate-spin text-blue-500" />
      </div>
    );
  }

  return (
    <div className="p-6 max-w-4xl mx-auto bg-slate-900 rounded-xl border border-slate-800 shadow-2xl overflow-y-auto max-h-[85vh]">
      <div className="flex items-center justify-between mb-8 border-b border-slate-800 pb-4">
        <div className="flex items-center gap-3">
          <div className="p-2 bg-indigo-500/20 rounded-lg">
            <MessageSquare className="w-6 h-6 text-indigo-400" />
          </div>
          <div>
            <h2 className="text-xl font-bold text-white">Discord Bridge 설정</h2>
            <p className="text-sm text-slate-400">오픈클로 스타일 8채널 독립 터미널 연동</p>
          </div>
        </div>
        <button
          onClick={handleSave}
          disabled={saving}
          className="flex items-center gap-2 px-6 py-2 bg-indigo-600 hover:bg-indigo-500 disabled:bg-slate-700 text-white rounded-lg transition-all font-semibold shadow-lg shadow-indigo-500/20"
        >
          {saving ? <RefreshCw className="w-4 h-4 animate-spin" /> : <Save className="w-4 h-4" />}
          저장하기
        </button>
      </div>

      {message && (
        <div className={`mb-6 p-4 rounded-lg flex items-center gap-3 ${
          message.type === 'success' ? 'bg-emerald-500/10 border border-emerald-500/20 text-emerald-400' : 'bg-rose-500/10 border border-rose-500/20 text-rose-400'
        }`}>
          <div className={`w-2 h-2 rounded-full ${message.type === 'success' ? 'bg-emerald-500' : 'bg-rose-500'}`} />
          {message.text}
        </div>
      )}

      {/* Bot Token Section */}
      <section className="mb-10">
        <div className="flex items-center gap-2 mb-4">
          <ShieldCheck className="w-5 h-5 text-indigo-400" />
          <h3 className="text-lg font-semibold text-white">Bot Authentication</h3>
        </div>
        <div className="bg-slate-950 p-5 rounded-xl border border-slate-800">
          <label className="block text-sm font-medium text-slate-400 mb-2">Discord Bot Token</label>
          <input
            type="password"
            value={config.token}
            onChange={(e) => setConfig({ ...config, token: e.target.value })}
            placeholder="MTIzNDU2Nzg5MDEyMzQ1Njc4OQ..."
            className="w-full bg-slate-900 border border-slate-700 rounded-lg px-4 py-3 text-white focus:ring-2 focus:ring-indigo-500 focus:border-transparent outline-none transition-all font-mono text-sm"
          />
          <p className="mt-2 text-xs text-slate-500 leading-relaxed">
            Discord Developer Portal에서 발급받은 봇 토큰을 입력하세요. <br />
            보안을 위해 `.env` 파일에 안전하게 저장됩니다.
          </p>
        </div>
      </section>

      {/* Channels Section */}
      <section>
        <div className="flex items-center gap-2 mb-4">
          <Hash className="w-5 h-5 text-indigo-400" />
          <h3 className="text-lg font-semibold text-white">Terminal Channels (T1 - T8)</h3>
        </div>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {Array.from({ length: 8 }, (_, i) => {
            const tNum = `T${i + 1}`;
            return (
              <div key={tNum} className="bg-slate-950 p-4 rounded-xl border border-slate-800 flex flex-col gap-2">
                <div className="flex items-center justify-between">
                  <span className="text-xs font-bold text-indigo-400 uppercase tracking-wider">Terminal {i + 1}</span>
                  <span className="text-[10px] text-slate-600 font-mono">CHANNEL_ID</span>
                </div>
                <input
                  type="text"
                  value={config.channels[tNum] || ''}
                  onChange={(e) => {
                    const newChannels = { ...config.channels, [tNum]: e.target.value };
                    setConfig({ ...config, channels: newChannels });
                  }}
                  placeholder="Channel ID (18-19 digits)"
                  className="w-full bg-slate-900 border border-slate-700 rounded-lg px-4 py-2 text-white focus:ring-2 focus:ring-indigo-500 outline-none text-sm font-mono"
                />
              </div>
            );
          })}
        </div>
        <div className="mt-6 p-4 bg-blue-500/5 border border-blue-500/10 rounded-lg">
          <p className="text-xs text-blue-400/80 leading-relaxed flex items-start gap-2">
            <span className="mt-0.5">ℹ️</span>
            각 터미널 번호에 대응하는 디스코드 채널 ID를 입력하세요. 
          </p>
        </div>
      </section>
    </div>
  );
};

export default DiscordConfigPanel;
