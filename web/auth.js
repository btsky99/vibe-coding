/*
  FILE: web/auth.js
  DESCRIPTION: 랜딩(index.html 로그인 모달) + 포털(portal/index.html 대시보드) 공용 인증/데이터 모듈.
    중복 제거를 위해 로그인·승인·데이터 로직을 한 곳에 모아 window.App으로 노출한다.
    [정적 한계] 세션·승인상태 = localStorage(브라우저 전용). 실사용(교차 사용자)은 Supabase 승격.
    [보안] 데모 비번은 더미값. client_secret은 GIS에 불필요 — 절대 포함 금지(공개 client_id만).
  REVISION HISTORY:
    - 2026-07-22 Claude: index/portal 공유 모듈로 분리(로그인 모달화 + 데모박스 제거 리팩터).
*/
window.App = (function () {
  // [SUPABASE 승격 지점] 아래 GOOGLE_CLIENT_ID/USERS/AUTH/PROJECTS를 supabase.auth/DB+RLS로 교체.
  const GOOGLE_CLIENT_ID = '832419973036-dt7p4u8oht9uvtlorce1k83rke8bmnau.apps.googleusercontent.com';
  const ADMIN_EMAILS = ['btsky99@gmail.com'];
  const USERS = {
    admin: { pw: 'admin123', role: 'admin', name: '관리자' },
    user:  { pw: 'user123',  role: 'user',  name: '유진수' },
  };
  const K = { sess: 'portal_sess', appr: 'portal_approved', pend: 'portal_pending' };
  const jget = (k, d) => { try { return JSON.parse(localStorage.getItem(k) || d); } catch { return JSON.parse(d); } };
  const save = s => localStorage.setItem(K.sess, JSON.stringify(s));

  // ── 승인 저장소 ──
  const getApproved = () => jget(K.appr, '[]');
  const isApproved = id => getApproved().includes(id);
  function approveId(id) { const a = getApproved(); if (!a.includes(id)) { a.push(id); localStorage.setItem(K.appr, JSON.stringify(a)); } removePending(id); }
  function revokeId(id) { localStorage.setItem(K.appr, JSON.stringify(getApproved().filter(x => x !== id))); }
  const getPending = () => jget(K.pend, '[]');
  function addPending(s) { const p = getPending(); if (!p.find(x => x.id === s.id)) { p.push({ id: s.id, name: s.name, email: s.email || '', via: s.via }); localStorage.setItem(K.pend, JSON.stringify(p)); } }
  function removePending(id) { localStorage.setItem(K.pend, JSON.stringify(getPending().filter(x => x.id !== id))); }

  // ── 인증 ──
  const AUTH = {
    login(id, pw) { const u = USERS[id]; if (u && u.pw === pw) { const s = { id, role: u.role, name: u.name, via: 'demo' }; save(s); return s; } return null; },
    loginGoogle(p) { const role = ADMIN_EMAILS.includes((p.email || '').toLowerCase()) ? 'admin' : 'user';
      const s = { id: p.email, email: p.email, name: p.name || p.email, picture: p.picture || '', role, via: 'google' }; save(s); return s; },
    current() { return jget(K.sess, 'null'); },
    logout() { localStorage.removeItem(K.sess); },
  };
  function decodeJwt(t) { const b = t.split('.')[1].replace(/-/g, '+').replace(/_/g, '/');
    return JSON.parse(decodeURIComponent(atob(b).split('').map(c => '%' + ('00' + c.charCodeAt(0).toString(16)).slice(-2)).join(''))); }

  // ── Google Identity Services 버튼 렌더 (컨테이너 element + 콜백 주입) ──
  function initGoogle(containerEl, noteEl, onProfile) {
    if (GOOGLE_CLIENT_ID.startsWith('YOUR_')) { if (noteEl) noteEl.textContent = '⚙️ GOOGLE_CLIENT_ID 설정 후 활성화'; return; }
    // [승인 오류 방지] GIS는 https 필수(localhost 예외). http 원본은 승인된 원본 목록에 없어
    //   Google이 '승인 오류'를 띄운다 → 버튼 대신 안내로 대체해 혼란 방지.
    if (location.protocol !== 'https:' && location.hostname !== 'localhost') {
      if (noteEl) noteEl.innerHTML = '🔒 Google 로그인은 <b>https</b> 연결에서만 가능합니다.<br>인증서 발급 후 <b>https://btsky.pe.kr</b> 에서 이용하세요.';
      return;
    }
    if (!window.google || !google.accounts || !google.accounts.id) { setTimeout(() => initGoogle(containerEl, noteEl, onProfile), 300); return; }
    google.accounts.id.initialize({ client_id: GOOGLE_CLIENT_ID, callback: r => onProfile(decodeJwt(r.credential)) });
    google.accounts.id.renderButton(containerEl, { theme: 'outline', size: 'large', text: 'signin_with', shape: 'pill', locale: 'ko', width: 300 });
  }

  return { GOOGLE_CLIENT_ID, ADMIN_EMAILS, USERS, AUTH, isApproved, approveId, revokeId,
    getApproved, getPending, addPending, removePending, decodeJwt, initGoogle };
})();
