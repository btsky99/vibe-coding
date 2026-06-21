# fix-claude-update.ps1
# 용도: 네이티브 설치 Claude Code 가 새 버전을 versions\ 에 받아두고도
#       런처(.local\bin\claude.exe) 교체를 못 한 상태를 한 줄로 마무리한다.
#
# [근본 원인] 바이브 코딩 앱(PyWebView + PTY 서버)이 claude.exe 를 자식
#   프로세스로 항상 띄워둠 → 표준 업데이터의 "덮어쓰기" 방식이 파일 잠금에
#   막혀 매번 실패. 새 버전은 versions\ 에만 받고 런처 스왑만 실패하면서도
#   .last-update-result.json 에는 "success" 로 기록 → 계속 옛 버전 실행.
#
# [핵심 트릭] 윈도우/NTFS 는 실행 중 .exe 의 *삭제/덮어쓰기*는 막지만
#   *rename(이동)*은 허용한다. 그래서 앱을 닫지 않고도 런처를 갈아끼울 수 있다:
#     1) claude.exe → claude.exe.old 로 rename (실행 중에도 가능)
#     2) versions\<최신> → claude.exe 로 복사
#     3) 다음 실행부터 새 버전. .old 는 다음 재시작 후 삭제됨.
#
# 실행: 일반 PowerShell 에서 그냥 실행하면 됨 (바이브 코딩 닫을 필요 없음).
#   powershell -ExecutionPolicy Bypass -File D:\vibe-coding\fix-claude-update.ps1

$ErrorActionPreference = 'Stop'
$launcher    = "$env:USERPROFILE\.local\bin\claude.exe"
$versionsDir = "$env:USERPROFILE\.local\share\claude\versions"

# versions 폴더에서 가장 높은 버전 선택 (이름이 곧 SemVer)
$latest = Get-ChildItem $versionsDir -File |
    Sort-Object { [version]$_.Name } -Descending |
    Select-Object -First 1
if (-not $latest) { throw "versions 폴더에 설치본이 없음: $versionsDir" }

# 이미 최신이면 스킵 (해시 비교)
if (Test-Path $launcher) {
    $curHash = (Get-FileHash $launcher -Algorithm SHA256).Hash
    $newHash = (Get-FileHash $latest.FullName -Algorithm SHA256).Hash
    if ($curHash -eq $newHash) {
        Write-Host "이미 최신($($latest.Name)) — 교체 불필요"
        & $launcher --version
        return
    }
    # rename 트릭: 실행 중 exe 는 삭제 불가하지만 이동은 가능
    $stamp = (Get-Item $launcher).LastWriteTime.ToString('yyyyMMddHHmmss')
    Move-Item $launcher "$launcher.$stamp.old" -Force
}

Copy-Item $latest.FullName $launcher -Force
Write-Host "런처 교체 완료 -> $($latest.Name)"

# 남은 .old 파일 중 잠기지 않은 것 정리 (이전 회차 잔재)
$binDir = Split-Path $launcher
Get-ChildItem -Path $binDir -Filter 'claude.exe.*.old' -ErrorAction SilentlyContinue | ForEach-Object {
    try { Remove-Item $_.FullName -Force -ErrorAction Stop } catch { }
}

& $launcher --version
