"""
FILE: infra/splash.py
DESCRIPTION: 부팅 스플래시 창 HTML 생성. WebView 창을 무거운 초기화(PG/PTY/HTTP)
             전에 먼저 띄워 즉시 피드백을 주기 위한 정적 화면으로, #status 요소는
             초기화 진행 상황 텍스트를 evaluate_js로 실시간 갱신한다(v3.7.179).

REVISION HISTORY:
- 2026-07-08 Claude: server.py main() 인라인 _SPLASH_HTML 블록 분리 (Phase 3 R17-3).
                     f-string 마크업 verbatim 유지 — project_name만 주입.
"""
from __future__ import annotations


def build_splash_html(project_name: str) -> str:
    """스플래시 창 HTML을 생성한다. #status 요소는 이후 진행 상황으로 갱신됨."""
    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{background:#0f0f1a;display:flex;align-items:center;justify-content:center;
height:100vh;font-family:-apple-system,'Segoe UI',sans-serif;color:white}}
.box{{text-align:center}}
.logo{{font-size:52px;margin-bottom:12px}}
.title{{font-size:22px;font-weight:600;margin-bottom:6px}}
.sub{{font-size:13px;color:#888;margin-bottom:28px;transition:opacity .3s}}
.proj{{font-size:12px;color:#7c3aed;margin-bottom:28px;
background:#1a0a3a;padding:4px 12px;border-radius:20px;display:inline-block}}
.ring{{width:36px;height:36px;border:3px solid #222;border-top-color:#7c3aed;
border-radius:50%;animation:spin 0.9s linear infinite;margin:0 auto}}
@keyframes spin{{to{{transform:rotate(360deg)}}}}
</style></head><body>
<div class="box">
  <div class="logo">🚀</div>
  <div class="title">바이브 코딩</div>
  <div class="proj">{project_name}</div>
  <div class="sub" id="status">초기화 준비 중...</div>
  <div class="ring"></div>
</div></body></html>"""
