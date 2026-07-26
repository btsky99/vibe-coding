/*
  FILE: web/site.js
  DESCRIPTION: 파란이발(btsky) 공용 사이트 스크립트 — 구글 & 깃허브 소셜 로그인 모달,
    파란이발 브랜딩 내비게이션, 다운로드 로그인 게이트, FAQ 토글 지원.
  REVISION HISTORY:
    - 2026-07-22 Claude: 멀티 프로덕트 허브 내비/모달 공용화.
    - 2026-07-26 Gemini: 파란이발(btsky99) 브랜딩, Google & GitHub 소셜 가입 통합.
*/
(function () {
  const BASE = window.SITE_BASE || './';
  const portalUrl = BASE + 'portal/';
  const homeUrl = BASE;
  let pendingAction = 'portal';
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
        <div class="mlogo">💈</div>
        <h2>파란이발 로그인</h2>
        <div class="msub">구글 / 깃허브 소셜 계정 또는 아이디로 시작하세요</div>

        <!-- 소셜 가입/로그인 영역 -->
        <div class="social-btns">
          <div id="mgwrap"></div>
          <button type="button" class="btn-github-social" onclick="Site.promptGithub()">
            <svg height="18" width="18" viewBox="0 0 16 16" fill="currentColor"><path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.28.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.013 8.013 0 0016 8c0-4.42-3.58-8-8-8z"/></svg>
            <span>GitHub 계정으로 계속하기</span>
          </button>
        </div>
        <div id="mgnote"></div>

        <div class="mdiv">또는 아이디 로그인</div>

        <form id="loginForm">
          <label for="muid">아이디 (관리자: btsky99)</label>
          <input id="muid" autocomplete="username" placeholder="아이디 입력 (예: btsky99)">
          <label for="mpw">비밀번호</label>
          <input id="mpw" type="password" autocomplete="current-password" placeholder="비밀번호 (예: admin123)">
          <button class="go-btn" type="submit">로그인 / 시작하기</button>
          <div class="merr" id="merr"></div>
        </form>
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

  function promptGithub() {
    const handle = prompt('GitHub 아이디(유저네임)를 입력해 주세요:', 'btsky99');
    if (handle) {
      App.AUTH.loginGithub(handle);
      afterLogin();
    }
  }

  function closeLogin() {
    const o = document.getElementById('loginOverlay');
    if (o) { o.classList.remove('open'); document.getElementById('merr').textContent = ''; }
  }

  function afterLogin() {
    if (pendingAction === 'download' && pendingDlUrl) {
      pendingAction = 'portal';
      closeLogin();
      location.href = pendingDlUrl;
    } else {
      location.href = portalUrl;
    }
  }

  function doLogin(e) {
    e.preventDefault();
    const uid = document.getElementById('muid').value.trim();
    const pw = document.getElementById('mpw').value;
    const s = App.AUTH.login(uid, pw);
    if (!s) {
      document.getElementById('merr').textContent = '아이디 또는 비밀번호가 올바르지 않습니다. (관리자: btsky99 / admin123)';
      return false;
    }
    afterLogin();
    return false;
  }

  function logout() {
    App.AUTH.logout();
    renderNav();
  }

  // ── 역할별 내비 (#navR에 채움) ──
  function renderNav(featuresHref) {
    const r = document.getElementById('navR');
    if (!r) return;
    const s = App.AUTH.current();
    const feat = featuresHref ? `<a class="nlink" href="${featuresHref}">기능</a>` : '';
    const home = (BASE !== './') ? `<a class="nlink" href="${homeUrl}">← 파란이발 허브</a>` : '';
    
    if (!s) {
      r.innerHTML = home + feat +
        `<button class="nlink" onclick="Site.openLogin()">로그인</button>` +
        `<button class="nlink solid" onclick="Site.openLogin()">시작하기 / 가입</button>`;
    } else if (s.role === 'admin' || (s.id && (s.id.includes('btsky99') || s.id.includes('paranibal')))) {
      r.innerHTML = home + feat +
        `<a class="nlink solid" href="${portalUrl}">👑 파란이발 관리자</a>` +
        `<button class="nlink" onclick="Site.logout()">로그아웃</button>`;
    } else {
      r.innerHTML = home + feat +
        `<span class="nlink" style="cursor:default">${s.name}</span>` +
        `<a class="nlink" href="${portalUrl}">내 계정</a>` +
        `<button class="nlink" onclick="Site.logout()">로그아웃</button>`;
    }
  }

  // ── 다운로드 로그인 게이트 ──
  function gateDownload(url) {
    if (App.AUTH.current()) { location.href = url; }
    else { pendingDlUrl = url; openLogin('download'); }
  }

  function isLoggedIn() { return !!App.AUTH.current(); }

  // ── FAQ 토글 유틸리티 ──
  function toggleFaq(el) {
    const item = el.closest('.faq-item');
    if (!item) return;
    item.classList.toggle('open');
  }

  window.Site = { openLogin, promptGithub, closeLogin, logout, renderNav, gateDownload, isLoggedIn, toggleFaq };
})();
