#!/usr/bin/env bash
# FILE: scripts/remote/vps-pg-tunnel-isolate.sh
# DESCRIPTION: 아픽스 서버 PG에 '터널 전용 루프백 주소(127.0.0.2)'를 추가해, 터널로 들어온
#              연결이 hive 계정 + hive_knowledge DB 외엔 아무것도 못 하게 격리한다.
#
#              [WHY 이게 필요한가] pg_hba에 `host all all 127.0.0.1/32 trust`가 있다.
#                터널이 127.0.0.1:5433에 닿으면 **무인증으로 아무 계정·아무 DB**에 붙는다.
#                permitopen으로 포트를 좁혀도 그 안이 무방비면 최소 권한 계정이 무의미하다.
#
#              [WHY trust를 그냥 끄지 않는가] 이 서버의 vibe-bridge/vibe-status는
#                /opt/vibe/vibe-coding(이 프로젝트의 복사본)을 돌리는데, 그 pg_base.py는
#                host='127.0.0.1'에 **비밀번호 파라미터 없이** 붙는다. trust를 끄면 즉시 죽는다.
#                그래서 기존 127.0.0.1 경로는 건드리지 않고 새 주소를 하나 더 연다.
#
#              [방어 범위 — 솔직히] 이건 침입 방어가 아니다. PC가 털리면 그 PC의 관리용
#                root 키로 서버 전체를 잃으므로 이 격리는 무의미하다. 이것이 막는 것은
#                **사고**다 — 앱 버그나 잘못된 쿼리가 다른 DB를 건드리는 경우.
#
#              [노출] 127.0.0.2는 루프백이다. 외부 노출은 여전히 0이고 방화벽도 안 건드린다.
#
# 사용:  ssh root@<IP> 'bash -s' < 이 파일        (멱등)
# 롤백:  ROLLBACK=1 을 붙여 실행하면 백업본으로 되돌리고 재시작한다.
#
# REVISION HISTORY:
# - 2026-08-08 Claude: 최초 작성 — 중앙 대화 PG Task 2 보안 보강.

set -euo pipefail

PGVER=18
CONF_DIR="/etc/postgresql/$PGVER/main"
HBA="$CONF_DIR/pg_hba.conf"
CONF="$CONF_DIR/postgresql.conf"
STAMP="pre-tunnel-isolate"
TUNNEL_ADDR="127.0.0.2"
PG_PORT=5433
DB_NAME=hive_knowledge
DB_USER=hive
MARK="# --- hive tunnel isolation (managed) ---"

# ── 롤백 경로 ────────────────────────────────────────────────────────────────
if [ "${ROLLBACK:-0}" = "1" ]; then
    echo "[rollback] 백업본으로 복원"
    for f in "$HBA" "$CONF"; do
        if [ -f "$f.$STAMP" ]; then
            cp -f "$f.$STAMP" "$f"
            echo "  복원: $f"
        else
            echo "  [!] 백업 없음: $f.$STAMP"
        fi
    done
    systemctl restart postgresql
    sleep 3
    systemctl is-active postgresql && echo "[rollback] PG 재시작 완료"
    exit 0
fi

echo "=== PG 터널 격리 ($TUNNEL_ADDR) ==="

# ── 0) 백업 (한 번만 — 최초 상태를 보존해야 롤백이 의미 있다) ─────────────────
for f in "$HBA" "$CONF"; do
    [ -f "$f.$STAMP" ] || { cp -a "$f" "$f.$STAMP"; echo "[0/4] 백업 생성: $f.$STAMP"; }
done

# ── 1) listen_addresses에 터널 주소 추가 ─────────────────────────────────────
# [🔴 함정 2026-08-08] postgresql.conf를 고쳐도 소용없다. 878줄의 `include_dir = 'conf.d'`가
#   **더 뒤에서** 읽히기 때문에 conf.d/99-lowmem.conf의 listen_addresses가 최종 승자다.
#   PG는 같은 파라미터가 여러 번 나오면 **마지막 값**을 쓴다. 그래서 conf.d 안에서
#   기존 파일보다 뒤에 정렬되는 이름(99-zz-)으로 넣어야 실제로 적용된다.
#   [불변식] 127.0.0.1을 절대 빼지 않는다 — 빼면 기존 서비스가 전부 끊긴다.
DROPIN="$CONF_DIR/conf.d/99-zz-hive-tunnel.conf"
CUR="$(su postgres -c "psql -p $PG_PORT -tAc 'SHOW listen_addresses'")"
echo "[1/4] 현재 listen_addresses = $CUR"

# 이전 판이 postgresql.conf를 직접 고쳤다면 그 흔적을 되돌린다(설정이 두 곳에 갈리면 헷갈린다).
if grep -q "# hive tunnel" "$CONF"; then
    sed -i "/# hive tunnel/d" "$CONF"
    echo "      postgresql.conf의 이전 수정 제거(설정 출처를 conf.d 한 곳으로 통일)"
fi

if echo "$CUR" | grep -q "$TUNNEL_ADDR"; then
    echo "      이미 적용됨 — 변경 없음"
    NEED_RESTART=0
else
    mkdir -p "$CONF_DIR/conf.d"
    cat > "$DROPIN" <<EOF
# 관리 파일 — vps-pg-tunnel-isolate.sh가 생성. 손으로 고치지 말 것.
# 127.0.0.2는 터널 전용 입구다. 루프백이라 외부 노출은 여전히 0이며,
# pg_hba가 이 주소에서는 hive/$DB_NAME 외 전부 거부한다.
listen_addresses = '127.0.0.1,$TUNNEL_ADDR'
EOF
    chown postgres:postgres "$DROPIN"
    echo "      드롭인 생성: $DROPIN (재시작 필요)"
    NEED_RESTART=1
fi

# ── 2) pg_hba 규칙 (첫 매치 우선이므로 파일 맨 앞에) ─────────────────────────
if grep -qF "$MARK" "$HBA"; then
    echo "[2/4] pg_hba 규칙 이미 존재 — 건너뜀"
else
    TMP="$(mktemp)"
    {
        echo "$MARK"
        echo "# 터널 전용 주소: hive 계정이 hive_knowledge에 접근할 때만 허용, 나머지는 전부 거부."
        echo "# 순서가 곧 정책이다 — reject가 뒤에 와야 허용 규칙이 먼저 매치된다."
        echo "host    $DB_NAME    $DB_USER    $TUNNEL_ADDR/32    scram-sha-256"
        echo "host    all         all         $TUNNEL_ADDR/32    reject"
        echo "$MARK"
        cat "$HBA"
    } > "$TMP"
    mv "$TMP" "$HBA"
    chown postgres:postgres "$HBA"; chmod 640 "$HBA"
    echo "[2/4] pg_hba 규칙 삽입 (허용 1줄 + 거부 1줄)"
fi

# ── 3) 반영 ──────────────────────────────────────────────────────────────────
echo "[3/4] 반영"
echo -n "      재시작 전 서비스: "
systemctl is-active vibe-bridge vibe-status 2>/dev/null | tr '\n' ' '; echo
if [ "$NEED_RESTART" = "1" ]; then
    systemctl restart postgresql
    sleep 4
else
    systemctl reload postgresql
    sleep 1
fi
systemctl is-active --quiet postgresql || { echo "[!] PG 기동 실패 — ROLLBACK=1로 복원할 것"; exit 1; }
echo "      postgresql: active"

# ── 4) 검증 ──────────────────────────────────────────────────────────────────
# [WHY set +e] 검증 항목 중 (3)(4)는 **실패해야 정상**이다. set -e인 채로 두면
#   기대한 거부에서 스크립트가 죽어 나머지 검증(기존 서비스 생존 등)을 못 본다.
set +e
echo "[4/4] 검증"
PW="$(cat /root/.hive_db_password)"

echo -n "      (1) 기존 경로 127.0.0.1 trust 유지: "
psql -h 127.0.0.1 -p $PG_PORT -U postgres -d postgres -tAc "SELECT 'OK'" 2>&1 | head -1

echo -n "      (2) 터널 주소로 hive → hive_knowledge (허용돼야 함): "
PGPASSWORD="$PW" psql -h $TUNNEL_ADDR -p $PG_PORT -U $DB_USER -d $DB_NAME -tAc "SELECT 'OK'" 2>&1 | head -1

echo -n "      (3) 터널 주소로 hive → vibe DB (거부돼야 함): "
PGPASSWORD="$PW" psql -h $TUNNEL_ADDR -p $PG_PORT -U $DB_USER -d vibe -tAc "SELECT 'LEAK'" 2>&1 | head -1

echo -n "      (4) 터널 주소로 postgres 슈퍼유저 (거부돼야 함): "
psql -h $TUNNEL_ADDR -p $PG_PORT -U postgres -d postgres -tAc "SELECT 'LEAK'" 2>&1 | head -1

echo -n "      (5) 기존 서비스 생존: "
systemctl is-active vibe-bridge vibe-status 2>/dev/null | tr '\n' ' '; echo

echo -n "      (6) 외부 노출 재확인: "
ss -tln 2>/dev/null | grep -c "$PG_PORT" | xargs -I{} echo "{} listener(s), 전부 루프백이어야 함"
ss -tln 2>/dev/null | grep "$PG_PORT" | sed 's/^/          /'
