def _extract_result_text(tool_result) -> str:
    if isinstance(tool_result, str):
        return _snippet(tool_result)
    if isinstance(tool_result, dict):
        # Gemini CLI의 run_shell_command 결과는 stdout, stderr, output 등을 포함할 수 있음
        for key in ("stdout", "output", "content", "message", "result", "stderr"):
            value = tool_result.get(key)
            if value:
                return _snippet(str(value))
        return _snippet(json.dumps(tool_result, ensure_ascii=False))
    return _snippet(str(tool_result))


def main() -> None:
    # Windows 환경에서 PAGER=cat으로 인해 psql/git 등이 먹통되는 문제 방지
    if sys.platform == "win32":
        os.environ["PAGER"] = ""

    _ensure_dashboard_running()
    _send_heartbeat()

    try:
        raw = sys.stdin.buffer.read().decode("utf-8", errors="replace")
        if not raw.strip():
            _success_response()
            return
        payload = json.loads(raw)
    except Exception:
        _success_response()
        return

    event = str(payload.get("hook_event_name") or "")

    if event == "BeforeAgent":
        prompt = str(payload.get("prompt") or "")
        additional_context = _build_additional_context(prompt)
        _register_prompt_task(prompt)
        if additional_context:
            _hook_response(decision="allow", context=additional_context)
        else:
            _hook_response(decision="allow")
        return

    try:
        from hive_bridge import log_task, log_thought
    except ImportError:
        _success_response()
        return

    tool_name = _get_tool_name(payload)
    tool_input = _get_tool_input(payload)

    if event == "BeforeTool":
        _log_tool_start(log_task, tool_name, tool_input)

    elif event == "AfterTool":
        tool_result = payload.get("tool_result") or payload.get("result") or payload.get("output") or payload.get("response") or {}
        _log_tool_finish(log_task, log_thought, tool_name, tool_input, tool_result)
        _refresh_hivemind_doc(force=False)

    elif event == "SessionEnd":
        log_task("Gemini", "Session end")
        try:
            from src.pg_store import bulk_update_tasks

            bulk_update_tasks("gemini", ["pending", "in_progress"], "done")
        except Exception:
            pass
        _send_session_summary()
        _refresh_hivemind_doc(force=True)

    _success_response()


if __name__ == "__main__":
    main()
