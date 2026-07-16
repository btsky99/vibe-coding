#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FILE: scripts/incident.py
DESCRIPTION: 사고 장부 CLI — 고친 에러 기록(record) / 재발 검색(search) /
             재발률 통계(stats, 북극성 지표). 자가 치유 2.0 ① (Task 10).

REVISION HISTORY:
- 2026-06-10 Claude: 최초 구현

사용법:
  python scripts/incident.py record --error "Traceback..." --cause "근본원인" --fix "수정법" [--commit abc123] [--files a.py,b.py]
  python scripts/incident.py search "에러 텍스트"
  python scripts/incident.py stats
"""
import argparse
import json
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / '.ai_monitor'))


def main():
    parser = argparse.ArgumentParser(description='사고 장부 — 고친 에러는 두 번 고치지 않는다')
    sub = parser.add_subparsers(dest='cmd', required=True)

    p_rec = sub.add_parser('record', help='수정 완료된 사고 기록')
    p_rec.add_argument('--error', required=True, help='에러 텍스트 (Traceback 등)')
    p_rec.add_argument('--cause', required=True, help='근본 원인 (증상 아님)')
    p_rec.add_argument('--fix', required=True, help='수정 방법')
    p_rec.add_argument('--commit', default='', help='수정 커밋 해시')
    p_rec.add_argument('--files', default='', help='수정 파일 (콤마 구분)')
    p_rec.add_argument('--project', default='', help='project_id (기본: 현재 프로젝트)')

    p_search = sub.add_parser('search', help='과거 사고 검색 (시그니처 → trgm 유사)')
    p_search.add_argument('query', help='에러 텍스트')
    p_search.add_argument('--project', default='', help='project_id 필터')
    p_search.add_argument('--json', action='store_true')

    p_stats = sub.add_parser('stats', help='재발률 통계 — 북극성 지표')
    p_stats.add_argument('--project', default='', help='project_id 필터')
    p_stats.add_argument('--json', action='store_true')

    args = parser.parse_args()
    from src.pg_schema import ensure_schema
    if not ensure_schema():
        print('[!] PostgreSQL 연결 실패 — 사고 장부 사용 불가')
        sys.exit(1)
    from src.pg_incidents import (
        record_incident, search_incidents, incident_stats, format_incident_briefing,
    )
    # project_id 기본값: slugify(프로젝트 루트) — 훅/서버와 동일 규칙 (project_context)
    from infra.project_context import slugify
    project_id = args.project or slugify(_PROJECT_ROOT)

    if args.cmd == 'record':
        files = [f.strip() for f in args.files.split(',') if f.strip()]
        result = record_incident(
            error_text=args.error, root_cause=args.cause,
            fix_description=args.fix, fix_commit=args.commit,
            files=files, project_id=project_id,
        )
        if not result:
            print('[!] 기록 실패 (빈 에러 텍스트 또는 DB 오류)')
            sys.exit(1)
        if result['recurred']:
            print(f"⚠️ 재발 사고 — {result['recurrence_count']}번째 수정 "
                  f"(시그니처 {result['signature']}). 이전 수정이 근본 원인을 못 잡았다는 신호.")
            # [자가치유 ③ 자동 트리거] 재발 = 회상/이전수정이 못 막은 반복 삽질 →
            #   교훈 후보를 자동 적재(승인 게이트 유지). 시그니처 dedupe로 재재발해도 1건.
            #   [WHY 재발만] Stop 훅은 매 턴 발화라 스팸 — 재발은 드물고 '교훈 필요'가 확실한 순간.
            try:
                sys.path.insert(0, str(_PROJECT_ROOT / 'scripts'))
                from lesson import propose_candidate
                propose_candidate(
                    lesson=(f"[재발 {result['recurrence_count']}회] {args.error[:60]} — "
                            f"근본원인 재점검 필요: {args.cause[:80]}"),
                    why=(f"시그니처 {result['signature']} {result['recurrence_count']}번째 재발. "
                         f"이전 수정({args.fix[:60]})이 근본을 못 잡음 — 일반화 교훈으로 승격 검토."),
                    dedupe_key=f"incident-{result['signature']}",
                )
                print("   📥 교훈 후보 자동 적재됨 — 승인: python scripts/lesson.py list")
            except Exception as _e:
                print(f"   (교훈 자동 적재 실패, 무시: {_e})")
        else:
            print(f"✅ 사고 기록 완료 (시그니처 {result['signature']}) — 재발 시 자동 회상됨")

        # [자가치유 ③ 2026-07-16] 클러스터 증류 — 재발 트리거는 재발률 0%라 영영 무발화
        # (승인 교훈 1건에서 파이프 정지). 매 기록마다 파일 클러스터(30일 3건+)를 재평가 —
        # dedupe('cluster:파일') upsert라 승인 큐 오염 없음. 실패는 기록을 방해하지 않는다.
        try:
            sys.path.insert(0, str(_PROJECT_ROOT / 'scripts'))
            from lesson import distill_from_incidents
            new_keys = distill_from_incidents()
            if new_keys:
                print(f"   📥 사고다발 클러스터 {len(new_keys)}건 교훈 후보 갱신 — "
                      f"승인: python scripts/lesson.py list")
        except Exception:
            pass

    elif args.cmd == 'search':
        results = search_incidents(args.query, project_id=project_id)
        if args.json:
            print(json.dumps(results, ensure_ascii=False, default=str, indent=2))
        else:
            print(format_incident_briefing(results) or '과거 동일/유사 사고 없음 — 새 유형')

    elif args.cmd == 'stats':
        stats = incident_stats(project_id=project_id)
        if args.json:
            print(json.dumps(stats, ensure_ascii=False, default=str, indent=2))
            return
        print('📊 사고 장부 통계 (북극성 지표: 재발률)')
        print(f"  전체 사고: {stats['total_incidents']}건")
        print(f"  재발 사고: {stats['recurred_incidents']}건 "
              f"(총 재발 {stats['total_recurrences']}회)")
        print(f"  ★ 재발률: {stats['recurrence_rate'] * 100:.1f}% — 낮을수록 삽질 감소")
        if stats['weekly']:
            print('  주별 추이 (최근 8주):')
            for w in stats['weekly']:
                print(f"    {w['week']}: 사고 {w['incidents']}건 / 재발 {w['recurred']}건")
        if stats['top_recurring']:
            print('  최다 재발 Top:')
            for t in stats['top_recurring']:
                if int(t['recurrence_count']) > 1:
                    print(f"    [{t['recurrence_count']}회] {t['error_text']}")


if __name__ == '__main__':
    main()
