<#
FILE: scripts/remote/Install-RustDeskServer.ps1
DESCRIPTION: RustDesk ID/중계 서버(hbbs + hbbr)를 이 PC에 셀프호스트한다 (계층 2).
             tailnet 안에서만 열리며, 클라이언트가 100.x.x.x 대신 짧은 ID로 붙게 해준다.
             공인망 노출은 하지 않는다 — 부모님/지인 확장은 docs/REMOTE_CONTROL.md 참조.

             사용:
               관리자 PowerShell> .\Install-RustDeskServer.ps1
               관리자 PowerShell> .\Install-RustDeskServer.ps1 -InstallDir 'D:\rustdesk-server'

REVISION HISTORY:
- 2026-08-07 Claude: 최초 작성 — Windows에는 공식 서비스 래퍼가 없어 예약 작업(SYSTEM)으로 상주시킴.
#>

[CmdletBinding()]
param(
    [string]$InstallDir = 'C:\ProgramData\rustdesk-server',

    # 중계 서버 주소. 비우면 이 PC의 Tailscale IP를 쓴다.
    # [제약] 여기에 LAN IP(192.168.x)를 넣으면 외부망에 나갔을 때 중계가 끊긴다 — tailnet IP여야 한다.
    [string]$RelayAddress = '',

    [switch]$Uninstall
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'rustdesk-common.ps1')

$TaskHbbs = 'vibe-remote hbbs'
$TaskHbbr = 'vibe-remote hbbr'

Write-Host ''
Write-Host '=== RustDesk 셀프호스트 서버 (hbbs/hbbr) ===' -ForegroundColor Cyan
Write-Host ''

Assert-Admin

# ── 제거 경로 ───────────────────────────────────────────────────────────────
if ($Uninstall) {
    foreach ($t in @($TaskHbbs, $TaskHbbr)) {
        if (Get-ScheduledTask -TaskName $t -ErrorAction SilentlyContinue) {
            Unregister-ScheduledTask -TaskName $t -Confirm:$false
            Write-Step "예약 작업 제거: $t" 'OK'
        }
    }
    Get-Process -Name 'hbbs', 'hbbr' -ErrorAction SilentlyContinue | Stop-Process -Force
    Get-NetFirewallRule -DisplayName 'vibe-remote hbbs*' -ErrorAction SilentlyContinue | Remove-NetFirewallRule
    Write-Step '서버 제거 완료. 설치 디렉터리와 키는 보존했다(재설치 시 ID 유지 목적).' 'OK'
    Write-Step "직접 지우려면: $InstallDir" 'INFO'
    return
}

# ── 1. 중계 주소 결정 ───────────────────────────────────────────────────────
if ([string]::IsNullOrWhiteSpace($RelayAddress)) {
    $RelayAddress = Get-TailscaleIPv4
    if ($null -eq $RelayAddress) {
        throw 'Tailscale IP를 찾지 못했다. Tailscale 로그인 후 다시 실행하거나 -RelayAddress를 직접 지정하라.'
    }
}
Write-Step "중계 주소: $RelayAddress" 'OK'

# ── 2. 바이너리 배치 ────────────────────────────────────────────────────────
$hbbs = Join-Path $InstallDir 'hbbs.exe'
$hbbr = Join-Path $InstallDir 'hbbr.exe'

if (-not (Test-Path $hbbs) -or -not (Test-Path $hbbr)) {
    $asset = Get-LatestReleaseAsset -Repo 'rustdesk/rustdesk-server' -NamePattern '*windows-x86_64*.zip'
    Write-Step "rustdesk-server $($asset.Tag) 내려받는 중..."
    $zip = Join-Path $env:TEMP $asset.Name
    Invoke-Download -Uri $asset.Url -OutFile $zip

    $stage = Join-Path $env:TEMP 'rustdesk-server-stage'
    if (Test-Path $stage) { Remove-Item $stage -Recurse -Force }
    Expand-Archive -Path $zip -DestinationPath $stage -Force

    if (-not (Test-Path $InstallDir)) { New-Item -ItemType Directory -Path $InstallDir -Force | Out-Null }

    # [제약] 배포 zip의 내부 폴더 구조가 릴리스마다 바뀐 전례가 있어 고정 경로를 쓰지 않고 재귀 탐색한다.
    foreach ($name in @('hbbs.exe', 'hbbr.exe')) {
        $found = Get-ChildItem -Path $stage -Filter $name -Recurse -File | Select-Object -First 1
        if ($null -eq $found) { throw "배포 zip에서 $name 을 찾지 못했다: $($asset.Name)" }
        Copy-Item -Path $found.FullName -Destination (Join-Path $InstallDir $name) -Force
    }
    Remove-Item $stage -Recurse -Force -ErrorAction SilentlyContinue
    Write-Step "바이너리 배치 완료: $InstallDir" 'OK'
} else {
    Write-Step "기존 바이너리 사용: $InstallDir" 'OK'
}

# ── 2.5 포트 21118 확보 ─────────────────────────────────────────────────────
# [🔴 과거사고 2026-08-07] 이 PC에 RustDesk 클라이언트가 이미 있고 '직접 IP 접속'이 켜져 있으면
# 클라이언트가 21118을 선점한다. 그 상태로 hbbs를 띄우면 웹소켓 바인딩에서 `os error 10013`으로
# 즉사한다(로그에는 "Listening on websocket :21118" 직후 에러만 남아 원인이 잘 안 보인다).
# hbbs의 21118은 기준 포트에서 파생돼 개별 변경이 불가하므로, 양보는 클라이언트가 한다.
$holder = Get-NetTCPConnection -State Listen -LocalPort 21118 -ErrorAction SilentlyContinue | Select-Object -First 1
if ($null -ne $holder) {
    $holderProc = Get-Process -Id $holder.OwningProcess -ErrorAction SilentlyContinue
    if ($null -ne $holderProc -and $holderProc.ProcessName -eq 'rustdesk') {
        Write-Step "포트 21118을 RustDesk 클라이언트가 선점 중 → 직접접속 포트를 $($script:DirectPortWhenHbbs)로 옮긴다." 'WARN'
        Set-RustDeskOptionsEverywhere -Options @{ 'direct-access-port' = "$($script:DirectPortWhenHbbs)" } | Out-Null
        New-TailnetOnlyRule -DisplayName 'vibe-remote RustDesk 직접접속' -TcpPorts @($script:DirectPortWhenHbbs) | Out-Null
        Start-Sleep -Seconds 3
    } else {
        throw "포트 21118을 다른 프로그램이 쓰고 있다(PID $($holder.OwningProcess) / $($holderProc.ProcessName)). 먼저 정리하라."
    }
}

# ── 3. 키 쌍 생성 ───────────────────────────────────────────────────────────
# [WHY 미리 한 번 띄우는가] hbbs는 최초 기동 시 작업 디렉터리에 id_ed25519 쌍을 만든다.
# 예약 작업으로만 띄우면 키 파일이 언제 생기는지 알 수 없어 공개키 출력이 빈 값이 된다.
# → 여기서 짧게 띄워 키를 확정한 뒤 종료하고, 상주는 예약 작업에 맡긴다.
$pubKeyFile = Join-Path $InstallDir 'id_ed25519.pub'
if (-not (Test-Path $pubKeyFile)) {
    Write-Step '키 쌍 생성을 위해 hbbs를 짧게 기동한다...'
    $p = Start-Process -FilePath $hbbs -ArgumentList "-r $RelayAddress -k _" `
                       -WorkingDirectory $InstallDir -PassThru -WindowStyle Hidden
    for ($i = 0; $i -lt 20; $i++) {
        Start-Sleep -Seconds 1
        if (Test-Path $pubKeyFile) { break }
    }
    Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 1
}
if (-not (Test-Path $pubKeyFile)) { throw "키 생성 실패. $InstallDir 쓰기 권한과 hbbs 실행 여부를 확인하라." }

$pubKey = (Get-Content $pubKeyFile -Raw).Trim()
Write-Step '키 쌍 확보 완료' 'OK'

# [WHY 개인키만 잠그는가] id_ed25519(개인키)가 유출되면 제3자가 이 ID 서버를 사칭할 수 있다.
# 반면 hbbs.exe/hbbr.exe는 공개 배포 바이너리라 감출 이유가 없다.
#
# [🔴 과거사고 2026-08-07] 처음엔 설치 디렉터리 전체에
#   icacls <dir> /inheritance:r /grant:r 'SYSTEM:(OI)(CI)F' 'Administrators:(OI)(CI)F' /T
# 를 걸었다가 서버가 통째로 기동 실패(예약 작업 LastResult=0x80070005 액세스 거부)했다.
# 원인: (OI)(CI)는 '컨테이너 상속' 플래그라 파일에는 적용되지 않는데 /T가 파일의 상속은 먼저 끊어버려
# → hbbs.exe에 ACE가 하나도 남지 않아 SYSTEM조차 실행 불가. icacls는 이 조합을 오류로 알리지 않는다.
# 교훈: 파일에 권한을 줄 때는 상속 플래그 없이 평범한 F/R로 준다. 그리고 넓은 /T 잠금은 쓰지 않는다.
$privKey = Join-Path $InstallDir 'id_ed25519'
if (Test-Path $privKey) {
    try {
        # SID로 지정 — 한국어 Windows에서 'Administrators' 이름 해석이 실패해도 안전하다.
        icacls $privKey /inheritance:r /grant:r '*S-1-5-18:F' '*S-1-5-32-544:F' /Q | Out-Null
        Write-Step '개인키 파일 ACL을 SYSTEM/관리자 전용으로 축소' 'OK'
    } catch {
        Write-Step '개인키 ACL 축소 실패 — 수동 확인 권장' 'WARN'
    }
}

# ── 4. 예약 작업으로 상주화 ─────────────────────────────────────────────────
function Register-ResidentTask {
    <#
      [WHY sc.exe 서비스가 아니라 예약 작업인가] hbbs/hbbr은 Windows 서비스 제어 메시지에
      응답하지 않는 순수 콘솔 프로그램이다. sc create로 등록하면 "제 시간에 응답하지 않았습니다"(1053)로
      기동에 실패한다. NSSM 같은 외부 래퍼를 끌어오면 이식성이 떨어지므로 내장 예약 작업을 쓴다.
      [불변식] 실행 계정 SYSTEM + AtStartup — 로그인하지 않아도 떠 있어야 원격제어의 의미가 있다.
    #>
    param([string]$Name, [string]$Exe, [string]$Arguments, [string]$WorkDir)

    if (Get-ScheduledTask -TaskName $Name -ErrorAction SilentlyContinue) {
        Unregister-ScheduledTask -TaskName $Name -Confirm:$false
    }
    # [제약] -Argument에 빈 문자열을 주면 등록은 되지만 인자 칸에 따옴표 한 쌍이 남아
    # 일부 환경에서 실행이 실패한다. 비어 있으면 아예 넘기지 않는다.
    if ([string]::IsNullOrWhiteSpace($Arguments)) {
        $action = New-ScheduledTaskAction -Execute $Exe -WorkingDirectory $WorkDir
    } else {
        $action = New-ScheduledTaskAction -Execute $Exe -Argument $Arguments -WorkingDirectory $WorkDir
    }
    $trigger   = New-ScheduledTaskTrigger -AtStartup
    $principal = New-ScheduledTaskPrincipal -UserId 'SYSTEM' -LogonType ServiceAccount -RunLevel Highest
    # ExecutionTimeLimit 0 = 무제한. 기본값(3일)이면 사흘 뒤 조용히 죽는다.
    $settings  = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
                    -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 999 `
                    -RestartInterval ([TimeSpan]::FromMinutes(1)) -MultipleInstances IgnoreNew
    Register-ScheduledTask -TaskName $Name -Action $action -Trigger $trigger `
                           -Principal $principal -Settings $settings -Force | Out-Null
    Write-Step "예약 작업 등록: $Name" 'OK'
}

function New-RunnerCmd {
    <#
      hbbs/hbbr을 감싸는 .cmd 래퍼를 만든다.

      [WHY 래퍼가 필요한가] 두 가지를 예약 작업만으로는 못 한다.
        1) DB_URL 환경변수 — 없으면 hbbs가 peer DB를 실행 계정의 APPDATA에 흩뿌린다.
           SYSTEM으로 돌면 systemprofile 안쪽에 생겨 백업·제거 때 놓친다.
        2) 로그 파일 — 예약 작업은 콘솔 출력을 버린다. 앞서 os error 10013로 즉사했을 때
           로그가 없어 원인 파악에 수동 재현이 필요했다. 관측 없는 상주 프로세스는 고칠 수 없다.
      [주의] `>` 로 매 기동마다 덮어쓴다. RestartCount가 999라 `>>`면 로그가 무한히 자란다.
    #>
    param([string]$Path, [string]$ExeName, [string]$Arguments, [string]$LogName)
    $body = @(
        '@echo off'
        'rem 자동 생성됨 — Install-RustDeskServer.ps1. 직접 수정하지 말 것.'
        'set "DB_URL=%~dp0db_v2.sqlite3"'
        'cd /d "%~dp0"'
        ('"%~dp0{0}" {1} > "%~dp0{2}" 2>&1' -f $ExeName, $Arguments, $LogName)
    )
    # [함정] .cmd는 콘솔 코드페이지로 해석된다. 한글 주석이 들어가므로 UTF-8 BOM 대신
    # 시스템 기본(ANSI/CP949)으로 써야 cmd가 깨진 바이트를 명령으로 오해하지 않는다.
    Set-Content -Path $Path -Value $body -Encoding Default
}

Get-Process -Name 'hbbs', 'hbbr' -ErrorAction SilentlyContinue | Stop-Process -Force
Start-Sleep -Seconds 1

$runHbbs = Join-Path $InstallDir 'run-hbbs.cmd'
$runHbbr = Join-Path $InstallDir 'run-hbbr.cmd'
New-RunnerCmd -Path $runHbbr -ExeName 'hbbr.exe' -Arguments '-k _' -LogName 'hbbr.log'
New-RunnerCmd -Path $runHbbs -ExeName 'hbbs.exe' -Arguments "-r $RelayAddress -k _" -LogName 'hbbs.log'

# [불변식] hbbr(중계)을 먼저 띄운다. hbbs가 먼저 뜨면 중계 대상이 없는 창이 잠깐 생긴다.
Register-ResidentTask -Name $TaskHbbr -Exe $runHbbr -Arguments '' -WorkDir $InstallDir
Register-ResidentTask -Name $TaskHbbs -Exe $runHbbs -Arguments '' -WorkDir $InstallDir

Start-ScheduledTask -TaskName $TaskHbbr
Start-Sleep -Seconds 2
Start-ScheduledTask -TaskName $TaskHbbs
Start-Sleep -Seconds 4

# ── 5. 방화벽 (tailnet 전용) ────────────────────────────────────────────────
# 21115 NAT 판정 / 21116 ID 등록·홀펀칭(TCP+UDP) / 21117 중계 / 21118·21119 웹클라이언트
New-TailnetOnlyRule -DisplayName 'vibe-remote hbbs/hbbr' `
                    -TcpPorts @(21115, 21116, 21117, 21118, 21119) -UdpPorts @(21116)

# ── 6. 검증 ─────────────────────────────────────────────────────────────────
$running = @(Get-Process -Name 'hbbs', 'hbbr' -ErrorAction SilentlyContinue)
$listen  = @(Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue |
             Where-Object { $_.LocalPort -in 21115, 21116, 21117 })

Write-Host ''
if ($running.Count -lt 2) {
    Write-Step "프로세스가 2개여야 하는데 $($running.Count)개다 — 기동 실패." 'FAIL'
    # 로그를 바로 보여준다. 이걸 안 찍으면 사용자가 로그 위치를 모른 채 막힌다.
    foreach ($lg in @('hbbs.log', 'hbbr.log')) {
        $lp = Join-Path $InstallDir $lg
        if (Test-Path $lp) {
            Write-Step "--- $lg (마지막 6줄) ---" 'INFO'
            Get-Content $lp -Tail 6 | ForEach-Object { Write-Host "      $_" -ForegroundColor DarkGray }
        }
    }
    Write-Step "수동 확인: cd `"$InstallDir`" ; .\hbbs.exe -r $RelayAddress -k _" 'INFO'
} else {
    Write-Step "hbbs/hbbr 상주 중 (리슨 포트 $($listen.Count)개)" 'OK'
    Write-Step "로그: $InstallDir\hbbs.log , hbbr.log" 'INFO'
}

Write-Host ''
Write-Host '=== 서버 구축 완료 ===' -ForegroundColor Cyan
Write-Host ("  ID 서버 주소 : {0}" -f $RelayAddress) -ForegroundColor Green
Write-Host ("  공개키(Key)  : {0}" -f $pubKey) -ForegroundColor Green
Write-Host ("  설치 위치    : {0}" -f $InstallDir)
Write-Host ''
Write-Host '  각 클라이언트 PC에서 아래를 실행하면 이 서버를 쓰게 된다:' -ForegroundColor Gray
Write-Host ("    .\Install-RustDeskClient.ps1 -IdServer {0} -Key '{1}'" -f $RelayAddress, $pubKey) -ForegroundColor White
Write-Host ''
Write-Host '  탭/폰은 RustDesk 앱 > 설정 > 네트워크 > ID/중계 서버에 위 두 값을 직접 입력.' -ForegroundColor Gray
Write-Host ''
