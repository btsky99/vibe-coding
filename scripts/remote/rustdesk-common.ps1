<#
FILE: scripts/remote/rustdesk-common.ps1
DESCRIPTION: RustDesk 원격제어 구축 스크립트들이 공유하는 공통 함수 모음.
             경로 탐지 / TOML [options] 병합 기록 / 인바운드 노출 제거 / 다운로드 헬퍼.
             단독 실행용이 아니라 Install-RustDeskClient.ps1, Install-RustDeskServer.ps1이 점으로 불러 쓴다.

REVISION HISTORY:
- 2026-08-07 Claude: 최초 작성 — 직결(계층1) + 셀프호스트 hbbs(계층2) 공통 기반.
- 2026-08-09 Claude: 외부 메시 VPN 전면 폐기 — 계층1(사설망 직결) 삭제. 아픽스 서버
                     hbbs 경유만 남기고, 인바운드 허용 규칙은 축소가 아니라 제거한다.
#>

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

# [WHY 저장소 밖인가] 비밀번호·개인키가 git에 들어가면 화면 조작 권한이 통째로 샌다.
# .gitignore에 의존하면 규칙이 빠지는 순간 커밋되므로, 아예 **저장소 바깥** 경로로 못 박는다.
$script:SecretDir = Join-Path $env:LOCALAPPDATA 'vibe-remote'

# [🔴 포트 충돌 — 2026-08-07 실측] hbbs는 21116(ID)·21115(NAT판정)과 함께
# **21118을 웹소켓 리슨으로 고정 사용**한다. 그런데 RustDesk 클라이언트의 '직접 IP 접속'
# 기본 포트도 21118이다. 한 PC에 서버와 클라이언트를 같이 올리면 나중에 뜨는 쪽이
# `os error 10013`으로 죽는다(실제로 hbbs가 즉사했다).
# → 서버를 겸하는 PC에서는 클라이언트 직접접속 포트를 아래 값으로 비켜준다.
#   hbbs의 21118은 OSS판에서 개별 변경이 불가(기준 포트에서 파생)하므로 양보하는 쪽은 클라이언트다.
$script:DirectPortDefault  = 21118
$script:DirectPortWhenHbbs = 21128


function Test-HbbsPresent {
    <#
      이 PC가 hbbs(ID 서버)를 겸하는지 판정한다.
      [WHY 프로세스만 보지 않는가] 설치 직후엔 아직 안 떠 있을 수 있고, 재부팅 대기 중일 수도 있다.
      예약 작업 등록 여부가 "이 PC는 서버 역할"의 더 안정적인 신호다.
    #>
    if (Get-Process -Name 'hbbs' -ErrorAction SilentlyContinue) { return $true }
    if (Get-ScheduledTask -TaskName 'vibe-remote hbbs' -ErrorAction SilentlyContinue) { return $true }
    return $false
}


function Write-Step {
    param([string]$Message, [string]$Level = 'INFO')
    $color = 'Gray'
    if ($Level -eq 'OK')   { $color = 'Green' }
    if ($Level -eq 'WARN') { $color = 'Yellow' }
    if ($Level -eq 'FAIL') { $color = 'Red' }
    Write-Host ("[{0,-4}] {1}" -f $Level, $Message) -ForegroundColor $color
}


function Assert-Admin {
    <#
      [제약] 클라이언트 서비스 등록, 방화벽 규칙 수정, SYSTEM 예약 작업 생성 모두
      관리자 토큰을 요구한다. 비관리자로 진행하면 절반만 적용된 상태로 끝나
      "설치는 됐는데 무인 접속이 안 되는" 진단 어려운 상태가 된다 → 진입부에서 차단.
    #>
    $id = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($id)
    if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
        throw '관리자 권한이 필요하다. PowerShell을 "관리자 권한으로 실행"한 뒤 다시 돌려라.'
    }
}



function Get-RustDeskExe {
    <#
      [반환] 설치된 rustdesk.exe 전체 경로, 없으면 $null.
      [제약] 1.4.x는 기본적으로 %ProgramFiles%\RustDesk 에 깔리지만 사용자가 경로를
      바꿨을 수 있어 레지스트리 언인스톨 키를 1순위로 본다.
    #>
    $keys = @(
        'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\RustDesk',
        'HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\RustDesk'
    )
    foreach ($k in $keys) {
        if (Test-Path $k) {
            $loc = (Get-ItemProperty $k -ErrorAction SilentlyContinue).InstallLocation
            if ($loc) {
                $candidate = Join-Path $loc 'rustdesk.exe'
                if (Test-Path $candidate) { return $candidate }
            }
        }
    }
    foreach ($p in @("$env:ProgramFiles\RustDesk\rustdesk.exe", "${env:ProgramFiles(x86)}\RustDesk\rustdesk.exe")) {
        if (Test-Path $p) { return $p }
    }
    return $null
}


function Get-RustDeskConfigDirs {
    <#
      [핵심 함정 — 2026-08-07 실측으로 확인] RustDesk 설정은 한 곳이 아니라 **두 곳**에 있다.
        1) 로그인 사용자 프로필 — GUI 화면이 읽는다
        2) 서비스 프로필        — 실제로 원격 접속을 받아들이는 rustdesk --service 가 읽는다
      한쪽만 고치면 "설정 화면엔 반영돼 보이는데 실제 접속은 공용 서버로 나가는" 무증상 실패가 난다.
      실제로 처음 구현에서 사용자 프로필에만 써서 서비스는 rs-ny.rustdesk.com(공용)을 계속 봤고
      직접 IP 접속도 꺼진 채였다.

      [🔴 경로 주의] 서비스 계정은 LocalSystem이 아니라 **LocalService**다.
      즉 systemprofile 이 아니라 C:\Windows\ServiceProfiles\LocalService\... 다.
      systemprofile 경로는 존재하지 않으므로 그쪽만 노리면 조용히 0건이 된다.
      (RustDesk 버전에 따라 달라질 수 있어 후보를 모두 훑고 '실재하는 것'만 채택한다.)

      [반환] 존재하는 config 디렉터리 배열. 사용자 프로필은 없으면 만들어서라도 포함한다.
    #>
    $userDir = Join-Path $env:APPDATA 'RustDesk\config'
    if (-not (Test-Path $userDir)) { New-Item -ItemType Directory -Path $userDir -Force | Out-Null }
    $out = @($userDir)

    $serviceRoots = @(
        'C:\Windows\ServiceProfiles\LocalService\AppData\Roaming\RustDesk',
        'C:\Windows\ServiceProfiles\NetworkService\AppData\Roaming\RustDesk',
        'C:\Windows\System32\config\systemprofile\AppData\Roaming\RustDesk'
    )
    foreach ($root in $serviceRoots) {
        # [불변식] 여기서는 디렉터리를 만들지 않는다. 서비스가 실제로 쓰는 곳만 골라야 하는데,
        # 빈 디렉터리를 새로 만들면 "썼다"는 착각만 남기고 서비스는 다른 곳을 계속 본다.
        if (Test-Path $root) {
            $cfg = Join-Path $root 'config'
            if (-not (Test-Path $cfg)) { New-Item -ItemType Directory -Path $cfg -Force | Out-Null }
            $out += $cfg
        }
    }
    return $out
}


function Merge-TomlOptions {
    <#
      RustDesk2.toml 의 [options] 섹션에 키/값을 병합한다.

      [WHY 정규식 파서인가] RustDesk 설정은 평평한 key = 'value' 뿐이라 완전한 TOML
      파서가 필요 없다. PowerShell 5.1에는 내장 TOML 파서가 없고 외부 모듈을 끌어오면
      "가벼움+이식성" 원칙을 깬다 → 이 파일이 다루는 좁은 문법에 한정한 수동 병합.
      [제약] 배열/중첩 테이블 값은 다루지 못한다. RustDesk2.toml에는 없으니 무방하나,
      RustDesk.toml(key_pair 배열 보유)에는 절대 쓰지 말 것.
      [불변식] 기존 키는 덮어쓰고, 언급 없는 키는 원본 그대로 보존한다 —
      사용자가 GUI에서 만진 다른 설정을 스크립트가 날리면 안 된다.
    #>
    param(
        [Parameter(Mandatory)][string]$Path,
        [Parameter(Mandatory)][hashtable]$Options
    )

    $lines = @()
    if (Test-Path $Path) {
        $lines = @(Get-Content -Path $Path -Encoding UTF8)
    }

    $optIndex = -1
    for ($i = 0; $i -lt $lines.Count; $i++) {
        if ($lines[$i].Trim() -eq '[options]') { $optIndex = $i; break }
    }

    if ($optIndex -lt 0) {
        # [options] 자체가 없으면 파일 끝에 새로 만든다.
        if ($lines.Count -gt 0 -and -not [string]::IsNullOrWhiteSpace($lines[-1])) { $lines += '' }
        $lines += '[options]'
        $optIndex = $lines.Count - 1
    }

    # [options] 이후 다음 섹션 헤더 직전까지가 편집 대상 구간.
    $endIndex = $lines.Count
    for ($i = $optIndex + 1; $i -lt $lines.Count; $i++) {
        if ($lines[$i].Trim() -match '^\[') { $endIndex = $i; break }
    }

    $remaining = @{}
    foreach ($k in $Options.Keys) { $remaining[$k] = $Options[$k] }

    for ($i = $optIndex + 1; $i -lt $endIndex; $i++) {
        $m = [regex]::Match($lines[$i], "^\s*(?<k>[A-Za-z0-9_\-]+)\s*=")
        if ($m.Success) {
            $key = $m.Groups['k'].Value
            if ($remaining.ContainsKey($key)) {
                $lines[$i] = "$key = '$($remaining[$key])'"
                $remaining.Remove($key)
            }
        }
    }

    $insert = @()
    foreach ($k in $remaining.Keys) { $insert += "$k = '$($remaining[$k])'" }
    if ($insert.Count -gt 0) {
        $head = @()
        if ($endIndex -gt 0) { $head = $lines[0..($endIndex - 1)] }
        $tail = @()
        if ($endIndex -lt $lines.Count) { $tail = $lines[$endIndex..($lines.Count - 1)] }
        $lines = $head + $insert + $tail
    }

    $dir = Split-Path $Path -Parent
    if (-not (Test-Path $dir)) { New-Item -ItemType Directory -Path $dir -Force | Out-Null }

    # [함정] RustDesk는 BOM 없는 UTF-8만 파싱한다. PowerShell 5.1의 Out-File -Encoding utf8은
    # BOM을 붙여버려 RustDesk가 설정을 통째로 무시한다(증상: 커스텀 서버가 적용 안 됨).
    # → .NET API로 BOM 없이 직접 쓴다.
    $enc = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText($Path, (($lines -join "`r`n") + "`r`n"), $enc)
}


function Set-RustDeskOptionsEverywhere {
    <#
      두 프로필(사용자/서비스) 양쪽 RustDesk2.toml에 동일 옵션을 주입한다.
      Get-RustDeskConfigDirs 의 주석 참조 — 한쪽만 고치면 무증상 실패.

      [불변식] 반드시 서비스를 멈춘 뒤 쓴다. 살아 있는 서비스는 종료 시점에 자기 메모리 상태를
      config 파일로 되쓰기 때문에, 돌아가는 중에 고치면 다음 재시작에서 조용히 덮여 사라진다.
      [사후검증] 쓴 값을 되읽어 확인한다 — "반영했다"는 로그만 믿으면 위 되쓰기 사고를 놓친다.
    #>
    param([Parameter(Mandatory)][hashtable]$Options)

    $svc = Get-Service -Name 'RustDesk' -ErrorAction SilentlyContinue
    $wasRunning = ($null -ne $svc -and $svc.Status -eq 'Running')
    if ($wasRunning) {
        Stop-Service -Name 'RustDesk' -Force
        Start-Sleep -Seconds 3
        Get-Process -Name 'rustdesk' -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
        Start-Sleep -Seconds 2
        Write-Step 'RustDesk 서비스 정지 (설정 되쓰기 방지)' 'INFO'
    }

    $applied = 0
    $targets = @(Get-RustDeskConfigDirs)
    foreach ($dir in $targets) {
        $file = Join-Path $dir 'RustDesk2.toml'
        Merge-TomlOptions -Path $file -Options $Options
        Write-Step "설정 반영: $file" 'OK'
        $applied++
    }
    if ($applied -eq 0) { throw 'RustDesk 설정 디렉터리를 찾지 못했다. 클라이언트가 설치되어 있는지 확인하라.' }

    if ($wasRunning) {
        Start-Service -Name 'RustDesk'
        Start-Sleep -Seconds 5
    }

    # 서비스가 다시 뜬 뒤 값이 살아남았는지 확인한다.
    $failed = @()
    foreach ($dir in $targets) {
        $file = Join-Path $dir 'RustDesk2.toml'
        $text = ''
        if (Test-Path $file) { $text = Get-Content $file -Raw }
        foreach ($k in $Options.Keys) {
            if ($text -notmatch [regex]::Escape("$k = '$($Options[$k])'")) { $failed += "$k @ $file" }
        }
    }
    if ($failed.Count -gt 0) {
        Write-Step "재기동 후 유실된 설정 $($failed.Count)건:" 'FAIL'
        foreach ($f in $failed) { Write-Step "  - $f" 'FAIL' }
        throw '설정이 서비스 재기동을 견디지 못했다. RustDesk를 완전히 종료한 뒤 다시 실행하라.'
    }
    # [함정] "$applied곳"처럼 변수 뒤에 한글이 바로 붙으면 PowerShell이 한글까지 변수명으로 삼켜
    # "정의되지 않은 변수" 오류를 낸다. 한글 문자열 보간은 항상 $(...) 로 감쌀 것.
    Write-Step "설정 $($Options.Count)개가 프로필 $($applied)곳에서 재기동 후에도 유지됨" 'OK'
    return $applied
}


function Get-RustDeskId {
    <#
      [🔴 2026-08-07 실측] RustDesk 1.4.x는 ID를 평문 `id`가 아니라 **`enc_id`(암호화)** 로 저장한다.
      따라서 TOML 정규식만으로는 절대 못 얻는다(첫 구현이 여기서 빈 값을 반환했다).
      → CLI `--get-id`가 사실상 유일한 경로다. 파일 파싱은 구버전(`id` 평문) 대비 폴백으로만 둔다.

      [제약] rustdesk.exe는 GUI 서브시스템이라 파이프로 직접 못 받는 경우가 있어
      출력을 임시 파일로 리다이렉트해 회수한다.
    #>
    $exe = Get-RustDeskExe
    if ($null -ne $exe) {
        $tmp = Join-Path $env:TEMP ('rustdesk-id-' + [guid]::NewGuid().ToString('N') + '.txt')
        try {
            Start-Process -FilePath $exe -ArgumentList '--get-id' -NoNewWindow -Wait `
                          -RedirectStandardOutput $tmp -ErrorAction SilentlyContinue
            if (Test-Path $tmp) {
                $val = (Get-Content $tmp -Raw).Trim()
                # ID는 9~12자리 숫자다. 로그 잡음이 섞여 들어오는 경우가 있어 형태로 걸러낸다.
                $m = [regex]::Match($val, '\b\d{6,12}\b')
                if ($m.Success) { return $m.Value }
            }
        } catch {
            # 폴백으로 넘어간다.
        } finally {
            Remove-Item $tmp -Force -ErrorAction SilentlyContinue
        }
    }

    foreach ($dir in (Get-RustDeskConfigDirs)) {
        $file = Join-Path $dir 'RustDesk.toml'
        if (Test-Path $file) {
            $m = Select-String -Path $file -Pattern "^\s*id\s*=\s*'([^']+)'" -ErrorAction SilentlyContinue |
                 Select-Object -First 1
            if ($m) { return $m.Matches[0].Groups[1].Value }
        }
    }
    return $null
}


function Remove-InboundExposure {
    <#
      RustDesk 인바운드 허용 규칙을 **삭제**한다(축소가 아니라 제거).

      [WHY 축소가 아니라 제거인가] 예전에는 사설망 대역으로 좁히는 방식이었다. 그 사설망을
      폐기한 지금, 남은 접속 경로는 아픽스 서버 hbbs 경유 하나뿐이고 그건 **아웃바운드**다
      — 이 PC가 서버로 나가서 붙으므로 인바운드 허용 규칙이 아예 필요 없다.
      규칙을 남겨두면 목적 없는 열린 포트만 남는다. 가장 좁은 노출은 노출 없음이다.

      [핵심 함정 — 남겨둠] Windows 방화벽에서 허용 규칙은 OR로 합쳐진다. 설치 프로그램이
      만든 "모든 주소 허용" 규칙이 하나라도 남아 있으면 좁은 규칙을 아무리 더해도 공인망
      노출은 그대로다. 그래서 '좁은 규칙 추가'가 아니라 '기존 규칙 제거'여야 한다.

      [불변식] 지운 개수를 반환한다. 0이면 원래 없었다는 뜻이라 정상이다 — 여기서 경고를
      띄우면 깨끗한 PC에서 매번 겁주는 문구가 뜬다.
    #>
    param([Parameter(Mandatory)][string]$DisplayNamePattern)

    $rules = @(Get-NetFirewallRule -DisplayName $DisplayNamePattern -ErrorAction SilentlyContinue |
               Where-Object { $_.Direction -eq 'Inbound' -and $_.Action -eq 'Allow' })
    if ($rules.Count -eq 0) {
        Write-Step "인바운드 허용 규칙 '$DisplayNamePattern' 없음 — 노출 0 (정상)" 'OK'
        return 0
    }
    foreach ($r in $rules) {
        Remove-NetFirewallRule -InputObject $r -ErrorAction SilentlyContinue
    }
    Write-Step "인바운드 허용 규칙 $($rules.Count)건 삭제 — 접속은 아픽스 서버 경유(아웃바운드)만" 'OK'
    return $rules.Count
}


function New-AllowedInboundRule {
    <#
      지정한 원격 대역에서만 들어오는 인바운드 허용 규칙을 만든다(같은 이름이면 갱신).

      [WHY AllowFrom 이 필수 인자인가] 예전에는 대역이 상수(사설망)로 박혀 있어 호출부가
      노출 범위를 생각할 필요가 없었다. 그 사설망을 폐기한 지금 대역은 상황마다 다르고,
      기본값을 Any 로 두면 실수 한 번에 전 세계로 열린다. 호출부가 매번 명시하게 만든다.

      [핵심 함정] 이 함수만으로는 노출이 좁아지지 않는다. Windows 방화벽에서 허용 규칙은
      OR 로 합쳐지므로, 설치 프로그램이 만든 "모든 주소 허용" 규칙이 남아 있으면 좁은 규칙을
      더해도 소용없다. 넓은 규칙은 Remove-InboundExposure 로 먼저 지워야 한다.
    #>
    param(
        [Parameter(Mandatory)][string]$DisplayName,
        [Parameter(Mandatory)][int[]]$TcpPorts,
        [Parameter(Mandatory)][string[]]$AllowFrom,
        [int[]]$UdpPorts = @()
    )
    if ($AllowFrom.Count -eq 0) {
        throw "AllowFrom 이 비었다. 열 대역을 명시하라 — 빈 값을 '전체 허용'으로 해석하지 않는다."
    }
    Get-NetFirewallRule -DisplayName $DisplayName -ErrorAction SilentlyContinue |
        Remove-NetFirewallRule -ErrorAction SilentlyContinue

    $desc = "vibe-remote: $($AllowFrom -join ',') 에서만 허용"
    if ($TcpPorts.Count -gt 0) {
        New-NetFirewallRule -DisplayName $DisplayName -Direction Inbound -Action Allow `
            -Protocol TCP -LocalPort $TcpPorts -RemoteAddress $AllowFrom `
            -Profile Any -Description $desc | Out-Null
    }
    if ($UdpPorts.Count -gt 0) {
        New-NetFirewallRule -DisplayName "$DisplayName (UDP)" -Direction Inbound -Action Allow `
            -Protocol UDP -LocalPort $UdpPorts -RemoteAddress $AllowFrom `
            -Profile Any -Description $desc | Out-Null
    }
    Write-Step "방화벽 규칙 생성: $DisplayName (TCP $($TcpPorts -join ',') / UDP $($UdpPorts -join ',')) ← $($AllowFrom -join ',')" 'OK'
}


function Save-Secret {
    <#
      비밀값을 %LOCALAPPDATA%\vibe-remote 아래에 저장한다.
      [WHY 저장소 밖인가] 이 값(고정 비밀번호, hbbs 개인키)이 git에 들어가면
      화면 조작 권한이 통째로 유출된다. 저장소 경로는 쓰지 않는다.
    #>
    param([Parameter(Mandatory)][string]$Name, [Parameter(Mandatory)][string]$Value)
    if (-not (Test-Path $script:SecretDir)) { New-Item -ItemType Directory -Path $script:SecretDir -Force | Out-Null }
    $path = Join-Path $script:SecretDir $Name
    $enc = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText($path, $Value, $enc)

    # 소유자만 읽도록 ACL 축소 — 다중 사용자 PC에서 다른 계정이 비밀번호를 읽는 것을 막는다.
    try {
        icacls $path /inheritance:r /grant:r "$($env:USERNAME):(R,W)" "SYSTEM:(F)" "Administrators:(F)" | Out-Null
    } catch {
        Write-Step "ACL 축소 실패(무시 가능): $path" 'WARN'
    }
    return $path
}


function New-StrongPassword {
    # [WHY 대소문자+숫자만] RustDesk 비밀번호는 폰/탭에서 손으로 치는 일이 잦다.
    # 기호를 넣으면 모바일 키보드 전환이 늘어 오타가 급증한다 — 길이(16자)로 강도를 확보한다.
    param([int]$Length = 16)
    $chars = 'abcdefghijkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789'
    $bytes = New-Object byte[] $Length
    $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    $rng.GetBytes($bytes)
    $sb = New-Object System.Text.StringBuilder
    foreach ($b in $bytes) { [void]$sb.Append($chars[$b % $chars.Length]) }
    return $sb.ToString()
}


function Invoke-Download {
    param([Parameter(Mandatory)][string]$Uri, [Parameter(Mandatory)][string]$OutFile)
    $dir = Split-Path $OutFile -Parent
    if (-not (Test-Path $dir)) { New-Item -ItemType Directory -Path $dir -Force | Out-Null }

    # [WHY] PS5.1 기본 보안 프로토콜이 TLS1.0인 환경이 남아 있어 GitHub이 연결을 끊는다.
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    # [WHY] Invoke-WebRequest는 진행률 렌더링 때문에 대용량에서 수십 배 느려진다.
    $prev = $ProgressPreference
    $ProgressPreference = 'SilentlyContinue'
    try {
        Invoke-WebRequest -Uri $Uri -OutFile $OutFile -UseBasicParsing -TimeoutSec 300
    } finally {
        $ProgressPreference = $prev
    }
    if (-not (Test-Path $OutFile)) { throw "다운로드 실패: $Uri" }
    $size = (Get-Item $OutFile).Length
    if ($size -lt 100KB) { throw "다운로드 결과가 비정상적으로 작다($size bytes): $Uri" }
    Write-Step ("다운로드 완료: {0} ({1:N1} MB)" -f (Split-Path $OutFile -Leaf), ($size / 1MB)) 'OK'
}


function Get-LatestReleaseAsset {
    <#
      GitHub 최신 릴리스에서 이름이 패턴에 맞는 자산의 다운로드 URL을 찾는다.
      [WHY 버전 고정 대신 조회인가] RustDesk는 릴리스가 잦고 URL에 버전이 박힌다.
      하드코딩하면 몇 달 뒤 이 스크립트가 404로 죽는다.
      [폴백] API 호출이 실패하면 호출부가 -Version 인자로 수동 지정할 수 있어야 한다.
    #>
    param([Parameter(Mandatory)][string]$Repo, [Parameter(Mandatory)][string]$NamePattern)
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    $rel = Invoke-RestMethod -Uri "https://api.github.com/repos/$Repo/releases/latest" `
                             -Headers @{ 'User-Agent' = 'vibe-remote' } -TimeoutSec 30
    $asset = $rel.assets | Where-Object { $_.name -like $NamePattern } | Select-Object -First 1
    if ($null -eq $asset) { throw "$Repo 최신 릴리스($($rel.tag_name))에 '$NamePattern' 자산이 없다." }
    return [pscustomobject]@{
        Tag  = $rel.tag_name
        Name = $asset.name
        Url  = $asset.browser_download_url
    }
}
