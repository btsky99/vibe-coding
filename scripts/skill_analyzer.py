"""
FILE: scripts/skill_analyzer.py
DESCRIPTION: 작업 로그를 분석하여 반복되는 패턴을 감지하고, 새로운 하이브 스킬(Skill)을 제안합니다.
REVISION HISTORY:
- 2026-02-26 Gemini-1: 초기 생성. 로그 기반 키워드 빈도 분석 및 스킬 초안 제안 로직 구현.
"""

import os
import json
import re
from collections import Counter
from datetime import datetime
from pathlib import Path

# 프로젝트 경로 설정
PROJECT_ROOT = Path(__file__).resolve().parent.parent
LOG_FILE = PROJECT_ROOT / ".ai_monitor" / "data" / "task_logs.jsonl"
SKILLS_DIR = PROJECT_ROOT / ".gemini" / "skills"

class SkillAnalyzer:
    def __init__(self):
        self.stop_words = {'the', 'to', 'and', 'a', 'in', 'is', 'it', 'you', 'that', 'he', 'was', 'for', 'on', 'are', 'with', 'as', 'I', 'his', 'they', 'be', 'at', 'one', 'have', 'this', 'from', 'or', 'had', 'by', 'hot', 'word', 'but', 'what', 'some', 'we', 'can', 'out', 'other', 'were', 'all', 'there', 'when', 'up', 'use', 'your', 'how', 'said', 'an', 'each', 'she'}

    def get_logs(self, limit=50):
        if not LOG_FILE.exists():
            return []
        logs = []
        with open(LOG_FILE, "r", encoding="utf-8") as f:
            for line in f:
                try:
                    logs.append(json.loads(line))
                except:
                    continue
        return logs[-limit:]

    def analyze_patterns(self):
        logs = self.get_logs()
        if not logs:
            return "No logs found to analyze."

        # 키워드 빈도 분석 (영문/한글 혼합 대응)
        words = []
        for entry in logs:
            task = entry.get("task", "")
            # 특수문자 제거 및 단어 분리
            clean_task = re.sub(r'[^\w\s]', ' ', task)
            words.extend([w.lower() for w in clean_task.split() if len(w) > 1 and w.lower() not in self.stop_words])

        common_words = Counter(words).most_common(10)
        
        # 스킬 제안 로직 (단순 빈도 기반)
        proposals = []
        for word, count in common_words:
            if count >= 3: # 3번 이상 반복되면 스킬 후보
                proposals.append({
                    "keyword": word,
                    "count": count,
                    "suggested_skill_name": f"pattern-{word}",
                    "description": f"'{word}' 관련 작업이 {count}회 반복되었습니다. 이 작업을 위한 표준 스킬 생성을 제안합니다."
                })

        return {
            "timestamp": datetime.now().isoformat(),
            "analyzed_count": len(logs),
            "top_keywords": common_words,
            "proposals": proposals
        }

    def save_analysis(self, report):
        analysis_file = PROJECT_ROOT / ".ai_monitor" / "data" / "skill_analysis.json"
        with open(analysis_file, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, ensure_ascii=False)
        return analysis_file

if __name__ == "__main__":
    analyzer = SkillAnalyzer()
    report = analyzer.analyze_patterns()
    saved_path = analyzer.save_analysis(report)
    print(f"[OK] 로그 분석 완료. {len(report.get('proposals', []))}개의 스킬 후보가 발견되었습니다.")
    print(json.dumps(report, indent=2, ensure_ascii=False))
