#!/usr/bin/env bash
#
# FILE: scripts/remote/vps-setup.sh
# DESCRIPTION: Vultr(Ubuntu 24.04) VPS를 RustDesk ID/중계 서버 + 웹(PWA) 호스트로 만든다.
#              Tailscale 없이 인터넷 너머에서 원격제어가 되게 하는 공개 진입점 서버 구성.
#              root로 1회 실행. 재실행해도 안전(멱등)하게 작성했다.
#
# 사용:
#   ssh -i ~/.ssh/vps_btsky_ed25519 root@<IP> 'bash -s' < vps-setup.sh
#   또는 서버에 올려서: bash vps-setup.sh
#
# REVISION HISTORY:
# - 2026-08-07 Claude: 최초 작성 — Tailscale 폐기 후 VPS 중심 구조로 전환.
#

set -euo pipefail

# ── 설정 ────────────────────────────────────────────────────────────────────
RUSTDESK_DIR="/opt/rustdesk-server"
RUSTDESK_USER="rustdesk"
SERVER_REPO="rustdesk/rustdesk-server"

log()  { printf '\033[0;36m[*]\033[0m %s\n' "$*"; }
ok()   { printf '\033[0;32m[OK]\033[0m %s\n' "$*"; }
warn() { printf '\033[0;33m[!]\033[0m %s\n' "$*"; }
die()  { printf '\033[0;31m[X]\033[0m %s\n' "$*" >&2; exit 1; }

[ "$(id -u)" -eq 0 ] || die "root로 실행해야 한다."

PUBLIC_IP="$(curl -fsS --max-time 10 https://api.ipify.org || true)"
[ -n "$PUBLIC_IP" ] || die "공인 IP 조회 실패 — 네트워크 확인."
log "이 서버의 공인 IP: ${PUBLIC_IP}"


# ── 1. 기본 패키지 ──────────────────────────────────────────────────────────
log "패키지 갱신 및 기본 도구 설치..."
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq \
  ufw fail2ban unattended-upgrades curl unzip ca-certificates \
  nginx certbot python3-certbot-nginx >/dev/null
ok "기본 패키지 설치 완료"


# ── 2. 보안 기본기 ──────────────────────────────────────────────────────────
# [WHY 비밀번호 로그인 차단] 공인 IP를 가진 SSH 서버는 부팅 몇 분 뒤부터 무차별 대입을 맞는다.
#   키 인증만 남기면 그 공격면이 통째로 사라진다.
# [불변식] 이 스크립트는 SSH 키로 접속해 실행되므로, 키가 이미 authorized_keys에 있다는 것이
#   증명된 상태다. 그래서 비밀번호 차단이 스스로를 잠그지 않는다. 키 없이 콘솔로 실행 중이라면
#   아래 가드가 막는다.
if [ ! -s /root/.ssh/authorized_keys ]; then
  warn "authorized_keys가 비어 있다 — 비밀번호 로그인 차단을 건너뛴다(잠김 방지)."
else
  sshd_conf=/etc/ssh/sshd_config.d/99-hardening.conf
  cat > "$sshd_conf" <<'EOF'
# vibe-coding VPS — 키 인증 전용
PasswordAuthentication no
KbdInteractiveAuthentication no
PermitRootLogin prohibit-password
EOF
  # [주의] 설정 오류로 sshd가 안 뜨면 영구 잠김이다. 반드시 검사 후 재시작한다.
  if sshd -t; then
    systemctl reload ssh || systemctl reload sshd
    ok "SSH 비밀번호 로그인 차단 (키 전용)"
  else
    rm -f "$sshd_conf"
    warn "sshd 설정 검사 실패 — 변경을 되돌렸다."
  fi
fi

# 자동 보안 업데이트 — 방치해도 커널/OpenSSL 패치가 들어오게.
echo 'APT::Periodic::Unattended-Upgrade "1";' > /etc/apt/apt.conf.d/20auto-upgrades
echo 'APT::Periodic::Update-Package-Lists "1";' >> /etc/apt/apt.conf.d/20auto-upgrades
systemctl enable --now unattended-upgrades >/dev/null 2>&1 || true
systemctl enable --now fail2ban >/dev/null 2>&1 || true
ok "자동 보안 업데이트 + fail2ban 활성화"


# ── 3. 방화벽 ───────────────────────────────────────────────────────────────
# [불변식] ufw enable 전에 22를 반드시 먼저 허용한다. 순서가 뒤바뀌면 그 즉시 잠긴다.
# 포트 용도: 21115 NAT판정 / 21116 ID등록·홀펀칭(TCP+UDP) / 21117 중계 / 21118·21119 웹소켓
log "방화벽 설정..."
ufw --force reset >/dev/null
ufw default deny incoming >/dev/null
ufw default allow outgoing >/dev/null
ufw allow 22/tcp    comment 'SSH'      >/dev/null
ufw allow 80/tcp    comment 'HTTP'     >/dev/null
ufw allow 443/tcp   comment 'HTTPS'    >/dev/null
ufw allow 21115/tcp comment 'hbbs nat' >/dev/null
ufw allow 21116/tcp comment 'hbbs id'  >/dev/null
ufw allow 21116/udp comment 'hbbs id'  >/dev/null
ufw allow 21117/tcp comment 'hbbr'     >/dev/null
ufw allow 21118/tcp comment 'hbbs ws'  >/dev/null
ufw allow 21119/tcp comment 'hbbr ws'  >/dev/null
ufw --force enable >/dev/null
ok "방화벽 활성화 (SSH·웹·RustDesk만 개방)"


# ── 4. RustDesk 서버 (hbbs/hbbr) ────────────────────────────────────────────
log "rustdesk-server 최신 릴리스 조회..."
ASSET_URL="$(curl -fsS "https://api.github.com/repos/${SERVER_REPO}/releases/latest" \
  | grep -o 'https://[^"]*rustdesk-server-linux-amd64\.zip' | head -n1)"
[ -n "$ASSET_URL" ] || die "릴리스 자산 URL을 찾지 못했다."

mkdir -p "$RUSTDESK_DIR"
tmp="$(mktemp -d)"
curl -fsSL "$ASSET_URL" -o "$tmp/server.zip"
unzip -qo "$tmp/server.zip" -d "$tmp"
# [제약] zip 내부 디렉터리 구조가 릴리스마다 바뀐 전례가 있어 고정 경로 대신 재귀 탐색한다.
for b in hbbs hbbr; do
  found="$(find "$tmp" -type f -name "$b" | head -n1)"
  [ -n "$found" ] || die "배포 zip에서 ${b}를 찾지 못했다."
  install -m 0755 "$found" "${RUSTDESK_DIR}/${b}"
done
rm -rf "$tmp"
ok "hbbs/hbbr 배치: ${RUSTDESK_DIR}"

# 전용 계정 — root로 상시 서비스를 돌릴 이유가 없다(권한 최소화).
id -u "$RUSTDESK_USER" >/dev/null 2>&1 || useradd -r -s /usr/sbin/nologin -d "$RUSTDESK_DIR" "$RUSTDESK_USER"
chown -R "$RUSTDESK_USER:$RUSTDESK_USER" "$RUSTDESK_DIR"

# [WHY -k _] 공개키 대조를 강제한다. 이 옵션이 없으면 **키를 모르는 아무 클라이언트나** 이
#   ID 서버에 등록할 수 있다. 공인망에 열려 있으므로 강제가 사실상 필수다.
cat > /etc/systemd/system/hbbr.service <<EOF
[Unit]
Description=RustDesk Relay Server (hbbr)
After=network.target

[Service]
Type=simple
User=${RUSTDESK_USER}
WorkingDirectory=${RUSTDESK_DIR}
ExecStart=${RUSTDESK_DIR}/hbbr -k _
Restart=always
RestartSec=5
LimitNOFILE=1000000

[Install]
WantedBy=multi-user.target
EOF

# [불변식] hbbs는 hbbr 뒤에 뜬다(After/Requires) — 중계 대상이 없는 창을 만들지 않는다.
cat > /etc/systemd/system/hbbs.service <<EOF
[Unit]
Description=RustDesk ID/Rendezvous Server (hbbs)
After=network.target hbbr.service
Requires=hbbr.service

[Service]
Type=simple
User=${RUSTDESK_USER}
WorkingDirectory=${RUSTDESK_DIR}
ExecStart=${RUSTDESK_DIR}/hbbs -r ${PUBLIC_IP}:21117 -k _
Restart=always
RestartSec=5
LimitNOFILE=1000000

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable --now hbbr >/dev/null
sleep 2
systemctl enable --now hbbs >/dev/null
sleep 3

# [검증] "설정했다"가 아니라 "실제로 떠 있다"를 확인한다. 실패를 조용히 넘기면
#   클라이언트에서 원인 불명의 접속 실패로만 드러나 진단이 몇 배 어려워진다.
for svc in hbbr hbbs; do
  if systemctl is-active --quiet "$svc"; then
    ok "${svc} 상주 중"
  else
    warn "${svc} 기동 실패 — journalctl -u ${svc} -n 30 으로 확인"
    journalctl -u "$svc" -n 15 --no-pager || true
  fi
done

# 공개키 — 클라이언트가 이 값을 넣어야 접속된다.
PUBKEY_FILE="${RUSTDESK_DIR}/id_ed25519.pub"
for _ in $(seq 1 15); do [ -f "$PUBKEY_FILE" ] && break; sleep 1; done
PUBKEY="$(cat "$PUBKEY_FILE" 2>/dev/null || echo '(생성 실패)')"

# [WHY 개인키 잠금] 유출되면 제3자가 이 ID 서버를 사칭할 수 있다.
chmod 600 "${RUSTDESK_DIR}/id_ed25519" 2>/dev/null || true


# ── 5. nginx 기본 페이지 (PWA 자리) ─────────────────────────────────────────
# [주의] HTTPS 인증서는 도메인이 이 서버를 가리킨 뒤에 발급해야 한다(Let's Encrypt가
#   실제 DNS를 확인한다). 그래서 여기서는 HTTP만 세우고 certbot은 별도 단계로 남긴다.
mkdir -p /var/www/vibe
if [ ! -f /var/www/vibe/index.html ]; then
  cat > /var/www/vibe/index.html <<'EOF'
<!doctype html><meta charset="utf-8"><title>vibe</title>
<p>준비 중입니다.</p>
EOF
fi
cat > /etc/nginx/sites-available/vibe <<'EOF'
server {
    listen 80 default_server;
    server_name _;
    root /var/www/vibe;
    index index.html;
    location / { try_files $uri $uri/ =404; }
}
EOF
ln -sf /etc/nginx/sites-available/vibe /etc/nginx/sites-enabled/vibe
rm -f /etc/nginx/sites-enabled/default
nginx -t >/dev/null 2>&1 && systemctl reload nginx && ok "nginx 기동 (HTTP)" || warn "nginx 설정 오류"


# ── 결과 ────────────────────────────────────────────────────────────────────
cat <<EOF

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  서버 준비 완료
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  ID/중계 서버 주소 : ${PUBLIC_IP}
  공개키(Key)       : ${PUBKEY}

  각 PC에서:
    ID 서버   ${PUBLIC_IP}
    Key       ${PUBKEY}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  다음 단계 (도메인 연결 후):
    certbot --nginx -d rd.btsky.pe.kr

EOF
