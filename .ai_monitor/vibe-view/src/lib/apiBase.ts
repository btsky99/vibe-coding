/**
 * ------------------------------------------------------------------------
 * 📄 파일명: lib/apiBase.ts
 * 📝 설명: 서버 주소 한 줄. 지금 열려 있는 포트가 곧 그 인스턴스의 API 다.
 *
 *          [🔴 왜 constants.tsx 에서 떼어 냈나] 거기엔 react-icons 가 딸려 있어서,
 *          주소 한 줄을 쓰려는 순수 로직 모듈(voiceBus 등)까지 아이콘 트리 전체를
 *          끌고 온다. 그러면 브라우저 없이(노드에서) 그 로직을 돌려 볼 수가 없다 —
 *          실제로 '누르고 말하기'를 계측하려다 막혔다. constants.tsx 는 이 파일을
 *          그대로 다시 내보내므로 기존 import 는 하나도 바뀌지 않는다.
 *
 *          [제약] 모듈이 로드되는 순간 window.location 을 읽는다. 서버 렌더링이나
 *          테스트에서는 그 전에 location 을 만들어 둬야 한다.
 *
 * REVISION HISTORY:
 * - 2026-08-15 Claude: constants.tsx 에서 분리 — 순수 로직을 아이콘 의존에서 떼어내기
 * ------------------------------------------------------------------------
 */

// 현재 접속 포트 기반으로 API/WS 주소 자동 결정
export const API_BASE = `http://${window.location.hostname}:${window.location.port}`;
export const WS_PORT = parseInt(window.location.port) + 1;
