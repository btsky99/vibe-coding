"""CLI 엔트리포인트 - llm-chat 명령어 정의"""
import click


@click.group()
@click.version_option()
def main():
    """LLM Group Chat - 터미널 간 LLM 실시간 그룹 채팅"""
    pass


@main.command()
@click.option("--host", default="localhost", help="서버 바인드 주소")
@click.option("--port", default=8765, type=int, help="서버 포트")
def serve(host, port):
    """채팅 서버 시작"""
    from llm_group_chat.server import run_server
    click.echo(f"채팅 서버 시작: ws://{host}:{port}")
    run_server(host, port)


@main.command()
@click.option("--name", required=True, help="참여자 이름 (예: claude, gemini)")
@click.option("--host", default="localhost", help="서버 주소")
@click.option("--port", default=8765, type=int, help="서버 포트")
def join(name, host, port):
    """채팅방에 참여 (인터랙티브 모드)"""
    from llm_group_chat.client import run_client
    click.echo(f"{name}(으)로 채팅 참여: ws://{host}:{port}")
    run_client(name, host, port)


@main.command()
@click.option("--name", required=True, help="보내는 사람 이름")
@click.option("--msg", required=True, help="보낼 메시지")
@click.option("--host", default="localhost", help="서버 주소")
@click.option("--port", default=8765, type=int, help="서버 포트")
def send(name, msg, host, port):
    """메시지 하나 보내고 종료 (스크립트/파이프용)"""
    from llm_group_chat.client import send_one
    send_one(name, msg, host, port)


@main.command()
@click.option("--tail", default=20, type=int, help="최근 N개 메시지")
@click.option("--log-file", default="chat.jsonl", help="로그 파일 경로")
def log(tail, log_file):
    """채팅 로그 보기"""
    from llm_group_chat.protocol import ChatMessage
    import os

    if not os.path.exists(log_file):
        click.echo("로그 파일이 없습니다.")
        return

    with open(log_file, "r", encoding="utf-8") as f:
        lines = f.readlines()

    for line in lines[-tail:]:
        msg = ChatMessage.from_json(line.strip())
        click.echo(msg.display())


@main.command()
@click.option("--name", required=True, help="참여자 이름 (예: claude, gemini)")
@click.option("--host", default="localhost", help="서버 주소")
@click.option("--port", default=8765, type=int, help="서버 포트")
def pipe(name, host, port):
    """LLM 연동 파이프 모드 (stdin→서버, 서버→stdout, JSON 라인)"""
    from llm_group_chat.client import run_pipe
    run_pipe(name, host, port)


@main.command(name="auto-reply")
@click.option("--name", required=True, help="참여자 이름 (예: claude, gemini)")
@click.option("--command", required=True, help='자동 응답 명령어. {msg},{sender},{room} 치환 가능. 예: \'claude -p "{msg}"\'')
@click.option("--host", default="localhost", help="서버 주소")
@click.option("--port", default=8765, type=int, help="서버 포트")
def auto_reply(name, command, host, port):
    """자동 응답 모드 - 수신 메시지마다 외부 LLM CLI로 응답 생성"""
    from llm_group_chat.client import run_auto_reply
    run_auto_reply(name, command, host, port)


@main.command()
@click.option("--name", required=True, help="터미널 이름 (예: T1-claude, T2-gemini)")
@click.option("--cli", required=True, type=click.Choice(["claude", "gemini", "codex"]), help="사용할 LLM CLI")
@click.option("--host", default="localhost", help="서버 주소")
@click.option("--port", default=8765, type=int, help="서버 포트")
@click.option("--no-auto", is_flag=True, help="자동 응답 끄기 (수동 채팅만)")
@click.option("--no-sdk", is_flag=True, help="SDK 대신 CLI subprocess 사용")
def terminal(name, cli, host, port, no_auto, no_sdk):
    """그룹챗 터미널 — SDK 기반 진짜 에이전트 + 그룹 채팅

    SDK 모드: 파일 편집, bash 실행, 코드 수정 가능 (진짜 에이전트)
    CLI 모드(--no-sdk): subprocess로 질문/답변만
    """
    from llm_group_chat.terminal import run_terminal
    run_terminal(name, cli, host, port, auto_reply=not no_auto, use_sdk=not no_sdk)


@main.command()
@click.option("--name", required=True, help="에이전트 이름 (예: claude-1, gemini-bot)")
@click.option("--cli", required=True, type=click.Choice(["claude", "gemini", "codex"]), help="사용할 LLM CLI")
@click.option("--host", default="localhost", help="서버 주소")
@click.option("--port", default=8765, type=int, help="서버 포트")
def agent(name, cli, host, port):
    """백그라운드 AI 에이전트 — LLM CLI로 자동 응답 (UI 없음)"""
    from llm_group_chat.agents import run_agent
    click.echo(f"[{name}] {cli} 에이전트 시작...")
    run_agent(name, cli, host, port)


@main.command()
@click.option("--agents", required=True, help='에이전트 목록 (쉼표 구분). 예: claude,gemini,codex')
@click.option("--host", default="localhost", help="서버 주소")
@click.option("--port", default=8765, type=int, help="서버 포트")
def squad(agents, host, port):
    """여러 AI 에이전트를 동시에 시작하여 그룹 채팅"""
    from llm_group_chat.agents import run_squad

    agent_list = []
    for i, cli in enumerate(agents.split(","), 1):
        cli = cli.strip()
        agent_list.append({"name": f"{cli}-{i}", "cli": cli})

    click.echo(f"스쿼드 시작: {', '.join(a['name'] for a in agent_list)}")
    run_squad(agent_list, host, port)
