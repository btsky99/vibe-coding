"""WebSocket 채팅 클라이언트 - 터미널에서 채팅 참여"""
import asyncio
import sys
from llm_group_chat.protocol import ChatMessage


async def _receive_loop(ws):
    """서버에서 메시지 수신 + 터미널에 출력"""
    try:
        async for raw in ws:
            msg = ChatMessage.from_json(raw)
            print(f"\r{msg.display()}")
            print("> ", end="", flush=True)
    except Exception:
        print("\n[연결 종료]")


async def _input_loop(ws, name):
    """사용자 입력을 받아 서버로 전송"""
    loop = asyncio.get_event_loop()
    while True:
        try:
            # 비동기 stdin 읽기
            line = await loop.run_in_executor(None, sys.stdin.readline)
            if not line:
                break
            content = line.strip()
            if not content:
                continue
            if content.lower() in ("/quit", "/exit", "/q"):
                break

            msg = ChatMessage(type="message", sender=name, content=content)
            await ws.send(msg.to_json())
        except (EOFError, KeyboardInterrupt):
            break


async def _run_client(name: str, host: str, port: int):
    """클라이언트 메인 루프"""
    import websockets
    uri = f"ws://{host}:{port}"

    async with websockets.connect(uri) as ws:
        # 입장 메시지 전송
        join_msg = ChatMessage(type="join", sender=name, content="")
        await ws.send(join_msg.to_json())

        print(f"[{name}] 채팅 참여 완료! 메시지를 입력하세요. (/quit으로 종료)")
        print("> ", end="", flush=True)

        # 수신 + 입력 동시 실행
        receive_task = asyncio.create_task(_receive_loop(ws))
        input_task = asyncio.create_task(_input_loop(ws, name))

        # 둘 중 하나가 끝나면 다른 것도 종료
        done, pending = await asyncio.wait(
            [receive_task, input_task],
            return_when=asyncio.FIRST_COMPLETED
        )
        for task in pending:
            task.cancel()

    print(f"[{name}] 채팅 종료")


def run_client(name: str, host: str = "localhost", port: int = 8765):
    """클라이언트 실행 (동기 래퍼)"""
    asyncio.run(_run_client(name, host, port))


async def _send_one(name: str, msg: str, host: str, port: int):
    """메시지 하나만 보내고 종료"""
    import websockets
    uri = f"ws://{host}:{port}"

    async with websockets.connect(uri) as ws:
        # 입장
        join_msg = ChatMessage(type="join", sender=name, content="")
        await ws.send(join_msg.to_json())

        # 메시지 전송
        chat_msg = ChatMessage(type="message", sender=name, content=msg)
        await ws.send(chat_msg.to_json())

        # 잠시 대기 후 종료 (브로드캐스트 완료 대기)
        await asyncio.sleep(0.5)

    print(f"[{name}] 메시지 전송 완료: {msg}")


def send_one(name: str, msg: str, host: str = "localhost", port: int = 8765):
    """원샷 메시지 전송 (동기 래퍼)"""
    asyncio.run(_send_one(name, msg, host, port))


# --- 파이프 모드 (LLM 연동용) ---

async def _pipe_receive_loop(ws):
    """파이프 모드: 수신 메시지를 JSON 라인으로 stdout에 출력"""
    try:
        async for raw in ws:
            # JSON 그대로 한 줄씩 출력 (LLM이 파싱하기 쉽게)
            print(raw, flush=True)
    except Exception:
        pass


async def _pipe_input_loop(ws, name):
    """파이프 모드: stdin에서 한 줄씩 읽어 서버로 전송

    입력 형식:
    - 일반 텍스트 → ChatMessage로 감싸서 전송
    - JSON (type 필드 포함) → 그대로 전송
    """
    loop = asyncio.get_event_loop()
    while True:
        try:
            line = await loop.run_in_executor(None, sys.stdin.readline)
            if not line:
                break
            content = line.strip()
            if not content:
                continue

            # JSON 입력인지 확인
            try:
                import json
                parsed = json.loads(content)
                if isinstance(parsed, dict) and "type" in parsed:
                    # 완전한 메시지 JSON → 그대로 전송
                    await ws.send(content)
                    continue
            except (json.JSONDecodeError, KeyError):
                pass

            # 일반 텍스트 → ChatMessage로 감싸서 전송
            msg = ChatMessage(type="message", sender=name, content=content)
            await ws.send(msg.to_json())
        except (EOFError, KeyboardInterrupt):
            break


async def _run_pipe(name: str, host: str, port: int):
    """파이프 모드 메인 루프 (프롬프트 없이 순수 stdin/stdout)"""
    import websockets
    uri = f"ws://{host}:{port}"

    async with websockets.connect(uri) as ws:
        # 입장
        join_msg = ChatMessage(type="join", sender=name, content="")
        await ws.send(join_msg.to_json())

        # 수신 + 입력 동시 실행 (프롬프트 없음)
        receive_task = asyncio.create_task(_pipe_receive_loop(ws))
        input_task = asyncio.create_task(_pipe_input_loop(ws, name))

        done, pending = await asyncio.wait(
            [receive_task, input_task],
            return_when=asyncio.FIRST_COMPLETED
        )
        for task in pending:
            task.cancel()


def run_pipe(name: str, host: str = "localhost", port: int = 8765):
    """파이프 모드 실행 (동기 래퍼)"""
    asyncio.run(_run_pipe(name, host, port))


# --- 자동 응답 모드 (LLM CLI 연동용) ---

async def _auto_reply_loop(ws, name: str, command: str):
    """수신 메시지마다 외부 LLM CLI 명령어를 실행하여 자동 응답

    동작 방식:
    1. 다른 참여자의 메시지를 수신
    2. command에 {msg}, {sender}, {room} 플레이스홀더를 치환
    3. subprocess로 실행하여 stdout을 응답으로 전송

    예시 command:
    - 'claude -p "{msg}"'
    - 'echo "수신: {sender}> {msg}"'
    """
    try:
        async for raw in ws:
            msg = ChatMessage.from_json(raw)

            # 시스템 메시지나 자기 자신 메시지는 무시
            if msg.type != "message" or msg.sender == name:
                print(f"[{name}:auto] {msg.display()}")
                continue

            print(f"[{name}:auto] 수신 ← {msg.sender}: {msg.content}")

            # 명령어 플레이스홀더 치환
            cmd = command.replace("{msg}", msg.content)
            cmd = cmd.replace("{sender}", msg.sender)
            cmd = cmd.replace("{room}", msg.room)

            # 외부 명령 실행
            try:
                proc = await asyncio.create_subprocess_shell(
                    cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                stdout, stderr = await asyncio.wait_for(
                    proc.communicate(), timeout=120
                )
                reply_text = stdout.decode("utf-8", errors="replace").strip()

                if not reply_text:
                    print(f"[{name}:auto] 응답 없음 (빈 출력)")
                    continue

                # 응답 전송
                reply_msg = ChatMessage(
                    type="message", sender=name, content=reply_text
                )
                await ws.send(reply_msg.to_json())
                print(f"[{name}:auto] 응답 → {reply_text[:80]}...")

            except asyncio.TimeoutError:
                print(f"[{name}:auto] 명령 타임아웃 (120초 초과)")
            except Exception as e:
                print(f"[{name}:auto] 명령 실행 오류: {e}")

    except Exception:
        print(f"\n[{name}:auto] 연결 종료")


async def _run_auto_reply(name: str, command: str, host: str, port: int):
    """자동 응답 모드 메인 루프"""
    import websockets
    uri = f"ws://{host}:{port}"

    async with websockets.connect(uri) as ws:
        # 입장
        join_msg = ChatMessage(type="join", sender=name, content="")
        await ws.send(join_msg.to_json())

        print(f"[{name}:auto] 자동 응답 모드 시작")
        print(f"[{name}:auto] 명령어: {command}")
        print(f"[{name}:auto] Ctrl+C로 종료")

        await _auto_reply_loop(ws, name, command)


def run_auto_reply(name: str, command: str, host: str = "localhost", port: int = 8765):
    """자동 응답 모드 실행 (동기 래퍼)"""
    asyncio.run(_run_auto_reply(name, command, host, port))
