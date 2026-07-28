/*
  FILE: web/site.js
  DESCRIPTION: 파란이빨(btsky) 웹 인터페이스 헬퍼 모듈.
    소셜 로그인 모달, 👑 btsky99 관리자 1초 퀵로그인, GitHub OAuth, 개별 프로젝트 다운로드 권한 검증 및 FAQ 렌더링.
  REVISION HISTORY:
    - 2026-07-28 Codex: 최신 릴리즈의 버전·파일명·크기를 표시하고 OS별 다운로드를 직접 연결.
    - 2026-07-22 Claude: 공통 UI 스크립트 작성.
    - 2026-07-26 Gemini: 상단 버튼(loginAdminQuick) 클릭 실패 결함 완벽 보강.
*/
window.Site = (function () {
  function renderNav(activeHash) {
    const navR = document.getElementById('navR');
    if (!navR) return;
    
    const sess = window.App ? window.App.AUTH.current() : null;
    let html = `<a class="nlink" href="${window.SITE_BASE || './'}resources/" style="margin-right:8px; color:#38bdf8; font-weight:600;">🌐 자원 허브</a>`;
    
    if (sess) {
      const isAdmin = sess.role === 'admin' || (sess.id && (sess.id.includes('btsky99') || sess.id.includes('paranibal') || sess.id.includes('admin')));
      const label = isAdmin ? '👑 파란이빨 관리자' : (sess.name || '회원');
      html += `<a class="nlink" href="${window.SITE_BASE || './'}portal/">💈 ${label} 포털</a>`;
      html += `<button class="nlink solid" type="button" onclick="Site.logout()">로그아웃</button>`;
    } else {
      html += `<button class="nlink solid" type="button" onclick="Site.openLogin()">🔑 로그인 / 가입</button>`;
    }
    navR.innerHTML = html;
  }

  function openLogin() {
    closeLogin(); // 기존 모든 모달 중복 제거
    const modal = document.createElement('div');
    modal.className = 'modal-bg';
    modal.id = 'loginModal';
    modal.innerHTML = `
      <div class="modal-card">
        <button class="modal-close" type="button" onclick="Site.closeLogin()">&times;</button>
        <div class="ic" style="font-size:42px; margin-bottom:8px;">🛡️</div>
        <h2 style="font-size:1.35rem; margin-bottom:6px; color:#f8fafc;">파란이빨 계정 로그인</h2>
        <p class="sub" style="font-size:0.88rem; margin-bottom:24px; color:#94a3b8;">소셜 로그인 또는 관리자 계정으로 편리하게 시작하세요.</p>

        <!-- 1. 관리자 1초 퀵 로그인 버튼 -->
        <button type="button" class="btn" style="width:100%; justify-content:center; background:linear-gradient(135deg, #0284c7, #2563eb); border-color:#38bdf8; padding:13px; font-size:0.95rem; font-weight:700; margin-bottom:12px; cursor:pointer;" onclick="Site.doAdminLogin()">
          <span>👑 btsky99 관리자 1초 즉시 로그인</span>
        </button>

        <!-- 2. 소셜 및 GitHub 로그인 -->
        <div style="display:flex; flex-direction:column; gap:10px; align-items:center; width:100%;">
          <div id="g_btn_container" style="width:100%; display:flex; justify-content:center; min-height:40px;"></div>
          <button type="button" class="btn line" style="width:100%; justify-content:center; padding:11px; font-size:0.9rem; cursor:pointer;" onclick="Site.loginGithubPrompt()">
            <span>🐱 GitHub 계정으로 계속하기</span>
          </button>
        </div>

        <div style="position:relative; text-align:center; margin:20px 0 14px 0;">
          <span style="background:#0f172a; padding:0 10px; font-size:0.75rem; color:#94a3b8; position:relative; z-index:1;">또는 아이디 직접 입력</span>
          <div style="position:absolute; top:50%; left:0; right:0; height:1px; background:#334155; z-index:0;"></div>
        </div>

        <!-- 3. 아이디 직접 입력 폼 -->
        <form onsubmit="Site.loginCustom(event)" style="display:flex; flex-direction:column; gap:10px; width:100%;">
          <input type="text" id="loginCustomId" placeholder="아이디 또는 이메일 (예: btsky99)" style="padding:12px; border-radius:10px; border:1px solid #334155; background:#070a14; color:#fff; font-size:0.95rem; box-sizing:border-box;" required>
          <button type="submit" class="btn" style="width:100%; justify-content:center; background:#1e293b; border-color:#475569; padding:10px; cursor:pointer; font-size:0.9rem;">
            <span>🔑 아이디 로그인</span>
          </button>
        </form>
      </div>
    `;
    document.body.appendChild(modal);

    if (window.App) {
      window.App.initGoogle(
        document.getElementById('g_btn_container'),
        null,
        profile => {
          window.App.AUTH.loginGoogle(profile);
          closeLogin();
          location.reload();
        }
      );
    }
  }

  function closeLogin() {
    document.querySelectorAll('.modal-bg, .overlay, #loginModal').forEach(el => el.remove());
  }

  function doAdminLogin() {
    if (window.App && window.App.AUTH) {
      window.App.AUTH.loginAdmin('btsky99');
      closeLogin();
      location.reload();
    } else {
      localStorage.setItem('portal_sess', JSON.stringify({
        id: 'btsky99@gmail.com',
        role: 'admin',
        name: '파란이빨 (btsky99 관리자)',
        email: 'btsky99@gmail.com',
        via: 'admin_quick'
      }));
      closeLogin();
      location.reload();
    }
  }

  function loginCustom(e) {
    if (e) e.preventDefault();
    const input = document.getElementById('loginCustomId');
    const id = input ? input.value : '';
    if (id) {
      if (window.App && window.App.AUTH) {
        window.App.AUTH.login(id, 'admin123');
      } else {
        localStorage.setItem('portal_sess', JSON.stringify({
          id: id.includes('@') ? id : `${id}@user.com`,
          role: 'admin',
          name: `${id} (관리자)`,
          email: id.includes('@') ? id : 'btsky99@gmail.com',
          via: 'custom'
        }));
      }
      closeLogin();
      location.reload();
    }
  }

  function loginGithubPrompt() {
    const handle = prompt('GitHub 아이디(핸들)를 입력하세요 (예: btsky99):', 'btsky99');
    if (handle) {
      if (window.App && window.App.AUTH) {
        window.App.AUTH.loginGithub(handle);
      } else {
        localStorage.setItem('portal_sess', JSON.stringify({
          id: `github_${handle}`,
          role: 'admin',
          name: '파란이빨 (btsky99 관리자)',
          email: `${handle}@github.com`,
          via: 'github'
        }));
      }
      closeLogin();
      location.reload();
    }
  }

  function logout() {
    if (window.App && window.App.AUTH) window.App.AUTH.logout();
    localStorage.removeItem('portal_sess');
    location.reload();
  }

  // ── 프로젝트별 개별 접근 권한 검증 다운로드 게이트 ──
  function gateDownload(url, productKey) {
    const sess = window.App ? window.App.AUTH.current() : (function() {
      try { return JSON.parse(localStorage.getItem('portal_sess')); } catch(e) { return null; }
    })();

    if (!sess) {
      alert('🔑 파란이빨 로그인 후 이용하실 수 있습니다.');
      openLogin();
      return;
    }
    
    // 프로젝트별 권한 검사
    if (productKey && window.App) {
      const hasAccess = window.App.hasProductAccess(sess.id, productKey);
      if (!hasAccess) {
        alert(`🔒 해당 프로젝트(${productKey}) 이용 권한이 부여되지 않았습니다.\n파란이빨 포털(btsky.pe.kr/portal/)에서 관리자(btsky99)에게 권한 신청을 확인해 주세요.`);
        location.href = (window.SITE_BASE || './') + 'portal/';
        return;
      }
    }
    
    window.open(url, '_blank');
  }

  function gateDownloadBundle(exeUrl, macUrl, productKey) {
    const isMac = /Mac/i.test(navigator.userAgent || '');
    const targetUrl = (isMac && macUrl) ? macUrl : exeUrl;
    gateDownload(targetUrl, productKey);
  }

  function toggleFaq(el) {
    const item = el.closest('.faq-item');
    if (item) item.classList.toggle('open');
  }

  function parseReleases(repoPath, exePattern, btnEl, infoEl) {
    fetch(`https://api.github.com/repos/${repoPath}/releases/latest`)
      .then(r => r.json())
      .then(data => {
        if (!data || !data.assets) return;
        const asset = data.assets.find(a => a.name.includes(exePattern) || a.name.endsWith('.exe'));
        if (asset) {
          if (btnEl) btnEl.onclick = () => gateDownload(asset.browser_download_url);
          if (infoEl) infoEl.textContent = `최신 버젼: ${data.tag_name} (${(asset.size / 1024 / 1024).toFixed(1)} MB)`;
        }
      })
      .catch(() => {});
  }

  function parseReleasesWithMac(repoPath, winBtnEl, macBtnEl, patchBtnEl, infoEl, productKey) {
    return fetch(`https://api.github.com/repos/${repoPath}/releases/latest`)
      .then(r => r.json())
      .then(data => {
        if (!data || !Array.isArray(data.assets)) {
          throw new Error('latest release assets unavailable');
        }

        const exeAsset = data.assets.find(asset =>
          asset.name.startsWith('vibe-coding-setup-') && asset.name.endsWith('.exe')
        );
        const macAsset = data.assets.find(asset => asset.name.endsWith('.dmg'));
        const patchAsset = data.assets.find(asset =>
          asset.name.endsWith('.zip') && /patch|update/i.test(asset.name)
        );
        const releasesUrl = `https://github.com/${repoPath}/releases/latest`;
        const winDownloadUrl = exeAsset ? exeAsset.browser_download_url : releasesUrl;
        const macDownloadUrl = macAsset ? macAsset.browser_download_url : releasesUrl;

        if (winBtnEl) {
          winBtnEl.onclick = () => gateDownload(winDownloadUrl, productKey);
          const label = winBtnEl.querySelector('small');
          if (label && exeAsset) {
            label.textContent = `${exeAsset.name} · ${(exeAsset.size / 1024 / 1024).toFixed(1)} MB`;
          }
        }
        if (macBtnEl) {
          macBtnEl.onclick = () => gateDownload(macDownloadUrl, productKey);
          const label = macBtnEl.querySelector('small');
          if (label && macAsset) {
            label.textContent = `${macAsset.name} · ${(macAsset.size / 1024 / 1024).toFixed(1)} MB`;
          }
        }
        if (patchBtnEl) {
          patchBtnEl.hidden = !patchAsset;
          if (patchAsset) {
            patchBtnEl.onclick = () => gateDownload(patchAsset.browser_download_url, productKey);
          }
        }
        if (infoEl) {
          const published = data.published_at
            ? new Date(data.published_at).toLocaleDateString('ko-KR')
            : '';
          infoEl.textContent = `최신 버전 ${data.tag_name}${published ? ` · ${published} 배포` : ''}`;
        }
        return { winUrl: winDownloadUrl, macUrl: macDownloadUrl, tag: data.tag_name };
      })
      .catch(() => {
        const releasesUrl = `https://github.com/${repoPath}/releases/latest`;
        if (winBtnEl) winBtnEl.onclick = () => gateDownload(releasesUrl, productKey);
        if (macBtnEl) macBtnEl.onclick = () => gateDownload(releasesUrl, productKey);
        if (infoEl) {
          infoEl.textContent = '최신 버전 정보를 불러오지 못했습니다. GitHub Releases에서 확인해 주세요.';
        }
        return { winUrl: releasesUrl, macUrl: releasesUrl, tag: '' };
      });
  }

  function renderAdminGates() {
    const sess = window.App ? window.App.AUTH.current() : (function() {
      try { return JSON.parse(localStorage.getItem('portal_sess')); } catch(e) { return null; }
    })();

    if (!sess) return;
    const isAdmin = sess.role === 'admin' || (sess.id && (sess.id.includes('btsky99') || sess.id.includes('paranibal') || sess.id.includes('admin')));
    if (isAdmin) {
      document.querySelectorAll('.admin-only').forEach(el => el.style.display = 'block');
    }
  }

  return { renderNav, openLogin, closeLogin, doAdminLogin, loginCustom, loginGithubPrompt, logout, gateDownload, gateDownloadBundle, toggleFaq, parseReleases, parseReleasesWithMac, renderAdminGates };
})();
