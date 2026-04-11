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
    // outDir 기본값(./dist) 유지 → .ai_monitor/vibe-view/dist/ 로 출력.
    // spec/workflow/pyproject/build_verify가 전부 이 경로를 참조하므로 기본값 유지 필수.
    // [2026-04-09] outDir: '../dist' 로 변경했다가 CI 파이프라인과 불일치로 롤백.
    // [v3.7.62] 1MB 단일 번들 → 청크 분할로 초기 로드 속도 개선
    // Monaco Editor(~800kB)를 별도 청크로 분리해 첫 화면 렌더링을 앞당김
    rollupOptions: {
      output: {
        manualChunks: {
          // React 코어 — 가장 먼저 로드되어야 하는 필수 런타임
          'vendor-react': ['react', 'react-dom'],
          // Monaco Editor — 무거운 에디터, 지연 로드 허용
          'vendor-monaco': ['@monaco-editor/react', 'monaco-editor'],
          // 아이콘 라이브러리
          'vendor-icons': ['lucide-react'],
        },
      },
    },
    // 청크 경고 임계값 상향 (Monaco 자체가 크므로 경고 노이즈 제거)
    chunkSizeWarningLimit: 1000,
  },
})
