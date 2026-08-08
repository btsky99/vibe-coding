#!/usr/bin/env bash
# FILE: scripts/remote/vps-pg-connections.sh
# DESCRIPTION: 아픽스 서버 PostgreSQL의 max_connections를 상향한다.
#              여러 노드가 중앙 대화 PG에 붙으면 사양이 아니라 이 설정값에서 먼저 막힌다.
#
#              [WHY 이 값이 병목인가] 실측 2026-08-09: 10/20 사용 중, 여유 10개.
#                노드가 붙을 때 쿼리용 1개 + NOTIFY LISTEN용 1개를 쓰면 노드당 2개다.
#                LISTEN 커넥션은 이벤트를 기다리며 **상시 점유**하므로 반납되지 않는다.
#                노드 5대만 붙어도 20을 넘고, 그때 나는 에러는
#                `FATAL: sorry, too many clients already` — 새로 붙는 쪽만 실패하므로
#                "내 PC에서만 안 된다"로 보여 진단이 오래 걸린다.
#
#              [WHY 메모리는 괜찮은가] 커넥션당 대략 5~10MB. 20→50이면 최대 +300MB이고
#                실측 여유가 1403MB다. 이 서버의 제약은 CPU/메모리가 아니라 설정값이었다.
#
#              [🔴 드롭인으로 넣는 이유 — 2026-08-08에 실제로 당한 함정]
#                postgresql.conf를 고쳐도 878줄의 `include_dir = 'conf.d'`가 **더 뒤에서**
#                읽히기 때문에 conf.d/99-lowmem.conf의 값이 최종 승자가 된다.
#                PG는 같은 파라미터가 여러 번 나오면 마지막 값을 쓴다. 그래서 conf.d 안에서
#                기존 파일보다 뒤에 정렬되는 이름(99-zz-)으로 넣어야 실제로 적용된다.
#
# 사용:  ssh root@<IP> 'bash -s' < 이 파일          (멱등)
# 롤백:  ROLLBACK=1 을 붙여 실행
#
# REVISION HISTORY:
# - 2026-08-09 Claude: 최초 작성 — Phase 10(중앙 대화 PG) 선행 조건.

set -euo pipefail

PGVER=18
CONF_DIR="/etc/postgresql/$PGVER/main"
DROPIN="$CONF_DIR/conf.d/99-zz-connections.conf"
PG_PORT=5433
TARGET="${MAX_CONN:-50}"

if [ "${ROLLBACK:-0}" = "1" ]; then
    echo "[rollback] 드롭인 제거 후 재시작"
    rm -f "$DROPIN"
    systemctl restart postgresql
    sleep 4
    echo -n "  max_connections = "
    su postgres -c "psql -p $PG_PORT -tAc 'SHOW max_connections'"
    exit 0
fi

echo "=== PG max_connections 상향 ==="
CUR="$(su postgres -c "psql -p $PG_PORT -tAc 'SHOW max_connections'")"
USED="$(su postgres -c "psql -p $PG_PORT -tAc 'SELECT count(*) FROM pg_stat_activity'")"
echo "  현재: $USED / $CUR  → 목표: $TARGET"

if [ "$CUR" -ge "$TARGET" ]; then
    echo "  이미 충분 — 변경 없음"
    exit 0
fi

mkdir -p "$CONF_DIR/conf.d"
cat > "$DROPIN" <<EOF
# 관리 파일 — vps-pg-connections.sh가 생성. 손으로 고치지 말 것.
# 중앙 대화 PG에 노드가 붙을 때 LISTEN 커넥션이 상시 점유되므로 여유가 필요하다.
# 이 파일은 99-lowmem.conf보다 뒤에 읽혀야 값이 적용된다(파일명 정렬이 곧 우선순위).
max_connections = $TARGET
EOF
chown postgres:postgres "$DROPIN"
echo "  드롭인 생성: $DROPIN"

echo -n "  재시작 전 서비스: "
systemctl is-active vibe-bridge vibe-status apix-collector oauth2-proxy nginx 2>/dev/null | tr '\n' ' '; echo

systemctl restart postgresql
sleep 5
systemctl is-active --quiet postgresql || { echo "[!] PG 기동 실패 — ROLLBACK=1로 복원할 것"; exit 1; }

echo
echo "=== 검증 ==="
echo -n "  max_connections = "
su postgres -c "psql -p $PG_PORT -tAc 'SHOW max_connections'"
echo -n "  현재 사용: "
su postgres -c "psql -p $PG_PORT -tAc 'SELECT count(*) FROM pg_stat_activity'"
echo -n "  기존 경로 접속(127.0.0.1 trust): "
psql -h 127.0.0.1 -p $PG_PORT -U postgres -d postgres -tAc "SELECT 'OK'" 2>&1 | head -1
echo -n "  hive 계정 접속: "
PGPASSWORD="$(cat /root/.hive_db_password)" psql -h 127.0.0.1 -p $PG_PORT -U hive -d hive_knowledge -tAc "SELECT 'OK'" 2>&1 | head -1
echo -n "  서비스 생존: "
systemctl is-active vibe-bridge vibe-status apix-collector oauth2-proxy nginx 2>/dev/null | tr '\n' ' '; echo
echo -n "  메모리 여유: "
free -m | awk '/Mem:/{print $7"MB"}'
