# -*- coding: utf-8 -*-
"""
FILE: scripts/skill_analyzer.py
DESCRIPTION: 작업 로그를 분석하여 반복되는 패턴을 감지하고,
             자기치유(Self-Healing) 메커니즘으로 하이브 스킬을 자동 업데이트합니다.

             [자기치유 동작 원리]
             1. task_logs.jsonl에서 사용자 [지시] 로그만 추출
             2. 한글/영문 키워드 빈도 분석 (불용어 제거)
             3. 3회 이상 반복 패턴 → vibe-master.md의 "자기치유 섹션"에 자동 기록
             4. hive_watchdog.py가 10분마다 이 스크립트를 호출하여 루프 완성

             [이전 버전과의 차이]
             기존: 분석 결과를 skill_analysis.json에 저장만 함 (적용 없음)
             현재: apply_knowledge_to_skill()로 실제 스킬 파일을 자동 수정

REVISION HISTORY:
- 2026-03-01 Claude: [자기치유 완성] apply_knowledge_to_skill() 추가
  - extract_user_instructions(): 사용자 지시 로그만 필터링
  - apply_knowledge_to_skill(): 반복 패턴을 vibe-master.md에 자동 반영
  - project_root 파라미터 추가 — 워치독이 경로 주입 가능하도록
- 2026-02-26 Gemini-1: 초기 생성. 로그 기반 키워드 빈도 분석 및 스킬 초안 제안 로직 구현.
"""

import json
import re
from collections import Counter
from datetime import datetime
from pathlib import Path

# 기본 경로 (단독 실행 시)
_DEFAULT_ROOT = Path(__file__).resolve().parent.parent

# 한글/영문 혼합 불용어 목록
# — 조사·접속사·빈도 높은 무의미 단어 제거
_STOP_WORDS = {
    # 영문
    'the', 'to', 'and', 'a', 'in', 'is', 'it', 'you', 'that', 'he', 'was',
    'for', 'on', 'are', 'with', 'as', 'his', 'they', 'be', 'at', 'one',
    'have', 'this', 'from', 'or', 'had', 'by', 'but', 'what', 'some', 'we',
    'can', 'out', 'other', 'were', 'all', 'there', 'when', 'up', 'use',
    'your', 'how', 'said', 'an', 'each', 'she', 'ok', 'no',
    # 한글 공통 조사·부사 (로그에서 잡음 유발)
    '지시', '수정', '완료', '시작', '실행', '생성', '확인', '작업',
    '파일', '코드', '서버', '빌드', '에러', '오류', '버그', '테스트',
    # 로그 접두사 (hive_hook/gemini_hook이 붙이는 레이블)
    '수정완료', '실행완료', '생성완료', '커밋', '세션',
}


class SkillAnalyzer:
    """하이브 스킬 자기치유 분석기.

    사용법:
        analyzer = SkillAnalyzer(project_root=Path("D:/vibe-coding"))
        report = analyzer.analyze_patterns()
        analyzer.apply_knowledge_to_skill(report['proposals'])
    """

    def __init__(self, project_root: Path = None):
        # project_root: 워치독에서 주입하거나, 단독 실행 시 __file__ 기준으로 결정
        self.project_root = project_root or _DEFAULT_ROOT
        self.log_file = self.project_root / ".ai_monitor" / "data" / "task_logs.jsonl"
        self.skills_dir = self.project_root / ".gemini" / "skills"
        self.claude_skills_dir = self.project_root / "skills" / "claude"

    # ── 로그 읽기 ─────────────────────────────────────────────────────────

    def get_logs(self, limit: int = 200) -> list:
        """task_logs.jsonl에서 최근 N개 로그 반환."""
        if not self.log_file.exists():
            return []
        logs = []
        with open(self.log_file, "r", encoding="utf-8") as f:
            for line in f:
                try:
                    logs.append(json.loads(line))
                except Exception:
                    continue
        return logs[-limit:]

    def extract_user_instructions(self, logs: list) -> list[str]:
        """로그에서 사용자 [지시] 항목만 추출하여 텍스트 리스트로 반환.

        사용자가 실제로 요청한 내용을 분석 대상으로 삼아
        단순 에이전트 내부 로그(수정완료, 실행완료 등) 노이즈를 제거합니다.
        """
        instructions = []
        for entry in logs:
            agent = entry.get("agent", "")
            task = entry.get("task", "")
            # "사용자" 에이전트이고 [지시] 접두사가 있는 로그만 선택
            if agent == "사용자" and "[지시]" in task:
                # "[지시] " 접두사 제거 후 실제 지시문만 남김
                text = task.replace("[지시]", "").strip()
                if text:
                    instructions.append(text)
        return instructions

    # ── 패턴 분석 ─────────────────────────────────────────────────────────

    def analyze_patterns(self) -> dict:
        """로그 분석 → 반복 패턴 감지 → 제안 목록 반환.

        반환값 형식:
        {
            "timestamp": "ISO 문자열",
            "analyzed_count": N,
            "instruction_count": M,
            "top_keywords": [("단어", 횟수), ...],
            "proposals": [{"keyword": ..., "count": ..., "description": ...}, ...]
        }
        """
        logs = self.get_logs()
        if not logs:
            return {"timestamp": datetime.now().isoformat(), "analyzed_count": 0,
                    "instruction_count": 0, "top_keywords": [], "proposals": []}

        # 사용자 지시문만 분석 대상으로 사용
        instructions = self.extract_user_instructions(logs)

        # 키워드 빈도 분석
        # — 한글 2글자 이상 단어, 영문 3글자 이상 단어만 유효 토큰으로 인정
        words = []
        for text in instructions:
            clean = re.sub(r'[^\w\s가-힣]', ' ', text)
            for w in clean.split():
                w_lower = w.lower()
                # 불용어 제거 + 최소 길이 조건
                if w_lower not in _STOP_WORDS:
                    if re.match(r'[가-힣]', w) and len(w) >= 2:
                        words.append(w_lower)
                    elif re.match(r'[a-z]', w_lower) and len(w) >= 3:
                        words.append(w_lower)

        top_keywords = Counter(words).most_common(15)

        # 3회 이상 반복 패턴 → 스킬 후보
        proposals = []
        for word, count in top_keywords:
            if count >= 3:
                proposals.append({
                    "keyword": word,
                    "count": count,
                    "description": (
                        f"'{word}' 관련 요청이 {count}회 반복되었습니다. "
                        f"이 패턴을 스킬에 등록하면 다음 에이전트가 즉시 활용 가능합니다."
                    )
                })

        return {
            "timestamp": datetime.now().isoformat(),
            "analyzed_count": len(logs),
            "instruction_count": len(instructions),
            "top_keywords": top_keywords,
            "proposals": proposals
        }

    # ── 자기치유 적용 ──────────────────────────────────────────────────────

    def apply_knowledge_to_skill(self, proposals: list) -> bool:
        """감지된 반복 패턴을 vibe-master.md의 자기치유 섹션에 자동 기록.

        [동작]
        - vibe-master.md 하단에 "## 🔄 자기치유 감지 패턴" 섹션을 추가/갱신
        - 기존 섹션이 있으면 최신 내용으로 교체 (누적 아닌 최신 유지)
        - proposals가 비어있으면 아무것도 하지 않음 (과다 기록 방지)

        반환값: True = 성공, False = 실패/스킵
        """
        if not proposals:
            return False

        skill_file = self.claude_skills_dir / "vibe-master.md"
        if not skill_file.exists():
            return False

        # 자기치유 섹션 마커
        MARKER = "## 🔄 자기치유 감지 패턴"
        SECTION_START = f"\n\n---\n\n{MARKER}"

        # 새 섹션 내용 생성
        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        lines = [SECTION_START, f" (자동 업데이트: {now})\n\n"]
        lines.append("> 워치독이 `task_logs.jsonl`에서 자동 감지한 반복 요청 패턴입니다.\n")
        lines.append("> 이 패턴들을 인지하고 작업 시 우선적으로 고려하세요.\n\n")
        for p in proposals[:10]:  # 최대 10개만 기록
            lines.append(
                f"- **`{p['keyword']}`** ({p['count']}회 반복): {p['description']}\n"
            )

        # 기존 파일 내용 로드
        content = skill_file.read_text(encoding="utf-8")

        # 기존 자기치유 섹션 제거 (있으면)
        if MARKER in content:
            idx = content.find(SECTION_START)
            if idx != -1:
                content = content[:idx]  # 섹션 이전 내용만 유지

        # 새 섹션 추가
        content += "".join(lines)
        skill_file.write_text(content, encoding="utf-8")
        return True

    # ── 분석 결과 저장 ─────────────────────────────────────────────────────

    def save_analysis(self, report: dict) -> Path:
        """분석 결과를 skill_analysis.json에 저장 (UI/외부 참조용)."""
        analysis_file = self.project_root / ".ai_monitor" / "data" / "skill_analysis.json"
        with open(analysis_file, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, ensure_ascii=False)
        return analysis_file


# ── 단독 실행 ──────────────────────────────────────────────────────────────
if __name__ == "__main__":
    analyzer = SkillAnalyzer()
    report = analyzer.analyze_patterns()
    saved_path = analyzer.save_analysis(report)

    proposals = report.get("proposals", [])
    print(f"[OK] 로그 분석 완료. {len(proposals)}개의 반복 패턴 발견.")

    if proposals:
        applied = analyzer.apply_knowledge_to_skill(proposals)
        if applied:
            print("[OK] 자기치유 완료 — vibe-master.md 업데이트됨")
        else:
            print("[WARN] 스킬 파일 업데이트 실패 (파일 없거나 쓰기 오류)")
    else:
        print("[INFO] 신규 반복 패턴 없음 — 스킬 최신 상태")

    print(json.dumps(report, indent=2, ensure_ascii=False, default=str))
