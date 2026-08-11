<#
FILE: scripts/remote/Fix-CentralNode.ps1
DESCRIPTION: 이미 붙어 있는 중앙 대화 노드를 '진단하고 고친다'. 대상 PC 에서 실행한다.
             Setup-CentralNode.ps1 이 '처음 붙이는' 도구라면, 이쪽은 '붙였는데 조용한'
             노드를 가르는 도구다 — config.json 손상 / central_db 유실 / 주입 게이트
             미설정 / 터널 미개통을 각각 구분해 보여주고, 고칠 수 있는 것은 고친다.

             사용 (대상 PC 의 PowerShell — 관리자 권한 불필요):
               .\Fix-CentralNode.ps1                 # 진단만
               .\Fix-CentralNode.ps1 -Apply          # 주입 게이트까지 세운다

             [🔴 왜 손으로 config.json 을 고치지 말아야 하는가 — 2026-08-11 실사고]
             한 줄 스니펫으로 고치라고 안내했다가 노드 하나가 통째로 버스에서 떨어졌다.
             원인이 될 수 있는 함정이 이 파일 하나에 셋이나 모여 있다:
               ① Set-Content -Encoding utf8 → PS 5.1 은 **BOM 을 붙인다**. 앱의
                  _read_config 는 encoding='utf-8' 로 읽어 BOM 에서 파싱이 깨지고,
                  그 예외를 '설정 없음'으로 삼킨다(앱이 죽지 않게 하려는 의도적 설계).
                  그 순간 central_db 가 사라진 것과 같아지고, 이어서 get_node_id 가
                  **새 uuid 를 발급해 파일을 덮어써** 노드 정체성까지 갈린다.
               ② Add-Member 의 첫 위치 인자는 -NotePropertyName 이 아니라 -MemberType 이다.
                  이름을 그냥 붙여 쓰면 조용히 실패하고 키가 안 들어간다.
               ③ ConvertTo-Json 기본 -Depth 2 → central_db.tunnel 이 3단계라 문자열로 뭉개진다.
             셋 다 '에러 없이 조용히 망가지는' 종류라 눈으로는 구분되지 않는다.

             [WHY 읽기와 쓰기를 둘 다 BOM 을 벗겨 다루는가] 이미 BOM 이 붙어버린 파일도
             되살려야 한다. 읽을 때 벗기지 않으면 이 스크립트마저 '설정 없음'으로 오판해
             멀쩡한 central_db 를 빈 값으로 덮어쓸 수 있다 — 진단 도구가 2차 사고를 낸다.

REVISION HISTORY:
- 2026-08-11 Claude: 최초 작성 — na2js 가 '앱은 살아 있는데 커서가 안 움직이는' 상태가
                     됐는데 원인을 원격에서 가를 수단이 없었다.
#>

[CmdletBinding()]
param(
    # 붙이면 고친다. 없으면 진단만 하고 파일을 건드리지 않는다.
    [switch]$Apply,

    # 이 노드의 CLI 에 말을 꽂을 수 있는 발신 노드 번호. 빈 배열이면 게이트를 끈다.
    [int[]]$AllowInjectFrom = @(1),

    # config.json 이 있는 폴더. 비우면 설치본 → 개발본 순서로 찾는다.
    [string]$DataDir = ''
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Say([string]$m, [string]$lv = 'INFO') {
    $c = switch ($lv) { 'OK' { 'Green' } 'WARN' { 'Yellow' } 'FAIL' { 'Red' } default { 'Gray' } }
    Write-Host ("[{0,-4}] {1}" -f $lv, $m) -ForegroundColor $c
}

# ── 1. config.json 찾기 ─────────────────────────────────────────────────────
# [제약] 설치본과 개발본은 서로 다른 config.json 을 본다(pg_base.DATA_DIR 분기).
#   둘 다 있는 PC 에서 엉뚱한 쪽을 고치면 '고쳤는데 그대로'가 된다 — 찾은 경로를 반드시 찍는다.
$candidates = @()
if ($DataDir) { $candidates += (Join-Path $DataDir 'config.json') }
$candidates += (Join-Path $env:APPDATA 'VibeCoding\config.json')
$candidates += (Join-Path $PSScriptRoot '..\..\.ai_monitor\data\config.json')

$confPath = $null
foreach ($p in $candidates) {
    if (Test-Path $p) { $confPath = (Resolve-Path $p).Path; break }
}
if (-not $confPath) {
    Say "config.json 을 못 찾았다. 찾아본 곳: $($candidates -join ' | ')" 'FAIL'
    exit 1
}
Say "설정 파일: $confPath" 'OK'

# ── 2. BOM 검사 ─────────────────────────────────────────────────────────────
$bytes = [IO.File]::ReadAllBytes($confPath)
$hasBom = ($bytes.Length -ge 3 -and $bytes[0] -eq 0xEF -and $bytes[1] -eq 0xBB -and $bytes[2] -eq 0xBF)
if ($hasBom) {
    Say 'BOM 이 붙어 있다 — 앱은 이 파일을 읽지 못하고 설정 전체를 무시한다(범인 유력)' 'FAIL'
} else {
    Say 'BOM 없음' 'OK'
}

# ── 3. 파싱 ─────────────────────────────────────────────────────────────────
$raw = [Text.Encoding]::UTF8.GetString($bytes).TrimStart([char]0xFEFF)
try {
    $conf = if ($raw.Trim()) { $raw | ConvertFrom-Json } else { [pscustomobject]@{} }
} catch {
    Say "JSON 파싱 실패 — 파일이 손상됐다: $($_.Exception.Message)" 'FAIL'
    Say '복구: Setup-CentralNode.ps1 -Password <hive DB 비밀번호> 를 다시 돌려라' 'WARN'
    exit 1
}

function Has([string]$name) {
    return ($conf.PSObject.Properties.Name -contains $name)
}

# ── 4. 키별 진단 ────────────────────────────────────────────────────────────
$fatal = $false

if (Has 'node_id') { Say "node_id: $($conf.node_id)" 'OK' }
else { Say 'node_id 없음 — 앱이 다음 부팅에 새로 발급한다(=중앙에서 다른 노드로 보인다)' 'WARN' }

if (Has 'node_seq') { Say "node_seq: $($conf.node_seq)" 'OK' }
else { Say 'node_seq 없음 — 호스트명 매핑으로 자동 배정된다' 'WARN' }

if (Has 'central_db') {
    $cdb = $conf.central_db
    $port = if ($cdb.PSObject.Properties.Name -contains 'port') { $cdb.port } else { '?' }
    Say "central_db: $($cdb.host):$port/$($cdb.dbname)" 'OK'

    # [🔴 tunnel 이 문자열이면 -Depth 2 사고의 흔적이다] 이 경우 앱은 터널을 못 열고,
    #   그러면 host=127.0.0.1 로 붙으려다 조용히 실패해 '수신 0' 이 된다.
    if ($cdb.PSObject.Properties.Name -contains 'tunnel') {
        if ($cdb.tunnel -is [string]) {
            Say "central_db.tunnel 이 문자열로 뭉개졌다: $($cdb.tunnel)" 'FAIL'
            $fatal = $true
        } else {
            Say "  tunnel: $($cdb.tunnel.ssh_user)@$($cdb.tunnel.ssh_host) → $($cdb.tunnel.remote_port)" 'OK'

            # 터널이 실제로 열려 있는가. [WHY 여기서 재는가] 설정이 맞아도 재시작 뒤
            #   ssh 가 안 올라오면 증상이 똑같다 — 설정 문제와 구분되어야 한다.
            $listening = @(Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue)
            if ($listening.Count -gt 0) { Say "  터널 입구 127.0.0.1:$port LISTEN 중" 'OK' }
            else { Say "  터널 입구 $port 가 안 열려 있다 — 앱이 ssh 터널을 못 세웠다" 'FAIL'; $fatal = $true }
        }
    } else {
        Say '  tunnel 없음 — 서버에 직접 붙는 설정이다(맞다면 정상)' 'WARN'
    }
} else {
    Say 'central_db 없음 — 이 노드는 중앙 대화에 아예 연결되지 않는다' 'FAIL'
    Say '복구: Setup-CentralNode.ps1 -Password <hive DB 비밀번호> 를 다시 돌려라' 'WARN'
    $fatal = $true
}

$injectOn = ($AllowInjectFrom -ne $null) -and ($AllowInjectFrom.Count -gt 0)
if (Has 'central_remote_inject') {
    $ri = $conf.central_remote_inject
    $nodes = @($ri.allow_nodes) -join ', '
    if ($ri.enabled -and $nodes) { Say "원격 주입 게이트: ON (허용 $nodes)" 'OK' }
    else { Say "원격 주입 게이트: OFF — 메시지를 화면에만 띄우고 CLI 에는 안 꽂는다" 'WARN' }
} else {
    Say '원격 주입 게이트 미설정 — 기본값은 꺼짐이다(=받아도 CLI 에 안 꽂힌다)' 'WARN'
}

# ── 5. 적용 ─────────────────────────────────────────────────────────────────
if (-not $Apply) {
    Write-Host ''
    Say '진단만 했다. 고치려면 -Apply 를 붙여 다시 실행하라' 'WARN'
    exit $(if ($fatal) { 1 } else { 0 })
}

$inject = [ordered]@{ enabled = $injectOn; allow_nodes = @($AllowInjectFrom) }
$conf | Add-Member -NotePropertyName 'central_remote_inject' -NotePropertyValue $inject -Force

# [🔴 BOM 없이 쓴다] 위 함정 ①. UTF8Encoding($false) 만이 BOM 을 안 붙인다 —
#   Out-File/Set-Content 의 -Encoding utf8 은 PS 5.1 에서 BOM 을 붙인다.
$utf8NoBom = [Text.UTF8Encoding]::new($false)
$json = $conf | ConvertTo-Json -Depth 12        # 함정 ③ — tunnel 이 3단계다
[IO.File]::WriteAllText($confPath, $json, $utf8NoBom)

Say $(if ($injectOn) { "주입 게이트 ON 기록 (허용: $($AllowInjectFrom -join ', '))" }
      else { '주입 게이트 OFF 기록' }) 'OK'
Write-Host ''
Say '앱을 재시작해야 반영된다. 재시작 뒤 T1 슬롯에 클로드를 띄워 둬라' 'WARN'
exit $(if ($fatal) { 1 } else { 0 })
