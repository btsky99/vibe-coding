#!/usr/bin/env bash
#
# FILE: scripts/remote/vps-backup.sh
# DESCRIPTION: 서울 VPS에서 '재구축으로 복원 불가능한 것'만 골라 백업한다.
#
#              [WHY 전체 백업이 아닌가] nginx 설정·systemd 유닛·설치 패키지는
#              vps-setup.sh / vps-web-deploy.sh 로 언제든 재생성된다. 그런 것까지
#              담으면 용량만 커지고 '무엇이 진짜 중요한지'가 흐려진다.
#              여기 담긴 것은 **잃으면 재생성이 불가능하거나 대가가 큰 것**뿐이다.
#
#              [🔴 가장 중요한 것: hbbs 키]
#              /opt/rustdesk-server/id_ed25519 를 잃으면 새 키가 발급되고,
#              그 순간 등록된 **모든 PC의 RustDesk ID가 무효**가 되어 전 기기를
#              다시 설정해야 한다. 서버 재구축보다 이쪽 복구 비용이 훨씬 크다.
#
# 사용: ssh root@<VPS> 'bash -s' < scripts/remote/vps-backup.sh > vps-backup.tar.gz
#       (표준출력으로 tar.gz를 뱉는다 — 서버에 파일을 남기지 않기 위함)
#
# REVISION HISTORY:
# - 2026-08-08 Claude: 최초 작성.
#
set -euo pipefail

# [불변식] 진단 메시지는 전부 stderr로. stdout은 tar 스트림 전용이라
#   한 줄이라도 섞이면 아카이브가 깨진다.
say(){ printf '%s\n' "$*" >&2; }

STAGE=$(mktemp -d)
trap 'rm -rf "$STAGE"' EXIT

say "[*] 백업 수집 중..."

# ── 1. RustDesk 서버 키 (최우선) ────────────────────────────────────────────
mkdir -p "$STAGE/rustdesk"
cp -a /opt/rustdesk-server/id_ed25519 "$STAGE/rustdesk/" 2>/dev/null || say "[!] hbbs 개인키 없음"
cp -a /opt/rustdesk-server/id_ed25519.pub "$STAGE/rustdesk/" 2>/dev/null || true
cp -a /opt/rustdesk-server/db_v2.sqlite3 "$STAGE/rustdesk/" 2>/dev/null || true

# ── 2. 접근 자격 ────────────────────────────────────────────────────────────
mkdir -p "$STAGE/ssh"
cp -a /root/.ssh/authorized_keys "$STAGE/ssh/root_authorized_keys" 2>/dev/null || true
cp -a /home/tunnel/.ssh/authorized_keys "$STAGE/ssh/tunnel_authorized_keys" 2>/dev/null || true

# ── 3. 비밀 환경 ────────────────────────────────────────────────────────────
mkdir -p "$STAGE/env"
cp -a /opt/vibe/discord.env "$STAGE/env/" 2>/dev/null || true

# ── 4. Claude 인증 ──────────────────────────────────────────────────────────
# [WHY 담나] 재인증은 브라우저 왕복이 필요해 원격만으로는 복구가 번거롭다.
# [🔴 캐시·백업 제외] .claude 전체를 담았더니 10MB가 됐고 그 대부분이 cache/·backups/·
#   projects/ 였다. 복구에 쓰이지 않으면서 용량만 키우고, 진짜 중요한 것(자격 파일)이
#   무엇인지 흐린다. 백업은 작을수록 자주 돌리고 자주 검증하게 된다.
mkdir -p "$STAGE/claude"
for u in root vibe; do
  h=$([ "$u" = root ] && echo /root || echo "/home/$u")
  if [ -d "$h/.claude" ]; then
    mkdir -p "$STAGE/claude/${u}_claude"
    # 자격·설정만. 캐시/대화기록/프로젝트 상태는 담지 않는다.
    for f in .credentials.json settings.json settings.local.json; do
      [ -f "$h/.claude/$f" ] && cp -a "$h/.claude/$f" "$STAGE/claude/${u}_claude/" 2>/dev/null || true
    done
  fi
  [ -f "$h/.claude.json" ] && cp -a "$h/.claude.json" "$STAGE/claude/${u}_claude.json" 2>/dev/null || true
done

# ── 5. PostgreSQL ───────────────────────────────────────────────────────────
# [제약] pg_dumpall은 역할·권한까지 담는다. 데이터가 적어 비용이 낮고,
#   복원 시 역할 재생성을 따로 하지 않아도 되어 실수가 준다.
if command -v pg_dumpall >/dev/null 2>&1; then
  sudo -u postgres pg_dumpall -p 5433 > "$STAGE/postgres_all.sql" 2>/dev/null \
    || say "[!] PG 덤프 실패(건너뜀)"
fi

# ── 6. 복구 안내 — 백업만 있고 순서를 모르면 못 살린다 ──────────────────────
cat > "$STAGE/RESTORE.md" <<'EOF'
# 서울 VPS 복구 절차

새 VPS(Ubuntu 24.04)를 만든 뒤 순서대로 진행한다.

## 1. 기본 구축
    ssh root@<새IP> 'bash -s' < scripts/remote/vps-setup.sh

## 2. 🔴 hbbs 키 복원 — 반드시 서비스 정지 상태에서
    systemctl stop hbbs hbbr
    cp rustdesk/id_ed25519* /opt/rustdesk-server/
    chown rustdesk:rustdesk /opt/rustdesk-server/id_ed25519*
    chmod 600 /opt/rustdesk-server/id_ed25519
    systemctl start hbbr && sleep 2 && systemctl start hbbs

이 단계를 건너뛰면 새 키가 발급되어 **모든 PC의 RustDesk ID가 무효**가 된다.
기존 기기들을 전부 다시 설정해야 하므로 서버 재설치보다 비용이 크다.

## 3. 접근 자격
    cp ssh/root_authorized_keys /root/.ssh/authorized_keys
    useradd -m -s /usr/sbin/nologin tunnel 2>/dev/null
    mkdir -p /home/tunnel/.ssh
    cp ssh/tunnel_authorized_keys /home/tunnel/.ssh/authorized_keys
    chown -R tunnel:tunnel /home/tunnel/.ssh
    chmod 700 /home/tunnel/.ssh && chmod 600 /home/tunnel/.ssh/authorized_keys

## 4. 디스코드
    mkdir -p /opt/vibe && cp env/discord.env /opt/vibe/ && chmod 600 /opt/vibe/discord.env

## 5. PostgreSQL
    sudo -u postgres psql -p 5433 -f postgres_all.sql

## 6. Claude 인증
    cp -a claude/root_claude /root/.claude
    cp -a claude/root_claude.json /root/.claude.json
    (vibe 계정도 동일. 소유권 chown 잊지 말 것)

## 7. 웹·상태판
    ssh root@<새IP> 'bash -s' < scripts/remote/vps-web-deploy.sh

## 8. 🔴 새 IP를 반영해야 하는 곳
- 각 PC의 RustDesk ID 서버 주소
- 각 PC의 역터널 대상 주소(tunnel-*.cmd)
- DNS A레코드
EOF

say "[*] 압축 중..."
tar -czf - -C "$STAGE" . 2>/dev/null
say "[OK] 백업 완료 ($(du -sh "$STAGE" | cut -f1))"
