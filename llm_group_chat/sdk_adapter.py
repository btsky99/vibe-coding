"""SDK 어댑터 — Claude Code / Gemini CLI / Codex SDK를 통일된 인터페이스로.

각 SDK의 차이를 추상화하여 동일한 방식으로 호출할 수 있게 합니다.
모든 SDK는 진짜 에이전트 — 파일 편집, bash 실행, 코드 수정 가능.

사용법:
    adapter = create_adapter("claude")
    response = await adapter.ask("이 코드의 버그를 찾아줘")
    print(response)
"""
import asyncio
from abc import ABC, abstractmethod


class LLMAdapter(ABC):
    """LLM SDK 통합 인터페이스."""

    def __init__(self, name: str, cwd: str = "."):
        self.name = name
        self.cwd = cwd

    @abstractmethod
    async def ask(self, prompt: str) -> str:
        """프롬프트를 보내고 응답을 받음. 진짜 에이전트로 동작."""
        pass

    @abstractmethod
    async def ask_with_context(self, prompt: str, system_prompt: str = "") -> str:
        """시스템 프롬프트 + 사용자 프롬프트로 응답."""
        pass


class ClaudeAdapter(LLMAdapter):
    """Claude Code SDK 어댑터 — 진짜 Claude Code 에이전트."""

    async def ask(self, prompt: str) -> str:
        from claude_code_sdk import query, ClaudeCodeOptions

        result_parts = []
        try:
            async for msg in query(
                prompt=prompt,
                options=ClaudeCodeOptions(
                    max_turns=3,
                    cwd=self.cwd,
                    permission_mode="auto",
                ),
            ):
                msg_type = getattr(msg, 'type', '')
                if msg_type == 'text':
                    result_parts.append(msg.content)
        except Exception as e:
            err_str = str(e)
            # rate_limit 등 파싱 에러는 무시하고 수집된 결과 반환
            if 'Unknown message type' in err_str:
                pass
            else:
                return f"[Claude 오류] {err_str}"

        return "\n".join(result_parts) if result_parts else ""

    async def ask_with_context(self, prompt: str, system_prompt: str = "") -> str:
        from claude_code_sdk import query, ClaudeCodeOptions

        result_parts = []
        try:
            async for msg in query(
                prompt=prompt,
                options=ClaudeCodeOptions(
                    max_turns=3,
                    cwd=self.cwd,
                    permission_mode="auto",
                    system_prompt=system_prompt or None,
                ),
            ):
                msg_type = getattr(msg, 'type', '')
                if msg_type == 'text':
                    result_parts.append(msg.content)
        except Exception as e:
            if 'Unknown message type' not in str(e):
                return f"[Claude 오류] {e}"

        return "\n".join(result_parts) if result_parts else ""


class GeminiAdapter(LLMAdapter):
    """Gemini CLI SDK 어댑터 — 진짜 Gemini 에이전트."""

    async def ask(self, prompt: str) -> str:
        from gemini_cli_sdk import query, GeminiOptions

        result_parts = []
        try:
            async for msg in query(
                prompt=prompt,
                options=GeminiOptions(
                    max_turns=3,
                    cwd=self.cwd,
                    yolo=True,
                ),
            ):
                msg_type = getattr(msg, 'type', '')
                if msg_type == 'text':
                    result_parts.append(msg.content)
        except Exception as e:
            if 'Unknown message type' not in str(e):
                return f"[Gemini 오류] {e}"

        return "\n".join(result_parts) if result_parts else ""

    async def ask_with_context(self, prompt: str, system_prompt: str = "") -> str:
        from gemini_cli_sdk import query, GeminiOptions

        result_parts = []
        try:
            async for msg in query(
                prompt=prompt,
                options=GeminiOptions(
                    max_turns=3,
                    cwd=self.cwd,
                    yolo=True,
                    system_prompt=system_prompt or None,
                ),
            ):
                msg_type = getattr(msg, 'type', '')
                if msg_type == 'text':
                    result_parts.append(msg.content)
        except Exception as e:
            if 'Unknown message type' not in str(e):
                return f"[Gemini 오류] {e}"

        return "\n".join(result_parts) if result_parts else ""


class CodexAdapter(LLMAdapter):
    """Codex SDK 어댑터 — 진짜 Codex 에이전트."""

    def __init__(self, name: str, cwd: str = "."):
        super().__init__(name, cwd)
        self._codex = None
        self._thread = None

    def _ensure_thread(self):
        """Codex 스레드 초기화 (대화 유지)."""
        if self._codex is None:
            from codex_sdk import Codex, ThreadOptions
            self._codex = Codex()
            self._thread = self._codex.start_thread(
                ThreadOptions(working_directory=self.cwd)
            )

    async def ask(self, prompt: str) -> str:
        try:
            self._ensure_thread()
            # Codex는 동기 API이므로 executor에서 실행
            loop = asyncio.get_event_loop()
            turn = await loop.run_in_executor(
                None, self._thread.run_sync, prompt
            )
            return str(turn) if turn else ""
        except Exception as e:
            return f"[Codex 오류] {e}"

    async def ask_with_context(self, prompt: str, system_prompt: str = "") -> str:
        # Codex는 시스템 프롬프트를 컨텍스트에 포함
        full_prompt = f"{system_prompt}\n\n{prompt}" if system_prompt else prompt
        return await self.ask(full_prompt)


# ── CLI subprocess 폴백 (SDK 실패 시) ──

class CLIFallbackAdapter(LLMAdapter):
    """CLI subprocess 폴백 — SDK가 안 될 때 claude -p / gemini -p 사용."""

    def __init__(self, name: str, cli: str, cwd: str = "."):
        super().__init__(name, cwd)
        self.cli = cli

    async def ask(self, prompt: str) -> str:
        import subprocess

        # 프롬프트에서 쉘에 위험한 문자 이스케이프
        safe_prompt = prompt.replace('"', '\\"').replace('\n', ' ')
        # 너무 긴 프롬프트는 자르기 (CLI 인자 길이 제한)
        if len(safe_prompt) > 3000:
            safe_prompt = safe_prompt[:3000]

        try:
            if self.cli == "claude":
                # Claude: stdin pipe 지원 — 가장 안정적
                cmd = "claude -p --output-format text"
                proc = await asyncio.create_subprocess_shell(
                    cmd,
                    stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    cwd=self.cwd,
                    creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0x08000000),
                )
                stdout, _ = await asyncio.wait_for(
                    proc.communicate(input=prompt.encode("utf-8")),
                    timeout=120,
                )
            elif self.cli == "gemini":
                # Gemini: -p 인자로 전달 + -o text
                # 프롬프트에 간결 응답 지시 포함 (GEMINI.md 읽어서 장황해지는 것 방지)
                cmd = f'gemini -p "{safe_prompt}" -o text'
                proc = await asyncio.create_subprocess_shell(
                    cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    cwd=self.cwd,
                    creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0x08000000),
                )
                stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=120)
            elif self.cli == "codex":
                # Codex: exec + stdin pipe
                cmd = "codex exec"
                proc = await asyncio.create_subprocess_shell(
                    cmd,
                    stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    cwd=self.cwd,
                    creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0x08000000),
                )
                stdout, _ = await asyncio.wait_for(
                    proc.communicate(input=prompt.encode("utf-8")),
                    timeout=120,
                )
            else:
                cmd = f'{self.cli} -p "{safe_prompt}"'
                proc = await asyncio.create_subprocess_shell(
                    cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    cwd=self.cwd,
                    creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0x08000000),
                )
                stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=120)

            text = stdout.decode("utf-8", errors="replace").strip()

            # Gemini CLI hook/시스템 로그 필터링
            if text and self.cli == "gemini":
                filtered = []
                for line in text.split("\n"):
                    # hook 실행 로그, 인증 로그 등 제거
                    if any(skip in line for skip in [
                        "Created execution plan",
                        "Expanding hook command",
                        "Hook execution for",
                        "hook(s) to execute",
                        "Loaded cached credentials",
                        "total duration:",
                    ]):
                        continue
                    filtered.append(line)
                text = "\n".join(filtered).strip()

            return text
        except asyncio.TimeoutError:
            return "[타임아웃]"
        except Exception as e:
            return f"[CLI 오류] {e}"

    async def ask_with_context(self, prompt: str, system_prompt: str = "") -> str:
        full = f"{system_prompt}\n\n{prompt}" if system_prompt else prompt
        return await self.ask(full)


def create_adapter(cli: str, name: str = "", cwd: str = ".", use_sdk: bool = True) -> LLMAdapter:
    """CLI 이름으로 적절한 어댑터 생성.

    SDK 지원 현황:
    - Claude: claude-code-sdk 사용 (진짜 에이전트, 파일 편집/bash 가능)
    - Gemini: SDK 없음 → CLI subprocess 폴백 (gemini -p)
    - Codex: SDK 없음 → CLI subprocess 폴백 (codex exec)
    """
    if not name:
        name = cli

    if not use_sdk:
        return CLIFallbackAdapter(name, cli, cwd)

    # 현재 상태:
    # - Claude SDK: rate limit 시 빈 응답 반환 → CLI 폴백이 안정적
    # - Gemini/Codex SDK: 미지원 → CLI 폴백
    # 향후 SDK 안정화 시 Claude SDK 재활성화 가능
    if cli == "claude":
        # SDK가 안정화될 때까지 CLI 폴백 사용
        # SDK 사용하려면: return ClaudeAdapter(name, cwd)
        return CLIFallbackAdapter(name, cli, cwd)
    else:
        return CLIFallbackAdapter(name, cli, cwd)
