"""그룹 채팅 AI 에이전트 — LLM CLI를 subprocess로 호출하여 깨끗하게 응답 받기.

PTY 터미널을 사용하지 않음. 각 LLM의 non-interactive 모드를 사용:
  - Claude: claude -p "prompt" --output-format json
  - Gemini: gemini -p "prompt"
  - Codex:  codex exec "prompt"

대시보드 시작 시 자동으로 squad를 백그라운드에서 실행합니다.
"""
import asyncio
import json
import subprocess
import threading
import time
from llm_group_chat.protocol import ChatMessage

# 에이전트 프로세스 관리
_squad_running = False
_squad_agents: list[dict] = []

# 각 에이전트의 대화 히스토리 (컨텍스트 유지)
_agent_history: dict[str, list[dict]] = {}
_MAX_HISTORY = 16


async def _call_cli(cli: str, prompt: str) -> str:
    """LLM CLI non-interactive 호출.

    Windows에서 .cmd 파일 호환을 위해 shell=True 사용.
    프롬프트는 stdin pipe로 전달.
    """
    try:
        if cli == "claude":
            cmd = "claude -p --output-format text"
        elif cli == "gemini":
            cmd = "gemini"
        elif cli == "codex":
            cmd = "codex exec"
        else:
            cmd = cli

        proc = await asyncio.create_subprocess_shell(
            cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0x08000000),
        )
        stdout, _ = await asyncio.wait_for(
            proc.communicate(input=prompt.encode("utf-8")),
            timeout=120,
        )
        return stdout.decode("utf-8", errors="replace").strip()
    except asyncio.TimeoutError:
        return ""
    except Exception as e:
        return f"[오류] {e}"


# CLI 목록
_SUPPORTED_CLIS = {"claude", "gemini", "codex"}


def _build_prompt(name: str, cli: str, sender: str, content: str) -> str:
    """그룹 채팅 컨텍스트를 포함한 프롬프트 생성."""
    history = _agent_history.get(name, [])

    # 최근 대화 히스토리 포맷
    context_lines = []
    for h in history[-8:]:
        context_lines.append(f"[{h['from']}] {h['text']}")

    context = "\n".join(context_lines) if context_lines else "(대화 시작)"

    return f"""당신은 '{name}'이라는 이름으로 그룹 채팅에 참여 중입니다.
다른 참여자들과 자연스럽게 대화하세요. 짧고 친근하게 답하세요 (1-3문장).
이름표 없이 답변만 하세요.

최근 대화:
{context}
[{sender}] {content}

위 대화에 이어서 자연스럽게 답하세요:"""


def _add_to_history(name: str, sender: str, text: str):
    """에이전트 히스토리에 메시지 추가."""
    if name not in _agent_history:
        _agent_history[name] = []
    _agent_history[name].append({"from": sender, "text": text[:500]})
    if len(_agent_history[name]) > _MAX_HISTORY:
        _agent_history[name] = _agent_history[name][-_MAX_HISTORY:]


async def _agent_loop(name: str, cli: str, host: str, port: int):
    """단일 에이전트 메인 루프 — WS 연결 + 메시지 수신 + LLM 응답."""
    import websockets

    uri = f"ws://{host}:{port}"
    if cli not in _SUPPORTED_CLIS:
        print(f"[{name}] 지원하지 않는 CLI: {cli}")
        return

    while True:
        try:
            async with websockets.connect(uri) as ws:
                # 입장
                join_msg = ChatMessage(type="join", sender=name, content="")
                await ws.send(join_msg.to_json())
                print(f"[{name}] 그룹 채팅 참여 ({cli})")

                async for raw in ws:
                    try:
                        msg = ChatMessage.from_json(raw)
                    except Exception:
                        continue

                    # 자기 메시지, 시스템, 입퇴장, bridge 무시
                    if msg.sender == name or msg.type != "message" or msg.sender == "bridge":
                        continue

                    # 다른 에이전트 메시지도 무시 (무한루프 방지)
                    # 사용자(dashboard 등)의 메시지에만 응답
                    if any(msg.sender.endswith(f"-{i}") for i in range(1, 9)):
                        # 다른 에이전트 메시지 → 히스토리에만 추가, 응답 안 함
                        _add_to_history(name, msg.sender, msg.content)
                        continue

                    print(f"[{name}] 수신 ← {msg.sender}: {msg.content[:60]}")

                    # 히스토리에 추가
                    _add_to_history(name, msg.sender, msg.content)

                    # LLM 호출
                    prompt = _build_prompt(name, cli, msg.sender, msg.content)
                    reply = await _call_cli(cli, prompt)

                    if reply and reply.strip() and not reply.startswith("[오류]"):
                        # 히스토리에 응답 추가
                        _add_to_history(name, name, reply)

                        # 그룹챗에 전송
                        reply_msg = ChatMessage(type="message", sender=name, content=reply)
                        await ws.send(reply_msg.to_json())
                        print(f"[{name}] 응답 → {reply[:60]}")
                    elif reply.startswith("[오류]"):
                        print(f"[{name}] {reply}")

        except Exception as e:
            print(f"[{name}] 연결 끊김, 5초 후 재시도: {e}")
            await asyncio.sleep(5)


def run_agent(name: str, cli: str, host: str = "localhost", port: int = 8765):
    """단일 에이전트 실행 (동기 래퍼)."""
    asyncio.run(_agent_loop(name, cli, host, port))


async def _squad_async(agents: list[dict], host: str, port: int):
    """여러 에이전트를 동시에 실행."""
    tasks = []
    for agent in agents:
        task = asyncio.create_task(
            _agent_loop(name=agent["name"], cli=agent["cli"], host=host, port=port)
        )
        tasks.append(task)
        await asyncio.sleep(1)  # 연결 간격

    print(f"[스쿼드] {len(agents)}개 에이전트 시작됨: {', '.join(a['name'] for a in agents)}")
    await asyncio.gather(*tasks, return_exceptions=True)


def run_squad(agents: list[dict], host: str = "localhost", port: int = 8765):
    """여러 에이전트를 동시에 실행 (동기 래퍼)."""
    global _squad_running, _squad_agents
    _squad_running = True
    _squad_agents = agents
    asyncio.run(_squad_async(agents, host, port))


def start_squad_background(agents: list[dict], host: str = "127.0.0.1", port: int = 8765):
    """백그라운드 스레드에서 스쿼드 시작 (대시보드 서버에서 호출)."""
    global _squad_running, _squad_agents
    if _squad_running:
        print("[스쿼드] 이미 실행 중")
        return

    _squad_running = True
    _squad_agents = agents

    def _run():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(_squad_async(agents, host, port))

    threading.Thread(target=_run, daemon=True, name="GroupChatSquad").start()


def get_squad_status() -> dict:
    """스쿼드 상태 반환."""
    return {
        "running": _squad_running,
        "agents": [a["name"] for a in _squad_agents],
    }
