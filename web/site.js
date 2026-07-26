/*
  FILE: web/site.js
  DESCRIPTION: 파란이빨(btsky) 웹 인터랙션, FAQ 및 다운로드 게이트 모듈.
    소셜 로그인 상태 확인 + 5대 프로젝트별(vibe_coding, ons, stock, crypto, finbee) 개별 접근 권한(hasProductAccess) 연동 게이트.
    Windows & 🍎 macOS (.dmg/.zip) 릴리즈 파서 모듈 포함.
  REVISION HISTORY:
    - 2026-07-22 Claude: 최초 생성.
    - 2026-07-26 Gemini: 🍎 macOS 자산 파싱(parseReleasesWithMac) 및 Windows/macOS 멀티 OS 다운로드 게이트 완성.
*/
window.Site = (function () {
  function renderNav(activeHash) {
    const navR = document.getElementById('navR');
    if (!navR) return;
    
    const sess = window.App ? window.App.AUTH.current() : null;
    let html = '';
    
    if (sess) {
      const isAdmin = sess.role === 'admin' || (sess.id && (sess.id.includes('btsky99') || sess.id.includes('paranibal')));
      const label = isAdmin ? '👑 파란이빨 관리자' : (sess.name || '회원');
      html += `<a class="nlink" href="${window.SITE_BASE || './'}portal/">💈 ${label} 포털</a>`;
      html += `<button class="nlink solid" onclick="Site.logout()">로그아웃</button>`;
    } else {
      html += `<button class="nlink solid" onclick="Site.openLogin()">🔑 소셜 로그인 / 가입</button>`;
    }
    navR.innerHTML = html;
  }

  function openLogin() {
    const modal = document.createElement('div');
    modal.className = 'modal-bg';
    modal.id = 'loginModal';
    modal.innerHTML = `
      <div class="modal-card">
        <button class="modal-close" onclick="Site.closeLogin()">&times;</button>
        <div class="ic" style="font-size:42px; margin-bottom:8px;">💈</div>
        <h2>파란이빨 계정 로그인</h2>
        <p class="sub">구글 또는 GitHub 소셜 계정으로 1초 만에 로그인 및 가입 신청이 진행됩니다.</p>
        
        <div style="margin:24px 0 16px; display:flex; flex-direction:column; gap:10px; align-items:center;">
          <div id="g_btn_container"></div>
          <button class="btn line" style="width:280px; justify-content:center;" onclick="Site.loginGithubPrompt()">
            <span>🐱 GitHub 계정으로 계속하기</span>
          </button>
        </div>

        <div style="font-size:12.5px; color:var(--muted); margin-top:14px; border-top:1px solid var(--line); padding-top:12px;">
          👑 <b>btsky99</b> 구글 / GitHub 계정 로그인 시 파란이빨 관리자 권한이 자동 연결됩니다.
        </div>
      </div>
    `;
    document.body.appendChild(modal);

    if (window.App) {
      window.App.initGoogle(
        document.getElementById('g_btn_container'),
        null,
        profile => {
          window.App.AUTH.loginGoogle(profile);
          Site.closeLogin();
          location.reload();
        }
      );
    }
  }

  function closeLogin() {
    const modal = document.getElementById('loginModal');
    if (modal) modal.remove();
  }

  function loginGithubPrompt() {
    const handle = prompt('GitHub 아이디(핸들)를 입력하세요 (예: btsky99):', 'btsky99');
    if (handle && window.App) {
      window.App.AUTH.loginGithub(handle);
      closeLogin();
      location.reload();
    }
  }

  function logout() {
    if (window.App) window.App.AUTH.logout();
    location.reload();
  }

  // ── 프로젝트별 개별 접근 권한 검증 다운로드 게이트 ──
  function gateDownload(url, productKey) {
    const sess = window.App ? window.App.AUTH.current() : null;
    if (!sess) {
      alert('🔑 파란이빨 소셜 로그인 후 다운로드하실 수 있습니다.');
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

    if (url) {
      const a = document.createElement('a');
      a.href = url;
      a.download = '';
      a.target = '_blank';
      document.body.appendChild(a);
      a.click();
      a.remove();
    }
  }

  function gateDownloadBundle(urls, productKey) {
    const sess = window.App ? window.App.AUTH.current() : null;
    if (!sess) {
      alert('🔑 파란이빨 소셜 로그인 후 전체 설치 5개 패키지를 받으실 수 있습니다.');
      openLogin();
      return;
    }

    if (productKey && window.App) {
      const hasAccess = window.App.hasProductAccess(sess.id, productKey);
      if (!hasAccess) {
        alert(`🔒 CipherTrader Crypto 프로젝트 이용 권한이 부여되지 않았습니다.\n포털 제어판에서 관리자(btsky99) 승인을 확인해 주세요.`);
        location.href = (window.SITE_BASE || './') + 'portal/';
        return;
      }
    }

    if (!urls || !urls.length) return;
    alert(`🚀 CipherTrader v22.6.3 전체 설치 5개 파일(.exe + .bin 1~4) 연속 다운로드를 시작합니다.\n\n(브라우저에서 '다중 파일 다운로드' 팝업이 뜨면 [허용]을 클릭해 주세요)`);
    
    urls.forEach((u, idx) => {
      setTimeout(() => {
        const a = document.createElement('a');
        a.href = u;
        a.download = '';
        document.body.appendChild(a);
        a.click();
        a.remove();
      }, idx * 450);
    });
  }

  function toggleFaq(el) {
    const item = el.parentElement;
    item.classList.toggle('open');
  }

  // Windows & macOS 릴리즈 파싱 모듈
  async function parseReleasesWithMac(repo, winBtnId, macBtnId, patchBtnId, verInfoId, fallbackUrl) {
    const winBtn = document.getElementById(winBtnId);
    const macBtn = document.getElementById(macBtnId);
    const patchBtn = document.getElementById(patchBtnId);
    const verInfo = document.getElementById(verInfoId);

    try {
      const res = await fetch(`https://api.github.com/repos/${repo}/releases`);
      if (!res.ok) throw new Error('API Rate Limit');
      const releases = await res.json();
      if (!releases || !releases.length) throw new Error('No releases');

      const latest = releases[0];
      const assets = latest.assets || [];

      // Windows 윈도우 인스톨러 (.exe)
      const winAsset = assets.find(a => a.name.endsWith('.exe')) || assets[0];
      // macOS 맥용 설치 패키지 (.dmg / .zip / mac / darwin)
      const macAsset = assets.find(a => a.name.endsWith('.dmg') || a.name.includes('mac') || a.name.includes('darwin')) || assets.find(a => a.name.endsWith('.zip'));

      if (winBtn) {
        const url = winAsset ? winAsset.browser_download_url : latest.html_url;
        winBtn.onclick = () => gateDownload(url, 'vibe_coding');
      }

      if (macBtn) {
        const url = macAsset ? macAsset.browser_download_url : latest.html_url;
        macBtn.onclick = () => gateDownload(url, 'vibe_coding');
      }

      if (patchBtn) {
        const patchAsset = assets.find(a => a.name.endsWith('.zip')) || assets[0];
        const url = patchAsset ? patchAsset.browser_download_url : latest.html_url;
        patchBtn.onclick = () => gateDownload(url, 'vibe_coding');
      }

      if (verInfo) {
        verInfo.innerHTML = `🚀 최신 배포 <b>${latest.tag_name}</b> · 🪟 Windows & 🍎 macOS (Apple Silicon/Intel) 지원`;
      }
    } catch (e) {
      if (winBtn) winBtn.onclick = () => gateDownload(fallbackUrl || `https://github.com/${repo}/releases`, 'vibe_coding');
      if (macBtn) macBtn.onclick = () => gateDownload(fallbackUrl || `https://github.com/${repo}/releases`, 'vibe_coding');
      if (patchBtn) patchBtn.onclick = () => gateDownload(fallbackUrl || `https://github.com/${repo}/releases`, 'vibe_coding');
    }
  }

  async function parseReleases(repo, fullBtnId, patchBtnId, verInfoId, forceFullUrl, forceReleasesUrl) {
    const fullBtn = document.getElementById(fullBtnId);
    const patchBtn = document.getElementById(patchBtnId);
    const verInfo = document.getElementById(verInfoId);

    try {
      const res = await fetch(`https://api.github.com/repos/${repo}/releases`);
      if (!res.ok) throw new Error('API Rate Limit or Private Repo');
      const releases = await res.json();
      if (!releases || !releases.length) throw new Error('No releases found');

      let fullRelease = releases.find(r => r.tag_name === 'v22.6.3') || releases[0];
      let patchRelease = releases.find(r => r.tag_name !== 'v22.6.3') || releases[0];

      if (fullBtn) {
        const fullAsset = (fullRelease.assets || []).find(a => a.name.endsWith('.exe')) || fullRelease.assets[0];
        const url = forceFullUrl || (fullAsset ? fullAsset.browser_download_url : fullRelease.html_url);
        fullBtn.onclick = () => gateDownload(url);
      }

      if (patchBtn) {
        const patchAsset = (patchRelease.assets || []).find(a => a.name.endsWith('.zip')) || patchRelease.assets[0];
        const url = forceReleasesUrl || (patchAsset ? patchAsset.browser_download_url : patchRelease.html_url);
        patchBtn.onclick = () => gateDownload(url);
      }

      if (verInfo) {
        verInfo.innerHTML = `⚡ 최신 릴리즈: <b>${patchRelease.tag_name}</b> (${patchRelease.name || '배포중'}) · 전체 셋업: <b>${fullRelease.tag_name}</b>`;
      }
    } catch (e) {
      if (fullBtn) fullBtn.onclick = () => gateDownload(forceFullUrl || `https://github.com/${repo}/releases`);
      if (patchBtn) patchBtn.onclick = () => gateDownload(forceReleasesUrl || `https://github.com/${repo}/releases`);
    }
  }

  function renderAdminGates() {
    const sess = window.App ? window.App.AUTH.current() : null;
    const isAdmin = sess && (sess.role === 'admin' || (sess.id && (sess.id.includes('btsky99') || sess.id.includes('paranibal'))));
    
    document.querySelectorAll('.admin-only-source').forEach(el => {
      const srcUrl = el.getAttribute('data-src-url');
      if (isAdmin) {
        el.style.display = 'inline-flex';
        el.href = srcUrl;
        el.target = '_blank';
      } else {
        el.style.display = 'none';
      }
    });
  }

  window.addEventListener('DOMContentLoaded', () => {
    renderNav();
    renderAdminGates();
  });

  return { renderNav, openLogin, closeLogin, loginGithubPrompt, logout, gateDownload, gateDownloadBundle, toggleFaq, parseReleases, parseReleasesWithMac, renderAdminGates };
})();
