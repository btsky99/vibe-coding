"""새로운 그룹챗 에이전트 터미널 — SDK로 진짜 에이전트 실행.

기존 CLI를 래핑하는 게 아니라, SDK로 직접 에이전트를 실행합니다.
에이전트의 모든 행동(파일 읽기, 코드 수정, bash 실행)이 실시간으로 표시됩니다.

동작:
1. claude-code-sdk / gemini-cli-sdk로 진짜 에이전트 실행
2. 에이전트의 도구 사용(파일 편집, bash 등)을 실시간 스트리밍
3. WebSocket 그룹 채팅 연결 — 다른 에이전트와 대화 공유
4. PostgreSQL 공유 히스토리

입력:
  (텍스트)        → 에이전트에게 작업 지시 (파일 편집, bash 등 가능)
  /chat (메시지)  → 그룹챗에 전송
  /share          → 마지막 응답을 그룹에 공유
  /auto on|off    → 그룹 자동 응답
  /help           → 명령어
  /quit           → 종료
"""
import asyncio
import sys
import time
from llm_group_chat.protocol import ChatMessage

# ANSI 색상
C_RESET = "\033[0m"
C_CYAN = "\033[36m"
C_GREEN = "\033[32m"
C_YELLOW = "\033[33m"
C_RED = "\033[31m"
C_MAGENTA = "\033[35m"
C_BLUE = "\033[34m"
C_DIM = "\033[2m"
C_BOLD = "\033[1m"

_COLORS = [C_CYAN, C_GREEN, C_YELLOW, C_RED, C_MAGENTA, C_BLUE, "\033[96m", "\033[92m"]
_color_map: dict[str, str] = {}


def _color(name: str) -> str:
    if name not in _color_map:
        _color_map[name] = _COLORS[len(_color_map) % len(_COLORS)]
    return _color_map[name]


def _ts() -> str:
    return time.strftime("%H:%M:%S")


async def _run_claude_agent(prompt: str, cwd: str) -> str:
    """Claude Code SDK로 진짜 에이전트 실행 — 도구 사용 포함, 실시간 출력."""
    from claude_code_sdk import query, ClaudeCodeOptions

    result_parts = []
    try:
        async for msg in query(
            prompt=prompt,
            options=ClaudeCodeOptions(
                max_turns=5,
                cwd=cwd,
                permission_mode="auto",
            ),
        ):
            msg_type = getattr(msg, 'type', '')

            if msg_type == 'text':
                result_parts.append(msg.content)
                # 실시간 출력
                print(f"{C_GREEN}{msg.content}{C_RESET}", end="", flush=True)

            elif msg_type == 'tool_use':
                # 도구 사용 표시 (파일 읽기, bash 실행 등)
                tool_name = getattr(msg, 'name', 'tool')
                print(f"\n{C_DIM}[{tool_name}]{C_RESET} ", end="", flush=True)

            elif msg_type == 'tool_result':
                # 도구 결과 (짧게 표시)
                content = str(getattr(msg, 'content', ''))[:200]
                if content:
                    print(f"{C_DIM}{content[:100]}...{C_RESET}" if len(content) > 100 else f"{C_DIM}{content}{C_RESET}")

    except Exception as e:
        err = str(e)
        if 'Unknown message type' in err:
            pass  # rate_limit 등 파싱 에러 무시
        elif 'rate' in err.lower():
            result_parts.append("[rate limit — 잠시 후 다시 시도하세요]")
        else:
            result_parts.append(f"[오류] {err}")

    print()  # 줄바꿈
    return "\n".join(result_parts) if result_parts else ""


async def _run_gemini_agent(prompt: str, cwd: str) -> str:
    """Gemini CLI SDK로 에이전트 실행."""
    try:
        from gemini_cli_sdk import query as gquery, GeminiOptions

        result_parts = []
        async for msg in gquery(
            prompt=prompt,
            options=GeminiOptions(
                max_turns=5,
                cwd=cwd,
                yolo=True,
            ),
        ):
            msg_type = getattr(msg, 'type', '')
            if msg_type == 'text':
                result_parts.append(msg.content)
                print(f"{C_GREEN}{msg.content}{C_RESET}", end="", flush=True)
            elif msg_type == 'tool_use':
                tool_name = getattr(msg, 'name', 'tool')
                print(f"\n{C_DIM}[{tool_name}]{C_RESET} ", end="", flush=True)

        print()
        return "\n".join(result_parts) if result_parts else ""

    except Exception as e:
        # SDK 실패 시 CLI 폴백
        return await _run_cli_fallback("gemini", prompt, cwd)


async def _run_codex_agent(prompt: str, cwd: str) -> str:
    """Codex CLI subprocess 폴백."""
    return await _run_cli_fallback("codex", prompt, cwd)


async def _run_cli_fallback(cli: str, prompt: str, cwd: str) -> str:
    """CLI subprocess 폴백 — SDK가 안 될 때."""
    import subprocess

    safe_prompt = prompt.replace('"', '\\"').replace('\n', ' ')
    if len(safe_prompt) > 3000:
        safe_prompt = safe_prompt[:3000]

    try:
        if cli == "claude":
            cmd = "claude -p --output-format text"
            use_stdin = True
        elif cli == "gemini":
            cmd = f'gemini -p "{safe_prompt}" -o text'
            use_stdin = False
        elif cli == "codex":
            cmd = "codex exec"
            use_stdin = True
        else:
            cmd = f'{cli} -p "{safe_prompt}"'
            use_stdin = False

        proc = await asyncio.create_subprocess_shell(
            cmd,
            stdin=asyncio.subprocess.PIPE if use_stdin else None,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0x08000000),
        )
        if use_stdin:
            stdout, _ = await asyncio.wait_for(
                proc.communicate(input=prompt.encode("utf-8")), timeout=120
            )
        else:
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=120)

        text = stdout.decode("utf-8", errors="replace").strip()

        # Gemini hook 로그 필터링
        if cli == "gemini" and text:
            lines = [l for l in text.split("\n") if not any(s in l for s in [
                "Created execution plan", "Expanding hook", "Hook execution",
                "hook(s) to execute", "Loaded cached credentials", "total duration:",
            ])]
            text = "\n".join(lines).strip()

        return text
    except asyncio.TimeoutError:
        return "[타임아웃]"
    except Exception as e:
        return f"[CLI 오류] {e}"


# 에이전트 실행 함수 매핑
_AGENT_RUNNERS = {
    "claude": _run_claude_agent,
    "gemini": _run_gemini_agent,
    "codex": _run_codex_agent,
}


class GroupChatTerminal:
    """새로운 에이전트 터미널 — SDK + 그룹 채팅."""

    def __init__(self, name: str, cli: str, host: str, port: int, cwd: str = "D:/vibe-coding"):
        self.name = name
        self.cli = cli
        self.host = host
        self.port = port
        self.cwd = cwd
        self.ws = None
        self.auto_reply = True
        self.last_reply = ""
        self._run_agent = _AGENT_RUNNERS.get(cli, lambda p, c: _run_cli_fallback(cli, p, c))

    def _print_group(self, sender: str, content: str, msg_type: str = "message"):
        c = _color(sender)
        t = _ts()
        if msg_type == "system":
            print(f"  {C_DIM}[그룹 {t}] ** {content} **{C_RESET}")
        elif msg_type == "join":
            print(f"  {C_DIM}[그룹 {t}] {c}>> {sender} 입장{C_RESET}")
        elif msg_type == "leave":
            print(f"  {C_DIM}[그룹 {t}] {c}<< {sender} 퇴장{C_RESET}")
        else:
            print(f"  {C_DIM}[그룹]{C_RESET} {c}{C_BOLD}{sender}{C_RESET}: {content}")

    def _print_status(self, text: str):
        print(f"{C_DIM}[{_ts()}] {text}{C_RESET}")

    def _save_to_db(self, sender: str, content: str):
        try:
            from llm_group_chat.shared_history import save_message
            save_message(sender, content)
        except Exception:
            pass

    def _get_group_context(self) -> str:
        try:
            from llm_group_chat.shared_history import get_context_prompt
            return get_context_prompt(self.name, limit=10)
        except Exception:
            return ""

    async def _ws_receive(self):
        """WS 수신 루프 — 그룹 메시지 표시 + 자동 응답."""
        async for raw in self.ws:
            try:
                msg = ChatMessage.from_json(raw)
            except Exception:
                continue

            if msg.sender == self.name:
                continue

            self._print_group(msg.sender, msg.content, msg.type)

            if msg.type == "message":
                self._save_to_db(msg.sender, msg.content)

            # 자동 응답 (사용자 메시지에만)
            is_agent = msg.sender.startswith("T") and "-" in msg.sender
            if msg.type == "message" and self.auto_reply and msg.sender != "bridge" and not is_agent:
                self._print_status(f"  {self.cli} 에이전트 실행 중...")

                ctx = self._get_group_context()
                prompt = f"[중요] 파일을 읽거나 도구를 사용하지 마세요. 대화만 하세요.\n당신은 '{self.name}'입니다. 한국어로 1-2문장으로만 답하세요.\n\n최근 대화:\n{ctx}\n\n답변:"

                reply = await self._run_agent(prompt, self.cwd)

                if reply and not reply.startswith("["):
                    self._save_to_db(self.name, reply)
                    reply_msg = ChatMessage(type="message", sender=self.name, content=reply)
                    await self.ws.send(reply_msg.to_json())
                    self._print_group(self.name, reply)
                    self.last_reply = reply

    async def _user_input(self):
        """사용자 입력 — 에이전트 작업 지시 + 그룹챗."""
        loop = asyncio.get_event_loop()

        while True:
            try:
                line = await loop.run_in_executor(None, sys.stdin.readline)
                if not line:
                    break
                content = line.strip()
                if not content:
                    continue

                if content.lower() in ("/quit", "/exit", "/q"):
                    break

                elif content.startswith("/chat "):
                    chat_msg = content[6:].strip()
                    if chat_msg:
                        msg = ChatMessage(type="message", sender=self.name, content=chat_msg)
                        await self.ws.send(msg.to_json())
                        self._print_group(self.name, chat_msg)
                        self._save_to_db(self.name, chat_msg)

                elif content == "/share":
                    if self.last_reply:
                        shared = f"[{self.cli} 결과 공유] {self.last_reply[:500]}"
                        msg = ChatMessage(type="message", sender=self.name, content=shared)
                        await self.ws.send(msg.to_json())
                        self._print_status("그룹에 공유 완료")
                    else:
                        self._print_status("공유할 내용 없음")

                elif content.startswith("/auto"):
                    parts = content.split()
                    if len(parts) >= 2:
                        self.auto_reply = parts[1].lower() == "on"
                    self._print_status(f"자동 응답: {'ON' if self.auto_reply else 'OFF'}")

                elif content == "/help":
                    print(f"""
{C_BOLD}━━━ 명령어 ━━━{C_RESET}
  (텍스트)        {C_GREEN}{self.cli} 에이전트에게 작업 지시{C_RESET}
                  파일 편집, bash 실행, 코드 분석 등 가능
  {C_CYAN}/chat{C_RESET} (메시지)  그룹챗에 메시지 전송
  {C_CYAN}/share{C_RESET}         마지막 결과를 그룹에 공유
  {C_CYAN}/auto{C_RESET} on|off   그룹 자동 응답 켜기/끄기
  {C_CYAN}/quit{C_RESET}          종료
""")

                else:
                    # 에이전트에게 작업 지시 — 진짜 에이전트 실행
                    print(f"{C_CYAN}[나→{self.cli}]{C_RESET} {content}")
                    self._print_status(f"{self.cli} 에이전트 실행 중...")

                    reply = await self._run_agent(content, self.cwd)
                    if reply:
                        self.last_reply = reply
                    else:
                        print(f"{C_RED}(응답 없음){C_RESET}")

            except (EOFError, KeyboardInterrupt):
                break

    async def run(self):
        """터미널 메인 루프."""
        import websockets

        uri = f"ws://{self.host}:{self.port}"

        print(f"""
{C_BOLD}{'━'*55}
  에이전트 그룹 채팅 터미널
{'━'*55}{C_RESET}
  이름:     {C_CYAN}{self.name}{C_RESET}
  에이전트: {C_GREEN}{self.cli}{C_RESET}
  작업폴더: {self.cwd}
  자동응답: {C_YELLOW}ON{C_RESET}

  {C_DIM}텍스트 입력 → {self.cli} 에이전트 실행 (파일 편집/bash 가능){C_RESET}
  {C_DIM}/chat 메시지 → 그룹챗 | /share → 결과 공유{C_RESET}
  {C_DIM}/help → 전체 명령어 | /quit → 종료{C_RESET}
{'━'*55}
""")

        while True:
            try:
                async with websockets.connect(uri) as ws:
                    self.ws = ws
                    join_msg = ChatMessage(type="join", sender=self.name, content="")
                    await ws.send(join_msg.to_json())
                    self._print_status("그룹 채팅 연결됨!")

                    recv_task = asyncio.create_task(self._ws_receive())
                    input_task = asyncio.create_task(self._user_input())

                    done, pending = await asyncio.wait(
                        [recv_task, input_task],
                        return_when=asyncio.FIRST_COMPLETED,
                    )
                    for task in pending:
                        task.cancel()
                    break

            except Exception as e:
                self._print_status(f"연결 실패: {e} — 3초 후 재시도")
                await asyncio.sleep(3)


def run_terminal(name: str, cli: str, host: str = "localhost", port: int = 8765,
                 auto_reply: bool = True, **kwargs):
    """에이전트 그룹챗 터미널 실행."""
    term = GroupChatTerminal(name, cli, host, port)
    term.auto_reply = auto_reply
    asyncio.run(term.run())
