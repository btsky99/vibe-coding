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

# ── 3. (은퇴) 상태 API · nginx ──────────────────────────────────────────────
# [🔴 2026-08-09 이후 이 스크립트는 정적 파일만 배포한다]
#   상태 API(vibe-status)는 아픽스 콘솔의 collector 가 승계했고, nginx 설정은
#   apix-console 리포(deploy/nginx-apix.conf)가 소유한다.
#
#   여기서 nginx 를 다시 쓰면 sites-enabled/vibe 가 되살아나 콘솔 사이트와
#   **같은 server_name 이 둘**이 된다. nginx 는 그때 뒤쪽을 경고 없이 무시하므로
#   "배포했는데 콘솔이 사라졌다"는 증상이 원인 불명으로 나타난다.
#   상태 API 도 마찬가지로 되살리면 9100 포트와 옛 /api/status 경로가 함께 부활해
#   무인증 공개 사고(2026-08-08)의 무대가 다시 열린다.
#
#   되돌릴 일이 생기면 git 이력에서 이 블록을 꺼내되, 반드시
#   apix-console 쪽 설정과의 충돌을 먼저 정리할 것.

# ── 4. 검증 — '설정했다'가 아니라 '응답한다'를 본다 ─────────────────────────
echo
echo "=== 검증 ==="
PUBIP=$(ip -4 -o addr show scope global | awk '{print $4}' | cut -d/ -f1 | head -1)
D1=btsky.pe.kr

# [🔴 함정] 서버가 자기 도메인을 확인할 때는 --resolve 로 IP 를 못박는다.
#   systemd-resolved 가 옛 레코드를 캐시해 자기 검사가 남의 서버 응답을 받아온다
#   (2026-08-08~09 에 두 번 오판했다). 평문 http 로 재는 것도 금물 — 80 블록은
#   리다이렉트뿐이라 콘텐츠 판정에 쓸 수 없다.
probe(){ curl -s -o /dev/null -w '%{http_code}' --max-time 10          --resolve "${D1}:443:${PUBIP}" "https://${D1}$1" || echo 000; }

m=$(probe /)
v=$(probe /vibe-coding/)
c=$(probe /console/)
printf '  메인            HTTP %s  ← 200
' "$m"
printf '  /vibe-coding/   HTTP %s  ← 200
' "$v"
printf '  /console/       HTTP %s  ← 302(로그인) — 200 이면 게이트가 풀린 것
' "$c"

[ "$m" = "200" ] && [ "$v" = "200" ] && [ "$c" = "302" ]   && ok "정적 배포 완료 (콘솔 게이트 정상)"   || warn "예상과 다름 — 위 코드 확인"
