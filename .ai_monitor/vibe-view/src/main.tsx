/**
 * ------------------------------------------------------------------------
 * 📄 파일명: main.tsx
 * 📝 설명: React 앱 진입점. ErrorBoundary로 전체 트리를 감싸
 *          컴포넌트 예외 발생 시 블랙스크린 대신 복구 UI를 표시합니다.
 * REVISION HISTORY:
 * - 2026-03-15 Claude: ErrorBoundary 추가 — 블랙스크린 버그 근본 수정.
 *                      에러 바운더리 없이 컴포넌트 예외 발생 시 React가 전체 트리를
 *                      언마운트해 #root가 비어 검은 화면이 되던 문제 해결.
 * ------------------------------------------------------------------------
 */
import { Component, StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.tsx'

interface EBState { hasError: boolean; error: Error | null }

/** 전역 에러 바운더리 — 예외 발생 시 블랙스크린 대신 복구 화면 표시 */
class ErrorBoundary extends Component<{ children: React.ReactNode }, EBState> {
  constructor(props: { children: React.ReactNode }) {
    super(props)
    this.state = { hasError: false, error: null }
  }

  static getDerivedStateFromError(error: Error): EBState {
    return { hasError: true, error }
  }

  componentDidCatch(error: Error, info: React.ErrorInfo) {
    // 에러 정보를 콘솔에 남겨 디버깅 가능하게 함
    console.error('[ErrorBoundary] 컴포넌트 예외 발생:', error, info.componentStack)
  }

  render() {
    if (this.state.hasError) {
      return (
        <div style={{
          background: '#0f0f1a', color: '#fff', height: '100vh',
          display: 'flex', flexDirection: 'column',
          alignItems: 'center', justifyContent: 'center',
          fontFamily: "'Segoe UI', sans-serif", gap: 16
        }}>
          <div style={{ fontSize: 48 }}>⚠️</div>
          <div style={{ fontSize: 20, fontWeight: 600 }}>렌더링 오류가 발생했습니다</div>
          <div style={{
            fontSize: 13, color: '#f87171', background: '#1a0a0a',
            padding: '8px 16px', borderRadius: 8, maxWidth: 600, wordBreak: 'break-all'
          }}>
            {this.state.error?.message ?? '알 수 없는 오류'}
          </div>
          <button
            onClick={() => window.location.reload()}
            style={{
              marginTop: 8, padding: '8px 24px', borderRadius: 8,
              background: '#7c3aed', color: '#fff', border: 'none',
              fontSize: 14, cursor: 'pointer'
            }}
          >
            🔄 앱 새로고침
          </button>
        </div>
      )
    }
    return this.props.children
  }
}

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <ErrorBoundary>
      <App />
    </ErrorBoundary>
  </StrictMode>,
)
