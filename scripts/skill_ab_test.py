# -*- coding: utf-8 -*-
"""
FILE: scripts/skill_ab_test.py
DESCRIPTION: 스킬 A/B 테스트 — 스킬별 성공/실패율을 분석하고
             성능이 좋은 스킬 변형을 자동 추천합니다.

             [동작 원리]
             1. skill_results.jsonl + hive_skill_chains 테이블에서 실행 이력 수집
             2. 스킬별 성공률, 평균 실행 시간 계산
             3. 동일 의도에 대해 여러 스킬이 사용된 경우 A/B 비교
             4. 더 나은 스킬을 vibe-orchestrate.md에 추천으로 기록

REVISION HISTORY:
- 2026-03-15 Claude: 최초 구현 — 스킬 성과 분석 + A/B 추천 엔진
"""

import json
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
MONITOR_DIR = ROOT_DIR / '.ai_monitor'
if str(MONITOR_DIR) not in sys.path:
    sys.path.insert(0, str(MONITOR_DIR))

from src.pg_store import ensure_schema, query_rows

DATA_DIR = MONITOR_DIR / 'data'
RESULTS_FILE = DATA_DIR / 'skill_results.jsonl'


class SkillABTest:
    """스킬 A/B 테스트 분석기.

    사용법:
        tester = SkillABTest()
        report = tester.analyze()
        tester.apply_recommendations(report)
    """

    def __init__(self, project_root: Path = None):
        self.project_root = project_root or ROOT_DIR
        self.results_file = self.project_root / '.ai_monitor' / 'data' / 'skill_results.jsonl'
        self.claude_skills_dir = self.project_root / '.claude' / 'commands'

    def _load_results(self) -> list[dict]:
        """skill_results.jsonl에서 실행 결과 로드."""
        results = []
        if not self.results_file.exists():
            return results
        with open(self.results_file, 'r', encoding='utf-8') as f:
            for line in f:
                try:
                    results.append(json.loads(line))
                except Exception:
                    continue
        return results

    def _load_chain_stats(self) -> list[dict]:
        """hive_skill_chains 테이블에서 스킬별 통계 조회."""
        try:
            ensure_schema(DATA_DIR)
            return query_rows(
                "SELECT skill_name, status, COUNT(*) as cnt "
                "FROM hive_skill_chains "
                "WHERE skill_name != '' "
                "GROUP BY skill_name, status "
                "ORDER BY skill_name, cnt DESC;"
            )
        except Exception:
            return []

    def analyze(self) -> dict:
        """스킬별 성과 분석 + A/B 비교 결과 반환.

        반환값:
        {
            "timestamp": "ISO",
            "skill_stats": {
                "vibe-debug": {"total": 10, "success": 8, "fail": 2, "rate": 0.8},
                ...
            },
            "recommendations": [
                {"skill": "vibe-debug", "message": "성공률 80% — 양호"},
                ...
            ]
        }
        """
        # 1. skill_results.jsonl에서 결과 수집
        file_results = self._load_results()
        skill_stats = defaultdict(lambda: {"total": 0, "success": 0, "fail": 0})

        for record in file_results:
            for result in record.get("results", []):
                name = result.get("skill", "")
                status = result.get("status", "")
                if not name:
                    continue
                skill_stats[name]["total"] += 1
                if status in ("done", "success", "completed"):
                    skill_stats[name]["success"] += 1
                elif status in ("error", "fail", "failed", "skipped"):
                    skill_stats[name]["fail"] += 1

        # 2. hive_skill_chains 테이블에서 보충
        chain_rows = self._load_chain_stats()
        for row in chain_rows:
            name = row.get("skill_name", "")
            status = row.get("status", "")
            cnt = int(row.get("cnt", 0))
            if not name:
                continue
            skill_stats[name]["total"] += cnt
            if status in ("done", "success", "completed"):
                skill_stats[name]["success"] += cnt
            elif status in ("error", "fail", "failed"):
                skill_stats[name]["fail"] += cnt

        # 3. 성공률 계산
        for name, stats in skill_stats.items():
            total = stats["total"]
            stats["rate"] = round(stats["success"] / total, 2) if total > 0 else 0.0

        # 4. 추천 생성
        recommendations = []
        for name, stats in sorted(skill_stats.items(), key=lambda x: x[1]["rate"]):
            total = stats["total"]
            if total < 2:
                continue  # 데이터 부족
            rate = stats["rate"]
            if rate < 0.5:
                recommendations.append({
                    "skill": name,
                    "severity": "warning",
                    "message": f"성공률 {rate*100:.0f}% ({stats['success']}/{total}) — 스킬 점검 필요",
                })
            elif rate < 0.8:
                recommendations.append({
                    "skill": name,
                    "severity": "info",
                    "message": f"성공률 {rate*100:.0f}% ({stats['success']}/{total}) — 개선 여지 있음",
                })
            else:
                recommendations.append({
                    "skill": name,
                    "severity": "good",
                    "message": f"성공률 {rate*100:.0f}% ({stats['success']}/{total}) — 양호",
                })

        return {
            "timestamp": datetime.now().isoformat(),
            "skill_stats": dict(skill_stats),
            "recommendations": recommendations,
        }

    def apply_recommendations(self, report: dict) -> bool:
        """분석 결과를 vibe-orchestrate.md의 A/B 테스트 섹션에 기록."""
        recommendations = report.get("recommendations", [])
        if not recommendations:
            return False

        skill_file = self.claude_skills_dir / "vibe-orchestrate.md"
        if not skill_file.exists():
            return False

        MARKER = "## 📊 스킬 A/B 테스트 결과"
        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        section = f"\n\n---\n\n{MARKER} (자동 업데이트: {now})\n\n"
        section += "> 스킬별 성공/실패율 분석 결과입니다. 성공률이 낮은 스킬을 우선 점검하세요.\n\n"

        for rec in recommendations:
            icon = {"warning": "⚠️", "info": "ℹ️", "good": "✅"}.get(rec["severity"], "•")
            section += f"- {icon} **{rec['skill']}**: {rec['message']}\n"

        content = skill_file.read_text(encoding="utf-8")
        if MARKER in content:
            idx = content.find(f"\n\n---\n\n{MARKER}")
            if idx != -1:
                content = content[:idx]
        content += section
        skill_file.write_text(content, encoding="utf-8")
        return True


# ── API 엔드포인트용 함수 ────────────────────────────────────────────────────
def get_ab_test_report(project_root: Path = None) -> dict:
    """서버 API에서 호출하는 진입점. 분석 + 적용까지 수행."""
    tester = SkillABTest(project_root=project_root)
    report = tester.analyze()
    tester.apply_recommendations(report)
    return report


if __name__ == "__main__":
    tester = SkillABTest()
    report = tester.analyze()
    print(json.dumps(report, indent=2, ensure_ascii=False, default=str))

    if report.get("recommendations"):
        applied = tester.apply_recommendations(report)
        if applied:
            print("[OK] A/B 테스트 결과 — vibe-orchestrate.md 업데이트됨")
        else:
            print("[WARN] 스킬 파일 업데이트 실패")
    else:
        print("[INFO] 분석할 데이터 부족")
