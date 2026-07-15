"""
FILE: scripts/heal_report.py
DESCRIPTION: 자가치유 계측 CLI — src/heal_metrics.compute_heal_metrics를 호출해 4장치 지표를
             터미널에 요약 출력한다. 계산 로직은 갖지 않음(단일 소스 = heal_metrics). `--json` raw 출력.

REVISION HISTORY:
- 2026-07-15 Claude: 폴백 사유 분해 표시 — load_failed(영구 고장)를 not_warm(일시)과 구분
- 2026-07-05 Claude: 신규 — 자가치유 계측 Task 2. incident.py stats 스타일 출력.
"""
import sys
import json
import argparse
from pathlib import Path

# .ai_monitor를 import 경로에 추가 (scripts/에서 src.heal_metrics 접근)
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / ".ai_monitor"))

from src.heal_metrics import compute_heal_metrics  # noqa: E402


def _bar(pct: float, width: int = 20) -> str:
    filled = int(round(pct / 100 * width))
    return "█" * filled + "░" * (width - filled)


def main() -> int:
    ap = argparse.ArgumentParser(description="자가치유 계측 리포트")
    ap.add_argument("--project", default="", help="project_id 필터 (기본: 전체)")
    ap.add_argument("--json", action="store_true", help="raw JSON 출력")
    args = ap.parse_args()

    m = compute_heal_metrics(args.project)
    if args.json:
        print(json.dumps(m, ensure_ascii=False, indent=2))
        return 0

    print("=" * 60)
    print(f"🩹 자가치유 계측 — {m['generated_at']}  (범위: {m['project_id']})")
    print("   성과 + 기록 성실도 이중계측. 표본 부족 시 성과는 '판단 보류'.")
    print("=" * 60)

    r = m["recall"]
    print(f"\n[1] 회상 v2  {r['verdict']}  — 지식이 실제로 회상되나")
    print(f"    임베딩 커버리지 {_bar(r['embed_coverage_pct'])} {r['embed_coverage_pct']}%"
          f"  (전체 {r['total_knowledge']}건)")
    print(f"    참조율         {_bar(r['referenced_pct'])} {r['referenced_pct']}%"
          f"  (참조합 {r['ref_sum']})")
    _live = r.get("live")
    if _live:
        print(f"    실발화율       {_bar(_live['fire_rate_pct'])} {_live['fire_rate_pct']}%"
              f"  (최근14일 {_live['calls_14d']}회, 적중 {_live['hit_rate_pct']}%)")
        _fr = _live.get("fallback_reasons") or {}
        if _fr:
            # load_failed가 보이면 일시적 미warm이 아니라 영구 고장 — 즉시 조치 신호
            print(f"      폴백 사유: " + ", ".join(f"{k}×{v}" for k, v in _fr.items()))
    else:
        print(f"    실발화율       (계측 대기 — recall-smart 호출 로그 없음)")
    for name, t in r["tables"].items():
        print(f"      - {name:<18} 임베딩 {t['embed_pct']:>5}% / 참조 {t['referenced']}건"
              f" (총 {t['total']})")
    print(f"    → {r['note']}")

    inc = m["incidents"]
    print(f"\n[2] 사고 장부  {inc['verdict']}  — 같은 버그 재발 방지 (북극성)")
    smp = "충분" if inc["sample_ok"] else f"부족(<{inc['min_sample']})"
    print(f"    총 사고 {inc['total']}건 / 재발 {inc['recurred']}건 → 재발률 {inc['recurrence_rate_pct']}%"
          f"  [표본 {smp}]")
    if inc["weekly"]:
        wk = "  ".join(f"{w['week']}:{w['n']}({w['recur']}R)" for w in inc["weekly"])
        print(f"    주별: {wk}")
    print(f"    → {inc['note']}")

    cp = m["checkpoints"]
    print(f"\n[3] 체크포인트  {cp['verdict']}  — 세션 튕김 후 이어받기")
    print(f"    총 {cp['total']}건 / 최근 7일 {cp['recent_7d']}건 / 에이전트 {cp['distinct_agents']}명")
    print(f"    → {cp['note']}")

    ls = m["lessons"]
    print(f"\n[4] 교훈 증류  {ls['verdict']}  — 프로젝트 특화 학습")
    print(f"    승인 교훈 {ls['approved']}건")
    print(f"    → {ls['note']}")

    print("\n" + "=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
