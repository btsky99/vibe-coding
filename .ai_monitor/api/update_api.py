"""
FILE: api/update_api.py
DESCRIPTION: 앱 업데이트 라우트 핸들러 모음 — EXE 풀빌드 채널(updater)과 경량 소스 채널(soft_updater)
             두 갈래를 한 도메인으로 묶는다. server.py의 do_GET/do_POST 디스패처에서 위임 호출된다.
             모든 함수는 SSEHandler 인스턴스(handler)를 받아 자체적으로 HTTP 응답을 완결한다.

REVISION HISTORY:
- 2026-07-12 Claude: apply_update가 update_ready.json의 is_installer 플래그를 읽어
  apply_downloaded_update에 명시 전달 — 파일명 추측 대신 다운로드 시점 판정을 신뢰
  (setup 인스톨러가 앱 exe로 스왑되던 코드32 사고 근본수정, updater.py와 짝).
- 2026-07-05 Claude: server.py SSEHandler do_GET/do_POST의 update/soft-update 6블록 분리
  (do_GET: check-update-ready·trigger-update-check·soft-update/check,
   do_POST: apply-update·soft-update/apply·trigger-update-check).
  클래스 메서드 → handler 인자 모듈 함수로 변환(telegram_api 패턴). server.py 4732→감량.
"""
from __future__ import annotations

import os
import json
import time
import threading
from pathlib import Path


def _parse_ver(v: str) -> tuple:
    """'3.6.10' → (3, 6, 10) 정수 튜플. 버전 비교용(문자열 비교의 '3.6.9'>'3.6.10' 함정 회피)."""
    result = []
    for p in str(v).split("."):
        try:
            result.append(int(p))
        except ValueError:
            result.append(0)
    while len(result) < 3:
        result.append(0)
    return tuple(result)


def check_update_ready(handler, data_dir: Path, current_version: str) -> None:
    """GET /api/check-update-ready — EXE 풀빌드 업데이트 캐시(update_ready.json) 반환.
    [불변식] 저장 버전이 현재 실행 버전보다 **실제로 높을 때만** ready 표시.
      == 비교만 하던 구버전은 v3.6.9 캐시가 v3.6.10에서도 '업데이트 있음'으로 오표시(버그).
      version 없는 파일은 updater 진단 상태(last_error 등)라 삭제 않고 그대로 반환.
    """
    handler.send_response(200)
    handler.send_header('Content-Type', 'application/json;charset=utf-8')
    handler.send_header('Access-Control-Allow-Origin', handler._cors_origin())
    handler.end_headers()
    update_file = data_dir / "update_ready.json"
    if update_file.exists():
        try:
            with open(update_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            file_ver = data.get("version", "").lstrip("v").strip()
            cur_ver = current_version.lstrip("v").strip()
            if file_ver and _parse_ver(file_ver) > _parse_ver(cur_ver):
                handler.wfile.write(json.dumps(data).encode('utf-8'))
            elif file_ver:
                update_file.unlink(missing_ok=True)
                handler.wfile.write(json.dumps({"ready": False, "downloading": False}).encode('utf-8'))
            else:
                handler.wfile.write(json.dumps(data).encode('utf-8'))
        except Exception as e:
            handler.wfile.write(json.dumps({"error": str(e)}).encode('utf-8'))
    else:
        handler.wfile.write(json.dumps({"ready": False, "downloading": False}).encode('utf-8'))


def trigger_update_check(handler, data_dir: Path) -> None:
    """GET·POST /api/trigger-update-check — updater.check_and_update를 백그라운드 스레드로 트리거.
    (GET/POST 양쪽에서 동일 로직 호출 — 프론트가 둘 다 사용.)
    """
    handler.send_response(200)
    handler.send_header('Content-Type', 'application/json;charset=utf-8')
    handler.send_header('Access-Control-Allow-Origin', handler._cors_origin())
    handler.end_headers()
    try:
        from updater import check_and_update
        threading.Thread(target=check_and_update, args=(data_dir,), daemon=True).start()
        handler.wfile.write(json.dumps({"started": True}).encode('utf-8'))
    except Exception as e:
        handler.wfile.write(json.dumps({"started": False, "reason": str(e)}).encode('utf-8'))


def soft_update_check(handler, data_dir: Path, src_dir: Path) -> None:
    """GET /api/soft-update/check — 경량 소스 채널: main 최신 SHA vs 로컬 체크아웃 비교 캐시 반환.
    [제약] 원격 SHA 조회는 ~10초 → 응답을 막지 않도록 백그라운드로 갱신만 트리거하고
      캐시(soft_update_ready.json)를 즉시 반환. EXE 풀빌드 채널(check-update-ready)과 독립.
    """
    handler.send_response(200)
    handler.send_header('Content-Type', 'application/json;charset=utf-8')
    handler.send_header('Access-Control-Allow-Origin', handler._cors_origin())
    handler.end_headers()
    try:
        from soft_updater import check_soft_update
        threading.Thread(target=check_soft_update,
                         args=(data_dir, src_dir), daemon=True).start()
    except Exception as e:
        print(f"[soft-update] check 트리거 실패: {e}")
    soft_file = data_dir / "soft_update_ready.json"
    if soft_file.exists():
        try:
            handler.wfile.write(soft_file.read_text(encoding="utf-8").encode('utf-8'))
        except Exception as e:
            handler.wfile.write(json.dumps({"ready": False, "error": str(e)}).encode('utf-8'))
    else:
        handler.wfile.write(json.dumps({"ready": False}).encode('utf-8'))


def apply_update(handler, data_dir: Path) -> None:
    """POST /api/apply-update — EXE 풀빌드 교체. 응답을 먼저 완전히 전송한 뒤 비동기 스레드로 교체.
    [제약] apply_update_from_temp가 프로세스를 종료하므로 응답-우선 패턴 필수.
      실패 시 update_ready.json 복원 + update_error.log 기록으로 UI에 에러 노출.
    """
    handler.send_response(200)
    handler.send_header('Content-Type', 'application/json;charset=utf-8')
    handler.send_header('Access-Control-Allow-Origin', handler._cors_origin())
    handler.end_headers()

    update_file = data_dir / "update_ready.json"
    if not update_file.exists():
        handler.wfile.write(json.dumps({"success": False, "error": "No update ready"}).encode('utf-8'))
        handler.wfile.flush()
        return

    try:
        with open(update_file, "r", encoding="utf-8") as f:
            update_data = json.load(f)

        exe_path = update_data.get("exe_path")
        if not exe_path or not os.path.exists(exe_path):
            handler.wfile.write(json.dumps({"success": False, "error": "New executable not found", "path": exe_path}).encode('utf-8'))
            handler.wfile.flush()
            return

        # 응답을 먼저 완전히 전송 — os._exit() 전에 클라이언트가 수신하도록 보장
        handler.wfile.write(json.dumps({"success": True}).encode('utf-8'))
        handler.wfile.flush()
        try:
            update_file.unlink()
        except OSError:
            pass

        # [전략 #2a] 디스패처 경유 — setup 자산이면 /SILENT 인스톨러, 아니면 구 exe-swap 폴백.
        # [불변식] is_installer는 다운로드 시점에 원본 에셋명으로 판정돼 update_ready.json에 저장됨.
        #   여기서 파일명(vibe-coding*.exe.new)으로 재판정하면 setup을 onefile로 오판할 수 있어
        #   (v3.7.252 코드32 사고) 반드시 저장된 플래그를 신뢰한다. 구 릴리즈 캐시(플래그 부재)는
        #   None → apply_downloaded_update가 파일명 폴백(보존된 이름이라 정확).
        from updater import apply_downloaded_update
        _exe = Path(exe_path)
        _is_installer = update_data.get("is_installer")

        def _do_apply():
            # 소켓 버퍼 플러시 대기 — 응답이 클라이언트에 도달할 시간 확보
            time.sleep(0.3)
            try:
                apply_downloaded_update(_exe, is_installer=_is_installer)
            except Exception as ex:
                import traceback
                err_detail = traceback.format_exc()
                print(f"[!] apply_update_from_temp 실패: {ex}\n{err_detail}")
                try:
                    with open(data_dir / "update_error.log", "w", encoding="utf-8") as lf:
                        lf.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {err_detail}\n")
                except OSError:
                    pass
                # 실패 시 update_ready.json 복원 — UI에 에러 메시지 표시
                try:
                    _ver = update_data.get("version", _exe.stem)
                    _update_info = {"ready": True, "downloading": False,
                                    "version": _ver, "exe_path": str(_exe),
                                    "error": str(ex)}
                    with open(data_dir / "update_ready.json", "w", encoding="utf-8") as ef:
                        json.dump(_update_info, ef)
                except OSError:
                    pass

        # daemon=False: 메인 프로세스 종료돼도 업데이트 스레드는 완료까지 실행
        threading.Thread(target=_do_apply, daemon=False).start()
    except Exception as e:
        handler.wfile.write(json.dumps({"success": False, "error": str(e)}).encode('utf-8'))
        handler.wfile.flush()


def soft_update_apply(handler, data_dir: Path, src_dir: Path) -> None:
    """POST /api/soft-update/apply — 경량 소스 채널 적용: git reset --hard origin/main + EXE 재시작.
    [제약] apply_soft_update가 성공 시 os._exit로 프로세스를 끝내므로 응답을 먼저 보낸 뒤
      별도 스레드에서 실행(EXE 풀빌드 apply와 동일한 응답-우선 패턴).
    """
    handler.send_response(200)
    handler.send_header('Content-Type', 'application/json;charset=utf-8')
    handler.send_header('Access-Control-Allow-Origin', handler._cors_origin())
    handler.end_headers()
    try:
        from soft_updater import apply_soft_update
        _src = src_dir

        def _do_soft_apply():
            time.sleep(0.3)  # 응답이 클라이언트에 도달할 시간 확보 후 reset/재시작
            try:
                result = apply_soft_update(_src)
                if not result.get("ok"):
                    with open(data_dir / "soft_update_ready.json", "w", encoding="utf-8") as ef:
                        json.dump({"ready": False, "error": result.get("error", "적용 실패")},
                                  ef, ensure_ascii=False)
            except Exception as ex:
                print(f"[soft-update] apply 실패: {ex}")

        handler.wfile.write(json.dumps({"success": True}).encode('utf-8'))
        handler.wfile.flush()
        threading.Thread(target=_do_soft_apply, daemon=False).start()
    except Exception as e:
        handler.wfile.write(json.dumps({"success": False, "error": str(e)}).encode('utf-8'))
        handler.wfile.flush()
