import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  build: {
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
