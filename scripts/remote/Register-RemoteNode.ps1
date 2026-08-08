<#
FILE: scripts/remote/Register-RemoteNode.ps1
DESCRIPTION: 원격 노드가 보내온 공개키를 VPS에 등록하고, 이쪽에서 `ssh <노드명>` 한 줄로
             붙을 수 있게 ~/.ssh/config 별칭까지 잡는다. Setup-RemoteNode.ps1의 짝(2단계).

             Setup-RemoteNode.ps1은 대상 PC에서 돌고, 이 스크립트는 **관리하는 쪽**에서 돈다.
             둘이 만나야 터널이 성립한다 — 한쪽만 하면 연결되지 않는다.

             사용:
               .\Register-RemoteNode.ps1 -NodeName cipher -TunnelPort 22001 `
                   -RemoteUser com -PublicKey 'ssh-ed25519 AAAA... tunnel-cipher'

REVISION HISTORY:
- 2026-08-07 Claude: 최초 작성 — VPS 경유 역터널 구조의 등록 단계.
#>

[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$NodeName,
    [Parameter(Mandatory)][int]$TunnelPort,

    # 대상 PC에서 로그인할 계정명(그 PC의 Windows 사용자명 또는 맥 계정).
    [Parameter(Mandatory)][string]$RemoteUser,

    # Setup-RemoteNode.ps1이 출력한 ssh-ed25519 로 시작하는 한 줄.
    [Parameter(Mandatory)][string]$PublicKey,

    [string]$VpsHost = '',
    [string]$VpsKey = ''
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Say($m, $lvl = 'INFO') {
    $c = @{ 'INFO' = 'Gray'; 'OK' = 'Green'; 'WARN' = 'Yellow'; 'FAIL' = 'Red' }[$lvl]
    Write-Host ("[{0,-4}] {1}" -f $lvl, $m) -ForegroundColor $c
}

# [WHY 저장소가 아니라 로컬 파일에서 읽나] 이 저장소는 공개다. 서버 주소를 기본값으로 박으면
#   공개된다(2026-08-07 실제 사고). 값은 vps-setup이 남긴 로컬 비밀 파일에서 읽는다.
$secretFile = Join-Path $env:LOCALAPPDATA 'vibe-remote\rustdesk-server.txt'
if ([string]::IsNullOrWhiteSpace($VpsHost)) {
    if (-not (Test-Path $secretFile)) { throw "VPS 주소를 알 수 없다. -VpsHost로 주거나 $secretFile 을 준비하라." }
    $VpsHost = ((Get-Content $secretFile | Where-Object { $_ -match '^server=' }) -split '=', 2)[1].Trim()
}
if ([string]::IsNullOrWhiteSpace($VpsKey)) { $VpsKey = "$env:USERPROFILE\.ssh\vps_btsky_ed25519" }
if (-not (Test-Path $VpsKey)) { throw "VPS SSH 키가 없다: $VpsKey" }

if ($PublicKey -notmatch '^ssh-(ed25519|rsa)\s+\S+') {
    throw "공개키 형식이 아니다. 'ssh-ed25519 AAAA...' 한 줄을 그대로 넣어라.`n받은 값: $PublicKey"
}
$PublicKey = $PublicKey.Trim()

Write-Host ''
Write-Host "=== 노드 등록: $NodeName (포트 $TunnelPort) ===" -ForegroundColor Cyan
Write-Host ''

# ── 1. VPS authorized_keys 등록 ─────────────────────────────────────────────
# [보안 불변식] restrict 로 전부 끄고, 되살릴 것만 골라 되살린다.
#
# [🔴 2026-08-08 실측으로 밝혀진 두 가지 — 추측으로 되돌리지 말 것]
#
#  (1) `restrict,permitlisten="PORT"` 만으로는 **터널이 아예 안 열린다.**
#      restrict 가 포트포워딩을 끄고, permitlisten 은 '허용 범위를 좁히는' 옵션일 뿐
#      꺼진 기능을 켜지 못한다. 그래서 `port-forwarding` 을 함께 줘야 한다.
#      실측: ssh 가 "remote port forwarding failed for listen port 22009" 로 거절.
#      이 형태로 등록된 노드는 등록은 성공한 것처럼 보이고 접속만 조용히 실패한다.
#
#  (2) `port-forwarding` 은 역방향(-R)뿐 아니라 **정방향(-L)까지 함께** 켠다.
#      그러면 이 키로 VPS 내부에 닿을 수 있다 — PostgreSQL(5433, 루프백 trust 인증)과
#      상태 API(9100)가 그대로 열린다. 실측에서 터널 키로 9100 JSON 응답을 받아냈다.
#      permitopen 을 존재하지 않는 대상 하나로 고정해 -L 을 봉쇄한다.
#      (permitopen 을 아예 안 쓰면 '전부 허용'이 기본값이라 구멍이 남는다.)
#
# permitlisten 을 3가지 표기로 적는 이유 — 클라이언트가 `-R PORT:`, `-R localhost:PORT:`,
#   `-R 127.0.0.1:PORT:` 중 무엇을 보내는지에 따라 매칭 대상이 달라진다. 셋 다 열어두면
#   노드 쪽 명령 형태가 무엇이든 걸리지 않는다(3형태 모두 실측 통과).
# [멱등] 같은 노드를 다시 등록하면 옛 줄을 지우고 새로 넣는다 — 중복 누적을 막는다.
$authOpts = @(
    'restrict'
    'port-forwarding'
    "permitlisten=`"$TunnelPort`""
    "permitlisten=`"localhost:$TunnelPort`""
    "permitlisten=`"127.0.0.1:$TunnelPort`""
    'permitopen="127.0.0.1:1"'
) -join ','
$authLine = "$authOpts $PublicKey"
$b64 = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($authLine))

# [함정] 여러 줄 bash를 PowerShell 문자열로 넘기면 따옴표/BOM에서 깨진다.
#   base64로 실어 보내고 서버에서 풀면 인용 문제가 사라진다.
$remote = @"
set -e
mkdir -p /home/tunnel/.ssh && touch /home/tunnel/.ssh/authorized_keys
LINE=`$(echo '$b64' | base64 -d)
# 같은 노드(포트)로 등록된 옛 줄 제거 후 재등록
grep -v 'permitlisten="$TunnelPort"' /home/tunnel/.ssh/authorized_keys > /tmp/ak.new 2>/dev/null || true
echo "`$LINE" >> /tmp/ak.new
mv /tmp/ak.new /home/tunnel/.ssh/authorized_keys
chown -R tunnel:tunnel /home/tunnel/.ssh
chmod 700 /home/tunnel/.ssh && chmod 600 /home/tunnel/.ssh/authorized_keys
echo "등록된 노드 수: `$(wc -l < /home/tunnel/.ssh/authorized_keys)"
"@

$remote = $remote -replace "`r`n", "`n"
$remote | & ssh -i $VpsKey -o BatchMode=yes "root@$VpsHost" "bash -s" 2>&1 | ForEach-Object { "  $_" }
Say "VPS authorized_keys 등록 완료 (permitlisten=$TunnelPort)" 'OK'

# ── 2. 로컬 SSH 별칭 ────────────────────────────────────────────────────────
# [WHY ProxyJump인가] 터널은 VPS의 **루프백**에만 열린다(sshd 기본값 GatewayPorts=no).
#   즉 바깥에서 VpsHost:22001로 바로 못 붙는다 — VPS 안에서 localhost:22001로 붙어야 한다.
#   ProxyJump가 그 한 단계를 자동으로 처리한다. 이 제약은 보안상 바람직하다(터널 포트가
#   공인망에 노출되지 않는다).
$cfgPath = "$env:USERPROFILE\.ssh\config"
$cfg = if (Test-Path $cfgPath) { Get-Content $cfgPath -Raw } else { '' }

if ($cfg -notmatch '(?m)^Host\s+vibe-vps\b') {
    $cfg += @"

# 서울 VPS — 역터널 점프 호스트 (Register-RemoteNode.ps1 자동 추가)
Host vibe-vps
    HostName $VpsHost
    User root
    IdentityFile $VpsKey
    StrictHostKeyChecking accept-new
"@
    Say '점프 호스트 별칭 추가: vibe-vps' 'OK'
}

# 기존 노드 블록이 있으면 통째로 걷어내고 다시 쓴다(멱등).
$cfg = [regex]::Replace($cfg, "(?ms)^# 원격 노드: $([regex]::Escape($NodeName))\b.*?(?=^Host |\z)", '')
$cfg += @"

# 원격 노드: $NodeName (VPS 경유 역터널)
Host $NodeName
    HostName localhost
    Port $TunnelPort
    User $RemoteUser
    ProxyJump vibe-vps
    StrictHostKeyChecking accept-new
    ServerAliveInterval 30
"@

$enc = New-Object System.Text.UTF8Encoding($false)
[System.IO.File]::WriteAllText($cfgPath, ($cfg -replace "`r`n", "`n"), $enc)
Say "SSH 별칭 추가: ssh $NodeName" 'OK'

# ── 3. 터널이 실제로 올라왔는지 ─────────────────────────────────────────────
# [WHY 확인하나] 등록만 하고 "됐다"고 하면, 상대 PC가 아직 재접속하지 않은 상태를
#   성공으로 착각한다. 터널 루프는 15초 주기라 잠깐 기다렸다 본다.
Say '터널 연결 대기 중 (최대 60초)...'
$up = $false
for ($i = 0; $i -lt 12; $i++) {
    Start-Sleep -Seconds 5
    $listen = & ssh -i $VpsKey -o BatchMode=yes "root@$VpsHost" "ss -tlnp 2>/dev/null | grep -c ':$TunnelPort '" 2>$null
    if ("$listen".Trim() -match '^[1-9]') { $up = $true; break }
}

Write-Host ''
if ($up) {
    Say "터널 연결 확인 — VPS의 localhost:$TunnelPort 가 열렸다" 'OK'
    Write-Host ''
    Write-Host "  이제 이렇게 붙는다:" -ForegroundColor Gray
    Write-Host "    ssh $NodeName" -ForegroundColor White
    Write-Host ''
} else {
    Say "터널이 아직 안 올라왔다." 'WARN'
    Write-Host '  확인할 것:' -ForegroundColor Gray
    Write-Host '   · 대상 PC에서 Setup-RemoteNode.ps1을 실행했는가' -ForegroundColor Gray
    Write-Host "   · 그 PC에서: Get-ScheduledTask -TaskName vibe-tunnel-$NodeName" -ForegroundColor Gray
    Write-Host '   · 예약 작업은 부팅 시 시작이라, 설치 직후엔 수동 시작이 필요할 수 있다:' -ForegroundColor Gray
    Write-Host "       Start-ScheduledTask -TaskName vibe-tunnel-$NodeName" -ForegroundColor Gray
    Write-Host '   · 공개키가 정확히 전달됐는가(줄바꿈으로 잘리지 않았는지)' -ForegroundColor Gray
    Write-Host ''
}
