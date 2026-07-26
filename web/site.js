/*
  FILE: web/site.js
  DESCRIPTION: btsky.pe.kr 공용 사이트 글루 — 로그인 모달 주입 + 역할별 내비 + 다운로드
    로그인 게이트 + FAQ 아코디언 토글 + 마이크로 인터랙션을 window.Site로 노출.
    경로: window.SITE_BASE(루트='./', 하위페이지='../')로 portal/home 링크를 상대 계산.
    인증 로직은 auth.js(window.App). Google 로그인은 https에서만(http는 안내).
  REVISION HISTORY:
    - 2026-07-22 Claude: 멀티 프로덕트 허브 개편.
    - 2026-07-26 Gemini: FAQ 아코디언 토글, 마이크로 스포트라이트 애니메이션 유틸리티 추가.
*/
(function () {
  const BASE = window.SITE_BASE || './';
  const portalUrl = BASE + 'portal/';
  const homeUrl = BASE;
  let pendingAction = 'portal';   // 'portal' | 'download'
  let pendingDlUrl = '';
  let gInited = false;

  // ── 로그인 모달 주입 ──
  function injectModal() {
    if (document.getElementById('loginOverlay')) return;
    const el = document.createElement('div');
    el.className = 'overlay'; el.id = 'loginOverlay';
    el.innerHTML = `
      <div class="modal">
        <button class="x" aria-label="닫기">&times;</button>
        <div class="mlogo">🧩</div>
        <h2>btsky 로그인</h2>
        <div class="msub">로그인하고 계속 진행하세요</div>
        <form id="loginForm">
          <label for="muid">아이디</label>
          <input id="muid" autocomplete="username" placeholder="아이디">
          <label for="mpw">비밀번호</label>
          <input id="mpw" type="password" autocomplete="current-password" placeholder="비밀번호">
          <button class="go-btn" type="submit">로그인</button>
          <div class="merr" id="merr"></div>
        </form>
        <div class="mdiv">또는</div>
        <div id="mgwrap"></div>
        <div id="mgnote"></div>
      </div>`;
    document.body.appendChild(el);
    el.addEventListener('click', e => { if (e.target === el) closeLogin(); });
    el.querySelector('.x').addEventListener('click', closeLogin);
    document.getElementById('loginForm').addEventListener('submit', doLogin);
    document.addEventListener('keydown', e => { if (e.key === 'Escape') closeLogin(); });
  }

  function openLogin(intent) {
    pendingAction = intent === 'download' ? 'download' : 'portal';
    injectModal();
    document.getElementById('loginOverlay').classList.add('open');
    document.getElementById('muid').focus();
    if (!gInited) {
      gInited = true;
      App.initGoogle(document.getElementById('mgwrap'), document.getElementById('mgnote'),
        profile => { App.AUTH.loginGoogle(profile); afterLogin(); });
    }
  }
  function closeLogin() {
    const o = document.getElementById('loginOverlay');
    if (o) { o.classList.remove('open'); document.getElementById('merr').textContent = ''; }
  }
  function afterLogin() {
    if (pendingAction === 'download' && pendingDlUrl) { pendingAction = 'portal'; closeLogin(); location.href = pendingDlUrl; }
    else location.href = portalUrl;
  }
  function doLogin(e) {
    e.preventDefault();
    const s = App.AUTH.login(document.getElementById('muid').value.trim(), document.getElementById('mpw').value);
    if (!s) { document.getElementById('merr').textContent = '아이디 또는 비밀번호가 올바르지 않습니다.'; return false; }
    afterLogin(); return false;
  }
  function logout() { App.AUTH.logout(); renderNav(); }

  // ── 역할별 내비 (#navR에 채움) ──
  function renderNav(featuresHref) {
    const r = document.getElementById('navR');
    if (!r) return;
    const s = App.AUTH.current();
    const feat = featuresHref ? `<a class="nlink" href="${featuresHref}">기능</a>` : '';
    const home = (BASE !== './') ? `<a class="nlink" href="${homeUrl}">← 허브</a>` : '';
    if (!s) {
      r.innerHTML = home + feat +
        `<button class="nlink" onclick="Site.openLogin()">로그인</button>` +
        `<button class="nlink solid" onclick="Site.openLogin()">회원가입</button>`;
    } else if (s.role === 'admin') {
      r.innerHTML = home + feat +
        `<a class="nlink solid" href="${portalUrl}">👑 관리자 페이지</a>` +
        `<button class="nlink" onclick="Site.logout()">로그아웃</button>`;
    } else {
      r.innerHTML = home + feat +
        `<span class="nlink" style="cursor:default">${s.name} 님</span>` +
        `<button class="nlink" onclick="Site.logout()">로그아웃</button>`;
    }
  }

  // ── 다운로드 로그인 게이트 ──
  function gateDownload(url) {
    if (App.AUTH.current()) { location.href = url; }
    else { pendingDlUrl = url; openLogin('download'); }
  }
  function isLoggedIn() { return !!App.AUTH.current(); }

  // ── FAQ 아코디언 토글 유틸리티 ──
  function toggleFaq(el) {
    const item = el.closest('.faq-item');
    if (!item) return;
    item.classList.toggle('open');
  }

  window.Site = { openLogin, closeLogin, logout, renderNav, gateDownload, isLoggedIn, toggleFaq };
})();
