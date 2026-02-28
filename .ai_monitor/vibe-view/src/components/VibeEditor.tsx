import React, { useEffect, useState } from 'react';
import Editor from '@monaco-editor/react';

/**
 * 🎨 VibeEditor: Monaco Editor 기반의 코드 편집기 컴포넌트
 * - VS Code 스타일의 코드 하이라이팅 및 주석 색상 강화 테마 적용
 * - 자동 언어 감지 및 편집 내용 실시간 반영 지원
 * - 저장(Save) API 연동 포함
 */
interface VibeEditorProps {
  path: string;
  content: string;
  onChange?: (val: string) => void;
  isReadOnly?: boolean;
}

const VibeEditor: React.FC<VibeEditorProps> = ({ path, content, onChange, isReadOnly = false }) => {
  const [internalContent, setInternalContent] = useState(content);
  const API_BASE = `http://${window.location.hostname}:${window.location.port}`;

  useEffect(() => {
    setInternalContent(content);
  }, [content]);

  const extension = path.split('.').pop()?.toLowerCase() || '';
  const languageMap: Record<string, string> = {
    'py': 'python', 'js': 'javascript', 'jsx': 'javascript', 'ts': 'typescript', 'tsx': 'typescript',
    'json': 'json', 'md': 'markdown', 'html': 'html', 'css': 'css', 'yml': 'yaml', 'yaml': 'yaml',
    'sh': 'shell', 'bat': 'bat', 'powershell': 'powershell', 'sql': 'sql', 'iss': 'pascal'
  };
  const language = languageMap[extension] || 'plaintext';

  const handleSave = (val: string) => {
    if (isReadOnly) return;
    
    fetch(`${API_BASE}/api/save-file`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ path, content: val })
    })
    .then(res => res.json())
    .then(data => {
      if (data.status === 'success') {
        console.log('File saved successfully:', path);
        // 시각적 피드백은 브라우저 콘솔 또는 별도 UI로 처리
      } else {
        alert('저장 실패: ' + (data.message || '알 수 없는 오류'));
      }
    })
    .catch(err => {
      console.error('Save error:', err);
    });
  };

  const handleEditorDidMount = (editor: any, monaco: any) => {
    // 하이브 마인드 전용 다크 테마 정의
    monaco.editor.defineTheme('vibe-dark-pro', {
      base: 'vs-dark',
      inherit: true,
      rules: [
        { token: 'comment', foreground: '6A9955', fontStyle: 'italic' }, // 주석: 밝은 초록색 (VS Code 표준)
        { token: 'keyword', foreground: '569CD6', fontStyle: 'bold' },   // 키워드: 하늘색 + 굵게
        { token: 'string', foreground: 'CE9178' },                      // 문자열: 연한 주황색
        { token: 'number', foreground: 'B5CEA8' },                      // 숫자: 연두색
        { token: 'type', foreground: '4EC9B0' },                        // 타입: 에메랄드색
        { token: 'function', foreground: 'DCDCAA' },                    // 함수명: 연한 노란색
      ],
      colors: {
        'editor.background': '#1e1e1e',
        'editorLineNumber.foreground': '#858585',
        'editorLineNumber.activeForeground': '#cccccc',
        'editor.selectionBackground': '#264F78',
        'editor.inactiveSelectionBackground': '#3A3D41',
      }
    });
    monaco.editor.setTheme('vibe-dark-pro');

    // Ctrl+S / Cmd+S 저장 단축키 바인딩
    editor.addCommand(monaco.KeyMod.CtrlCmd | monaco.KeyCode.KeyS, () => {
      const currentVal = editor.getValue();
      handleSave(currentVal);
    });
  };

  return (
    <div className="w-full h-full relative group">
      <Editor
        height="100%"
        language={language}
        value={internalContent}
        theme="vs-dark"
        onChange={(val) => {
          const newVal = val || '';
          setInternalContent(newVal);
          if (onChange) onChange(newVal);
        }}
        onMount={handleEditorDidMount}
        options={{
          readOnly: isReadOnly,
          fontSize: 13,
          fontFamily: "'Fira Code', 'Consolas', monospace",
          minimap: { enabled: false },
          scrollBeyondLastLine: false,
          wordWrap: 'on',
          automaticLayout: true,
          lineNumbers: 'on',
          renderLineHighlight: 'all',
          padding: { top: 12, bottom: 12 },
          tabSize: 4,
          insertSpaces: true,
        }}
      />
      {isReadOnly && (
        <div className="absolute top-2 right-4 px-2 py-0.5 bg-black/50 text-[10px] text-white/50 rounded pointer-events-none border border-white/10 backdrop-blur-sm z-50">
          READ-ONLY
        </div>
      )}
      {!isReadOnly && (
        <div className="absolute bottom-4 right-6 opacity-0 group-hover:opacity-100 transition-opacity z-50">
          <button 
            onClick={() => handleSave(internalContent)}
            className="flex items-center gap-1.5 px-3 py-1.5 bg-primary/80 hover:bg-primary text-white text-[11px] font-bold rounded shadow-lg backdrop-blur-md border border-white/10 transition-all hover:scale-105"
          >
            <span>Save</span>
            <span className="text-[9px] opacity-60">Ctrl+S</span>
          </button>
        </div>
      )}
    </div>
  );
};

export default VibeEditor;
