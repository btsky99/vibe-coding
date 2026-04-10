# 🏢 메타버스 오피스 UI 완전 재설계 — 아이소메트릭 픽셀 로봇 오피스

**작성일**: 2026-04-10  
**목표**: Phaser.js + LimeZu 에셋 완전 제거 → React + CSS 아이소메트릭으로 재설계  
**컨셉**: CEO(사람) + LLM들(로봇), 방 분리형 레이아웃, 픽셀 스타일 캐릭터

---

## 확정 스펙

- **뷰**: 아이소메트릭 (CSS transform: rotateX + rotateZ)
- **캐릭터**: SVG 인라인 (CEO=사람, LLM=로봇)
- **레이아웃**: CEO실 / 부서실 / 회의실 방 분리형
- **제거**: OfficeCanvas.tsx (Phaser), OfficeWorld.tsx (레거시), LimeZu PNG 에셋
- **재사용**: officeApi.ts, useOfficeState.ts, OfficeChatPanel.tsx

---

## 태스크 목록

[ ] Task 1: isometric.css 생성 — 아이소메트릭 변환 기반 스타일 시스템
    파일: .ai_monitor/vibe-view/src/components/office/isometric.css
    방법:
      - CSS 변수로 타일 크기, 높이 계수 정의
      - .iso-scene: perspective + transform-style: preserve-3d
      - .iso-floor: rotateX(60deg) 바닥 타일
      - .iso-wall-left / .iso-wall-right: 좌우 벽면
      - .iso-object: 가구/캐릭터 기본 위치 클래스
      - @keyframes: led-blink(LED 깜빡), bob(아이들), lean-forward(타이핑)
    검증: 브라우저에서 css import 후 클래스 적용 시 아이소메트릭 변환 확인

[ ] Task 2: IsoFurniture.tsx 생성 — 책상/모니터/파티션/소파 SVG 컴포넌트
    파일: .ai_monitor/vibe-view/src/components/office/IsoFurniture.tsx
    방법:
      - IsoDesk: L자형 책상 (아이소메트릭 SVG, 나무 갈색)
      - IsoMonitor: 모니터 스탠드 + 화면 (코딩 화면)
      - IsoPartition: 반투명 유리 파티션 (반높이 벽)
      - IsoSofa: CEO실 전용 소파 (파란색)
      - IsoTable: 회의실 원형 테이블
      - IsoFloorTile: 체크무늬 바닥 타일 (밝음/어두움 교차)
    검증: OfficeApp에서 import 후 렌더링 오류 없음

[ ] Task 3: IsoAgent.tsx 생성 — 로봇/사람 캐릭터 SVG 컴포넌트
    파일: .ai_monitor/vibe-view/src/components/office/IsoAgent.tsx
    방법:
      - CeoCharacter: 원형 머리 + 머리카락 + 정장 몸통 (SVG)
      - RobotCharacter: 공통 로봇 기반 컴포넌트
        - ClaudeRobot: 네모머리 + 안테나, 보라(#a78bfa) LED 눈
        - GeminiRobot: 다이아몬드머리, 에메랄드(#34d399) LED 눈
        - CodexRobot: 실린더머리, 시안(#22d3ee) LED 눈
        - DefaultRobot: 회색 기본 로봇
      - props: status('idle'|'working'|'meeting'|'error'), agentType, name
      - LED 상태: working=초록, error=빨간, idle=파란, meeting=주황
    검증: 각 에이전트 타입별 캐릭터가 올바른 색상/모양으로 렌더링

[ ] Task 4: IsoRoom.tsx 생성 — 아이소메트릭 방 컴포넌트
    파일: .ai_monitor/vibe-view/src/components/office/IsoRoom.tsx
    방법:
      - IsoRoom props: width, depth, wallColor, label, children
      - 바닥: IsoFloorTile 격자 배치
      - 좌벽 / 우벽: CSS transform으로 아이소메트릭 벽면 2개
      - 방 레이블: 벽 상단 텍스트
      - RoomCeo: CEO실 (소파 + 책상 + 모니터 고정)
      - RoomDept: 부서실 (에이전트 수에 따라 책상 동적 배치)
      - RoomMeeting: 회의실 (원형 테이블 + 의자 고정)
    검증: 3가지 방 타입 아이소메트릭 렌더링 확인

[ ] Task 5: IsometricOffice.tsx 생성 — 메인 오피스 컨테이너
    파일: .ai_monitor/vibe-view/src/components/office/IsometricOffice.tsx
    방법:
      - useOfficeState 훅 연결 (기존 재사용)
      - 전체 레이아웃: CEO실(좌상) + 부서실(중앙) + 회의실(우하)
      - 에이전트 위치: 상태별 방 배정 (meeting → 회의실, else → 부서실)
      - CEO는 항상 CEO실 고정
      - 드래그 패닝 + 휠 줌 (0.5x ~ 2x)
      - 에이전트 클릭 → 이름/상태/현재 태스크 툴팁
    검증: 에이전트 목록이 오피스에 올바르게 배치

[ ] Task 6: OfficeApp.tsx 교체 — OfficeCanvas → IsometricOffice
    파일: .ai_monitor/vibe-view/src/components/office/OfficeApp.tsx
    방법:
      - import OfficeCanvas 제거
      - import IsometricOffice 추가
      - JSX에서 <OfficeCanvas .../> → <IsometricOffice .../> 교체
    검증: 오피스 탭 전환 시 IsometricOffice 렌더링

[ ] Task 7: Phaser 제거 + 에셋 정리
    파일: package.json, OfficeCanvas.tsx, OfficeWorld.tsx, public/assets/limezu/
    방법:
      - OfficeCanvas.tsx 삭제
      - OfficeWorld.tsx 삭제
      - package.json에서 "phaser" 제거
      - cd .ai_monitor/vibe-view && npm uninstall phaser
      - public/assets/limezu/ 디렉토리 삭제
    검증: npm run build 성공, phaser import 오류 없음

[ ] Task 8: 빌드 검증 + 릴리즈
    방법:
      - cd .ai_monitor/vibe-view && npm run build
      - 오류 없으면 /vibe-release 실행
    검증: dist/ 생성 성공, 버전 증가 + 커밋 + push 완료

---

## 의존성 순서

1. Task 1 먼저
2. Task 2 + Task 3 병렬 (둘 다 Task 1 필요)
3. Task 4 (Task 2, 3 완료 후)
4. Task 5 (Task 4 완료 후)
5. Task 6 (Task 5 완료 후)
6. Task 7 (Task 6 완료 후)
7. Task 8 (Task 7 완료 후)
