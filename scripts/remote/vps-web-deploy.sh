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
# [2026-08-08] 발급·연결된 이름은 admin.btsky.pe.kr 이고, 같은 인증서에 apex
#   (btsky.pe.kr)가 SAN 으로 들어가 있다. status 는 DNS 레코드가 없다(이름만 유지).
#
# [🔴 apex 를 목록에서 빼지 말 것] 2026-08-08 개편으로 apex 의 A레코드가 GitHub
#   Pages 에서 이 서버로 넘어왔다. 여기서 apex 를 지우면 server_name 이 어긋나
#   certbot 갱신이 **조용히 실패**하고, 90일 뒤 아무 경고 없이 사이트가 죽는다.
#   DNS A레코드 ↔ 이 변수 ↔ 인증서 SAN 세 곳은 항상 함께 움직인다.
DOMAIN="${STATUS_DOMAIN:-btsky.pe.kr admin.btsky.pe.kr status.btsky.pe.kr}"

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
#
# [🔴 2026-08-08 보안사고] 이 엔드포인트는 발견 시점까지 **무인증 공개**였다.
#   노출된 것: 상주 서비스 목록·재시작 횟수·메모리/디스크·역터널 포트(22001~4)와
#   각 터널에 붙은 노드의 실명("크립토 PC", "맥미니"). 공격자에게는 그대로
#   정찰 지도다. 아픽스 콘솔 개편의 Phase 0 으로 즉시 닫았다.
#
# [불변식] 이 API는 **절대 무인증으로 열지 않는다**. 여는 방법은 하나뿐 —
#   아픽스 콘솔의 로그인 게이트(oauth2-proxy) 뒤에 두는 것.
#   "잠깐 확인하려고" allow 를 늘리는 순간 같은 사고가 반복된다.
location = /api/status {
    allow 127.0.0.1;
    deny all;

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
# [🔴 함정 — 평문 http 로 재면 전부 404다] certbot 이 붙고 난 뒤로 80 포트 블록은
#   `return 404` 뿐이고 실제 콘텐츠·snippet 은 전부 443 블록에 있다. 예전처럼
#   `http://127.0.0.1/...` 로 재면 정상인데도 404가 찍혀 배포가 실패로 보인다.
#   그래서 검증은 전부 HTTPS + --resolve 로 통일한다.
PUBIP=$(ip -4 -o addr show scope global | awk '{print $4}' | cut -d/ -f1 | head -1)
D1=$(echo "$DOMAIN" | awk '{print $1}')
HAS_TLS=0; [ -d "/etc/letsencrypt/live/${D1}" ] && HAS_TLS=1

if [ "$HAS_TLS" = "1" ]; then
  probe(){ curl -sk -o /dev/null -w '%{http_code}' --max-time 8 --resolve "${D1}:443:${2:-127.0.0.1}" "https://${D1}$1" || echo 000; }
else
  probe(){ curl -s  -o /dev/null -w '%{http_code}' --max-time 8 -H "Host: ${D1}" "http://${2:-127.0.0.1}$1" || echo 000; }
fi

m=$(probe /)
h=$(probe /status/)
printf '  메인 페이지  HTTP %s\n' "$m"
printf '  상태판       HTTP %s\n' "$h"

# [WHY 공인 IP로 자기 자신을 치는가] allow/deny 는 **실제 소스 IP**로 판정하므로
#   127.0.0.1 로 부르면 영원히 200이 나온다. 차단이 실제로 걸렸는지 보려면
#   루프백이 아닌 소스 주소로 한 번 나갔다 들어와야 한다. 이 확인을 빼먹으면
#   "닫았다고 생각했는데 열려 있는" 2026-08-08 사고가 그대로 재발한다.
#
# [🔴 함정 — 이렇게 재면 거짓말한다] `http://127.0.0.1/api/status` 로 재면 404가 나온다.
#   snippet 은 certbot 이 만든 **443 블록에만** include 되어 있고, 80 포트의
#   default_server 블록은 `return 404` 이기 때문이다. 반드시 HTTPS + 올바른 Host 로,
#   --resolve 로 소스 IP만 바꿔 가며 같은 이름을 쳐야 allow/deny 판정을 볼 수 있다.
x=$(probe /api/status "$PUBIP")
y=$(probe /api/status 127.0.0.1)
printf '  상태 API(외부) HTTP %s  ← 403 이어야 정상\n' "$x"
printf '  상태 API(로컬) HTTP %s  ← 200 이어야 정상\n' "$y"

[ "$m" = "200" ] && [ "$h" = "200" ] && [ "$x" = "403" ] && [ "$y" = "200" ] \
  && ok "전부 정상 (상태 API 외부 차단 확인)" \
  || warn "일부 실패 — 위 코드 확인"
