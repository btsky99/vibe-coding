<#
FILE: scripts/remote/Install-RustDeskClient.ps1
DESCRIPTION: 이 PC를 "원격으로 조종당할 수 있는 기기"로 만든다 (계층 1 = tailnet 직결).
             RustDesk 클라이언트 설치 → 무인 접속 서비스 → 고정 비밀번호 → 직접 IP 접속 →
             방화벽을 tailnet 대역으로 축소. 조종하는 쪽 기기에서도 그냥 돌리면 된다(양방향 동일).

             사용:
               관리자 PowerShell> .\Install-RustDeskClient.ps1
               관리자 PowerShell> .\Install-RustDeskClient.ps1 -IdServer 100.75.28.53 -Key '<hbbs 공개키>'

REVISION HISTORY:
- 2026-08-07 Claude: 최초 작성 — Tailscale 위 직결 전제. hbbs 없이도 완결되게 설계.
#>

[CmdletBinding()]
param(
    # 셀프호스트 hbbs를 쓸 때만 지정. 비워두면 ID 서버 설정을 건드리지 않고
    # 직접 IP 접속(tailnet)만으로 완결된다.
    [string]$IdServer = '',
    [string]$Key = '',

    # 비우면 16자 무작위 생성. 이미 쓰던 비밀번호를 유지하려면 명시.
    [string]$Password = '',

    # [WHY 0 = 자동] 기본은 21118(RustDesk 표준)이지만, 이 PC가 hbbs를 겸하면 21118이 겹쳐
    # 둘 중 하나가 죽는다. 0이면 hbbs 유무를 보고 21118/21128 중에 알아서 고른다.
    # 명시적으로 숫자를 주면 그 값을 그대로 쓴다.
    [int]$DirectPort = 0,

    # 이미 설치된 PC에서 설정만 다시 밀 때.
    [switch]$SkipInstall
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'rustdesk-common.ps1')

Write-Host ''
Write-Host '=== RustDesk 클라이언트 구축 (계층 1: tailnet 직결) ===' -ForegroundColor Cyan
Write-Host ''

Assert-Admin

# ── 0. 직접접속 포트 결정 ───────────────────────────────────────────────────
if ($DirectPort -eq 0) {
    if (Test-HbbsPresent) {
        $DirectPort = $script:DirectPortWhenHbbs
        Write-Step "이 PC는 hbbs(ID 서버)를 겸한다 → 직접접속 포트를 $DirectPort 로 비켜준다 (21118은 hbbs 웹소켓이 쓴다)." 'WARN'
    } else {
        $DirectPort = $script:DirectPortDefault
    }
}

# ── 1. Tailscale 확인 ────────────────────────────────────────────────────────
# [WHY 치명 아님] Tailscale이 없어도 설치 자체는 유효하다(LAN 직결/공용 서버 경유는 가능).
# 다만 이 구축의 전제인 "어디서든 안전하게"가 깨지므로 명시적으로 경고한다.
$tsIp = Get-TailscaleIPv4
if ($null -eq $tsIp) {
    Write-Step 'Tailscale 미설치 또는 미로그인 — tailnet 직결을 쓸 수 없다.' 'WARN'
    Write-Step '먼저 https://tailscale.com/download 설치 후 같은 계정으로 로그인할 것.' 'WARN'
} else {
    Write-Step "Tailscale IP: $tsIp" 'OK'
}

# ── 2. 클라이언트 설치 ──────────────────────────────────────────────────────
$exe = Get-RustDeskExe
if ($SkipInstall -and $null -eq $exe) { throw '-SkipInstall을 줬지만 RustDesk가 설치돼 있지 않다.' }

if (-not $SkipInstall -and $null -eq $exe) {
    $asset = Get-LatestReleaseAsset -Repo 'rustdesk/rustdesk' -NamePattern 'rustdesk-*-x86_64.exe'
    Write-Step "RustDesk $($asset.Tag) 내려받는 중..."
    $installer = Join-Path $env:TEMP $asset.Name
    Invoke-Download -Uri $asset.Url -OutFile $installer

    Write-Step '무인 설치 실행 중 (--silent-install)...'
    # [과거사고 2026-08-07] -Wait를 걸면 영원히 안 끝난다. --silent-install은 설치를 마친 뒤
    # 그 프로세스가 그대로 트레이/서비스 기동으로 이어져 종료되지 않기 때문. 실제 설치는 20초 안에 끝났는데
    # 스크립트만 9분 매달렸다. → 기다리지 말고 "설치 결과물(exe) 등장"을 폴링해 완료를 판정한다.
    $proc = Start-Process -FilePath $installer -ArgumentList '--silent-install' -PassThru

    for ($i = 0; $i -lt 60; $i++) {
        $exe = Get-RustDeskExe
        if ($null -ne $exe) { break }
        Start-Sleep -Seconds 2
    }
    if ($null -eq $exe) { throw '설치가 끝나지 않았다. 내려받은 설치 파일을 수동 실행해 확인하라: ' + $installer }

    # 설치가 확인되면 남아 있는 설치 프로세스는 회수한다(임시 exe 파일 잠금 해제 목적).
    Start-Sleep -Seconds 3
    if (-not $proc.HasExited) { Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue }
    Write-Step "설치 완료: $exe" 'OK'
} else {
    Write-Step "기존 설치 사용: $exe" 'OK'
}

# ── 3. 서비스 기동 확인 ─────────────────────────────────────────────────────
# [WHY 서비스가 필수인가] 서비스가 없으면 "로그인 화면 / 사용자 로그오프 상태"에서 접속이 끊긴다.
# 부모님 PC 지원이나 외출 중 접속에서 이게 곧바로 문제가 된다.
$svc = Get-Service -Name 'RustDesk' -ErrorAction SilentlyContinue
if ($null -eq $svc) {
    Write-Step 'RustDesk 서비스가 없다 — 등록 시도 중...'
    Start-Process -FilePath $exe -ArgumentList '--install-service' -Wait -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 3
    $svc = Get-Service -Name 'RustDesk' -ErrorAction SilentlyContinue
}
if ($null -ne $svc) {
    if ($svc.StartType -ne 'Automatic') { Set-Service -Name 'RustDesk' -StartupType Automatic }
    if ($svc.Status -ne 'Running') { Start-Service -Name 'RustDesk'; Start-Sleep -Seconds 3 }
    Write-Step "RustDesk 서비스: $((Get-Service RustDesk).Status) / 시작유형 자동" 'OK'
} else {
    Write-Step 'RustDesk 서비스를 등록하지 못했다. GUI에서 "서비스 설치"를 눌러야 할 수 있다.' 'WARN'
}

# ── 4. 접속 옵션 주입 ───────────────────────────────────────────────────────
$opts = @{
    # 매번 바뀌는 임시 비밀번호가 아니라 고정 비밀번호로만 인증 — 무인 접속의 전제.
    'verification-method'  = 'use-permanent-password'
    # 대상 PC 앞에 사람이 없어도 승인 없이 붙는다. 화면 앞 수동 수락을 요구하면 무인이 아니다.
    'approve-mode'         = 'password'
    # 직접 IP 접속 — 이 한 줄이 "ID 서버 없이 100.x.x.x로 바로 붙기"를 가능하게 한다.
    'direct-server'        = 'Y'
    'direct-access-port'   = "$DirectPort"
    'stop-service'         = 'N'
}

if (-not [string]::IsNullOrWhiteSpace($IdServer)) {
    # [불변식] custom-rendezvous-server 와 key 는 반드시 짝으로 들어간다.
    # key 없이 서버만 지정하면 클라이언트가 서버를 신뢰하지 못해 조용히 접속에 실패한다.
    if ([string]::IsNullOrWhiteSpace($Key)) {
        throw '-IdServer를 지정했으면 -Key(hbbs 공개키)도 함께 줘야 한다. 키 없이는 접속이 조용히 실패한다.'
    }
    # [🔴 과거사고 2026-08-07] ID 서버가 '이 PC 자신'이면 자기 tailnet 주소로는 못 붙는다.
    # 실측: 100.75.28.53:21116 으로 SYN을 보내면 RST도 드롭 로그도 없이 그냥 타임아웃.
    # 방화벽을 전면 허용해도, 평범한 TcpListener를 띄워 시험해도 동일 — 즉 방화벽 규칙 문제가 아니라
    # "자기 자신의 비-루프백 주소로 들어오는 연결"이 이 호스트 환경에서 막혀 있다.
    # (RustDesk 본체만 예외적으로 통과한다 — 자체 프로그램 규칙 보유.)
    # → 서버를 겸하는 PC는 ID 서버로 127.0.0.1을 쓴다. 중계 주소는 원격 피어가 써야 하므로 tailnet IP 유지.
    $rendezvous = $IdServer
    if ($null -ne $tsIp -and $IdServer -eq $tsIp -and (Test-HbbsPresent)) {
        $rendezvous = '127.0.0.1'
        Write-Step 'ID 서버가 이 PC 자신 → 등록 경로만 127.0.0.1로 바꾼다 (자기 tailnet 주소로는 못 붙는다).' 'WARN'
    }
    $opts['custom-rendezvous-server'] = $rendezvous
    $opts['relay-server']             = $IdServer
    $opts['key']                      = $Key
    Write-Step "셀프호스트 ID 서버 사용: $rendezvous (중계 $IdServer)" 'OK'
} else {
    Write-Step 'ID 서버 미지정 — tailnet 직접 IP 접속 전용으로 구성한다.' 'INFO'
}

Set-RustDeskOptionsEverywhere -Options $opts | Out-Null

# ── 5. 고정 비밀번호 ────────────────────────────────────────────────────────
if ([string]::IsNullOrWhiteSpace($Password)) { $Password = New-StrongPassword -Length 16 }

# [WHY CLI인가] 비밀번호는 salt와 함께 해시로 저장돼 TOML에 평문으로 못 쓴다.
# rustdesk.exe --password 가 유일한 공식 경로다.
Start-Process -FilePath $exe -ArgumentList "--password `"$Password`"" -Wait -NoNewWindow -ErrorAction SilentlyContinue
Start-Sleep -Seconds 2
$secretPath = Save-Secret -Name 'rustdesk-password.txt' -Value $Password
Write-Step "고정 비밀번호 설정 완료 → $secretPath" 'OK'

# ── 6. 방화벽 ───────────────────────────────────────────────────────────────
# [🔴 2026-08-07] 노출 정책은 **ID 서버가 어디냐**로 갈린다. 한쪽 규칙을 양쪽에 쓰면 조용히 깨진다.
#   - tailnet ID 서버(또는 ID 서버 없음): 접속이 tailnet 안에서만 오므로 100.64.0.0/10로 좁힌다.
#   - 공인 VPS ID 서버: 상대가 **임의의 공인 IP**에서 홀펀칭으로 들어온다. tailnet으로 좁히면
#     P2P 직결이 막혀 매번 중계로 떨어지거나 아예 실패한다. 좁히면 안 된다.
#   실제로 VPS 전환 직후 이 축소가 그대로 걸려 직결 경로를 막았다 — 그래서 자동 판별로 바꿨다.
$isTailnetServer = ($IdServer -eq '') -or ($IdServer -match '^100\.(6[4-9]|[7-9]\d|1[0-1]\d|12[0-7])\.')

if ($isTailnetServer) {
    Restrict-FirewallToTailnet -DisplayNamePattern '*RustDesk*' | Out-Null
    New-TailnetOnlyRule -DisplayName 'vibe-remote RustDesk 직접접속' -TcpPorts @($DirectPort) | Out-Null
} else {
    # 공인 서버 모드 — 설치 프로그램이 만든 RustDesk 규칙을 원래대로(모든 주소) 되돌린다.
    # [주의] 이건 노출을 넓히는 동작이다. 이 구조에서는 불가피하다(상대 IP를 미리 알 수 없음).
    #   대신 인증은 고정 비밀번호 16자 + hbbs 공개키 대조 2중으로 막는다.
    $rules = @(Get-NetFirewallRule -DisplayName '*RustDesk*' -ErrorAction SilentlyContinue |
               Where-Object { $_.Direction -eq 'Inbound' -and $_.Action -eq 'Allow' })
    foreach ($r in $rules) { Set-NetFirewallRule -InputObject $r -RemoteAddress Any -Enabled True }
    Write-Step "공인 ID 서버 모드 — RustDesk 방화벽 $($rules.Count)건을 모든 주소 허용으로 복원(홀펀칭 필요)" 'WARN'

    # tailnet 전용으로 만들어 둔 직접접속 규칙은 이 모드에서 의미가 없다. 남기면 오해를 부른다.
    # [WHY 대신 열지 않나] 직접 IP 접속은 같은 LAN에서나 쓸모 있고, 공인망에 21118을 여는 것은
    #   ID 서버를 두는 이유(홀펀칭)를 무색하게 하면서 공격면만 넓힌다.
    Get-NetFirewallRule -DisplayName 'vibe-remote RustDesk 직접접속' -ErrorAction SilentlyContinue |
        Remove-NetFirewallRule -ErrorAction SilentlyContinue
}

# ── 7. 서비스 재기동 후 ID 확보 ─────────────────────────────────────────────
if ($null -ne (Get-Service -Name 'RustDesk' -ErrorAction SilentlyContinue)) {
    Restart-Service -Name 'RustDesk' -Force -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 4
}

$rid = $null
for ($i = 0; $i -lt 10; $i++) {
    $rid = Get-RustDeskId
    if (-not [string]::IsNullOrWhiteSpace($rid)) { break }
    Start-Sleep -Seconds 2
}

# ── 결과 ────────────────────────────────────────────────────────────────────
# [WHY 모드별로 다르게 찍나] 안내문이 실제 구성과 어긋나면 사용자가 엉뚱한 주소로 접속을 시도한다.
#   실제로 VPS로 전환한 뒤에도 "Tailscale 주소를 입력하라"고 찍혀 혼란을 유발했다.
#   관측 도구가 거짓이면 판단도 거짓이 된다 — 출력은 항상 실제 구성을 따라간다.
Write-Host ''
Write-Host '=== 구축 완료 ===' -ForegroundColor Cyan
Write-Host ("  이 PC          : {0}" -f $env:COMPUTERNAME)
if (-not [string]::IsNullOrWhiteSpace($rid)) { Write-Host ("  RustDesk ID    : {0}   <- 접속할 때 ID 칸에 이걸 입력" -f $rid) -ForegroundColor Green }
Write-Host ("  비밀번호       : {0}" -f $Password) -ForegroundColor Yellow
Write-Host ("  비밀번호 파일  : {0}" -f $secretPath)
Write-Host ''
if ($isTailnetServer) {
    if ($null -ne $tsIp) { Write-Host ("  Tailscale 주소 : {0}:{1}   (직접 IP 접속용)" -f $tsIp, $DirectPort) -ForegroundColor Green }
    Write-Host '  붙는 쪽 기기도 같은 Tailscale 계정에 로그인돼 있어야 한다.' -ForegroundColor Gray
} else {
    Write-Host ("  ID 서버        : {0}" -f $IdServer) -ForegroundColor Green
    Write-Host '  붙는 쪽 기기의 RustDesk 설정 > 네트워크에 같은 ID 서버/Key를 넣으면 된다.' -ForegroundColor Gray
    Write-Host '  그 기기는 계정도 VPN도 필요 없다 — 인터넷만 되면 붙는다.' -ForegroundColor Gray
}
Write-Host ''
