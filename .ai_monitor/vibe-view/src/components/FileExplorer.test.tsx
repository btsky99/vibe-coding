import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import FileExplorer from './FileExplorer';
import { API_BASE } from '../constants';

// --- API 모킹 ---
const mockFetch = vi.fn();
global.fetch = mockFetch;

// --- lucide-react 및 react-icons 모킹 ---
vi.mock('lucide-react', () => ({
  ChevronLeft: () => <div data-testid="icon-chevron-left" />,
  Plus: () => <div data-testid="icon-plus" />,
  Trash2: () => <div data-testid="icon-trash2" />,
  Edit3: () => <div data-testid="icon-edit3" />,
  ClipboardList: () => <div data-testid="icon-clipboard-list" />,
}));

vi.mock('react-icons/vsc', () => ({
  VscFolder: () => <div data-testid="icon-vsc-folder" />,
  VscFolderOpened: () => <div data-testid="icon-vsc-folder-opened" />,
  VscNewFolder: () => <div data-testid="icon-vsc-new-folder" />,
  VscFile: () => <div data-testid="icon-vsc-file" />,
  VscTrash: () => <div data-testid="icon-vsc-trash" />,
}));

describe('FileExplorer 컴포넌트 테스트', () => {
  const mockOnPathChange = vi.fn();
  const mockOnOpenFile = vi.fn();
  const defaultProps = {
    currentPath: 'C:/test-project',
    onPathChange: mockOnPathChange,
    onOpenFile: mockOnOpenFile,
  };

  beforeEach(() => {
    vi.clearAllMocks();
    // 기본 API 응답 설정
    mockFetch.mockImplementation((url: string) => {
      if (url.includes('/api/drives')) return Promise.resolve({ json: () => Promise.resolve(['C:/', 'D:/']) });
      if (url.includes('/api/projects')) return Promise.resolve({ json: () => Promise.resolve(['C:/test-project']) });
      if (url.includes('/api/config')) return Promise.resolve({ json: () => Promise.resolve({ last_path: 'C:/test-project' }) });
      if (url.includes('/api/files')) return Promise.resolve({ 
        json: () => Promise.resolve([
          { name: 'src', path: 'C:/test-project/src', isDir: true },
          { name: 'package.json', path: 'C:/test-project/package.json', isDir: false },
        ]) 
      });
      return Promise.resolve({ json: () => Promise.resolve({}) });
    });
  });

  it('초기 렌더링 시 드라이브 및 파일 목록을 로드해야 함', async () => {
    render(<FileExplorer {...defaultProps} />);

    // 드라이브 로드 확인
    await waitFor(() => {
      expect(mockFetch).toHaveBeenCalledWith(expect.stringContaining('/api/drives'));
    });

    // 파일 목록 렌더링 확인 (src 폴더와 package.json 파일)
    expect(await screen.findByText('src')).toBeInTheDocument();
    expect(await screen.findByText('package.json')).toBeInTheDocument();
  });

  it('드라이브 선택 시 경로 변경 함수가 호출되어야 함', async () => {
    render(<FileExplorer {...defaultProps} />);
    
    const select = await screen.findByRole('combobox');
    fireEvent.change(select, { target: { value: 'D:/' } });

    expect(mockOnPathChange).toHaveBeenCalledWith('D:/');
  });

  it('상위 폴더 이동 버튼 클릭 시 상위 경로로 변경되어야 함', async () => {
    render(<FileExplorer {...defaultProps} currentPath="C:/test-project/src" />);
    
    const upButton = await screen.findByText('..');
    fireEvent.click(upButton);

    expect(mockOnPathChange).toHaveBeenCalledWith('C:/test-project');
  });

  it('파일 클릭 시 onOpenFile이 호출되어야 함', async () => {
    render(<FileExplorer {...defaultProps} />);
    
    const fileItem = await screen.findByText('package.json');
    fireEvent.click(fileItem);

    expect(mockOnOpenFile).toHaveBeenCalledWith(expect.objectContaining({
      name: 'package.json',
      path: 'C:/test-project/package.json',
      isDir: false
    }));
  });

  it('폴더 클릭 시 onPathChange가 호출되어야 함', async () => {
    render(<FileExplorer {...defaultProps} />);
    
    const dirItem = await screen.findByText('src');
    fireEvent.click(dirItem);

    expect(mockOnPathChange).toHaveBeenCalledWith('C:/test-project/src');
  });

  it('트리/플랫 뷰 토글 버튼 동작 확인', async () => {
    render(<FileExplorer {...defaultProps} />);
    
    const toggleButton = screen.getByTitle('플랫 뷰로 전환');
    fireEvent.click(toggleButton);

    // 플랫 뷰 상태 확인 (버튼 타이틀 변경)
    expect(screen.getByTitle('트리 뷰로 전환')).toBeInTheDocument();
  });

  it('컨텍스트 메뉴 표시 확인', async () => {
    render(<FileExplorer {...defaultProps} />);
    
    const fileItem = await screen.findByText('package.json');
    // 우클릭 (Context Menu)
    fireEvent.contextMenu(fileItem);

    // 컨텍스트 메뉴 항목들이 표시되는지 확인
    expect(await screen.findByText('경로 복사')).toBeInTheDocument();
    expect(await screen.findByText('이름 변경...')).toBeInTheDocument();
    expect(await screen.findByText('삭제')).toBeInTheDocument();
  });
});
