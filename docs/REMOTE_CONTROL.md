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

> **일회용 대신 고정 ID로 간다.** 매번 "화면의 9자리 숫자를 불러주세요"를 요구하는 방식은
> 정작 도움이 필요한 상대에게는 쓸 수 없다. 아래 두 경로 모두 **한 번 세팅하면 이후로는
> 상대가 아무것도 하지 않아도** 같은 주소·같은 비밀번호로 붙는다.
>
> 전용 스크립트: **`scripts/remote/Install-RustDeskForFamily.ps1`** (그 PC에서 관리자 권한 1회 실행)

### 3-A. 부모님 PC — Tailscale 방식 (권장)

공인망에 아무것도 열지 않고, 내 기기와 동일하게 취급된다.

```powershell
# 그 PC에서 관리자 PowerShell 1회
.\Install-RustDeskForFamily.ps1 -TailscaleAuthKey 'tskey-auth-xxxxx'
```

auth key는 https://login.tailscale.com/admin/settings/keys 에서 미리 발급해 간다.
**이게 없으면 그 PC에서 브라우저 로그인을 시켜야 하는데, 전화로 안내하기 가장 어려운 단계다.**

끝나면 접속 정보가 화면과 그 PC 바탕화면(`원격접속-정보.txt`)에 남는다.

#### 🔴 auth key는 반드시 태그를 붙여 발급할 것

발급 화면에서 **Tags에 `tag:family`를 지정**한다. 두 가지가 걸려 있다.

1. **키 만료** — 태그 없는 기기는 기본 180일 뒤 인증이 만료돼 tailnet에서 떨어진다.
   그러면 **다시 방문해서 로그인**해야 한다(원격으로는 복구 불가 — 이 구축의 목적이 무너진다).
   **태그된 기기는 만료되지 않는다.**
2. **역방향 차단** — 태그가 있어야 아래 ACL로 "내 기기 → 그 PC"만 허용할 수 있다.

#### 🔴 ACL — 역방향 접근 차단

tailnet은 기본이 **양방향**이다. 그대로 두면 부모님 PC에서 내 개발 PC·맥미니·폰이 전부 보인다.
그 PC가 악성코드에 감염되면 내 기기 전체가 같은 네트워크 안에 있는 셈이다.

관리 콘솔 → Access controls 에 아래를 반영한다.

```jsonc
{
  "tagOwners": {
    "tag:family": ["autogroup:admin"],
  },
  "acls": [
    // 내 기기끼리는 기존대로 자유롭게
    { "action": "accept", "src": ["autogroup:member"], "dst": ["autogroup:member:*"] },
    // 내 기기 → 가족 PC (원격지원 방향만 허용)
    { "action": "accept", "src": ["autogroup:member"], "dst": ["tag:family:*"] },
    // tag:family 를 src로 쓰는 규칙이 없다 = 그 PC에서는 내 기기 어디에도 못 간다
  ],
}
```

### 3-B. 지인 PC — 공용 서버 + 고정 ID

Tailscale까지 부탁하기 어려운 상대용. **포터블 실행이 아니라 설치**를 해야 ID가 고정된다.

```powershell
.\Install-RustDeskForFamily.ps1 -Mode public
```

이 경로만 RustDesk 공용 서버를 경유한다(무료, 개인 사용 제한 없음).
내 쪽에서 붙을 때는 **ID 서버를 잠시 기본값(공백)으로** 되돌려야 한다 —
셀프호스트 서버를 보고 있으면 공용 서버에 등록된 ID를 찾지 못한다.

> `-Mode public`에서는 방화벽을 tailnet으로 좁히지 않는다. 홀펀칭 상대의 공인 IP를
> 미리 알 수 없어 제한하면 연결 자체가 성립하지 않기 때문이다.

### 3-C. 🔴 절전 — 실패 원인 1위

원격제어가 안 되는 사고의 대부분은 소프트웨어가 아니라 **그 PC가 자고 있어서**다.
Windows 기본값은 유휴 30분 뒤 절전이고, 절전에 들어가면 tailnet에서도 사라진다.
**인터넷 너머에서는 깨울 방법이 없다** — Wake-on-LAN은 같은 랜에서만 동작한다.

스크립트가 전원 연결 시 절전/최대절전을 해제하고, 노트북은 뚜껑을 닫아도 안 자게 만든다.
화면 꺼짐은 그대로 둔다(접속에 영향 없음). 배터리 구동 중 절전까지 끄려면
`-DisableSleepOnBattery`를 주되, 노트북이면 방전에 주의한다.

### 3-D. hbbs를 공인망에 노출 — 하지 않았다

### 3-C. hbbs를 공인망에 노출 — 하지 않았다

부모님 PC를 내 ID 서버로 직접 붙이려면 공유기 포트포워딩(21115~21119)과 DDNS가 필요하다.
**이 구축에서는 의도적으로 하지 않았다** — 3-A가 같은 목적을 노출 없이 달성하기 때문.
필요해지면 그때 별도로 판단할 것.

### 3-E. IP가 바뀌면?

**아무 영향 없다.** 이 구축은 공인 IP를 쓰지 않는다(포트포워딩이 하나도 없다).
접속에 쓰는 주소는 Tailscale이 기기별로 고정 배정한 `100.x.x.x` 뿐이고, 이 값은
집·카페·테더링 어디에 있든 동일하다. LAN IP가 바뀌어도 마찬가지다.

바뀌는 유일한 경우는 **Tailscale을 로그아웃했다 다시 붙이거나 콘솔에서 기기를 삭제했다 재등록**할 때다.
그것까지 막고 싶으면 IP 대신 MagicDNS 이름(`<호스트명>.<tailnet>.ts.net`)을 쓰면 된다 —
이 이름은 IP가 바뀌어도 기기를 따라간다.

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
