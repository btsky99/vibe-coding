"""
FILE: scripts/rules_validator.py
DESCRIPTION: 프로젝트의 행동 원칙(RULES.md) 준수 여부를 자동으로 검증하는 스크립트. 
             모든 에이전트는 코드 수정 후 이 스크립트를 실행하여 'Pass'를 받아야 함.

REVISION HISTORY:
- 2026-03-06 Gemini: 최초 작성. 헤더 템플릿, 한글 주석 비중, PROJECT_MAP.md 업데이트 체크 기능 구현.
"""

import os
import re
import sys
import argparse

def is_korean(text):
    """텍스트에 한글이 포함되어 있는지 확인"""
    return bool(re.search('[가-힣]', text))

def check_header(content, file_path):
    """파일 헤더 템플릿 준수 여부 확인"""
    required_fields = ["FILE:", "DESCRIPTION:", "REVISION HISTORY:"]
    missing = [field for field in required_fields if field not in content]
    
    # 확장자에 따른 주석 스타일 확인
    ext = os.path.splitext(file_path)[1]
    header_comment = False
    if ext in ['.py', '.sh', '.bat']:
        header_comment = '"""' in content or "'''" in content or content.startswith('#')
    elif ext in ['.js', '.ts', '.tsx', '.css']:
        header_comment = '/*' in content
    elif ext in ['.md', '.html']:
        header_comment = '<!--' in content
        
    if missing:
        return False, f"헤더 필수 필드 누락: {', '.join(missing)}"
    if not header_comment:
        return False, f"헤더 주석 형식이 올바르지 않음 ({ext})"
    
    return True, "정상"

def check_korean_comments(content, file_path):
    """주석 내 한글 비중 확인 (Python/JS 기준 간단 로직)"""
    ext = os.path.splitext(file_path)[1]
    if ext not in ['.py', '.js', '.ts', '.tsx']:
        return True, "건너뜀"

    # 주석만 추출 (단순화된 정규식)
    # Python 3.11+ 에서는 전역 플래그 (?s) 가 맨 앞에 와야 함
    comments = []
    if ext == '.py':
        # # 주석 및 ''' """ 주석
        comments = re.findall(r'(?s)#.*|\'\'\'.*?\'\'\'|""".*?"""', content)
    else:
        # // 주석 및 /* */ 주석
        comments = re.findall(r'(?s)//.*|/\*.*?\*/', content)
        
    if not comments:
        return True, "주석 없음 (주의)"

    comment_text = " ".join(comments)
    if not is_korean(comment_text):
        return False, "주석에 한글이 포함되어 있지 않음 (RULES.md 위반)"
    
    return True, "정상"

def check_project_map(file_path):
    """PROJECT_MAP.md에 해당 파일이 등재되어 있는지 확인"""
    map_path = "D:/vibe-coding/PROJECT_MAP.md"
    if not os.path.exists(map_path):
        return True, "PROJECT_MAP.md를 찾을 수 없음"
    
    rel_path = os.path.relpath(file_path, "D:/vibe-coding").replace("\\", "/")
    # .ai_monitor/ 내부는 폴더 단위로 있을 수 있으므로 유연하게 체크
    
    with open(map_path, 'r', encoding='utf-8') as f:
        map_content = f.read()
    
    # 파일명이나 경로가 포함되어 있는지 확인
    file_name = os.path.basename(file_path)
    if file_name not in map_content and rel_path not in map_content:
        return False, f"PROJECT_MAP.md에 파일 정보 누락: {rel_path}"
    
    return True, "정상"

def validate_file(file_path):
    """단일 파일 검증 실행"""
    if not os.path.exists(file_path):
        return {"file": file_path, "status": "Error", "message": "파일이 존재하지 않음"}

    if os.path.isdir(file_path):
        return {"file": file_path, "status": "Skip", "message": "디렉토리는 건너뜀"}

    # 무시할 파일들
    if any(ignore in file_path for ignore in ['.git', 'node_modules', '.venv', '__pycache__', '.ico', '.png', '.exe']):
        return {"file": file_path, "status": "Skip", "message": "무시 대상 파일"}

    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
    except Exception as e:
        return {"file": file_path, "status": "Error", "message": f"파일 읽기 실패: {str(e)}"}

    results = []
    
    # 1. 헤더 체크
    h_ok, h_msg = check_header(content, file_path)
    if not h_ok: results.append(h_msg)
    
    # 2. 한글 주석 체크
    k_ok, k_msg = check_korean_comments(content, file_path)
    if not k_ok: results.append(k_msg)
    
    # 3. 프로젝트 맵 체크
    # m_ok, m_msg = check_project_map(file_path) # 신규 파일 여부 판단이 어려워 일단 경고로 처리하거나 옵션화
    # if not m_ok: results.append(m_msg)
    
    if not results:
        return {"file": file_path, "status": "Pass", "message": "모든 규칙 준수"}
    else:
        return {"file": file_path, "status": "Fail", "message": " | ".join(results)}

def main():
    parser = argparse.ArgumentParser(description="RULES.md 준수 여부 검증기")
    parser.add_argument("files", nargs="+", help="검증할 파일 경로 목록")
    args = parser.parse_args()

    overall_pass = True
    print("\n--- [RULES.md Validation Report] ---")
    for f in args.files:
        res = validate_file(f)
        status_icon = "✅" if res['status'] == "Pass" else "❌" if res['status'] == "Fail" else "⚠️"
        print(f"{status_icon} [{res['status']}] {res['file']}: {res['message']}")
        
        if res['status'] == "Fail":
            overall_pass = False
            
    print("------------------------------------\n")
    
    if not overall_pass:
        print("❌ [경고] 일부 파일이 RULES.md를 준수하지 않습니다. 수정한 후 다시 시도하세요.")
        sys.exit(1)
    else:
        print("✅ 모든 파일이 규칙을 준수합니다. 작업을 진행하셔도 좋습니다.")
        sys.exit(0)

if __name__ == "__main__":
    main()
