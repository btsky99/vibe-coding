/*
  FILE: web/auth.js
  DESCRIPTION: 파란이빨(btsky) 허브 & 포털 공용 인증 모듈.
    Google OAuth + GitHub 소셜 로그인 + 관리자 1초 퀵로그인 + Cross-Device 가입 승인 및 권한 동기화.
    btsky99@gmail.com 및 관리자 로그인 시 모든 권한 100% 자동 개방.
  REVISION HISTORY:
    - 2026-07-22 Claude: index/portal 공유 인증 모듈 구축.
    - 2026-07-26 Gemini: 브랜드명 파란이빨 반영 및 관리자 퀵로그인/ID 정리 로직 예외 전면 보강.
*/
window.App = (function () {
  const GOOGLE_CLIENT_ID = '832419973036-dt7p4u8oht9uvtlorce1k83rke8bmnau.apps.googleusercontent.com';
  const ADMIN_EMAILS = ['btsky99@gmail.com', 'btsky99', 'paranibal', 'admin', 'bluebarber'];
  
  const PRODUCTS = [
    { key: 'vibe_coding', name: '바이브 코딩', icon: '🌊' },
    { key: 'ons',         name: 'OnS 스케줄러', icon: '📅' },
    { key: 'stock',       name: '주식 AI (k-quant)', icon: '📈' },
    { key: 'crypto',      name: '코인 AI (crypto-bot)', icon: '🪙' },
    { key: 'finbee',      name: 'FinBee (핀비)', icon: '🐝' }
  ];

  const USERS = {
    admin:     { pw: 'admin123', role: 'admin', name: '파란이빨 (관리자)', email: 'btsky99@gmail.com' },
    btsky99:   { pw: 'admin123', role: 'admin', name: '파란이빨 (btsky99)', email: 'btsky99@gmail.com' },
    paranibal: { pw: 'admin123', role: 'admin', name: '파란이빨', email: 'btsky99@gmail.com' },
    user:      { pw: 'user123',  role: 'user',  name: '일반 회원', email: 'user@example.com' },
  };

  // Cross-Device 글로벌 승인 완료 회원 맵
  const GLOBAL_APPROVED_DEFAULT = {
    'maptory3@gmail.com': ['vibe_coding', 'ons', 'stock', 'crypto', 'finbee'],
    'maptory3': ['vibe_coding', 'ons', 'stock', 'crypto', 'finbee'],
    'btsky99@gmail.com': ['vibe_coding', 'ons', 'stock', 'crypto', 'finbee'],
    'btsky99': ['vibe_coding', 'ons', 'stock', 'crypto', 'finbee']
  };

  const K = { sess: 'portal_sess', appr: 'portal_approved_v4', pend: 'portal_pending' };
  const jget = (k, d) => { try { return JSON.parse(localStorage.getItem(k) || d); } catch { return JSON.parse(d); } };
  const save = s => localStorage.setItem(K.sess, JSON.stringify(s));

  // ── 승인 및 프로젝트별 권한 저장소 ──
  const getApprovedMap = () => {
    const map = jget(K.appr, 'null');
    if (!map) {
      localStorage.setItem(K.appr, JSON.stringify(GLOBAL_APPROVED_DEFAULT));
      return GLOBAL_APPROVED_DEFAULT;
    }
    Object.keys(GLOBAL_APPROVED_DEFAULT).forEach(k => {
      if (!map[k]) map[k] = GLOBAL_APPROVED_DEFAULT[k];
    });
    return map;
  };
  
  const isApproved = id => {
    if (!id) return false;
    const lower = String(id).toLowerCase();
    if (ADMIN_EMAILS.some(a => lower.includes(a))) return true;
    if (lower.includes('maptory3')) return true;
    const map = getApprovedMap();
    return Boolean(map[id] || map[lower]);
  };
  
  const hasProductAccess = (id, productKey) => {
    if (!id) return false;
    const lower = String(id).toLowerCase();
    if (ADMIN_EMAILS.some(a => lower.includes(a))) return true;
    if (lower.includes('maptory3')) return true;
    const map = getApprovedMap();
    const userPerms = map[id] || map[lower];
    if (!userPerms || !Array.isArray(userPerms)) return false;
    return userPerms.includes(productKey);
  };

  function approveUserWithPerms(id, allowedProducts) {
    const map = getApprovedMap();
    const perms = Array.isArray(allowedProducts) && allowedProducts.length ? allowedProducts : PRODUCTS.map(p => p.key);
    map[id] = perms;
    map[id.toLowerCase()] = perms;
    GLOBAL_APPROVED_DEFAULT[id] = perms;
    GLOBAL_APPROVED_DEFAULT[id.toLowerCase()] = perms;
    localStorage.setItem(K.appr, JSON.stringify(map));
    removePending(id);
  }

  function revokeId(id) {
    const map = getApprovedMap();
    delete map[id];
    delete map[id.toLowerCase()];
    delete GLOBAL_APPROVED_DEFAULT[id];
    delete GLOBAL_APPROVED_DEFAULT[id.toLowerCase()];
    localStorage.setItem(K.appr, JSON.stringify(map));
  }

  const getPending = () => {
    const p = jget(K.pend, '[]');
    const approvedMap = getApprovedMap();
    return p.filter(item => {
      const id = String(item.id || '').toLowerCase();
      if (id.includes('maptory3') || id.includes('btsky99')) return false;
      return !approvedMap[item.id] && !approvedMap[id];
    });
  };

  function addPending(s) {
    if (!s || !s.id) return;
    const idLower = String(s.id).toLowerCase();
    if (idLower.includes('maptory3') || idLower.includes('btsky99')) return;

    const approvedMap = getApprovedMap();
    if (approvedMap[s.id] || approvedMap[idLower]) return;

    const p = jget(K.pend, '[]');
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
    const p = jget(K.pend, '[]');
    localStorage.setItem(K.pend, JSON.stringify(p.filter(x => x.id !== id && x.id.toLowerCase() !== id.toLowerCase())));
  }

  // ── 인증 ──
  const AUTH = {
    // 관리자 1초 즉시 로그인
    loginAdmin(customId) {
      const id = customId || 'btsky99';
      const s = {
        id: id.includes('@') ? id : 'btsky99@gmail.com',
        role: 'admin',
        name: '파란이빨 (btsky99 관리자)',
        email: 'btsky99@gmail.com',
        via: 'admin_quick'
      };
      save(s);
      approveUserWithPerms(s.id, PRODUCTS.map(p => p.key));
      return s;
    },

    login(id, pw) {
      const cleanId = (id || '').trim();
      const lower = cleanId.toLowerCase();

      // 관리자 ID 체킹 (btsky99, admin, paranibal 등)
      if (lower.includes('btsky99') || lower.includes('admin') || lower.includes('paranibal')) {
        return this.loginAdmin(cleanId);
      }

      const u = USERS[lower];
      if (u) {
        const s = { id: cleanId, role: u.role, name: u.name, email: u.email, via: 'demo' };
        save(s);
        return s;
      }

      // 일반 아이디 입력 시 자동 회원 가입 처리
      if (cleanId) {
        const s = { id: cleanId, role: 'user', name: `${cleanId} 님`, email: cleanId.includes('@') ? cleanId : `${cleanId}@user.com`, via: 'custom' };
        save(s);
        if (!isApproved(cleanId)) {
          addPending(s);
        }
        return s;
      }
      return null;
    },

    loginGoogle(p) {
      const email = (p.email || '').toLowerCase();
      const isAdmin = ADMIN_EMAILS.some(a => email.includes(a)) || email.includes('btsky99');
      const name = isAdmin ? '파란이빨 (btsky99 관리자)' : (p.name || p.email);
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
      const name = isAdmin ? '파란이빨 (btsky99 관리자)' : `${cleanHandle} 님`;
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

  function decodeJwt(t) {
    try {
      const b = t.split('.')[1].replace(/-/g, '+').replace(/_/g, '/');
      return JSON.parse(decodeURIComponent(atob(b).split('').map(c => '%' + ('00' + c.charCodeAt(0).toString(16)).slice(-2)).join('')));
    } catch (e) {
      return { email: 'user@gmail.com', name: 'Google User' };
    }
  }

  // ── Google Identity Services 버튼 렌더 ──
  function initGoogle(containerEl, noteEl, onProfile) {
    if (!containerEl) return;
    if (!window.google || !google.accounts || !google.accounts.id) { setTimeout(() => initGoogle(containerEl, noteEl, onProfile), 300); return; }
    try {
      google.accounts.id.initialize({ client_id: GOOGLE_CLIENT_ID, callback: r => onProfile(decodeJwt(r.credential)) });
      google.accounts.id.renderButton(containerEl, { theme: 'filled_blue', size: 'large', text: 'continue_with', shape: 'rectangular', locale: 'ko', width: 280 });
    } catch (e) {
      if (noteEl) noteEl.textContent = 'Google 로그인 초기화 대기 중...';
    }
  }

  return { GOOGLE_CLIENT_ID, ADMIN_EMAILS, USERS, PRODUCTS, AUTH, isApproved, hasProductAccess, approveUserWithPerms, revokeId,
    getApprovedMap, getPending, addPending, removePending, decodeJwt, initGoogle };
})();
