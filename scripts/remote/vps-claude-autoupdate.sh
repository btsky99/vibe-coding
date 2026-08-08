#!/usr/bin/env bash
# FILE: scripts/remote/vps-claude-autoupdate.sh
# DESCRIPTION: 아픽스 서버의 Claude Code CLI를 자동 갱신하는 systemd 타이머를 설치한다.
#              동시에 서버 상주 에이전트의 기본 모델을 Sonnet으로 고정한다.
#
#              [WHY 타이머가 필요한가] Claude Code는 자체 업데이터를 갖고 있지만, 이 서버는
#                npm 글로벌(root 소유 /usr/lib/node_modules)로 설치돼 있고 실행 주체가
#                systemd 서비스(vibe-bridge)라 대화형 업데이트 경로를 타지 않는다.
#                실측 2026-08-08: 설치 2.1.224 / npm 최신 2.1.226 — 갱신이 멎어 있었다.
#
#              [WHY Sonnet인가] 서버 에이전트의 일은 상태 해석과 짧은 알림이다. 인증이
#                OAuth 구독이라 서버가 쓰는 토큰이 **사용자 PC의 작업 쿼터에서 나간다** —
#                상위 티어를 상주시키면 정작 사람이 코딩할 때 한도를 만난다.
#
#              [WHY cron이 아니라 systemd timer인가] 로그가 journald로 모여 사후 추적이
#                되고, Persistent=true 덕에 서버가 꺼져 있던 동안 놓친 실행을 부팅 후
#                따라잡는다. cron은 둘 다 직접 만들어야 한다.
#
# 사용: ssh root@<IP> 'bash -s' < scripts/remote/vps-claude-autoupdate.sh   (멱등)
#
# REVISION HISTORY:
# - 2026-08-08 Claude: 최초 작성 — 자동 갱신 + 모델 고정.

set -euo pipefail

PKG="@anthropic-ai/claude-code"
MODEL="${CLAUDE_MODEL:-claude-sonnet-5}"
UPDATER=/usr/local/bin/claude-autoupdate.sh

echo "=== Claude CLI 자동 갱신 설치 ==="
echo "모델: $MODEL"
echo

# ── 1) 모델 고정 ─────────────────────────────────────────────────────────────
# [제약] settings.json은 사람이 편집하는 파일이다. 통째로 덮으면 permissions/projects가
#   날아간다 — python으로 해당 키만 병합한다(jq는 이 서버에 없을 수 있다).
echo "[1/3] settings.json에 모델 고정"
for home in /root /home/vibe; do
    f="$home/.claude/settings.json"
    [ -f "$f" ] || { echo "  건너뜀(없음): $f"; continue; }
    python3 - "$f" "$MODEL" <<'PY'
import json, sys
path, model = sys.argv[1], sys.argv[2]
with open(path, encoding='utf-8') as fh:
    cfg = json.load(fh)
before = cfg.get('model')
cfg['model'] = model
with open(path, 'w', encoding='utf-8') as fh:
    json.dump(cfg, fh, ensure_ascii=False, indent=2)
print(f"  {path}: {before or '(미지정)'} -> {model}")
PY
done

# ── 2) 갱신 스크립트 ─────────────────────────────────────────────────────────
echo "[2/3] 갱신 스크립트 설치: $UPDATER"
cat > "$UPDATER" <<UPD
#!/usr/bin/env bash
# Claude Code CLI 갱신. 버전이 바뀐 경우에만 브리지를 재시작한다.
# [제약] 실패해도 0으로 끝낸다 — 타이머 실패가 알림 소음이 되면 진짜 사고가 묻힌다.
set -uo pipefail

before="\$(claude --version 2>/dev/null | awk '{print \$1}')"
latest="\$(npm view $PKG version 2>/dev/null)"

if [ -z "\$latest" ]; then
    echo "npm 조회 실패 — 건너뜀 (현재 \$before)"
    exit 0
fi
if [ "\$before" = "\$latest" ]; then
    echo "최신 상태 (\$before)"
    exit 0
fi

echo "갱신 \$before -> \$latest"
if ! npm install -g "$PKG@latest" >/dev/null 2>&1; then
    echo "npm 설치 실패 — 현재 버전 유지 (\$before)"
    exit 0
fi

after="\$(claude --version 2>/dev/null | awk '{print \$1}')"
echo "설치 완료: \$after"

# [WHY 재시작하나] 브리지는 claude를 매 호출마다 새로 실행하므로 대개 재시작이 필요 없다.
#   다만 갱신 시점에 장시간 호출이 물려 있으면 옛 바이너리 경로를 잡고 있을 수 있어,
#   버전이 실제로 바뀐 경우에만 한 번 정리한다.
if [ "\$after" != "\$before" ]; then
    systemctl restart vibe-bridge 2>/dev/null && echo "vibe-bridge 재시작" || echo "vibe-bridge 재시작 실패(무시)"
fi
exit 0
UPD
chmod +x "$UPDATER"

# ── 3) systemd 타이머 ────────────────────────────────────────────────────────
echo "[3/3] systemd 타이머 등록"
cat > /etc/systemd/system/claude-autoupdate.service <<'SVC'
[Unit]
Description=Claude Code CLI 자동 갱신
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
ExecStart=/usr/local/bin/claude-autoupdate.sh
SVC

# [WHY 하루 1회 + 무작위 지연] 릴리즈는 하루 여러 번 나올 수 있지만 서버 에이전트가
#   최신을 분 단위로 따라갈 이유가 없다. RandomizedDelaySec은 같은 시각에 여러 노드가
#   npm 레지스트리를 동시에 때리는 것을 흩는다.
cat > /etc/systemd/system/claude-autoupdate.timer <<'TMR'
[Unit]
Description=Claude Code CLI 자동 갱신 (매일)

[Timer]
OnCalendar=daily
RandomizedDelaySec=1h
Persistent=true

[Install]
WantedBy=timers.target
TMR

systemctl daemon-reload
systemctl enable --now claude-autoupdate.timer >/dev/null 2>&1
echo "  타이머 활성화"

echo
echo "=== 확인 ==="
echo -n "  현재 버전: "; claude --version 2>/dev/null
echo -n "  npm 최신:  "; npm view "$PKG" version 2>/dev/null
echo "  다음 실행:"; systemctl list-timers claude-autoupdate.timer --no-pager 2>/dev/null | sed -n 2p | sed 's/^/    /'
echo
echo "지금 즉시 한 번 돌리려면: systemctl start claude-autoupdate.service"
echo "로그 보기:                journalctl -u claude-autoupdate -n 30 --no-pager"
