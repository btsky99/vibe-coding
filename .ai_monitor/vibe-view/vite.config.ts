import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    // 개발 모드에서 /api/* 요청을 메인 Python 서버(9000)로 프록시
    proxy: {
      // PTY 요청 → Node PTY 서버(9001)로 직접 프록시
      // (개발 모드에서 Python 서버 프록시를 거치지 않고 직접 통신)
      '/api/pty': {
        target: 'http://127.0.0.1:9001',
        changeOrigin: true,
      },
      // 나머지 API → Python 메인 서버(9000)
      '/api': {
        target: 'http://127.0.0.1:9000',
        changeOrigin: true,
      },
      '/stream': {
        target: 'http://127.0.0.1:9000',
        changeOrigin: true,
      },
    },
  },
  build: {
    // outDir 기본값(./dist) 유지. spec/workflow/pyproject가 이 경로 참조.
    // [2026-04-13] 오피스/클래식이 같은 dist/ 공유 — 빌드 시 기존 번들 삭제하면
    // 다른 윈도우의 lazy import가 404로 크래시. 기존 파일 보존.
    emptyOutDir: false,
    // [v3.7.62] 1MB 단일 번들 → 청크 분할로 초기 로드 속도 개선
    // Monaco Editor(~800kB)를 별도 청크로 분리해 첫 화면 렌더링을 앞당김
    // [Vite 8 마이그레이션 2026-07-16] Rolldown은 객체형 manualChunks 미지원 →
    // codeSplitting.groups로 전환(advancedChunks는 8.1에서 deprecated). 정규식 끝의 [\\/]가 필수 — /react/만 쓰면
    // react-icons/react-markdown까지 vendor-react로 빨려들어감. 그룹은 선착순 매칭.
    rollupOptions: {
      output: {
        codeSplitting: {
          groups: [
            // Monaco Editor — 무거운 에디터, 지연 로드 허용
            { name: 'vendor-monaco', test: /node_modules[\\/](monaco-editor|@monaco-editor)[\\/]/ },
            // React 코어 — 가장 먼저 로드되어야 하는 필수 런타임
            { name: 'vendor-react', test: /node_modules[\\/](react|react-dom)[\\/]/ },
            // 아이콘 라이브러리
            { name: 'vendor-icons', test: /node_modules[\\/]lucide-react[\\/]/ },
          ],
        },
      },
    },
    // 청크 경고 임계값 상향 (Monaco 자체가 크므로 경고 노이즈 제거)
    chunkSizeWarningLimit: 1000,
  },
})
