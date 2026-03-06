# ⚛️ React & Tailwind Best Practices (v19+)

1. **컴포넌트 설계**: Server/Client 컴포넌트 분리 준수. 불필요한 `useEffect` 최소화.
2. **성능 최적화**: `useMemo`, `useCallback`은 성능 병목 확인 시에만 적용.
3. **TailwindCSS**: `cn()` 유틸리티를 통한 조건부 클래스 관리. 디자인 일관성을 위해 매직 넘버 지양.
4. **상태 관리**: 로컬 상태 우선. 전역 상태(Zustand/Redux)는 최소한으로 유지.
5. **Vite**: 빌드 최적화 및 빠른 HMR 유지.
