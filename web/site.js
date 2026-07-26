/*
  FILE: web/site.js
  DESCRIPTION: 파란이발(btsky) 공용 사이트 스크립트 — 소셜 로그인 모달,
    관리자 전용 소스코드 보안 게이트, 전체 설치 전용 릴리즈(v22.6.3 .exe+.bin) & 패치 릴리즈 독립 이원화 파서.
  REVISION HISTORY:
    - 2026-07-22 Claude: 멀티 프로덕트 허브 내비/모달 공용화.
    - 2026-07-26 Gemini: 전체 설치 전용 태그(v22.6.3) 고정 유지 및 패치 릴리즈 독립 이원화 파싱 지원.
*/
(function () {
  const BASE = window.SITE_BASE || './';
  const portalUrl = BASE + 'portal/';
  const homeUrl = BASE;
  let pendingAction = 'portal';
  let pendingDlUrl = '';
  let gInited = false;

  // ── 로그인 모달 ──
  function injectModal() {
    if (document.getElementById('loginOverlay')) return;
    const el = document.createElement('div');
    el.className = 'overlay'; el.id = 'loginOverlay';
    el.innerHTML = `
      <div class="modal">
        <button class="x" aria-label="닫기">&times;</button>
        <div class="mlogo">💈</div>
        <h2>파란이발 로그인</h2>
        <div class="msub">소셜 계정으로 1초 만에 시작하세요</div>

        <div class="social-btns">
          <div id="mgwrap"></div>
          <button type="button" class="btn-github-social" onclick="Site.promptGithub()">
            <svg height="18" width="18" viewBox="0 0 16 16" fill="currentColor"><path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.28.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.013 8.013 0 0016 8c0-4.42-3.58-8-8-8z"/></svg>
            <span>GitHub 계정으로 시작하기</span>
          </button>
        </div>
        <div id="mgnote"></div>
      </div>`;
    document.body.appendChild(el);
    el.addEventListener('click', e => { if (e.target === el) closeLogin(); });
    el.querySelector('.x').addEventListener('click', closeLogin);
    document.addEventListener('keydown', e => { if (e.key === 'Escape') closeLogin(); });
  }

  function openLogin(intent) {
    pendingAction = intent === 'download' ? 'download' : 'portal';
    injectModal();
    document.getElementById('loginOverlay').classList.add('open');
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
    if (o) { o.classList.remove('open'); }
  }

  function afterLogin() {
    if (pendingAction === 'download' && pendingDlUrl) {
      const target = pendingDlUrl;
      pendingAction = 'portal';
      pendingDlUrl = '';
      closeLogin();
      location.href = target;
    } else {
      location.href = portalUrl;
    }
  }

  function logout() {
    App.AUTH.logout();
    location.reload();
  }

  // ── 역할별 내비 ──
  function renderNav(featuresHref) {
    const r = document.getElementById('navR');
    if (!r) return;
    const s = App.AUTH.current();
    const feat = featuresHref ? `<a class="nlink" href="${featuresHref}">기능</a>` : '';
    const home = (BASE !== './') ? `<a class="nlink" href="${homeUrl}">← 파란이발 허브</a>` : '';
    
    if (!s) {
      r.innerHTML = home + feat +
        `<button class="nlink solid" onclick="Site.openLogin()">소셜 로그인 / 가입</button>`;
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
    renderAdminGates();
  }

  // ── 보안 게이트: 소스코드 링크는 오직 '관리자(admin/btsky99)'에게만 보임 ──
  function renderAdminGates() {
    const s = App.AUTH.current();
    const isAdmin = s && (s.role === 'admin' || (s.id && (s.id.includes('btsky99') || s.id.includes('paranibal'))));
    document.querySelectorAll('.admin-only-source').forEach(el => {
      const srcUrl = el.getAttribute('data-src-url');
      if (isAdmin) {
        el.href = srcUrl;
        el.target = '_blank';
        el.rel = 'noopener';
        el.innerHTML = `<span>👑 소스코드 (관리자 전용)</span>`;
        el.style.opacity = '1';
        el.onclick = null;
      } else {
        el.removeAttribute('href');
        el.removeAttribute('target');
        el.innerHTML = `<span>🔒 소스코드 (관리자 전용)</span>`;
        el.style.opacity = '0.7';
        el.onclick = (e) => {
          e.preventDefault();
          alert('🔒 소스코드 저장소는 파란이발 관리자(btsky99) 로그인 후에만 접근 가능합니다.');
          openLogin();
        };
      }
    });
  }

  // ── 다운로드 게이트 ──
  function gateDownload(url) {
    if (!url) url = portalUrl;
    if (App.AUTH.current()) {
      location.href = url;
    } else {
      pendingDlUrl = url;
      openLogin('download');
    }
  }

  function isLoggedIn() { return !!App.AUTH.current(); }

  // ── FAQ 토글 ──
  function toggleFaq(el) {
    const item = el.closest('.faq-item');
    if (!item) return;
    item.classList.toggle('open');
  }

  // ── GitHub Releases 파서 (전체 설치 전용 v22.6.3 vs 패치 이원화 관리) ──
  function parseReleases(repo, fullElId, patchElId, verElId, fallbackFullUrl, fallbackPatchUrl) {
    const fmt = b => { if (!b) return ''; const mb = b / 1048576; return mb >= 1 ? mb.toFixed(1) + ' MB' : (b / 1024).toFixed(0) + ' KB'; };
    
    // 기본 전체 설치 전용 태그 URL (패치 업데이트에 무관하게 항상 v22.6.3 설치본 지목)
    const defaultFull = fallbackFullUrl || (repo.includes('crypto') 
      ? 'https://github.com/btsky99/crypto-bot-releases/releases/tag/v22.6.3' 
      : `https://github.com/${repo}/releases/latest`);
      
    const defaultPatch = fallbackPatchUrl || `https://github.com/${repo}/releases`;

    const fullEl = document.getElementById(fullElId);
    if (fullEl) {
      fullEl.onclick = () => gateDownload(defaultFull);
    }
    const patchEl = document.getElementById(patchElId);
    if (patchEl) {
      patchEl.onclick = () => gateDownload(defaultPatch);
    }

    // 전체 설치버전은 v22.6.3 고정 파싱 시도
    if (repo.includes('crypto')) {
      fetch(`https://api.github.com/repos/btsky99/crypto-bot-releases/releases/tags/v22.6.3`, { headers: { 'Accept': 'application/vnd.github+json' } })
        .then(r => { if (!r.ok) throw 0; return r.json(); })
        .then(rel => {
          if (verElId) {
            const vEl = document.getElementById(verElId);
            if (vEl) vEl.innerHTML = `전체 설치버전 <b>v22.6.3</b> (CipherTrader_Setup_v22.6.3.exe + .bin 1~4) & 패치채널 독립 관리`;
          }
          const assets = rel.assets || [];
          const setupExe = assets.find(x => /CipherTrader_Setup.*\.exe$/i.test(x.name)) || assets[0];
          if (fullEl && setupExe) {
            fullEl.onclick = () => gateDownload(setupExe.browser_download_url);
            const szEl = fullEl.querySelector('small');
            if (szEl) szEl.textContent = `CipherTrader_Setup_v22.6.3.exe (${fmt(setupExe.size)})`;
          }
        })
        .catch(() => {
          if (verElId) {
            const vEl = document.getElementById(verElId);
            if (vEl) vEl.innerHTML = `전체 설치버전 <b>v22.6.3</b> (CipherTrader_Setup_v22.6.3.exe + .bin 1~4)`;
          }
        });
    } else {
      // 바이브 코딩 등 일반 레포지토리 파싱
      fetch(`https://api.github.com/repos/${repo}/releases/latest`, { headers: { 'Accept': 'application/vnd.github+json' } })
        .then(r => { if (!r.ok) throw 0; return r.json(); })
        .then(rel => {
          if (verElId) {
            const vEl = document.getElementById(verElId);
            if (vEl) vEl.innerHTML = `현재 최신 버전 <b>${rel.tag_name || 'v1.0.0'}</b> (실시간 자동 갱신)`;
          }
          const assets = rel.assets || [];
          const fullAsset = assets.find(x => /setup|installer|full|\.exe$/i.test(x.name)) || assets[0];
          if (fullEl && fullAsset) {
            fullEl.onclick = () => gateDownload(fullAsset.browser_download_url);
            const szEl = fullEl.querySelector('small');
            if (szEl) szEl.textContent = `전체 설치 (.exe) · ${fmt(fullAsset.size)}`;
          }
        })
        .catch(() => {});
    }
  }

  window.Site = { openLogin, promptGithub, closeLogin, logout, renderNav, gateDownload, isLoggedIn, toggleFaq, parseReleases };
})();
