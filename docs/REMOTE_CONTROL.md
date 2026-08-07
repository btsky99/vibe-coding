<!--
FILE: docs/REMOTE_CONTROL.md
DESCRIPTION: 무료 원격제어(RustDesk + Tailscale 셀프호스트) 구축 구조와 기기별 운영 절차.
             상용 원격제어(팀뷰어/애니데스크) 대체. 스크립트 실체는 scripts/remote/.

REVISION HISTORY:
- 2026-08-07 Claude: 최초 작성 — yjscom 실구축 결과 및 실측으로 확인된 함정 3건 반영.
-->

# 원격제어 (RustDesk + Tailscale) — 운영 가이드

---

## 요약

| 항목 | 값 |
|------|-----|
| 소프트웨어 | RustDesk 1.4.9 (오픈소스, AGPL) + rustdesk-server 1.1.16 |
| 비용 | 0원 (계정·구독·기기 수 제한 없음) |
| 전송 경로 | Tailscale(WireGuard) 위 — 공인망에 포트를 열지 않는다 |
| ID 서버 | 셀프호스트 hbbs (`100.75.28.53`), 공용 서버 미사용 |

**핵심 설계 판단**: Tailscale이 이미 WireGuard 직결이라 RustDesk의 ID 서버가 원래 해주는 일
(NAT 뚫기·중계)이 이미 해결돼 있다. 따라서 **ID 서버가 죽어도 원격제어는 계속된다** —
직접 IP 접속이 독립적으로 동작하기 때문. 서버는 편의(짧은 ID)와 확장(부모님 지원)용이다.

---

## 3계층 구조

```
계층 1  tailnet 직결 (기반, 서버 0대)
        조종할 PC의 RustDesk ID 칸에 상대 Tailscale IP를 입력 → 바로 붙는다.
        커버: 탭→개발PC / PC↔PC / 외부망→집PC
        ↑ 이것만으로 완결된다. 아래 계층이 다 죽어도 동작한다.

계층 2  셀프호스트 ID 서버 (hbbs/hbbr, 편의)
        IP 대신 9자리 ID로 접속. tailnet 안에서만 열린다.
        커버: 계층 1과 동일 범위 + 입력 편의

계층 3  tailnet 밖 (부모님/지인)
        3-A 부모님 PC → Tailscale 설치해서 계층 1로 흡수 (권장)
        3-B 지인 1회성 → RustDesk 공용 서버 기본값으로 포터블 실행
```

---

## 계층 1·2 — 내 기기 세팅

### Windows PC

```powershell
# 관리자 PowerShell
cd <저장소>\scripts\remote

# (A) 기반만 — tailnet 직결
.\Install-RustDeskClient.ps1

# (B) 셀프호스트 ID 서버까지 쓰기
.\Install-RustDeskClient.ps1 -IdServer 100.75.28.53 -Key '<공개키>'
```

끝나면 화면에 **Tailscale 주소 / RustDesk ID / 고정 비밀번호**가 출력된다.
비밀번호는 `%LOCALAPPDATA%\vibe-remote\rustdesk-password.txt` 에도 저장된다
(**저장소 바깥** — git에 절대 들어가지 않는다).

### 안드로이드 탭 / 폰

1. Tailscale 앱 설치 → 같은 계정 로그인 → **Always-on VPN 켜기**
   (안 켜면 화면 꺼질 때 tailnet이 끊겨 접속이 실패한다)
2. RustDesk 앱 설치 (Play 스토어 또는 GitHub APK)
3. 계층 1로 쓸 경우: ID 칸에 `100.75.28.53:21128` 입력 → 비밀번호 입력
4. 계층 2로 쓸 경우: 설정 > 네트워크 > ID/중계 서버에
   - ID 서버 `100.75.28.53`
   - Key `<공개키>`
   입력 후, ID 칸에 상대 PC의 9자리 ID 입력

### macOS (macmini)

RustDesk `.dmg`를 받아 설치하고, 설정 > 네트워크에 위와 동일한 ID 서버/Key를 넣는다.
스크립트는 Windows 전용이라 맥은 GUI 설정으로 처리한다.

---

## 계층 3 — 부모님 / 지인

### 3-A. 부모님 PC (반복적으로 도와줄 대상) — 권장

Tailscale을 한 번만 깔아드리면 **내 기기와 완전히 동일하게** 취급된다.
공인망에 아무것도 열지 않으므로 가장 안전하다.

1. 부모님 PC에 Tailscale 설치 → 내 계정으로 로그인 (1회, 직접 방문하거나 전화로 안내)
2. 관리자 PowerShell로 `Install-RustDeskClient.ps1` 실행
3. 이후로는 내 tailnet에 뜬 기기이므로 계층 1·2 그대로 사용

> Tailscale 무료 플랜은 개인 100대까지라 기기 수는 문제되지 않는다.

### 3-B. 지인 1회성 지원

Tailscale까지 깔라고 하기 어려운 상황용. **아무 설정도 하지 않는다.**

1. 지인에게 https://rustdesk.com/ 에서 실행 파일만 받아 **설치 없이 실행**하라고 안내
2. 화면에 뜨는 9자리 ID와 임시 비밀번호를 알려달라고 함
3. 내 RustDesk에서 **ID 서버를 잠시 기본값(공백)으로** 되돌린 뒤 접속
   (셀프호스트 서버를 보고 있으면 공용 서버의 ID를 못 찾는다)
4. 지원이 끝나면 지인은 프로그램을 닫기만 하면 된다 — 흔적이 남지 않는다

이 경로만 RustDesk 공용 서버를 경유한다. 무료이고 개인 사용에 제한이 없다.

### 3-C. hbbs를 공인망에 노출 — 하지 않았다

부모님 PC를 ID 서버로 직접 붙이려면 공유기 포트포워딩(21115~21119)과 DDNS가 필요하다.
**이 구축에서는 의도적으로 하지 않았다** — 3-A가 같은 목적을 노출 없이 달성하기 때문.
필요해지면 그때 별도로 판단할 것.

---

## 보안 경계

- **공인망에 열린 포트: 0개.** 모든 규칙의 원격 주소가 `100.64.0.0/10`(Tailscale 대역)으로 축소돼 있다.
- 인증은 **고정 비밀번호 16자** + hbbs **공개키 대조**(`-k _`) 2중.
- hbbs 개인키(`C:\ProgramData\rustdesk-server\id_ed25519`)는 SYSTEM/관리자만 읽을 수 있다.
  유출되면 제3자가 이 ID 서버를 사칭할 수 있으므로 백업 시에도 저장소·클라우드에 올리지 말 것.
- 무인 접속이 켜져 있다 = **비밀번호를 아는 사람은 화면 앞에 아무도 없어도 조작할 수 있다.**
  비밀번호를 메신저로 보내지 말 것.

### 방화벽을 좁힐 때의 함정

설치 프로그램이 만든 "모든 주소 허용" 규칙이 남아 있으면, 좁은 규칙을 **추가**해도 노출은 그대로다
(Windows 방화벽에서 허용 규칙은 OR로 합쳐진다). 반드시 기존 규칙을 `Set-NetFirewallRule`로 **수정**해야 한다.
`Restrict-FirewallToTailnet`이 이 일을 한다.

---

## 포트 지도

| 포트 | 프로토콜 | 주인 | 용도 |
|------|----------|------|------|
| 21115 | TCP | hbbs | NAT 유형 판정 |
| 21116 | TCP+UDP | hbbs | ID 등록 · 홀펀칭 |
| 21117 | TCP | hbbr | 중계 |
| 21118 | TCP | hbbs | 웹소켓 |
| 21119 | TCP | hbbr | 웹소켓 중계 |
| **21128** | TCP | RustDesk 클라이언트 | **직접 IP 접속** (기본 21118에서 비켜난 값) |

> 21118이 기본값이 아닌 이유는 아래 함정 ① 참조.

---

## 실측으로 확인된 함정 (재발 방지)

### ① 서버와 클라이언트가 같은 PC면 21118이 충돌한다

hbbs는 21118을 웹소켓으로 고정 사용하는데 RustDesk 클라이언트의 직접 IP 접속 기본 포트도 21118이다.
나중에 뜨는 쪽이 `os error 10013`으로 **즉사**한다. hbbs의 포트는 기준 포트에서 파생돼 개별 변경이
불가하므로 **클라이언트가 21128로 비켜준다**. 스크립트가 자동 처리한다.

→ 접속하는 쪽에서는 `100.75.28.53:21128` 처럼 포트를 붙여야 한다(계층 1로 붙을 때).

### ② 설정이 두 군데에 있다 — 한쪽만 고치면 무증상 실패

- 사용자 프로필: `%APPDATA%\RustDesk\config\` — **설정 화면**이 읽는다
- 서비스 프로필: `C:\Windows\ServiceProfiles\LocalService\AppData\Roaming\RustDesk\config\` —
  **실제로 원격 접속을 받아들이는 쪽**이 읽는다

사용자 프로필만 고치면 화면상으로는 반영돼 보이는데 실제 접속은 공용 서버로 나간다.
서비스 계정은 LocalSystem이 아니라 **LocalService**다 (`systemprofile` 경로는 존재하지 않는다).

또한 **서비스를 멈추고 써야 한다.** 살아 있는 서비스는 종료 시점에 자기 메모리 상태를 파일로
되쓰기 때문에, 돌아가는 중에 고치면 다음 재시작에서 조용히 덮인다.

### ③ 이 PC는 자기 자신의 tailnet 주소로 못 붙는다

`100.75.28.53:21116`으로 SYN을 보내면 RST도 방화벽 드롭 로그도 없이 그냥 타임아웃된다.
방화벽을 전면 허용해도, 평범한 `TcpListener`를 띄워 시험해도 동일 — 즉 **방화벽 규칙 문제가 아니라
"자기 자신의 비-루프백 주소로 들어오는 연결"이 이 호스트 환경에서 막혀 있다.**
(RustDesk 본체만 자체 프로그램 규칙 덕에 예외적으로 통과한다.)

→ hbbs를 겸하는 PC는 **자기 ID 서버 주소로 `127.0.0.1`을 쓴다.** 중계 주소(`relay-server`)는
원격 피어가 사용해야 하므로 tailnet IP를 유지한다. 스크립트가 자동 판별한다.

> 이 증상의 근본 원인(보안 프로그램의 WFP 필터 등)은 규명하지 않았다.
> 원격제어 동작에는 영향이 없어 추적을 중단했다 — 다른 서비스에서 같은 증상이 보이면 여기를 먼저 의심할 것.

---

## 상태 확인 / 문제 해결

```powershell
# 서버 상주 여부
Get-Process hbbs, hbbr
Get-Content C:\ProgramData\rustdesk-server\hbbs.log -Tail 20

# 클라이언트가 ID 서버에 붙었는지 (key_confirmed = true 면 등록 성공)
Select-String 'C:\Windows\ServiceProfiles\LocalService\AppData\Roaming\RustDesk\config\RustDesk.toml' -Pattern key_confirmed

# 실제 접속 로그
Get-Content 'C:\Windows\ServiceProfiles\LocalService\AppData\Roaming\RustDesk\log\server\RustDesk_rCURRENT.log' -Tail 30

# 내 RustDesk ID
& 'C:\Program Files\RustDesk\rustdesk.exe' --get-id

# 서버 제거 (키·DB는 보존)
.\Install-RustDeskServer.ps1 -Uninstall
```

`http://.../21114/api/sysinfo failed` 경고는 **무시해도 된다** — 21114는 유료판 API 서버 포트라
오픈소스 hbbs에는 존재하지 않는다.

---

## 아직 검증되지 않은 것

- **원격 피어 → hbbs 접속**: hbbs는 기동·리슨·로컬 등록까지 확인됐으나, *다른 기기에서* ID로
  접속하는 왕복은 검증하지 못했다. 구축 시점에 tailnet의 다른 기기가 전부 오프라인이었다
  (레노버 7일, 갤럭시탭 7일, 다른 PC는 SSH 미응답).
  → 탭이나 다른 PC를 켠 뒤 **한 번은 실제로 붙여봐야 한다.**
- **부모님/지인 경로(계층 3)**: 절차만 정리했고 실제 수행은 하지 않았다.
