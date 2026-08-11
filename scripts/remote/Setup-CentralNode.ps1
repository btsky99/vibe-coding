<#
FILE: scripts/remote/Setup-CentralNode.ps1
DESCRIPTION: 바이브 코딩이 깔린 PC 를 '중앙 대화' 노드로 붙인다. 대상 PC 에서 1회 실행한다.
             하는 일 — ① 터널 전용 SSH 키 발급 ② config.json 의 central_db + 원격 주입
             게이트 주입 ③ 터널을 실제로 열어 실증 ④ 안 되면 원인을 갈라 보여준다.

             사용 (대상 PC 의 PowerShell — 관리자 권한 불필요):
               .\Setup-CentralNode.ps1 -Password '<hive DB 비밀번호>'
               .\Setup-CentralNode.ps1 -Password '<...>' -NodeSeq 3     # 번호를 고정하고 싶을 때

             비밀번호는 관리 PC 에서 받아 온다(서버가 화면에 출력하지 않는 값):
               ssh root@158.247.205.192 cat /root/.hive_db_password

             [🔴 왜 2단계인가 — 개인키가 PC 를 떠나지 못하기 때문] 이 스크립트는 공개키만
             출력한다. 그 한 줄을 관리 PC 에서 서버에 등록해야 연결이 성립한다(아래 안내가
             명령을 그대로 찍어 준다). 초판 설계는 서버에서 키쌍을 만들어 개인키를 내려주는
             것이었는데, 이 프로젝트는 대화 로그를 제텔 볼트에 남기고 볼트는 GDrive 로
             나간다 — 개인키가 클라우드까지 흘러갈 경로가 실재해서 폐기했다(2026-08-08).

             [🔴 등록용 스크립트를 새로 만들지 않았다] 서버 쪽 등록은 기존
             vps-knowledge-db.sh 가 TUNNEL_PUBKEY 환경변수로 이미 처리한다(멱등).
             authorized_keys 옵션 문자열은 조각 하나만 빠져도 조용히 뚫리거나 조용히
             막히는 값이라, 같은 문자열을 두 곳에 두는 순간 한쪽만 고쳐지는 사고가 난다.

             [WHY 실증까지 하나] 설정만 써 두고 끝내면 '붙었다'는 착각만 남는다. 터널은
             프로세스가 멀쩡히 살아 있어도 채널이 거부될 수 있어(아래 port-forwarding 함정)
             겉보기로는 구분되지 않는다 — 실제로 TCP 를 한 번 열어봐야 안다.

REVISION HISTORY:
- 2026-08-11 Claude: central_remote_inject 도 같이 세운다 — 연결만 세운 노드(na2js)가
                     메시지를 받고도 CLI 에 못 꽂아 '답 없는 노드'가 됐다.
- 2026-08-11 Claude: 최초 작성 — Phase 10 Task 32. 지금까지 신규 노드 연결이 수작업이라
                     다른 PC 를 붙이는 것 자체가 막혀 있었다.
#>

[CmdletBinding()]
param(
    # 서버의 hive 계정 비밀번호. 서버는 이 값을 화면에 출력하지 않는다 — 위 안내 참조.
    [Parameter(Mandatory)][string]$Password,

    [string]$ServerHost = '158.247.205.192',
    [string]$SshUser = 'root',

    # 서버에서 PG 가 듣는 포트. 터널의 반대편 끝.
    [int]$RemotePort = 5433,

    # 이 PC 안에서 터널 입구가 될 포트. 0 이면 비어 있는 것을 찾아 쓴다.
    [int]$LocalPort = 0,

    [string]$DbName = 'hive_knowledge',
    [string]$DbUser = 'hive',

    # 대화 화면에 '아픽스 3-1' 처럼 뜰 때의 앞 번호. 0 이면 앱이 호스트명으로 자동 배정한다.
    [int]$NodeSeq = 0,

    # config.json 이 있는 폴더. 비우면 설치본 → 개발본 순서로 찾는다.
    [string]$DataDir = '',

    # 이 노드의 슬롯 CLI 에 '말을 꽂을 수 있는' 발신 노드 번호들. 빈 배열이면 게이트를 끈다.
    # [🔴 왜 기본이 1 인가 — 이 스크립트는 '내 노드를 내가 붙이는' 도구다]
    #   central_inject 의 원격 게이트는 앱 기본값이 꺼짐이다(모르는 노드의 RCE 차단).
    #   그런데 온보딩이 이 값을 안 쓰고 넘어가면, 붙인 노드는 중앙 메시지를 받아 화면에
    #   띄우기만 하고 CLI 에는 안 꽂는다 — 사람 눈에는 '연결됐는데 답이 없다'로만 보인다.
    #   2026-08-11 na2js(3번)가 정확히 이 상태였다: 커서는 140까지 올라갔는데 답이 0건.
    #   관리 PC(1번)만 기본 허용하고, 필요 없으면 -AllowInjectFrom @() 로 끈다.
    [int[]]$AllowInjectFrom = @(1),

    [string]$KeyName = 'hive_tunnel_ed25519'
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Say($m, $lvl = 'INFO') {
    $c = @{ 'INFO' = 'Gray'; 'OK' = 'Green'; 'WARN' = 'Yellow'; 'FAIL' = 'Red' }[$lvl]
    Write-Host ("[{0,-4}] {1}" -f $lvl, $m) -ForegroundColor $c
}

# BOM 없는 UTF-8. config.json 과 authorized_keys 둘 다 BOM 이 붙으면 조용히 깨진다.
$utf8NoBom = New-Object System.Text.UTF8Encoding($false)

# ── 1. ssh 도구 확인 ────────────────────────────────────────────────────────
# [🔴 OpenSSH.Client 는 Server 와 별개 기능이다] 한쪽만 깔린 PC 가 흔하다. 여기서 필요한
#   것은 클라이언트(ssh/ssh-keygen)뿐이며, 없으면 아래 명령 한 줄로 깔린다.
foreach ($tool in @('ssh', 'ssh-keygen')) {
    if (-not (Get-Command $tool -ErrorAction SilentlyContinue)) {
        throw "$tool 이 없다. 관리자 PowerShell 에서: Add-WindowsCapability -Online -Name OpenSSH.Client~~~~0.0.1.0"
    }
}
Say 'ssh 클라이언트 확인' 'OK'

# ── 2. 터널 전용 키 발급 ────────────────────────────────────────────────────
# [WHY 전용 키인가] 관리용 키로 터널을 뚫으면 그 키가 새는 순간 서버 전체를 잃는다.
#   이 키는 서버 쪽 authorized_keys 옵션 때문에 PG 포워딩 외엔 아무것도 못 한다 — 셸도 못 연다.
$sshDir = Join-Path $HOME '.ssh'
New-Item -ItemType Directory -Force -Path $sshDir | Out-Null
$keyPath = Join-Path $sshDir $KeyName
$pubPath = "$keyPath.pub"

if (Test-Path $keyPath) {
    Say "기존 키 재사용: $keyPath" 'OK'
} else {
    # [제약] -N '' 는 PS 에서 빈 문자열이 인자로 사라지는 경우가 있어 `""` 로 넘긴다.
    #   암호구를 걸면 데몬이 무인 재연결을 못 해 절전 복귀 때마다 대화가 끊긴다.
    & ssh-keygen -t ed25519 -N '""' -C "hive-tunnel@$env:COMPUTERNAME" -f $keyPath | Out-Null
    if (-not (Test-Path $keyPath)) { throw '키 생성 실패.' }
    Say "키 생성: $keyPath" 'OK'
}
$pubKey = ([IO.File]::ReadAllText($pubPath)).Trim()

# ── 3. config.json 위치 결정 ────────────────────────────────────────────────
# [🔴 설치본과 개발본은 서로 다른 config.json 을 본다] frozen(EXE)은 %APPDATA%\VibeCoding,
#   개발 모드는 .ai_monitor\data 다(src/pg_base.py 의 DATA_DIR). 엉뚱한 쪽에 쓰면 앱은
#   아무 변화 없이 조용히 '미설정' 상태로 남는다 — 원인이 전혀 드러나지 않는 실패다.
if ($DataDir) {
    $dataPath = $DataDir
} else {
    $installed = Join-Path $env:APPDATA 'VibeCoding'
    $devGuess = Join-Path (Split-Path -Parent (Split-Path -Parent $PSScriptRoot)) '.ai_monitor\data'
    if (Test-Path (Join-Path $installed 'config.json')) { $dataPath = $installed }
    elseif (Test-Path (Join-Path $devGuess 'config.json')) { $dataPath = $devGuess }
    else { $dataPath = $installed }   # 아직 한 번도 안 띄운 PC — 설치본 자리에 만든다
}
New-Item -ItemType Directory -Force -Path $dataPath | Out-Null
$confPath = Join-Path $dataPath 'config.json'
Say "설정 파일: $confPath"

# ── 4. 로컬 포트 결정 ───────────────────────────────────────────────────────
# [WHY 5432 를 쓰지 않나] 그 PC 에 로컬 PostgreSQL 이 있으면 정면 충돌한다. 이 프로젝트는
#   로컬 PG 를 5433 에서 돌리므로 그것도 피한다. 5436 부터 비어 있는 것을 고른다.
function Test-PortFree([int]$p) {
    try {
        $l = [Net.Sockets.TcpListener]::new([Net.IPAddress]::Loopback, $p)
        $l.Start(); $l.Stop(); return $true
    } catch { return $false }
}
if ($LocalPort -le 0) {
    $LocalPort = 5436
    while (-not (Test-PortFree $LocalPort) -and $LocalPort -lt 5460) { $LocalPort++ }
}
Say "터널 로컬 포트: $LocalPort"

# ── 5. config.json 주입 ─────────────────────────────────────────────────────
# [🔴 다른 키를 보존한다] 이 파일에는 슬롯 이름·포트·토글이 함께 산다. 통째로 덮으면
#   그 PC 의 설정이 전부 날아간다. 읽어서 central_db 만 갈아 끼운다.
$conf = if (Test-Path $confPath) {
    $raw = [IO.File]::ReadAllText($confPath)
    if ($raw.Trim()) { $raw | ConvertFrom-Json } else { [pscustomobject]@{} }
} else { [pscustomobject]@{} }

$central = [ordered]@{
    host     = '127.0.0.1'          # 항상 루프백 — 터널 입구다. 서버 주소를 여기 쓰지 말 것.
    port     = $LocalPort
    user     = $DbUser
    password = $Password
    dbname   = $DbName
    tunnel   = [ordered]@{
        ssh_host    = $ServerHost
        ssh_user    = $SshUser
        key         = "~/$('.ssh')/$KeyName"   # ~ 는 앱이 expanduser 로 푼다
        remote_port = $RemotePort
    }
}

# [제약] Add-Member -Force 는 속성이 있든 없든 동작한다. 있을 때만 지우고 다시 넣으면
#   PS 5.1 에서 순서가 뒤바뀌어 diff 가 지저분해진다.
$conf | Add-Member -NotePropertyName 'central_db' -NotePropertyValue $central -Force
if ($NodeSeq -gt 0) {
    $conf | Add-Member -NotePropertyName 'node_seq' -NotePropertyValue $NodeSeq -Force
}

# [🔴 연결(central_db)과 주입 게이트(central_remote_inject)는 별개다]
#   전자는 '중앙 대화를 받는가', 후자는 '받은 말을 이 PC 의 CLI 에 꽂는가'다. 전자만 넣으면
#   노드는 듣기만 하고 말을 못 해 대화가 단방향으로 퇴화한다. 온보딩은 둘을 같이 세운다.
# [불변식] allow_nodes 가 비면 enabled 가 true 여도 꺼진 것과 같다(src/central_inject.remote_gate).
#   그래서 빈 배열일 때는 enabled 를 false 로 적는다 — 설정 파일만 봐도 상태가 읽히게.
$injectOn = ($AllowInjectFrom -ne $null) -and ($AllowInjectFrom.Count -gt 0)
$inject = [ordered]@{
    enabled     = $injectOn
    allow_nodes = @($AllowInjectFrom)
}
$conf | Add-Member -NotePropertyName 'central_remote_inject' -NotePropertyValue $inject -Force

# [🔴 PS 5.1 ConvertTo-Json 기본 -Depth 는 2] tunnel 은 3단계라 기본값으로는 중첩이
#   "System.Collections.Specialized.OrderedDictionary" 문자열로 뭉개진다. 에러는 나지 않고
#   앱만 조용히 '터널 미설정'이 된다 — 반드시 -Depth 를 넉넉히 준다.
$json = $conf | ConvertTo-Json -Depth 12
[IO.File]::WriteAllText($confPath, $json, $utf8NoBom)
Say 'central_db 주입 완료' 'OK'
Say $(if ($injectOn) { "원격 주입 게이트 ON — 허용 노드: $($AllowInjectFrom -join ', ')" }
      else { '원격 주입 게이트 OFF — 이 노드는 중앙 메시지를 화면에만 띄운다' }) 'OK'

# ── 6. 공개키 등록 안내 ─────────────────────────────────────────────────────
Write-Host ''
Write-Host '─── 관리 PC 에서 아래 한 줄을 실행해 이 노드를 등록하라 ───' -ForegroundColor Cyan
Write-Host ''
Write-Host "  `$env:TUNNEL_PUBKEY='$pubKey'" -ForegroundColor White
Write-Host "  ssh $SshUser@$ServerHost `"TUNNEL_PUBKEY='$pubKey' bash -s`" < scripts/remote/vps-knowledge-db.sh" -ForegroundColor White
Write-Host ''
Write-Host '  (등록은 멱등하다 — 이미 등록된 키면 옵션만 다시 적용된다)' -ForegroundColor DarkGray
Write-Host ''

# ── 7. 실증 — 터널을 실제로 열어 본다 ───────────────────────────────────────
# [🔴 ssh 가 살아 있다고 터널이 열린 것이 아니다] 서버 쪽 옵션에서 port-forwarding 조각이
#   빠지면 restrict 가 포워딩까지 꺼서 채널만 거부된다. 이때 ssh 프로세스는 멀쩡히 살아
#   있고 로그도 조용하다(2026-08-09 실측). 그래서 프로세스 생존이 아니라 TCP 연결로 판정한다.
Say '터널 실증 중...'
$sshArgs = @(
    '-i', $keyPath, '-N',
    '-o', 'StrictHostKeyChecking=accept-new',
    '-o', 'ExitOnForwardFailure=yes',      # 포워딩이 거부되면 ssh 자체를 죽인다 — 조용한 실패 방지
    '-o', 'ConnectTimeout=10',
    '-o', 'BatchMode=yes',                 # 비밀번호를 물으면 그대로 매달리므로 즉시 실패시킨다
    '-L', "${LocalPort}:127.0.0.1:${RemotePort}",
    "$SshUser@$ServerHost"
)
$proc = Start-Process -FilePath 'ssh' -ArgumentList $sshArgs -NoNewWindow -PassThru

$ok = $false
foreach ($i in 1..10) {
    Start-Sleep -Milliseconds 700
    if ($proc.HasExited) { break }
    try {
        $cli = [Net.Sockets.TcpClient]::new('127.0.0.1', $LocalPort)
        $cli.Close(); $ok = $true; break
    } catch { }
}

if (-not $proc.HasExited) { $proc.Kill() | Out-Null }

if ($ok) {
    Say '터널 연결 성공 — 서버 PG 까지 길이 뚫렸다' 'OK'
    Write-Host ''
    Say '남은 것은 앱 재시작뿐이다. 대화 화면 오른쪽 창에 다른 노드가 보이면 완료.' 'OK'
    exit 0
}

# 실패 — 원인을 갈라 준다. 여기서 뭉뚱그리면 사용자가 어디를 고쳐야 할지 알 수 없다.
Write-Host ''
Say '터널이 열리지 않았다. 아래 순서로 확인하라.' 'FAIL'
Write-Host '  1) 공개키를 아직 등록하지 않았다면 위 6번 명령을 먼저 실행하라 (가장 흔한 원인).' -ForegroundColor Yellow
Write-Host '  2) 등록했는데도 안 되면 서버에서 옵션 조각을 확인:' -ForegroundColor Yellow
Write-Host "       ssh $SshUser@$ServerHost grep -n 'permitopen' /root/.ssh/authorized_keys" -ForegroundColor DarkGray
Write-Host "     port-forwarding 이 빠져 있으면 채널만 거부된다(restrict 가 포워딩까지 끔)." -ForegroundColor DarkGray
Write-Host '  3) 손으로 직접 붙여 메시지를 본다:' -ForegroundColor Yellow
Write-Host "       ssh -i $keyPath -v -N -L ${LocalPort}:127.0.0.1:${RemotePort} $SshUser@$ServerHost" -ForegroundColor DarkGray
Write-Host ''
Say 'config.json 은 이미 기록됐다 — 등록 후 이 스크립트를 다시 돌리면 실증만 재시도한다.' 'INFO'
exit 2
