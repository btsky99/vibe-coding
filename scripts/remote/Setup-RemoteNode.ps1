<#
FILE: scripts/remote/Setup-RemoteNode.ps1
DESCRIPTION: 원격지 PC(CipherTrader 학습 노드 등)를 "밖에서 화면도 보고 셸로도 들어갈 수 있는"
             노드로 만든다. 서울 VPS를 경유하므로 그 PC의 공유기를 건드리지 않고, VPN 계정도 필요 없다.

             두 경로를 함께 세운다 — 둘은 용도가 다르다:
               · RustDesk  → 사람이 화면을 보고 마우스로 조작
               · SSH 역터널 → 에이전트가 로그를 읽고 명령을 돌리고 진단

             이 스크립트는 **1단계**다. 실행하면 공개키를 출력하는데, 그 값을 관리자에게
             전달해야 VPS가 이 PC를 받아들인다(2단계). 개인키는 이 PC 밖으로 나가지 않는다.

             사용: 관리자 PowerShell에서
               .\Setup-RemoteNode.ps1 -NodeName cipher -TunnelPort 22001

REVISION HISTORY:
- 2026-08-07 Claude: 최초 작성 — Tailscale 폐기 후 VPS 경유 구조로 전환하며 신설.
#>

[CmdletBinding()]
param(
    # 이 노드를 부를 이름. 키·작업 이름에 쓰인다.
    [Parameter(Mandatory)][string]$NodeName,

    # VPS에서 이 PC로 들어오는 입구가 될 포트. 노드마다 달라야 한다.
    #   22001=cipher / 22002=macmini / 22003~ 예비
    [Parameter(Mandatory)][int]$TunnelPort,

    # [🔴 하드코딩 금지 — 2026-08-07 사고] 이 저장소는 **공개(PUBLIC)** 다.
    #   초판에서 VpsHost/RustDeskKey를 기본값으로 박아 푸시했다가 회수했다.
    #   hbbs 공개키 자체로 화면을 볼 수는 없지만, `-k _` 게이트가 "이 키를 아는 클라이언트만
    #   받는다"는 구조라 키가 공개되면 게이트가 무력해진다(제3자가 내 ID 서버에 무단 등록).
    #   → 서버 주소와 키는 **호출 시점에 주입**한다. 저장소에는 남기지 않는다.
    #   값은 %LOCALAPPDATA%\vibe-remote\rustdesk-server.txt 또는 관리자에게서 받는다.
    [Parameter(Mandatory)][string]$VpsHost,
    [Parameter(Mandatory)][string]$RustDeskKey,

    # 비우면 16자 자동 생성.
    [string]$RustDeskPassword = '',

    # 화면 경로가 필요 없으면(셸만) 지정.
    [switch]$SkipRustDesk
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$SecretDir = Join-Path $env:LOCALAPPDATA 'vibe-remote'
$KeyPath   = Join-Path $SecretDir "tunnel_$NodeName"
$TaskName  = "vibe-tunnel-$NodeName"

function Say($m, $lvl = 'INFO') {
    $c = @{ 'INFO' = 'Gray'; 'OK' = 'Green'; 'WARN' = 'Yellow'; 'FAIL' = 'Red' }[$lvl]
    Write-Host ("[{0,-4}] {1}" -f $lvl, $m) -ForegroundColor $c
}

$id = [Security.Principal.WindowsIdentity]::GetCurrent()
if (-not (New-Object Security.Principal.WindowsPrincipal($id)).IsInRole(
        [Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw '관리자 권한으로 실행해야 한다. PowerShell을 "관리자 권한으로 실행"할 것.'
}

Write-Host ''
Write-Host "=== 원격 노드 세팅: $NodeName ===" -ForegroundColor Cyan
Write-Host ''

if (-not (Test-Path $SecretDir)) { New-Item -ItemType Directory -Path $SecretDir -Force | Out-Null }


# ── 1. OpenSSH 서버 ─────────────────────────────────────────────────────────
# [WHY 필요한가] 역터널은 "VPS의 포트 → 이 PC의 22번"으로 연결한다. 이 PC에 sshd가 없으면
#   터널은 열리지만 그 끝에 아무것도 없어 접속이 거부된다. 증상이 "터널은 붙었는데 안 됨"이라
#   원인 파악이 오래 걸린다 → 먼저 세운다.
$cap = Get-WindowsCapability -Online -Name 'OpenSSH.Server*' -ErrorAction SilentlyContinue |
       Select-Object -First 1
if ($cap -and $cap.State -ne 'Installed') {
    Say 'OpenSSH 서버 설치 중...'
    Add-WindowsCapability -Online -Name $cap.Name | Out-Null
}
Set-Service -Name sshd -StartupType Automatic -ErrorAction SilentlyContinue
Start-Service -Name sshd -ErrorAction SilentlyContinue
if ((Get-Service sshd -ErrorAction SilentlyContinue).Status -eq 'Running') {
    Say 'OpenSSH 서버 실행 중 (자동 시작)' 'OK'
} else {
    Say 'OpenSSH 서버를 띄우지 못했다 — 셸 경로는 동작하지 않는다.' 'FAIL'
}

# [불변식] sshd는 **루프백만** 들어오면 된다. 역터널이 VPS→localhost:22로 꽂히기 때문이다.
#   22번을 LAN/공인망에 열 이유가 없다 — 방화벽 규칙을 만들지 않는 것이 곧 최소 노출이다.
Get-NetFirewallRule -Name 'OpenSSH-Server-In-TCP' -ErrorAction SilentlyContinue |
    Set-NetFirewallRule -Enabled False -ErrorAction SilentlyContinue
Say 'sshd 인바운드 방화벽 규칙 비활성 (역터널은 루프백이라 불필요)' 'OK'


# ── 2. 터널 키 생성 ─────────────────────────────────────────────────────────
# [WHY 여기서 만드나] 개인키를 문서/드라이브로 나르면 그 경로가 곧 유출 경로가 된다.
#   이 PC에서 만들고 **공개키만** 밖으로 내보낸다. 개인키는 이 디스크를 떠나지 않는다.
if (-not (Test-Path $KeyPath)) {
    ssh-keygen -t ed25519 -N '""' -C "tunnel-$NodeName" -f $KeyPath 2>&1 | Out-Null
}
if (-not (Test-Path "$KeyPath.pub")) { throw "키 생성 실패: $KeyPath" }
# 개인키는 소유자만 읽게 — 다중 사용자 PC 대비.
icacls $KeyPath /inheritance:r /grant:r "$($env:USERNAME):(R,W)" /Q 2>&1 | Out-Null
$pub = (Get-Content "$KeyPath.pub" -Raw).Trim()
Say "터널 키 준비: $KeyPath" 'OK'


# ── 3. 역터널 상주화 ────────────────────────────────────────────────────────
# [WHY .cmd 래퍼인가] 예약 작업은 인자 따옴표 처리가 까다롭고 재시도 로직을 넣을 수 없다.
#   래퍼를 두면 ssh가 끊겼을 때 즉시 다시 붙는 루프를 넣을 수 있다(회선 끊김·VPS 재시작 대비).
# [불변식] ExitOnForwardFailure=yes — 포트를 못 잡으면 조용히 "붙은 척" 하지 않고 죽는다.
#   그래야 루프가 다시 시도한다. 이게 없으면 터널 없는 좀비 세션이 남아 진단을 흐린다.
$runner = Join-Path $SecretDir "tunnel-$NodeName.cmd"
$runnerBody = @(
    '@echo off'
    'rem 자동 생성 — Setup-RemoteNode.ps1. 직접 수정하지 말 것.'
    ':loop'
    ('ssh -N -T -o StrictHostKeyChecking=accept-new -o ExitOnForwardFailure=yes ' +
     '-o ServerAliveInterval=30 -o ServerAliveCountMax=3 -o ConnectTimeout=15 ' +
     "-i `"$KeyPath`" -R $TunnelPort`:localhost:22 tunnel@$VpsHost")
    'timeout /t 15 /nobreak >NUL'
    'goto loop'
)
Set-Content -Path $runner -Value $runnerBody -Encoding Default

if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
}
$action    = New-ScheduledTaskAction -Execute $runner
$trigger   = New-ScheduledTaskTrigger -AtStartup
$principal = New-ScheduledTaskPrincipal -UserId 'SYSTEM' -LogonType ServiceAccount -RunLevel Highest
$settings  = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
                -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 999 `
                -RestartInterval ([TimeSpan]::FromMinutes(1)) -MultipleInstances IgnoreNew
Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger `
                       -Principal $principal -Settings $settings -Force | Out-Null
Say "역터널 예약 작업 등록: $TaskName (부팅 시 자동)" 'OK'


# ── 4. 절전 해제 ────────────────────────────────────────────────────────────
# 24시간 접근이 목적이면 이게 실패 원인 1위다. 자는 PC는 터널도 화면도 없다.
& powercfg /change standby-timeout-ac 0 2>&1 | Out-Null
& powercfg /change hibernate-timeout-ac 0 2>&1 | Out-Null
& powercfg /change monitor-timeout-ac 15 2>&1 | Out-Null
Say '전원 연결 시 절전 해제 (화면 꺼짐은 유지 — 접근에 영향 없음)' 'OK'


# ── 5. RustDesk (화면 경로) ─────────────────────────────────────────────────
$rustdeskId = ''
if (-not $SkipRustDesk) {
    $rd = @("$env:ProgramFiles\RustDesk\rustdesk.exe", "${env:ProgramFiles(x86)}\RustDesk\rustdesk.exe") |
          Where-Object { Test-Path $_ } | Select-Object -First 1
    if (-not $rd) {
        Say 'RustDesk 내려받는 중...'
        [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
        $rel = Invoke-RestMethod 'https://api.github.com/repos/rustdesk/rustdesk/releases/latest' `
                                 -Headers @{ 'User-Agent' = 'vibe' } -TimeoutSec 30
        $asset = $rel.assets | Where-Object { $_.name -like 'rustdesk-*-x86_64.exe' } | Select-Object -First 1
        $inst = Join-Path $env:TEMP $asset.name
        $prev = $ProgressPreference; $ProgressPreference = 'SilentlyContinue'
        Invoke-WebRequest $asset.browser_download_url -OutFile $inst -UseBasicParsing -TimeoutSec 300
        $ProgressPreference = $prev
        # [과거사고] -Wait를 걸면 설치 프로세스가 트레이/서비스로 이어져 영원히 안 끝난다.
        #   결과물 등장을 폴링해 완료를 판정한다.
        $p = Start-Process $inst -ArgumentList '--silent-install' -PassThru
        for ($i = 0; $i -lt 60; $i++) {
            $rd = @("$env:ProgramFiles\RustDesk\rustdesk.exe") | Where-Object { Test-Path $_ } | Select-Object -First 1
            if ($rd) { break }
            Start-Sleep -Seconds 2
        }
        Start-Sleep -Seconds 3
        if ($p -and -not $p.HasExited) { Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue }
    }
    if (-not $rd) {
        Say 'RustDesk 설치 실패 — 화면 경로는 건너뛴다(셸 경로는 유효).' 'WARN'
    } else {
        $svc = Get-Service RustDesk -ErrorAction SilentlyContinue
        if (-not $svc) { Start-Process $rd -ArgumentList '--install-service' -Wait -ErrorAction SilentlyContinue; Start-Sleep 3 }
        Set-Service RustDesk -StartupType Automatic -ErrorAction SilentlyContinue
        Start-Service RustDesk -ErrorAction SilentlyContinue

        # [핵심 함정] 설정은 두 곳에 있다. 실제 접속을 받는 쪽은 서비스 프로필이며 계정은
        #   LocalSystem이 아니라 **LocalService**다. 사용자 프로필만 고치면 화면상 반영돼 보이지만
        #   실제로는 RustDesk 공용 서버로 나간다. 그리고 서비스를 멈추고 써야 되쓰기로 덮이지 않는다.
        Stop-Service RustDesk -Force -ErrorAction SilentlyContinue
        Start-Sleep -Seconds 3
        Get-Process rustdesk -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
        Start-Sleep -Seconds 2

        $opts = @{
            'custom-rendezvous-server' = $VpsHost
            'relay-server'             = $VpsHost
            'key'                      = $RustDeskKey
            'verification-method'      = 'use-permanent-password'
            'approve-mode'             = 'password'
            'stop-service'             = 'N'
        }
        $dirs = @((Join-Path $env:APPDATA 'RustDesk\config'))
        foreach ($root in @('C:\Windows\ServiceProfiles\LocalService\AppData\Roaming\RustDesk',
                            'C:\Windows\System32\config\systemprofile\AppData\Roaming\RustDesk')) {
            if (Test-Path $root) { $dirs += (Join-Path $root 'config') }
        }
        foreach ($d in $dirs) {
            if (-not (Test-Path $d)) { New-Item -ItemType Directory -Path $d -Force | Out-Null }
            $f = Join-Path $d 'RustDesk2.toml'
            $lines = @(); if (Test-Path $f) { $lines = @(Get-Content $f -Encoding UTF8) }
            if ($lines -notcontains '[options]') { $lines += ''; $lines += '[options]' }
            foreach ($k in $opts.Keys) {
                $lines = $lines | Where-Object { $_ -notmatch "^\s*$([regex]::Escape($k))\s*=" }
            }
            $idx = [array]::IndexOf($lines, '[options]')
            $ins = $opts.Keys | ForEach-Object { "$_ = '$($opts[$_])'" }
            $lines = $lines[0..$idx] + $ins + $(if ($idx + 1 -lt $lines.Count) { $lines[($idx + 1)..($lines.Count - 1)] } else { @() })
            # [함정] RustDesk는 BOM 있는 파일을 통째로 무시한다 → .NET API로 BOM 없이 쓴다.
            [System.IO.File]::WriteAllText($f, (($lines -join "`r`n") + "`r`n"), (New-Object System.Text.UTF8Encoding($false)))
        }
        Start-Service RustDesk -ErrorAction SilentlyContinue
        Start-Sleep -Seconds 5

        if ([string]::IsNullOrWhiteSpace($RustDeskPassword)) {
            $chars = 'abcdefghijkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789'
            $bytes = New-Object byte[] 16
            [System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
            $sb = New-Object System.Text.StringBuilder
            foreach ($b in $bytes) { [void]$sb.Append($chars[$b % $chars.Length]) }
            $RustDeskPassword = $sb.ToString()
        }
        Start-Process $rd -ArgumentList "--password `"$RustDeskPassword`"" -Wait -NoNewWindow -ErrorAction SilentlyContinue
        Start-Sleep -Seconds 2

        # ID는 enc_id(암호화)로 저장돼 TOML 파싱으로는 못 얻는다 → CLI가 유일한 경로.
        $tmp = Join-Path $env:TEMP 'rid.txt'
        Start-Process $rd -ArgumentList '--get-id' -NoNewWindow -Wait -RedirectStandardOutput $tmp -ErrorAction SilentlyContinue
        if (Test-Path $tmp) {
            $m = [regex]::Match((Get-Content $tmp -Raw), '\b\d{6,12}\b')
            if ($m.Success) { $rustdeskId = $m.Value }
            Remove-Item $tmp -Force -ErrorAction SilentlyContinue
        }
        Say 'RustDesk 설정 완료 (VPS ID 서버)' 'OK'
    }
}


# ── 결과 ────────────────────────────────────────────────────────────────────
$report = @()
$report += '=========================================================='
$report += "  노드: $NodeName   ($env:COMPUTERNAME)"
$report += '=========================================================='
$report += ''
$report += '[1] 아래 공개키 한 줄을 관리자에게 그대로 전달하세요.'
$report += '    이게 등록돼야 이 PC가 서버에 연결됩니다.'
$report += ''
$report += $pub
$report += ''
$report += "    터널 포트: $TunnelPort"
if ($rustdeskId) {
    $report += ''
    $report += '[2] 화면 접속 정보'
    $report += "    RustDesk ID : $rustdeskId"
    $report += "    비밀번호    : $RustDeskPassword"
}
$report += '=========================================================='

Write-Host ''
$report | ForEach-Object { Write-Host $_ -ForegroundColor Green }
Write-Host ''

$out = Join-Path ([Environment]::GetFolderPath('Desktop')) "원격노드-$NodeName-정보.txt"
[System.IO.File]::WriteAllText($out, ($report -join "`r`n"), (New-Object System.Text.UTF8Encoding($true)))
Say "바탕화면에도 저장: $out" 'OK'
Write-Host '  공개키를 전달하면 관리자가 서버에 등록합니다. 그 전까지 터널은 연결되지 않습니다.' -ForegroundColor Gray
Write-Host ''
