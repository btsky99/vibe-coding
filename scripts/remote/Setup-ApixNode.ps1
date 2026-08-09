<#
FILE: scripts/remote/Setup-ApixNode.ps1
DESCRIPTION: 아무 Windows PC 를 아픽스 관제의 '노드'로 만든다. 대상 PC 에서 1회 실행한다.
             하는 일 — ① 토큰 저장 ② 푸시 스크립트 내려받기 ③ 즉시 1회 전송해 실증
             ④ 5분 주기 예약 작업 등록 ⑤ (선택) 관리 PC 공개키 등록으로 조종 통로 확보.

             사용 (대상 PC 의 PowerShell):
               .\Setup-ApixNode.ps1 -Token '<발급받은 토큰>'
               .\Setup-ApixNode.ps1 -Token '<토큰>' -AdminKey 'ssh-ed25519 AAAA... mesh-yjscom'

             토큰 발급은 **서버에서** 한다(관리자 쪽 작업):
               ssh apix "cd /opt/apix/src/collector && python3 manage.py add <node_id> '<라벨>' windows"

             [🔴 이 스크립트는 역터널과 무관하다] 노드 생존 판정의 정본은 노드→서버
             HTTPS 하트비트다(infra/node_status.py 참조). 역터널(Setup-RemoteNode.ps1)은
             '내가 그 노드를 조종할 수 있는가'라는 다른 질문에 답한다. 둘을 한 절차로
             묶으면 터널이 안 되는 노드는 관제에도 안 잡히게 되어, 정작 상태를 알아야 할
             약한 노드가 화면에서 사라진다.

             [WHY 저장소에서 내려받나] 대상 PC 에 vibe-coding 이 설치돼 있다는 보장이 없다.
             apix_push.py 는 패키지 밖 단독 실행을 전제로 쓰였으므로(그 파일 헤더 참조)
             파일 2개만 있으면 돈다. USB·클라우드로 나르면 버전이 갈라진다.

REVISION HISTORY:
- 2026-08-09 Claude: 최초 작성 — 다른 PC 하트비트 온보딩. 지금까지 노드가 이 PC 1대뿐이라
                     '중앙화'가 사실상 단일 노드였던 상태를 푸는 첫 단계.
#>

[CmdletBinding()]
param(
    # 서버 manage.py add 가 1회만 출력하는 값. 잃어버리면 재발급뿐이다.
    [Parameter(Mandatory)][string]$Token,

    [string]$Url = 'https://btsky.pe.kr',

    # 관리 PC 의 공개키 한 줄. 주면 이 PC 의 sshd 가 그 키를 받아들인다.
    # 비워 두면 하트비트만 붙고 원격 접속은 불가(그래도 관제는 정상 동작).
    [string]$AdminKey = '',

    [int]$IntervalMinutes = 5,

    [string]$RepoRaw = 'https://raw.githubusercontent.com/btsky99/vibe-coding/main'
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Say($m, $lvl = 'INFO') {
    $c = @{ 'INFO' = 'Gray'; 'OK' = 'Green'; 'WARN' = 'Yellow'; 'FAIL' = 'Red' }[$lvl]
    Write-Host ("[{0,-4}] {1}" -f $lvl, $m) -ForegroundColor $c
}

# [🔴 PS 5.1 기본 보안 프로토콜] 5.1 은 TLS 1.0 을 기본으로 쓰는 구성이 남아 있어
#   GitHub/Let's Encrypt 엔드포인트에서 조용히 연결이 끊긴다. 증상이 'SSL/TLS 보안 채널'
#   한 줄뿐이라 원인이 드러나지 않는다 — 내려받기 전에 반드시 올린다.
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

# ── 1. 파이썬 확인 ──────────────────────────────────────────────────────────
# [WHY py 런처 우선] 여러 버전이 깔린 PC 에서 `python` 은 Microsoft Store 스텁일 수 있다.
#   스텁은 실행하면 스토어 창만 띄우고 종료 코드 9009 를 남겨 원인을 감춘다.
$py = ''
foreach ($cand in @('py', 'python')) {
    try {
        $v = & $cand -3 --version 2>&1
        if ($LASTEXITCODE -eq 0 -and "$v" -match 'Python 3') { $py = $cand; break }
    } catch { }
    try {
        $v = & $cand --version 2>&1
        if ($LASTEXITCODE -eq 0 -and "$v" -match 'Python 3') { $py = $cand; break }
    } catch { }
}
if (-not $py) {
    throw "Python 3 이 없다. https://www.python.org/downloads/ 설치 후 다시 실행하라 (설치 시 'Add to PATH' 체크)."
}
Say "파이썬: $py" 'OK'

# ── 2. 토큰·주소 저장 ───────────────────────────────────────────────────────
# [WHY 홈 디렉터리인가] 저장소 안(config.json)에 두면 커밋 한 번으로 유출된다.
#   apix_push.py 가 ~/.apix 를 읽도록 쓰인 이유가 이것이다 — 위치를 바꾸지 말 것.
$confDir = Join-Path $HOME '.apix'
New-Item -ItemType Directory -Force -Path $confDir | Out-Null

# [🔴 인코딩] 토큰 파일에 BOM 이 섞이면 Bearer 헤더 앞에 보이지 않는 3바이트가 붙어
#   서버가 401 을 돌려준다. 증상은 '토큰이 틀렸다'로만 보인다. BOM 없는 UTF-8 고정.
$utf8NoBom = New-Object System.Text.UTF8Encoding($false)
[IO.File]::WriteAllText((Join-Path $confDir 'token'), $Token.Trim(), $utf8NoBom)
[IO.File]::WriteAllText((Join-Path $confDir 'url'), $Url.Trim(), $utf8NoBom)
Say "설정 저장: $confDir" 'OK'

# ── 3. 푸시 스크립트 배치 ───────────────────────────────────────────────────
# [제약] apix_push.py 는 같은 폴더의 apix_sources.py 를 import 한다(전송/수집 분리).
#   한쪽만 받으면 하트비트는 가고 작업 데이터만 조용히 0 건이 된다.
$appDir = Join-Path $env:LOCALAPPDATA 'apix-node'
New-Item -ItemType Directory -Force -Path $appDir | Out-Null
foreach ($f in @('apix_push.py', 'apix_sources.py')) {
    $dest = Join-Path $appDir $f
    Invoke-WebRequest -Uri "$RepoRaw/scripts/$f" -OutFile $dest -UseBasicParsing
    Say "내려받음: $f"
}

# ── 4. 즉시 1회 전송 — 실증 ─────────────────────────────────────────────────
# [WHY 등록 전에 먼저 쏘나] 예약 작업만 걸고 끝내면 '등록됐다'는 착각만 남는다.
#   토큰 오타·방화벽·DNS 는 전부 첫 전송에서 드러난다. 여기서 실패하면 중단한다.
Say '첫 전송 시도...'
$out = & $py (Join-Path $appDir 'apix_push.py') 2>&1
$out | ForEach-Object { Write-Host "       $_" -ForegroundColor DarkGray }
if ("$out" -notmatch 'heartbeat ok') {
    throw "첫 전송 실패. 위 출력을 확인하라 (no_token=토큰 미저장, http_401=토큰 불일치, http_301=주소 문제)."
}
Say '서버가 하트비트를 받았다' 'OK'

# ── 5. 예약 작업 등록 ───────────────────────────────────────────────────────
# [WHY 서비스가 아니라 예약 작업인가] 5분에 한 번 수 초 도는 일에 상주 프로세스는 과하다.
#   예약 작업은 실패해도 다음 주기에 알아서 재시도하고, 로그인 세션과 무관하게 돈다.
$taskName = 'APIX Node Push'
$action = New-ScheduledTaskAction -Execute $py `
    -Argument "`"$(Join-Path $appDir 'apix_push.py')`"" -WorkingDirectory $appDir
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) `
    -RepetitionInterval (New-TimeSpan -Minutes $IntervalMinutes)
# [제약] -Hidden 이 없으면 5분마다 콘솔 창이 번쩍인다(이 프로젝트가 반복해서 밟은 함정).
$settings = New-ScheduledTaskSettingsSet -Hidden -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries -StartWhenAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 10)
Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger `
    -Settings $settings -Force | Out-Null
Say "예약 작업 등록: '$taskName' ($IntervalMinutes 분 주기)" 'OK'

# ── 6. (선택) 관리 PC 공개키 등록 ───────────────────────────────────────────
if ($AdminKey) {
    if ($AdminKey -notmatch '^(ssh-ed25519|ssh-rsa|ecdsa-)') {
        throw '공개키 형식이 아니다. ssh-ed25519 로 시작하는 한 줄을 그대로 넣어라.'
    }
    # [🔴 Windows sshd 함정] 관리자 그룹 계정으로 로그인하면 sshd 는 사용자 홈의
    #   authorized_keys 를 **무시하고** ProgramData\ssh\administrators_authorized_keys
    #   만 본다. 홈에만 넣고 "키를 넣었는데 왜 안 되지"로 오래 헤매는 전형적 함정이다.
    $isAdmin = ([Security.Principal.WindowsPrincipal] `
        [Security.Principal.WindowsIdentity]::GetCurrent()
    ).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)

    if ($isAdmin) {
        $keyFile = Join-Path $env:ProgramData 'ssh\administrators_authorized_keys'
    } else {
        $sshDir = Join-Path $HOME '.ssh'
        New-Item -ItemType Directory -Force -Path $sshDir | Out-Null
        $keyFile = Join-Path $sshDir 'authorized_keys'
    }

    $existing = if (Test-Path $keyFile) { [IO.File]::ReadAllText($keyFile) } else { '' }
    # 키 본문(3필드 중 2번째)으로 중복을 판정한다 — 주석(별칭)은 PC마다 달라 키가 아니다.
    $keyBody = ($AdminKey.Trim() -split '\s+')[1]
    if ($existing -match [regex]::Escape($keyBody)) {
        Say '공개키가 이미 등록돼 있다' 'OK'
    } else {
        # [🔴 BOM 금지] authorized_keys 에 BOM 이 붙으면 sshd 가 첫 줄을 통째로 못 읽는다.
        $sep = if ($existing -and -not $existing.EndsWith("`n")) { "`n" } else { '' }
        [IO.File]::WriteAllText($keyFile, $existing + $sep + $AdminKey.Trim() + "`n", $utf8NoBom)
        Say "공개키 등록: $keyFile" 'OK'
    }

    if ($isAdmin) {
        # [불변식] administrators_authorized_keys 는 Administrators+SYSTEM 외에 권한이
        #   있으면 sshd 가 파일을 **조용히 무시한다**. 상속을 끊고 두 주체만 남긴다.
        icacls $keyFile /inheritance:r /grant 'Administrators:F' /grant 'SYSTEM:F' | Out-Null
        Say '키 파일 ACL 잠금 완료' 'OK'
    }

    $svc = Get-Service sshd -ErrorAction SilentlyContinue
    if (-not $svc) {
        Say 'sshd 가 설치돼 있지 않다 — 하트비트는 정상이나 원격 접속은 불가' 'WARN'
    } elseif ($svc.Status -ne 'Running') {
        Say "sshd 가 멈춰 있다(상태: $($svc.Status)) — 시작하려면: Start-Service sshd" 'WARN'
    } else {
        Say 'sshd 실행 중' 'OK'
    }
}

Write-Host ''
Say '완료. 관리 PC 의 상태판에서 이 노드가 보이면 성공이다.' 'OK'
