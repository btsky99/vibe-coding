# -*- coding: utf-8 -*-
"""
FILE: scripts/skill_predictor.py
DESCRIPTION: 예측적 스킬 실행 — 과거 스킬 체인 시퀀스를 분석하여
             다음에 실행할 스킬을 자동 제안합니다.

             [동작 원리]
             1. hive_skill_chains에서 과거 세션별 스킬 시퀀스 추출
             2. 마르코프 체인 방식으로 "스킬 A 다음에 스킬 B" 전이 확률 계산
             3. 현재 실행 중인 스킬의 다음 스킬을 확률 순으로 제안
             4. /api/skill/predict 엔드포인트로 제안 목록 반환

REVISION HISTORY:
- 2026-03-15 Claude: 최초 구현 — 마르코프 체인 기반 스킬 시퀀스 예측
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


class SkillPredictor:
    """마르코프 체인 기반 스킬 시퀀스 예측기.

    사용법:
        predictor = SkillPredictor()
        predictions = predictor.predict("vibe-debug")
        # → [{"skill": "vibe-execute-plan", "probability": 0.45}, ...]
    """

    def __init__(self, project_root: Path = None):
        self.project_root = project_root or ROOT_DIR
        self._transitions = None  # 캐시

    def _build_transition_matrix(self) -> dict:
        """hive_skill_chains에서 세션별 스킬 시퀀스를 추출하고 전이 행렬을 생성."""
        if self._transitions is not None:
            return self._transitions

        try:
            ensure_schema(DATA_DIR)
            rows = query_rows(
                "SELECT session_id, skill_name, step_order "
                "FROM hive_skill_chains "
                "WHERE skill_name != '' "
                "ORDER BY session_id, step_order;"
            )
        except Exception:
            rows = []

        # 세션별 스킬 시퀀스 구성
        sessions = defaultdict(list)
        for row in rows:
            sid = row.get('session_id', '')
            skill = row.get('skill_name', '')
            if sid and skill:
                sessions[sid].append(skill)

        # 전이 횟수 계산 (스킬 A → 스킬 B 전이 카운트)
        transitions = defaultdict(lambda: defaultdict(int))
        for skills in sessions.values():
            for i in range(len(skills) - 1):
                current = skills[i]
                next_skill = skills[i + 1]
                if current != next_skill:  # 자기 전이 제외
                    transitions[current][next_skill] += 1

        # task_logs.jsonl에서도 시퀀스 보충
        log_file = self.project_root / '.ai_monitor' / 'data' / 'task_logs.jsonl'
        if log_file.exists():
            prev_skill = None
            try:
                for line in open(log_file, 'r', encoding='utf-8'):
                    entry = json.loads(line)
                    task = entry.get('task', '')
                    # [스킬:vibe-debug] 패턴에서 스킬명 추출
                    if '[스킬:' in task:
                        start = task.find('[스킬:') + 4
                        end = task.find(']', start)
                        if end > start:
                            skill = task[start:end]
                            if prev_skill and prev_skill != skill:
                                transitions[prev_skill][skill] += 1
                            prev_skill = skill
            except Exception:
                pass

        self._transitions = dict(transitions)
        return self._transitions

    def predict(self, current_skill: str, top_k: int = 3) -> list[dict]:
        """현재 스킬 기반으로 다음 스킬 예측 목록 반환.

        Args:
            current_skill: 현재 실행 중인 스킬 이름
            top_k: 반환할 최대 추천 수

        Returns:
            [{"skill": "vibe-execute-plan", "probability": 0.45, "count": 9}, ...]
        """
        transitions = self._build_transition_matrix()
        next_skills = transitions.get(current_skill, {})

        if not next_skills:
            return []

        total = sum(next_skills.values())
        predictions = [
            {
                "skill": skill,
                "probability": round(count / total, 2),
                "count": count,
            }
            for skill, count in sorted(next_skills.items(), key=lambda x: -x[1])
        ]
        return predictions[:top_k]

    def predict_from_context(self, recent_skills: list[str], top_k: int = 3) -> list[dict]:
        """최근 스킬 시퀀스 기반으로 다음 스킬 예측.
        마지막 스킬의 전이 확률을 사용합니다.
        """
        if not recent_skills:
            return []
        return self.predict(recent_skills[-1], top_k=top_k)

    def get_full_report(self) -> dict:
        """전체 전이 행렬 + 인기 시퀀스 보고서."""
        transitions = self._build_transition_matrix()

        # 스킬별 총 전이 수
        skill_usage = defaultdict(int)
        for src, dests in transitions.items():
            for dst, count in dests.items():
                skill_usage[src] += count
                skill_usage[dst] += count

        # 인기 시퀀스 (전이 횟수 상위 10)
        top_sequences = []
        for src, dests in transitions.items():
            for dst, count in dests.items():
                top_sequences.append({"from": src, "to": dst, "count": count})
        top_sequences.sort(key=lambda x: -x["count"])

        return {
            "timestamp": datetime.now().isoformat(),
            "transition_matrix": {
                src: dict(dsts) for src, dsts in transitions.items()
            },
            "skill_usage": dict(skill_usage),
            "top_sequences": top_sequences[:10],
        }


# ── API 엔드포인트용 함수 ────────────────────────────────────────────────────
def predict_next_skill(current_skill: str, project_root: Path = None) -> list[dict]:
    predictor = SkillPredictor(project_root=project_root)
    return predictor.predict(current_skill)


def get_prediction_report(project_root: Path = None) -> dict:
    predictor = SkillPredictor(project_root=project_root)
    return predictor.get_full_report()


if __name__ == "__main__":
    predictor = SkillPredictor()
    report = predictor.get_full_report()
    print(json.dumps(report, indent=2, ensure_ascii=False, default=str))

    # 각 스킬의 다음 예측 출력
    for skill in report.get("skill_usage", {}):
        predictions = predictor.predict(skill)
        if predictions:
            print(f"\n{skill} 다음 →")
            for p in predictions:
                print(f"  {p['skill']}: {p['probability']*100:.0f}% ({p['count']}회)")
