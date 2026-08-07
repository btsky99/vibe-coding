<#
FILE: scripts/remote/Install-RustDeskForFamily.ps1
DESCRIPTION: 원격지 PC(부모님/지인)를 "고정 ID로 언제든 붙을 수 있는" 상태로 한 번에 만든다.
             RustDesk 무인 접속 + 고정 비밀번호 + 절전 해제 + (선택) Tailscale 자동 합류.
             Install-RustDeskClient.ps1이 '내 기기'용이라면 이 스크립트는 '남의 기기'용이다 —
             다시 방문하지 않아도 되도록 재접속에 필요한 모든 조건을 한 번에 건다.

             사용 (그 PC에서 관리자 PowerShell):
               # 부모님 — 내 tailnet에 합류시켜 인터넷 노출 0으로
               .\Install-RustDeskForFamily.ps1 -TailscaleAuthKey 'tskey-auth-xxxxx'

               # 지인 — Tailscale 없이 RustDesk 공용 서버로 (고정 ID는 동일하게 유지됨)
               .\Install-RustDeskForFamily.ps1 -Mode public

REVISION HISTORY:
- 2026-08-07 Claude: 최초 작성 — 일회용 지원을 고정 ID 재접속으로 전환.
                     절전 해제를 포함한 이유는 아래 Disable-SleepForRemote 주석 참조.
#>

[CmdletBinding()]
param(
    # tailscale: 내 tailnet에 합류(권장, 노출 0) / public: RustDesk 공용 서버 경유
    [ValidateSet('tailscale', 'public')]
    [string]$Mode = 'tailscale',

    # Tailscale 관리 콘솔(https://login.tailscale.com/admin/settings/keys)에서 발급.
    # [WHY 필요한가] 이게 없으면 그 PC에서 브라우저 로그인을 시켜야 한다 —
    #   부모님께 전화로 안내하기 가장 어려운 단계다. 사전 발급 키 하나면 무인으로 끝난다.
    [string]$TailscaleAuthKey = '',

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

$TailscaleMsi = 'https://pkgs.tailscale.com/stable/tailscale-setup-latest-amd64.msi'

Write-Host ''
Write-Host '=== 원격지 PC 세팅 (고정 ID 무인 접속) ===' -ForegroundColor Cyan
Write-Host ''

Assert-Admin


function Disable-SleepForRemote {
    <#
      시스템 절전/최대 절전을 끈다. 화면 꺼짐은 그대로 둔다.

      [WHY 이게 핵심인가] 원격제어가 안 되는 사고의 대부분은 소프트웨어 문제가 아니라
        "그 PC가 자고 있어서"다. Windows 기본값은 유휴 30분 뒤 절전이고, 절전에 들어가면
        tailnet에서도 사라진다. **인터넷 너머에서는 깨울 방법이 없다** —
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


function Install-TailscaleAndJoin {
    <#
      Tailscale 설치 후 사전 발급 키로 무인 합류시킨다.
      [불변식] --unattended 필수 — 없으면 사용자가 로그아웃한 뒤 tailnet 연결이 끊긴다.
        원격지 PC는 아무도 로그인해 있지 않은 시간이 대부분이라 이 플래그가 곧 가용성이다.
    #>
    param([string]$AuthKey)

    $exe = 'C:\Program Files\Tailscale\tailscale.exe'
    if (-not (Test-Path $exe)) {
        Write-Step 'Tailscale 설치 중...'
        $msi = Join-Path $env:TEMP 'tailscale-setup.msi'
        Invoke-Download -Uri $TailscaleMsi -OutFile $msi
        Start-Process msiexec.exe -ArgumentList "/i `"$msi`" /quiet /norestart" -Wait
        for ($i = 0; $i -lt 30; $i++) {
            if (Test-Path $exe) { break }
            Start-Sleep -Seconds 2
        }
    }
    if (-not (Test-Path $exe)) { throw 'Tailscale 설치 실패 — https://tailscale.com/download 에서 수동 설치 후 다시 실행하라.' }
    Write-Step "Tailscale 설치 확인: $exe" 'OK'

    $already = Get-TailscaleIPv4
    if ($null -ne $already) {
        Write-Step "이미 tailnet에 합류돼 있다: $already" 'OK'
        return $already
    }

    if ([string]::IsNullOrWhiteSpace($AuthKey)) {
        throw @'
Tailscale 로그인이 안 돼 있고 -TailscaleAuthKey 도 없다.
  해결: https://login.tailscale.com/admin/settings/keys 에서 auth key를 발급해
        -TailscaleAuthKey 'tskey-auth-...' 로 다시 실행하라.
        (Reusable 체크, 만료 기간은 짧게 잡아도 된다 — 합류는 1회면 끝난다)
'@
    }

    Write-Step 'tailnet 합류 중...'
    & $exe up --authkey=$AuthKey --unattended 2>&1 | Out-Null
    Start-Sleep -Seconds 5
    $ip = Get-TailscaleIPv4
    if ($null -eq $ip) { throw 'tailnet 합류 실패 — auth key 만료/오타 또는 네트워크 확인.' }
    Write-Step "tailnet 합류 완료: $ip" 'OK'
    return $ip
}


# ── 1. Tailscale (모드에 따라) ──────────────────────────────────────────────
$tsIp = $null
if ($Mode -eq 'tailscale') {
    $tsIp = Install-TailscaleAndJoin -AuthKey $TailscaleAuthKey
} else {
    Write-Step 'public 모드 — Tailscale 없이 RustDesk 공용 서버를 쓴다.' 'INFO'
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
if ($Mode -eq 'tailscale') {
    # tailnet 직결 — 공용 서버를 거치지 않는다.
    $opts['direct-server']      = 'Y'
    $opts['direct-access-port'] = "$($script:DirectPortDefault)"
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
if ($Mode -eq 'tailscale') {
    # tailnet에서만 들어오게 축소 — 공인망 노출 0.
    Restrict-FirewallToTailnet -DisplayNamePattern '*RustDesk*' | Out-Null
    New-TailnetOnlyRule -DisplayName 'vibe-remote RustDesk 직접접속' -TcpPorts @($script:DirectPortDefault) | Out-Null
} else {
    # [주의] public 모드에서는 방화벽을 좁히면 안 된다. 공용 서버로 홀펀칭할 때 상대가
    #   임의의 공인 IP에서 들어오므로, tailnet 대역으로 제한하면 연결 자체가 성립하지 않는다.
    Write-Step 'public 모드 — 방화벽은 RustDesk 기본값 유지(홀펀칭 상대 IP를 미리 알 수 없음).' 'INFO'
}

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
if ($Mode -eq 'tailscale') {
    $card += ("  접속 주소   : {0}:{1}" -f $tsIp, $script:DirectPortDefault)
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
if ($Mode -eq 'tailscale') {
    Write-Host '  ※ 관리 콘솔에서 이 기기에 ACL을 걸어 역방향 접근을 막을 것 (docs/REMOTE_CONTROL.md).' -ForegroundColor Yellow
}
Write-Host ''
