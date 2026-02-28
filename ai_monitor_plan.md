# 🗺️ Vibe Coding UI Restoration Plan (VS Code Style)

## [x] Task 1: 프론트엔드 이름 변경(Rename) 공통 로직 구현
- **파일**: `.ai_monitor/vibe-view/src/App.tsx`
- **방법**: `renameFile(src, dest)` 함수를 추가하여 `/api/file-rename` 호출 로직 구현.
- **검증**: 콘솔에 에러 없이 서버와 통신하는지 확인.
- **예상 위험**: 파일 경로에 특수문자 포함 시 인코딩 문제 발생 가능.

## [x] Task 2: 트리 뷰(FileTreeNode) 호버 액션 및 인라인 편집 구현
- **파일**: `.ai_monitor/vibe-view/src/App.tsx`
- **방법**: `FileTreeNode`에 `isEditing`, `editName` 상태 추가. 호버 시 우측에 (새 파일, 새 폴더, 경로 복사, 이름 변경, 삭제) 버튼 그룹 추가.
- **검증**: 트리 뷰 호버 시 버튼 노출 및 이름 변경 시 인라인 `input` 박스로 전환 확인.

## [x] Task 3: 플랫 뷰(Flat View) 호버 액션 및 인라인 편집 구현
- **파일**: `.ai_monitor/vibe-view/src/App.tsx`
- **방법**: 기존 플랫 뷰 렌더링 루프에 인라인 편집 상태 및 호버 버튼 그룹(경로 복사, 이름 변경, 삭제) 적용.
- **검증**: 플랫 뷰 호버 시 버튼 노출 및 인라인 편집 동작 확인.

## [x] Task 4: 컨텍스트 메뉴(Context Menu) 항목 확장
- **파일**: `.ai_monitor/vibe-view/src/App.tsx`
- **방법**: 우클릭 메뉴에 "경로 복사" 및 "이름 변경" 항목 추가.
- **검증**: 우클릭 시 메뉴 항목 노출 및 기능 동작 확인.

## [x] Task 5: 전체 시스템 빌드 및 최종 검증
- **파일**: N/A
- **방법**: `npm run build` 수행 후 프로그램 실행하여 UI 최종 확인.
- **검증**: 모든 버튼이 VS Code와 유사하게 동작하는지 확인.
