#!/usr/bin/env bash
# FILE: scripts/remote/vps-knowledge-db.sh
# DESCRIPTION: 아픽스 서버(서울 VPS)에 중앙 대화/지식용 PostgreSQL DB와 최소 권한 계정,
#              그리고 SSH 터널 전용 키를 준비한다. 여러 PC의 클로드가 이 DB로 대화를 주고받는다.
#
#              [🔴 이 스크립트가 하지 않는 것 — 의도적]
#                - listen_addresses 변경 금지: PG는 127.0.0.1에만 묶인 채로 둔다.
#                  접근은 SSH 터널로만 한다(공인망 노출 0). 여기를 열면 그 순간 스캔 대상이 된다.
#                - 방화벽(ufw) 변경 금지: 22/tcp만 열린 현 상태를 유지한다.
#                - 기존 DB(postgres/vibe/root)와 서비스(nginx/hbbs/hbbr/vibe-bridge/vibe-status)
#                  는 건드리지 않는다. 이 서버는 이미 5개 서비스가 운영 중이다.
#
#              [WHY Tailscale이 아닌 SSH 터널인가] 이 서버를 세운 목적 자체가 제3자 서비스
#                의존을 줄이는 것이다. SSH는 이미 쓰고 있는 수단이라 새 의존이 0이다.
#
#              [🔴 알려진 한계 — 이 서버의 pg_hba는 `host all all 127.0.0.1/32 trust`다]
#                터널이 5433에 닿으면 **무인증으로 아무 계정·아무 DB**에 붙는다. 즉 아래에서
#                만드는 최소 권한 계정은 '사고 방어'조차 되지 못한다(hive로 vibe DB가 읽힌다).
#                2026-08-08에 터널 전용 루프백(127.0.0.2)으로 격리를 시도했으나 **실패**했다 —
#                pg_hba는 목적지가 아니라 **소스 주소**로 매칭하고, 루프백에서는 목적지가
#                127.0.0.2여도 커널이 소스를 127.0.0.1로 잡아 규칙이 영원히 매치되지 않는다.
#                근본 해결은 trust 제거 + 전 클라이언트 비밀번호화인데, 이 서버의
#                vibe-bridge/vibe-status가 /opt/vibe/vibe-coding(이 프로젝트 복사본)의
#                pg_base.py를 쓰고 그 코드에는 **비밀번호 파라미터가 없다**. 코드 변경이 선행돼야 한다.
#                → 현재는 "터널 키를 가진 PC = 신뢰 경계"로 수용한다. 그 PC에는 이미 서버
#                  관리용 root 키가 있어 위험 증가폭이 크지 않다는 판단(사용자 승인 2026-08-08).
#
#              [멱등] 두 번 이상 실행해도 안전하다. 이미 있으면 건너뛴다.
#
# 사용:
#   ssh -i ~/.ssh/vps_btsky_ed25519 root@<IP> 'bash -s' < scripts/remote/vps-knowledge-db.sh
#
# REVISION HISTORY:
# - 2026-08-08 Claude: 최초 작성 — 중앙 대화 PG 1차(Task 1).

set -euo pipefail

DB_NAME="${DB_NAME:-hive_knowledge}"
DB_USER="${DB_USER:-hive}"
PG_PORT="${PG_PORT:-5433}"
TUNNEL_KEY_NAME="${TUNNEL_KEY_NAME:-hive_tunnel_ed25519}"
AUTH_KEYS="/root/.ssh/authorized_keys"

echo "=== 아픽스 서버 중앙 대화 DB 셋업 ==="
echo "DB=$DB_NAME  USER=$DB_USER  PORT=$PG_PORT"
echo

# ── 0) 전제 확인 ─────────────────────────────────────────────────────────────
if ! systemctl is-active --quiet postgresql; then
    echo "[!] postgresql이 실행 중이 아니다. 중단한다." >&2
    exit 1
fi
echo "[0/4] PostgreSQL 실행 중 확인"

# ── 1) 비밀번호 준비 ──────────────────────────────────────────────────────────
# [WHY 파일에 보관] 재실행(멱등) 시 같은 비밀번호를 다시 써야 각 PC의 설정이 안 깨진다.
#   매번 새로 만들면 이미 배포된 config.json이 전부 무효가 된다.
PW_FILE="/root/.hive_db_password"
if [ -f "$PW_FILE" ]; then
    DB_PASS="$(cat "$PW_FILE")"
    echo "[1/4] 기존 비밀번호 재사용 ($PW_FILE)"
else
    DB_PASS="$(head -c 32 /dev/urandom | base64 | tr -d '/+=' | head -c 32)"
    printf '%s' "$DB_PASS" > "$PW_FILE"
    chmod 600 "$PW_FILE"
    echo "[1/4] 새 비밀번호 생성 → $PW_FILE (600)"
fi

# ── 2) 역할 + DB 생성 ────────────────────────────────────────────────────────
# [최소 권한] 슈퍼유저를 주지 않는다. DB 생성 권한도 없다. 이 계정이 유출돼도
#   서버의 다른 DB(vibe/root/postgres)에는 닿지 못한다.
su - postgres -c "psql -p $PG_PORT -tAc \"SELECT 1 FROM pg_roles WHERE rolname='$DB_USER'\"" \
    | grep -q 1 && ROLE_EXISTS=1 || ROLE_EXISTS=0

if [ "$ROLE_EXISTS" = "1" ]; then
    su - postgres -c "psql -p $PG_PORT -c \"ALTER ROLE $DB_USER WITH LOGIN PASSWORD '$DB_PASS' NOSUPERUSER NOCREATEDB NOCREATEROLE\"" >/dev/null
    echo "[2/4] 역할 $DB_USER 존재 → 비밀번호/권한 재적용"
else
    su - postgres -c "psql -p $PG_PORT -c \"CREATE ROLE $DB_USER WITH LOGIN PASSWORD '$DB_PASS' NOSUPERUSER NOCREATEDB NOCREATEROLE\"" >/dev/null
    echo "[2/4] 역할 $DB_USER 생성"
fi

if su - postgres -c "psql -p $PG_PORT -tAc \"SELECT 1 FROM pg_database WHERE datname='$DB_NAME'\"" | grep -q 1; then
    echo "      DB $DB_NAME 이미 존재 — 건너뜀"
else
    su - postgres -c "createdb -p $PG_PORT -O $DB_USER $DB_NAME"
    echo "      DB $DB_NAME 생성 (소유자 $DB_USER)"
fi

# pgvector — 2차(지식 공유)에서 쓴다. apt에 0.8.6이 이미 있으므로 지금 켜 둔다.
su - postgres -c "psql -p $PG_PORT -d $DB_NAME -c 'CREATE EXTENSION IF NOT EXISTS vector'" >/dev/null 2>&1 \
    && echo "      pgvector 확장 준비됨" \
    || echo "      [!] pgvector 활성화 실패 (1차 대화 기능에는 지장 없음)"

# [불변식] public 스키마에 임의 생성 권한을 열어두지 않는다(PG15+ 기본이 이미 제한적).
#   테이블 생성은 앱(pg_central)이 이 계정으로 자기 DB 안에서만 한다.
su - postgres -c "psql -p $PG_PORT -d $DB_NAME -c 'GRANT ALL ON SCHEMA public TO $DB_USER'" >/dev/null
echo "      스키마 권한 부여"

# ── 3) 터널 전용 SSH 키 등록 (공개키만 받는다) ────────────────────────────────
# [WHY 전용 키] 기존 관리용 키로 터널을 뚫으면 그 키가 유출될 때 서버 전체를 잃는다.
#   이 키는 permitopen 때문에 5433 포워딩 외엔 아무것도 못 한다 — 셸도 못 연다.
#
# [🔴 사고 2026-08-08] 초판은 서버에서 키쌍을 만들어 **개인키를 stdout으로 출력**했다.
#   이 프로젝트는 대화/작업 로그를 PG와 제텔 볼트에 기록하고 볼트는 GDrive로 나간다 —
#   즉 개인키가 클라우드까지 흘러갈 경로가 실재했다. 발급 직후 폐기하고 방식을 바꿨다.
#   이제 **키쌍은 각 PC에서 만들고 공개키만 여기로 보낸다.** 개인키는 그 PC를 떠나지 않는다.
#
# 사용: TUNNEL_PUBKEY="ssh-ed25519 AAAA... hive-tunnel@내PC" 를 환경변수로 넘긴다.
if [ -z "${TUNNEL_PUBKEY:-}" ]; then
    echo "[3/4] TUNNEL_PUBKEY 미지정 — 키 등록 건너뜀"
    echo "      각 PC에서: ssh-keygen -t ed25519 -N '' -f ~/.ssh/$TUNNEL_KEY_NAME"
    echo "      그 공개키를 TUNNEL_PUBKEY로 넘겨 이 스크립트를 다시 실행하면 등록된다."
    PUB=""
else
    PUB="$TUNNEL_PUBKEY"
    echo "[3/4] 전달받은 공개키 등록 (개인키는 서버에 존재하지 않는다)"
fi

if [ -n "$PUB" ]; then
# [🔴 옵션 조각을 하나도 빼지 말 것]
#   permitopen 없음 → 이 키로 서버의 아무 포트나 포워딩 가능(PG·상태API가 뚫린다).
#   no-pty 없음     → 셸 접속이 가능해진다.
#   과거 사고: authorized_keys 옵션 누락으로 터널 키가 VPS 내부에 닿던 구멍(cff33fb).
    # [🔴 조각을 하나도 빼지 말 것 — 둘 다 실제로 당한 사고다]
    #   port-forwarding 없음 → restrict가 포워딩까지 끄므로 터널이 열리지 않는다.
    #     permitopen은 '허용 목록'일 뿐 포워딩을 켜지 않는다. 증상은
    #     `channel N: open failed: administratively prohibited`이고, ssh 프로세스는
    #     멀쩡히 살아 있어 겉보기엔 연결된 것처럼 보인다(2026-08-09 실측).
    #   permitopen 없음 → 이 키로 서버의 아무 포트나 포워딩할 수 있다(PG·상태 API가 뚫림).
    #   no-pty 없음 → 셸 접속이 가능해진다.
    OPTS='restrict,port-forwarding,permitopen="127.0.0.1:'"$PG_PORT"'",no-agent-forwarding,no-X11-forwarding,no-pty'
    LINE="$OPTS $PUB"

    touch "$AUTH_KEYS"; chmod 600 "$AUTH_KEYS"
    if grep -qF "$PUB" "$AUTH_KEYS"; then
        # 키는 있는데 옵션이 다를 수 있다 — 해당 줄을 통째로 교체해 옵션을 강제한다.
        grep -vF "$PUB" "$AUTH_KEYS" > "$AUTH_KEYS.tmp" || true
        printf '%s\n' "$LINE" >> "$AUTH_KEYS.tmp"
        mv "$AUTH_KEYS.tmp" "$AUTH_KEYS"
        chmod 600 "$AUTH_KEYS"
        echo "      authorized_keys 항목 갱신(옵션 재적용)"
    else
        printf '%s\n' "$LINE" >> "$AUTH_KEYS"
        echo "      authorized_keys 등록"
    fi
fi

# ── 4) 결과 ──────────────────────────────────────────────────────────────────
# [🔴 비밀번호를 출력하지 않는다] 초판이 stdout으로 뿌렸다가 폐기했다(위 사고 주석 참조).
#   각 PC는 필요할 때 `ssh root@<서버> cat /root/.hive_db_password`로 직접 받아
#   config.json에 곧바로 기록한다 — 사람 눈과 로그를 거치지 않는 경로다.
echo
echo "[4/4] 완료."
echo "  DB_NAME=$DB_NAME  DB_USER=$DB_USER  PG_PORT=$PG_PORT"
echo "  비밀번호: /root/.hive_db_password (600) — 화면에 출력하지 않는다"
echo
echo "[확인] listen_addresses / 방화벽은 변경하지 않았다:"
su - postgres -c "psql -p $PG_PORT -tAc 'SHOW listen_addresses'" | sed 's/^/  listen_addresses = /'
ufw status 2>/dev/null | head -3 | sed 's/^/  /'
