/**
 * ------------------------------------------------------------------------
 * 📄 파일명: constants.ts
 * 📝 설명: 여러 컴포넌트에서 공유하는 전역 상수 및 타입 정의.
 *          API_BASE, WS_PORT, getFileIcon, OpenFile, TreeItem,
 *          Shortcut, defaultShortcuts, SLASH_COMMANDS 등을 중앙 관리합니다.
 * REVISION HISTORY:
 * - 2026-03-01 Claude: App.tsx 분리 작업 일환으로 신규 생성.
 *                      공유 상수/타입을 한 파일로 모아 순환 참조 방지.
 * ------------------------------------------------------------------------
 */

import {
  SiPython, SiJavascript, SiTypescript, SiMarkdown,
  SiGit, SiCss3, SiHtml5
} from 'react-icons/si';
import { FaWindows } from 'react-icons/fa';
import { VscJson, VscFileMedia, VscArchive, VscFile } from 'react-icons/vsc';

// 현재 접속 포트 기반으로 API/WS 주소 자동 결정
export const API_BASE = `http://${window.location.hostname}:${window.location.port}`;
export const WS_PORT = parseInt(window.location.port) + 1;

// ─── 파일 확장자별 아이콘 반환 함수 ───────────────────────────────────────
// 파일 탐색기, 플로팅 윈도우, 터미널 슬롯 등 여러 곳에서 공통 사용
export const getFileIcon = (fileName: string) => {
  const ext = fileName.split('.').pop()?.toLowerCase();
  switch (ext) {
    case 'py': return <SiPython className="w-4 h-4 text-[#3776ab] shrink-0" />;
    case 'js': case 'jsx': case 'mjs': case 'cjs': return <SiJavascript className="w-4 h-4 text-[#F7DF1E] shrink-0" />;
    case 'ts': case 'tsx': return <SiTypescript className="w-4 h-4 text-[#3178C6] shrink-0" />;
    case 'json': return <VscJson className="w-4 h-4 text-[#cbcb41] shrink-0" />;
    case 'md': return <SiMarkdown className="w-4 h-4 text-[#083fa1] shrink-0" />;
    case 'html': case 'htm': return <SiHtml5 className="w-4 h-4 text-[#E34F26] shrink-0" />;
    case 'css': case 'scss': case 'less': return <SiCss3 className="w-4 h-4 text-[#1572B6] shrink-0" />;
    case 'png': case 'jpg': case 'jpeg': case 'gif': case 'svg': case 'ico': return <VscFileMedia className="w-4 h-4 text-[#a074c4] shrink-0" />;
    case 'zip': case 'tar': case 'gz': case 'rar': case '7z': return <VscArchive className="w-4 h-4 text-[#d19a66] shrink-0" />;
    case 'bat': case 'cmd': case 'exe': return <FaWindows className="w-4 h-4 text-[#0078D4] shrink-0" />;
    case 'gitignore': return <SiGit className="w-4 h-4 text-[#F05032] shrink-0" />;
    default: return <VscFile className="w-4 h-4 text-[#cccccc] shrink-0" />;
  }
};

// ─── 플로팅 윈도우 열린 파일 상태 타입 ────────────────────────────────────
export interface OpenFile {
  id: string;
  name: string;
  path: string;
  content: string;
  isLoading: boolean;
  zIndex: number;
}

// ─── 파일 탐색기 트리 노드 타입 ────────────────────────────────────────────
export type TreeItem = { name: string; path: string; isDir: boolean };

// ─── 터미널 단축어 타입 및 기본값 ─────────────────────────────────────────
export interface Shortcut { label: string; cmd: string; }

export const defaultShortcuts: Shortcut[] = [
  { label: '마스터 호출', cmd: 'gemini --skill master' },
  { label: '🧹 화면 지우기', cmd: '/clear' },
  { label: '깃 커밋', cmd: 'git add . && git commit -m "update"' },
  { label: '깃 푸시', cmd: 'git push' },
  { label: '문서 업데이트', cmd: 'gemini "현재까지 진행 상황 문서 업데이트"' },
];

// ─── 에이전트별 슬래시 커맨드 목록 ───────────────────────────────────────
// 터미널 슬롯의 /커맨드 팝업에서 사용. 카테고리별로 분류하여 표시
interface SlashCommand { cmd: string; desc: string; category: string; }
export const SLASH_COMMANDS: Record<string, SlashCommand[]> = {
  claude: [
    { cmd: '/model',       desc: '모델 변경 (opus / sonnet / haiku)',    category: '설정' },
    { cmd: '/clear',       desc: '대화 기록 초기화',                      category: '설정' },
    { cmd: '/compact',     desc: '대화 압축 — 컨텍스트 절약',             category: '설정' },
    { cmd: '/memory',      desc: '메모리(CLAUDE.md) 파일 편집',           category: '설정' },
    { cmd: '/vim',         desc: 'Vim 키 바인딩 모드 토글',               category: '설정' },
    { cmd: '/help',        desc: '전체 도움말 보기',                       category: '도움말' },
    { cmd: '/doctor',      desc: '개발 환경 진단',                         category: '도움말' },
    { cmd: '/status',      desc: '현재 상태 및 컨텍스트 확인',            category: '도움말' },
    { cmd: '/bug',         desc: '버그 리포트 Anthropic에 전송',           category: '도움말' },
    { cmd: '/review',      desc: '현재 코드 리뷰 요청',                   category: '작업' },
    { cmd: '/commit',      desc: 'Git 커밋 메시지 자동 생성',             category: '작업' },
    { cmd: '/init',        desc: 'CLAUDE.md 프로젝트 가이드 생성',        category: '작업' },
    { cmd: '/pr_comments', desc: 'GitHub PR 댓글 가져오기',               category: '작업' },
    { cmd: '/terminal',    desc: '터미널 명령 실행 모드',                  category: '작업' },
  ],
  gemini: [
    { cmd: '/help',        desc: '전체 도움말 보기',                       category: '도움말' },
    { cmd: '/clear',       desc: '대화 초기화',                            category: '설정' },
    { cmd: '/chat',        desc: '대화형 채팅 모드 전환',                  category: '설정' },
    { cmd: '/tools',       desc: '사용 가능한 툴 목록 보기',              category: '도움말' },
  ],
};
