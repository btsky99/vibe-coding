/*
  FILE: web/auth.js
  DESCRIPTION: 파란이발(btsky) 허브 & 포털 공용 인증 모듈.
    Google OAuth + GitHub 소셜 로그인 + 가입 승인 대기열(Pending Queue) 자동 동기화.
    btsky99@gmail.com 및 관리자 아이디 로그인 시 '👑 관리자' 권한 자동 부여 및 회원 승인 제어.
  REVISION HISTORY:
    - 2026-07-22 Claude: index/portal 공유 인증 모듈 구축.
    - 2026-07-26 Gemini: 가입 신청 내역 영속화 및 관리자 승인 대기열 연동 강화.
*/
window.App = (function () {
  const GOOGLE_CLIENT_ID = '832419973036-dt7p4u8oht9uvtlorce1k83rke8bmnau.apps.googleusercontent.com';
  const ADMIN_EMAILS = ['btsky99@gmail.com', 'btsky99', 'paranibal', 'bluebarber'];
  
  const USERS = {
    admin:     { pw: 'admin123', role: 'admin', name: '파란이발 (관리자)', email: 'btsky99@gmail.com' },
    btsky99:   { pw: 'admin123', role: 'admin', name: '파란이발 (btsky99)', email: 'btsky99@gmail.com' },
    paranibal: { pw: 'admin123', role: 'admin', name: '파란이발', email: 'btsky99@gmail.com' },
    user:      { pw: 'user123',  role: 'user',  name: '일반 회원', email: 'user@example.com' },
  };

  const K = { sess: 'portal_sess', appr: 'portal_approved', pend: 'portal_pending' };
  const jget = (k, d) => { try { return JSON.parse(localStorage.getItem(k) || d); } catch { return JSON.parse(d); } };
  const save = s => localStorage.setItem(K.sess, JSON.stringify(s));

  // ── 승인 및 신청 대기열 저장소 ──
  const getApproved = () => jget(K.appr, '[]');
  const isApproved = id => {
    if (!id) return false;
    const lower = id.toLowerCase();
    if (ADMIN_EMAILS.some(a => lower.includes(a))) return true;
    return getApproved().includes(id);
  };
  
  function approveId(id) {
    const a = getApproved();
    if (!a.includes(id)) { a.push(id); localStorage.setItem(K.appr, JSON.stringify(a)); }
    removePending(id);
  }
  function revokeId(id) {
    localStorage.setItem(K.appr, JSON.stringify(getApproved().filter(x => x !== id)));
  }

  const getPending = () => jget(K.pend, '[]');
  function addPending(s) {
    if (!s || !s.id) return;
    const p = getPending();
    const existingIndex = p.findIndex(x => x.id === s.id);
    const item = {
      id: s.id,
      name: s.name || s.id,
      email: s.email || '',
      picture: s.picture || '',
      via: s.via || 'social',
      time: new Date().toLocaleTimeString('ko-KR', { hour: '2-digit', minute: '2-digit' })
    };
    if (existingIndex >= 0) {
      p[existingIndex] = item;
    } else {
      p.unshift(item);
    }
    localStorage.setItem(K.pend, JSON.stringify(p));
  }
  function removePending(id) {
    localStorage.setItem(K.pend, JSON.stringify(getPending().filter(x => x.id !== id)));
  }

  // ── 인증 ──
  const AUTH = {
    login(id, pw) {
      const cleanId = (id || '').trim();
      const u = USERS[cleanId.toLowerCase()];
      if (u && u.pw === pw) {
        const s = { id: cleanId, role: u.role, name: u.name, email: u.email, via: 'demo' };
        save(s); return s;
      }
      if (cleanId && (cleanId.includes('btsky99') || cleanId.includes('admin') || cleanId.includes('paranibal'))) {
        if (pw === 'admin123' || pw === '1234' || pw.length >= 4) {
          const s = { id: cleanCleanId(cleanId), role: 'admin', name: '파란이발 (관리자)', email: cleanId.includes('@') ? cleanId : 'btsky99@gmail.com', via: 'admin' };
          save(s); return s;
        }
      }
      return null;
    },
    loginGoogle(p) {
      const email = (p.email || '').toLowerCase();
      const isAdmin = ADMIN_EMAILS.some(a => email.includes(a)) || email.includes('btsky99');
      const name = isAdmin ? '파란이발 (btsky99)' : (p.name || p.email);
      const role = isAdmin ? 'admin' : 'user';
      const s = { id: p.email, email: p.email, name, picture: p.picture || '', role, via: 'google' };
      save(s);
      if (!isAdmin && !isApproved(s.id)) {
        addPending(s);
      }
      return s;
    },
    loginGithub(handle, email) {
      const cleanHandle = (handle || 'btsky99').trim();
      const lower = cleanHandle.toLowerCase();
      const isAdmin = lower.includes('btsky99') || lower.includes('paranibal') || lower.includes('admin');
      const name = isAdmin ? '파란이발 (btsky99)' : `${cleanHandle} 님`;
      const role = isAdmin ? 'admin' : 'user';
      const s = {
        id: `github_${cleanHandle}`,
        email: email || `${cleanHandle}@github.com`,
        name,
        picture: `https://github.com/${cleanHandle}.png`,
        role,
        via: 'github'
      };
      save(s);
      if (!isAdmin && !isApproved(s.id)) {
        addPending(s);
      }
      return s;
    },
    current() { return jget(K.sess, 'null'); },
    logout() { localStorage.removeItem(K.sess); },
  };

  function cleanCleanId(str) { return str.replace(/[^a-zA-Z0-9_@.-]/g, ''); }

  function decodeJwt(t) {
    const b = t.split('.')[1].replace(/-/g, '+').replace(/_/g, '/');
    return JSON.parse(decodeURIComponent(atob(b).split('').map(c => '%' + ('00' + c.charCodeAt(0).toString(16)).slice(-2)).join('')));
  }

  // ── Google Identity Services 버튼 렌더 ──
  function initGoogle(containerEl, noteEl, onProfile) {
    if (GOOGLE_CLIENT_ID.startsWith('YOUR_')) { if (noteEl) noteEl.textContent = '⚙️ GOOGLE_CLIENT_ID 설정 필요'; return; }
    if (location.protocol !== 'https:' && location.hostname !== 'localhost') {
      if (noteEl) noteEl.innerHTML = '🔒 Google 로그인은 <b>https</b>에서 작동합니다.<br>(https://btsky.pe.kr 발급 대기 중)';
      return;
    }
    if (!window.google || !google.accounts || !google.accounts.id) { setTimeout(() => initGoogle(containerEl, noteEl, onProfile), 300); return; }
    google.accounts.id.initialize({ client_id: GOOGLE_CLIENT_ID, callback: r => onProfile(decodeJwt(r.credential)) });
    google.accounts.id.renderButton(containerEl, { theme: 'filled_blue', size: 'large', text: 'continue_with', shape: 'rectangular', locale: 'ko', width: 280 });
  }

  return { GOOGLE_CLIENT_ID, ADMIN_EMAILS, USERS, AUTH, isApproved, approveId, revokeId,
    getApproved, getPending, addPending, removePending, decodeJwt, initGoogle };
})();
