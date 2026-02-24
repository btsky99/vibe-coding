# -*- coding: utf-8 -*-
"""
프로젝트: Vibe Coding (하이브 마인드)
파일: scripts/skill_manager.py
설명: Gemini CLI 및 Claude용 스킬 통합 관리자.
      로컬 스킬 목록 조회, 외부 저장소(Gallery, GitHub) 검색 및 설치 기능을 제공합니다.
      이 스크립트는 Vibe-View 대시보드와 연동되어 시각적인 스킬 관리를 지원합니다.
버전: v1.0.0 - [Gemini] 생성
참조: docs/skill_manager.py.md
"""

import os
import json
import sys
import subprocess
from datetime import datetime

# 프로젝트 루트 및 스킬 디렉토리 설정
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
GEMINI_SKILLS_DIR = os.path.join(PROJECT_ROOT, '.gemini', 'skills')

def list_local_skills():
    """
    로컬 (.gemini/skills) 에 설치된 모든 스킬 목록을 가져옵니다.
    각 스킬 폴더 내의 SKILL.md 파일을 분석하여 설명을 추출합니다.
    """
    skills = []
    if not os.path.exists(GEMINI_SKILLS_DIR):
        return skills
    
    for item in os.listdir(GEMINI_SKILLS_DIR):
        skill_path = os.path.join(GEMINI_SKILLS_DIR, item)
        if os.path.isdir(skill_path):
            skill_md = os.path.join(skill_path, 'SKILL.md')
            description = "설명 정보가 없습니다."
            
            if os.path.exists(skill_md):
                try:
                    with open(skill_md, 'r', encoding='utf-8') as f:
                        lines = f.readlines()
                        for line in lines:
                            line = line.strip()
                            # 첫 번째 헤더가 아닌 일반 텍스트 줄을 설명으로 사용
                            if line and not line.startswith('#'):
                                description = line
                                break
                except Exception as e:
                    description = f"설명을 읽는 중 오류 발생: {str(e)}"
            
            skills.append({
                "name": item,
                "path": skill_path,
                "description": description,
                "type": "Gemini",
                "installed_at": datetime.fromtimestamp(os.path.getctime(skill_path)).isoformat()
            })
    return skills

def search_remote_skills(query):
    """
    외부 저장소에서 스킬을 검색합니다.
    실제 구현 시에는 공갤 갤러리 API나 GitHub 검색 API를 호출할 수 있습니다.
    현재는 검색을 수행하기 위한 가이드와 시뮬레이션 데이터를 반환합니다.
    """
    # 시뮬레이션 데이터 (추후 실제 API 연동 가능)
    # 실제로는 Gemini 에이전트가 이 스크립트의 출력을 보고 google_web_search를 실행하도록 설계됨
    mock_results = [
        {
            "name": "python-optimizer",
            "description": "파이썬 코드의 성능을 분석하고 최적화 제안을 하는 전문 스킬",
            "url": "https://github.com/google-gemini/skills/python-optimizer",
            "author": "Gemini Community"
        },
        {
            "name": "ui-tester",
            "description": "Playwright 기반의 UI 자동화 테스트 생성 및 실행 스킬",
            "url": "https://github.com/google-gemini/skills/ui-tester",
            "author": "Vibe Team"
        }
    ]
    
    # 쿼리에 따른 필터링 (간단 예시)
    filtered = [s for s in mock_results if query.lower() in s['name'].lower() or query.lower() in s['description'].lower()]
    return filtered

def install_skill(name, url):
    """
    지정된 URL(주로 Git 저장소)로부터 스킬을 다운로드하여 로컬에 설치합니다.
    """
    target_path = os.path.join(GEMINI_SKILLS_DIR, name)
    
    if os.path.exists(target_path):
        return {"status": "error", "message": f"이미 '{name}' 스킬이 존재합니다."}
    
    try:
        # Git이 설치되어 있다고 가정하고 클론 수행
        # 주의: 실제 환경에서는 보안 검증이 필요함
        subprocess.run(["git", "clone", url, target_path], check=True, capture_output=True)
        return {"status": "success", "message": f"스킬 '{name}' 설치 완료.", "path": target_path}
    except Exception as e:
        return {"status": "error", "message": f"설치 중 오류 발생: {str(e)}"}

def main():
    import argparse
    parser = argparse.ArgumentParser(description="하이브 마인드 통합 스킬 관리자 (Skill Manager)")
    parser.add_argument("command", choices=["list", "search", "install"], help="실행할 명령 (list, search, install)")
    parser.add_argument("--query", help="검색할 스킬 키워드")
    parser.add_argument("--name", help="설치할 스킬 이름")
    parser.add_argument("--url", help="설치할 스킬의 소스 URL")
    
    args = parser.parse_args()
    
    if args.command == "list":
        skills = list_local_skills()
        print(json.dumps(skills, ensure_ascii=False, indent=2))
        
    elif args.command == "search":
        if not args.query:
            print(json.dumps({"error": "검색어(--query)가 필요합니다."}, ensure_ascii=False))
            return
        results = search_remote_skills(args.query)
        print(json.dumps(results, ensure_ascii=False, indent=2))
        
    elif args.command == "install":
        if not args.name or not args.url:
            print(json.dumps({"error": "이름(--name)과 URL(--url)이 필요합니다."}, ensure_ascii=False))
            return
        result = install_skill(args.name, args.url)
        print(json.dumps(result, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()
