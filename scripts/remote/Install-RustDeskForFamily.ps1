<#
FILE: scripts/remote/Install-RustDeskForFamily.ps1
DESCRIPTION: 원격지 PC(부모님/지인)를 "고정 ID로 언제든 붙을 수 있는" 상태로 한 번에 만든다.
             RustDesk 무인 접속 + 고정 비밀번호 + 절전 해제 + 아픽스 서버 hbbs 지정.
             Install-RustDeskClient.ps1이 '내 기기'용이라면 이 스크립트는 '남의 기기'용이다 —
             다시 방문하지 않아도 되도록 재접속에 필요한 모든 조건을 한 번에 건다.

             사용 (그 PC에서 관리자 PowerShell):
               # 기본 — 내 아픽스 서버 경유 (제3자 서버를 거치지 않는다)
               .\Install-RustDeskForFamily.ps1 -IdServer 158.247.205.192 -Key '<hbbs 공개키>'

               # 서버를 안 쓸 때 — RustDesk 공용 서버 경유 (고정 ID는 동일하게 유지됨)
               .\Install-RustDeskForFamily.ps1 -Mode public

REVISION HISTORY:
- 2026-08-07 Claude: 최초 작성 — 일회용 지원을 고정 ID 재접속으로 전환.
                     절전 해제를 포함한 이유는 아래 Disable-SleepForRemote 주석 참조.
- 2026-08-09 Claude: 외부 메시 VPN 전면 폐기 — 사설망 합류 모드 삭제, 아픽스 서버 hbbs 모드로 대체.
#>

[CmdletBinding()]
param(
    # apix: 내 아픽스 서버 hbbs 경유(권장, 제3자 없음) / public: RustDesk 공용 서버 경유
    [ValidateSet('apix', 'public')]
    [string]$Mode = 'apix',

    # 아픽스 서버(hbbs) 주소와 공개키. apix 모드에서 **둘 다 필수**다.
    # [🔴 키가 없으면 조용히 실패한다] 클라이언트가 서버를 신뢰하지 못해 접속이 안 되는데
    #   화면에는 아무 에러도 안 뜬다 — 그래서 아래에서 명시적으로 막는다.
    [string]$IdServer = '',
    [string]$Key = '',

    # 비우면 16자 자동 생성. 이 값을 형이 보관하면 언제든 재접속 가능.
    [string]$Password = '',

    # 접속 중임을 상대 화면에 표시. 기본 켬.
    [bool]$ShowConnectionNotice = $true,

    # 노트북에서 배터리 사용 중일 때의 절전까지 끌지 여부. 기본은 끄지 않는다(배터리 방전 방지).
    [switch]$DisableSleepOnBattery
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'rustdesk-common.ps1')


Write-Host ''
Write-Host '=== 원격지 PC 세팅 (고정 ID 무인 접속) ===' -ForegroundColor Cyan
Write-Host ''

Assert-Admin


function Disable-SleepForRemote {
    <#
      시스템 절전/최대 절전을 끈다. 화면 꺼짐은 그대로 둔다.

      [WHY 이게 핵심인가] 원격제어가 안 되는 사고의 대부분은 소프트웨어 문제가 아니라
        "그 PC가 자고 있어서"다. Windows 기본값은 유휴 30분 뒤 절전이고, 절전에 들어가면
        네트워크에서도 사라진다. **인터넷 너머에서는 깨울 방법이 없다** —
        Wake-on-LAN은 같은 브로드캐스트 도메인(=같은 랜)에서만 동작하기 때문.
        원격지 PC는 애초에 안 자게 만드는 것 말고 답이 없다.
      [WHY 화면은 끄나] 모니터 절전은 원격 접속을 막지 않는다. 전기와 번인만 아끼면 되므로 유지.
      [제약] 배터리 구동 노트북까지 끄면 방전된다 → -DisableSleepOnBattery 로 명시 요청할 때만.
    #>
    param([bool]$IncludeBattery)

    # 0 = 안 함(never). AC = 전원 연결 시.
    & powercfg /change standby-timeout-ac 0 2>&1 | Out-Null
    & powercfg /change hibernate-timeout-ac 0 2>&1 | Out-Null
    & powercfg /change monitor-timeout-ac 15 2>&1 | Out-Null
    Write-Step '전원 연결 시 절전/최대절전 해제 (화면은 15분 뒤 꺼짐 — 접속에 영향 없음)' 'OK'

    if ($IncludeBattery) {
        & powercfg /change standby-timeout-dc 0 2>&1 | Out-Null
        & powercfg /change hibernate-timeout-dc 0 2>&1 | Out-Null
        Write-Step '배터리 구동 시에도 절전 해제 — 노트북이면 방전에 주의' 'WARN'
    }

    # [보강] 절전 자체를 껐어도 뚜껑을 닫으면 잠드는 노트북이 있다. 전원 연결 시에는 무시하게 한다.
    #   (2 = 아무 것도 안 함 / lidaction GUID)
    try {
        $scheme = ((& powercfg /getactivescheme) -split '\s+')[3]
        & powercfg /setacvalueindex $scheme 4f971e89-eebd-4455-a8de-9e59040e7347 5ca83367-6e45-459f-a27b-476b1d01c936 0 2>&1 | Out-Null
        & powercfg /setactive $scheme 2>&1 | Out-Null
        Write-Step '전원 연결 시 노트북 뚜껑 닫아도 안 자게 설정' 'OK'
    } catch {
        Write-Step '뚜껑 동작 설정 실패(데스크톱이면 정상)' 'INFO'
    }
}



# ── 1. 접속 경로 확인 (모드에 따라) ─────────────────────────────────────────
$tsIp = $null
if ($Mode -eq 'apix') {
    if ([string]::IsNullOrWhiteSpace($IdServer) -or [string]::IsNullOrWhiteSpace($Key)) {
        throw 'apix 모드에는 -IdServer 와 -Key 가 모두 필요하다. 키 없이는 접속이 조용히 실패한다.'
    }
    Write-Step "아픽스 서버 경유: $IdServer" 'OK'
} else {
    Write-Step 'public 모드 — RustDesk 공용 서버(제3자)를 거친다.' 'WARN'
}

# ── 2. RustDesk 설치 ────────────────────────────────────────────────────────
$exe = Get-RustDeskExe
if ($null -eq $exe) {
    $asset = Get-LatestReleaseAsset -Repo 'rustdesk/rustdesk' -NamePattern 'rustdesk-*-x86_64.exe'
    Write-Step "RustDesk $($asset.Tag) 내려받는 중..."
    $installer = Join-Path $env:TEMP $asset.Name
    Invoke-Download -Uri $asset.Url -OutFile $installer

    Write-Step '무인 설치 실행 중...'
    # [과거사고 2026-08-07] -Wait를 걸면 영원히 안 끝난다(설치 프로세스가 트레이/서비스로 이어짐).
    #   결과물 등장을 폴링해 완료를 판정한다. Install-RustDeskClient.ps1과 동일 규약.
    $proc = Start-Process -FilePath $installer -ArgumentList '--silent-install' -PassThru
    for ($i = 0; $i -lt 60; $i++) {
        $exe = Get-RustDeskExe
        if ($null -ne $exe) { break }
        Start-Sleep -Seconds 2
    }
    if ($null -eq $exe) { throw "설치가 끝나지 않았다. 수동 실행: $installer" }
    Start-Sleep -Seconds 3
    if (-not $proc.HasExited) { Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue }
}
Write-Step "RustDesk: $exe" 'OK'

# ── 3. 서비스 등록 — 로그인 화면/로그아웃 상태에서도 붙게 ──────────────────
# [WHY 필수] 원격지 PC는 아무도 로그인해 있지 않은 시간이 대부분이다. 서비스가 없으면
#   "부모님이 로그아웃하면 못 붙는" 상태가 되고, 그러면 다시 방문해야 한다 — 목적이 무너진다.
$svc = Get-Service -Name 'RustDesk' -ErrorAction SilentlyContinue
if ($null -eq $svc) {
    Start-Process -FilePath $exe -ArgumentList '--install-service' -Wait -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 3
    $svc = Get-Service -Name 'RustDesk' -ErrorAction SilentlyContinue
}
if ($null -ne $svc) {
    if ($svc.StartType -ne 'Automatic') { Set-Service -Name 'RustDesk' -StartupType Automatic }
    if ($svc.Status -ne 'Running') { Start-Service -Name 'RustDesk'; Start-Sleep -Seconds 3 }
    Write-Step "RustDesk 서비스 자동 시작 ($((Get-Service RustDesk).Status))" 'OK'
} else {
    Write-Step 'RustDesk 서비스 등록 실패 — GUI에서 "서비스 설치"를 눌러야 할 수 있다.' 'WARN'
}

# ── 4. 접속 옵션 ────────────────────────────────────────────────────────────
$opts = @{
    'verification-method' = 'use-permanent-password'  # 매번 바뀌는 임시 비번 대신 고정 비번
    'approve-mode'        = 'password'                # 상대가 수락 안 눌러도 붙는다(= 무인)
    'stop-service'        = 'N'
}
if ($ShowConnectionNotice) {
    # 접속 중임을 상대 화면에 띄운다. 상대 기기이므로 기본값으로 켠다.
    $opts['show-remote-cursor'] = 'Y'
    $opts['enable-tray']        = 'Y'
}
if ($Mode -eq 'apix') {
    # 내 서버가 ID/중계를 맡는다 — 공용 서버를 거치지 않는다.
    $opts['custom-rendezvous-server'] = $IdServer
    $opts['relay-server']             = $IdServer
    $opts['key']                      = $Key
}
Set-RustDeskOptionsEverywhere -Options $opts | Out-Null

# ── 5. 고정 비밀번호 ────────────────────────────────────────────────────────
if ([string]::IsNullOrWhiteSpace($Password)) { $Password = New-StrongPassword -Length 16 }
Start-Process -FilePath $exe -ArgumentList "--password `"$Password`"" -Wait -NoNewWindow -ErrorAction SilentlyContinue
Start-Sleep -Seconds 2
Write-Step '고정 비밀번호 설정 완료' 'OK'

# ── 6. 절전 해제 ────────────────────────────────────────────────────────────
Disable-SleepForRemote -IncludeBattery ([bool]$DisableSleepOnBattery)

# ── 7. 방화벽 ───────────────────────────────────────────────────────────────
# [주의] 두 모드 모두 방화벽을 좁히면 안 된다. ID 서버가 어디든 홀펀칭 상대는 임의의
#   공인 IP에서 들어오므로, 대역을 제한하면 연결 자체가 성립하지 않는다.
#   방어선은 방화벽이 아니라 고정 비밀번호 16자 + (apix 모드) hbbs 공개키 대조다.
Write-Step '방화벽은 RustDesk 기본값 유지 — 홀펀칭 상대 IP를 미리 알 수 없다.' 'INFO'
# 과거 사설망 전용으로 만들어 둔 직접접속 규칙이 남아 있으면 지운다(이제 의미 없는 대역).
Remove-InboundExposure -DisplayNamePattern 'vibe-remote RustDesk 직접접속' | Out-Null

# ── 8. 재기동 후 ID 확보 ────────────────────────────────────────────────────
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

# ── 결과 — 이 화면을 사진 찍어 보내달라고 하면 된다 ─────────────────────────
$card = @()
$card += '━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━'
$card += '  이 PC에 원격으로 접속할 때 쓸 정보'
$card += '━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━'
$card += ("  컴퓨터 이름 : {0}" -f $env:COMPUTERNAME)
if ($Mode -eq 'apix') {
    $card += ("  ID 서버     : {0}" -f $IdServer)
}
if (-not [string]::IsNullOrWhiteSpace($rid)) {
    $card += ("  RustDesk ID : {0}" -f $rid)
}
$card += ("  비밀번호     : {0}" -f $Password)
$card += '━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━'

Write-Host ''
foreach ($line in $card) { Write-Host $line -ForegroundColor Green }
Write-Host ''

# 그 PC 바탕화면에도 남긴다 — 나중에 전화로 물어볼 때 찾기 쉽게.
# [주의] 비밀번호가 평문으로 남는다. 상대 PC이므로 본인이 볼 수 있는 건 문제가 아니지만,
#   공용 PC라면 -Password로 직접 지정하고 이 파일을 지우는 편이 낫다.
try {
    $desktop = [Environment]::GetFolderPath('Desktop')
    $out = Join-Path $desktop '원격접속-정보.txt'
    [System.IO.File]::WriteAllText($out, ($card -join "`r`n"), (New-Object System.Text.UTF8Encoding($true)))
    Write-Step "바탕화면에도 저장: $out" 'OK'
} catch {
    Write-Step '바탕화면 저장 실패(무시 가능)' 'WARN'
}

Write-Host '  이 화면을 사진으로 찍어 보내주시면 됩니다.' -ForegroundColor Gray
if ($Mode -eq 'apix') {
    Write-Host '  ※ 붙는 쪽 기기에도 같은 ID 서버/Key 를 넣어야 한다 (docs/REMOTE_CONTROL.md).' -ForegroundColor Yellow
}
Write-Host ''
