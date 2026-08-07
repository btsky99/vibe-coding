#!/usr/bin/env bash
#
# FILE: scripts/remote/vps-web-deploy.sh
# DESCRIPTION: 서울 VPS에 웹(메인 사이트 + 상태판)과 상태 API를 배포한다. 멱등.
#
#              [WHY vps-setup.sh와 분리했나] vps-setup.sh는 `ufw --force reset`과
#              sshd 설정 교체가 들어 있어 **재실행이 파괴적**이다. 배포는 코드가 바뀔
#              때마다 반복해야 하므로 파괴적 초기화와 같은 파일에 둘 수 없다.
#              이 스크립트는 몇 번을 돌려도 같은 결과가 되게 만들었다.
#
#              [배경] 이전에는 이 절차가 스크래치패드에만 있어 저장소에 재현 수단이
#              없었다(서버가 날아가면 복구 불가). 그 결함을 메우기 위한 파일이다.
#
# 사용: ssh root@<VPS> 'bash -s' < scripts/remote/vps-web-deploy.sh
#
# REVISION HISTORY:
# - 2026-08-08 Claude: 최초 작성 — 상태판/상태API 배포 경로를 저장소로 편입.
#
set -euo pipefail

SRC=/opt/vibe/vibe-coding
VENV=/opt/vibe/venv
WWW=/var/www/vibe
DOMAIN="${STATUS_DOMAIN:-status.btsky.pe.kr}"

log(){ printf '\033[0;36m[*]\033[0m %s\n' "$*"; }
ok(){  printf '\033[0;32m[OK]\033[0m %s\n' "$*"; }
warn(){ printf '\033[0;33m[!]\033[0m %s\n' "$*"; }

[ "$(id -u)" -eq 0 ] || { echo "root로 실행할 것"; exit 1; }

# ── 1. 소스 ─────────────────────────────────────────────────────────────────
if [ -d "$SRC/.git" ]; then
  git -C "$SRC" fetch -q origin main && git -C "$SRC" reset -q --hard origin/main
  ok "소스: $(git -C "$SRC" rev-parse --short HEAD)"
else
  warn "$SRC 가 git 체크아웃이 아니다 — 현재 파일 그대로 배포한다"
fi

# ── 2. 정적 파일 ────────────────────────────────────────────────────────────
# [WHY 심볼릭 링크가 아니라 복사인가] nginx(www-data)가 저장소 디렉터리 권한에 묶이면
#   조용히 403이 난다. 복사는 권한 경계를 넘지 않아 그런 종류의 실패가 없다.
mkdir -p "$WWW"
if [ -d "$SRC/web" ]; then
  cp -r "$SRC/web/." "$WWW/"
  ok "웹 파일 배치: $(find "$WWW" -name '*.html' | wc -l)개 HTML"
else
  warn "$SRC/web 없음"
fi

# ── 3. 상태 API ─────────────────────────────────────────────────────────────
# [🔴 DynamicUser를 쓰지 않는 이유 — 미래의 함정]
#   격리를 위해 DynamicUser=yes + RestrictAddressFamilies 를 붙이고 싶어지는데,
#   vps_status_api.remote_nodes()가 호출하는 `ss`는 **NETLINK_SOCK_DIAG** 소켓을 쓴다.
#   RestrictAddressFamilies에 AF_NETLINK를 빠뜨리면 ss가 실패하고, _sh()가 예외를
#   삼키기 때문에 화면에는 "터널 0개"가 **정상처럼** 표시된다. 거짓 정상은 장애보다 나쁘다.
#   지금은 단순함을 택했다. 강화한다면 AF_NETLINK를 반드시 함께 허용할 것.
cat > /etc/systemd/system/vibe-status.service <<EOF
[Unit]
Description=Vibe VPS Status API (read-only)
After=network.target

[Service]
Type=simple
WorkingDirectory=${SRC}
ExecStart=${VENV}/bin/python ${SRC}/scripts/vps_status_api.py
Environment=PYTHONUNBUFFERED=1
Restart=always
RestartSec=5
NoNewPrivileges=yes
ProtectSystem=strict
ProtectHome=yes
PrivateTmp=yes

[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload
systemctl enable --now vibe-status >/dev/null 2>&1 || true
systemctl restart vibe-status
sleep 3
systemctl is-active --quiet vibe-status && ok "상태 API 상주" || warn "상태 API 기동 실패"

# ── 4. nginx ────────────────────────────────────────────────────────────────
# [WHY snippet + include 인가] 사이트 파일을 통째로 덮어쓰면 certbot이 나중에 써넣는
#   443 블록이 날아간다. 프록시 규칙만 별도 파일로 두고 include 한 줄만 주입하면
#   HTTPS 발급 이후에도 이 스크립트를 안전하게 재실행할 수 있다.
mkdir -p /etc/nginx/snippets
cat > /etc/nginx/snippets/vibe-status.conf <<'EOF'
# 상태 API 프록시 — vps-web-deploy.sh 가 관리. 직접 수정하지 말 것.
location = /api/status {
    proxy_pass http://127.0.0.1:9100/;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_read_timeout 10s;
}
EOF

SITE=/etc/nginx/sites-available/vibe
if [ ! -f "$SITE" ] || ! grep -q 'vibe-status.conf' "$SITE"; then
  cp -f "$SITE" "${SITE}.bak.$(date +%s)" 2>/dev/null || true
  cat > "$SITE" <<EOF
server {
    listen 80 default_server;
    server_name ${DOMAIN} _;

    root ${WWW};
    index index.html;

    # 개인 상태판 — 검색 노출 방지 및 기본 방어 헤더
    add_header X-Robots-Tag "noindex, nofollow" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header X-Frame-Options "DENY" always;
    add_header Referrer-Policy "no-referrer" always;

    include /etc/nginx/snippets/vibe-status.conf;

    location / { try_files \$uri \$uri/ \$uri/index.html =404; }
}
EOF
fi
ln -sf "$SITE" /etc/nginx/sites-enabled/vibe
rm -f /etc/nginx/sites-enabled/default /etc/nginx/sites-enabled/status

if nginx -t >/dev/null 2>&1; then
  systemctl reload nginx
  ok "nginx 재설정"
else
  warn "nginx 설정 오류 — 되돌린다"
  nginx -t
  LAST_BAK=$(ls -t "${SITE}".bak.* 2>/dev/null | head -1 || true)
  [ -n "$LAST_BAK" ] && cp -f "$LAST_BAK" "$SITE" && systemctl reload nginx
  exit 1
fi

# ── 5. 검증 — '설정했다'가 아니라 '응답한다'를 본다 ─────────────────────────
echo
echo "=== 검증 ==="
h=$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 http://127.0.0.1/status/ || echo 000)
a=$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 http://127.0.0.1/api/status || echo 000)
m=$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 http://127.0.0.1/ || echo 000)
printf '  메인 페이지  HTTP %s\n' "$m"
printf '  상태판       HTTP %s\n' "$h"
printf '  상태 API     HTTP %s\n' "$a"
[ "$a" = "200" ] && curl -s --max-time 5 http://127.0.0.1/api/status | head -c 200 && echo
[ "$m" = "200" ] && [ "$h" = "200" ] && [ "$a" = "200" ] && ok "전부 정상" || warn "일부 실패 — 위 코드 확인"
