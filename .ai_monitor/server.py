import json
import time
import os
import mimetypes
import webbrowser
import shutil
import subprocess


def open_app_window(url):
    """Chrome/Edge 앱 모드로 열기 (주소창/탭 없이 GUI처럼 표시)"""
    chrome = shutil.which("chrome") or shutil.which("google-chrome")
    edge = shutil.which("msedge")
    # Windows 기본 경로 확인
    for path in [
        os.path.expandvars(r"%ProgramFiles%\Google\Chrome\Application\chrome.exe"),
        os.path.expandvars(r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"),
        os.path.expandvars(r"%LocalAppData%\Google\Chrome\Application\chrome.exe"),
        os.path.expandvars(r"%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe"),
        os.path.expandvars(r"%ProgramFiles%\Microsoft\Edge\Application\msedge.exe"),
    ]:
        if os.path.isfile(path):
            if not chrome and "chrome" in path.lower():
                chrome = path
            if not edge and "edge" in path.lower():
                edge = path
    browser = chrome or edge
    if browser:
        subprocess.Popen([browser, f"--app={url}"])
    else:
        webbrowser.open(url)
from http.server import BaseHTTPRequestHandler, HTTPServer
from socketserver import ThreadingMixIn
from pathlib import Path

import sys

from _version import __version__

if sys.stdout is None:
    sys.stdout = open(os.devnull, 'w')
if sys.stderr is None:
    sys.stderr = open(os.devnull, 'w')

if getattr(sys, 'frozen', False):
    BASE_DIR = Path(sys._MEIPASS)
else:
    BASE_DIR = Path(__file__).resolve().parent

# 정적 파일 경로를 절대 경로로 고정 (404 방지 핵심!)
STATIC_DIR = (BASE_DIR / "nexus-view" / "dist").resolve()
DATA_DIR = (Path(sys.executable).resolve().parent / "data") if getattr(sys, 'frozen', False) else (BASE_DIR / "data")
SESSIONS_FILE = DATA_DIR / "sessions.jsonl"

print("Static files directory:", STATIC_DIR)
if not STATIC_DIR.exists():
    print("WARNING: Static directory not found!")


class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
    """멀티 스레드 지원 HTTP 서버 (SSE 등 지속적 연결 동시 처리용)"""
    daemon_threads = True

last_heartbeat_time = time.time()
client_connected_once = False

def monitor_heartbeat():
    global last_heartbeat_time, client_connected_once
    while True:
        time.sleep(5)
        if client_connected_once and (time.time() - last_heartbeat_time > 15):
            print("브라우저 창이 닫혀 하트비트가 끊어졌습니다. 서버를 자동 종료합니다...")
            os._exit(0)

import string
from urllib.parse import urlparse, parse_qs

class SSEHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed_path = urlparse(self.path)
        if parsed_path.path == '/stream':
            self.send_response(200)
            self.send_header('Content-Type', 'text/event-stream')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.send_header('Cache-Control', 'no-cache')
            self.send_header('Connection', 'keep-alive')
            self.end_headers()
            
            # SSE 스트리밍 루프
            last_size = 0
            if SESSIONS_FILE.exists():
                last_size = SESSIONS_FILE.stat().st_size
                # 초기 진입 시 최신 50개 전송
                with open(SESSIONS_FILE, 'r', encoding='utf-8') as f:
                    lines = f.readlines()
                    lines = lines[-50:]
                    for line in lines:
                        if line.strip():
                            self.wfile.write(f"data: {line.strip()}\n\n".encode('utf-8'))
                            self.wfile.flush()
            
            while True:
                try:
                    if SESSIONS_FILE.exists():
                        current_size = SESSIONS_FILE.stat().st_size
                        if current_size > last_size:
                            with open(SESSIONS_FILE, 'r', encoding='utf-8') as f:
                                f.seek(last_size)
                                new_lines = f.readlines()
                                for line in new_lines:
                                    if line.strip():
                                        self.wfile.write(f"data: {line.strip()}\n\n".encode('utf-8'))
                                        self.wfile.flush()
                            last_size = current_size
                    time.sleep(0.5) # 감시 주기
                except (BrokenPipeError, ConnectionResetError):
                    break
                except Exception as e:
                    print(f"Server error: {e}")
                    time.sleep(1)
        elif parsed_path.path == '/api/heartbeat':
            global last_heartbeat_time, client_connected_once
            last_heartbeat_time = time.time()
            client_connected_once = True
            self.send_response(200)
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(b"OK")
        elif parsed_path.path == '/api/drives':
            self.send_response(200)
            self.send_header('Content-Type', 'application/json;charset=utf-8')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            drives = []
            if os.name == 'nt':
                for letter in string.ascii_uppercase:
                    drive = f"{letter}:\\"
                    if os.path.exists(drive):
                        drives.append(drive)
            else:
                drives = ['/']
            self.wfile.write(json.dumps(drives).encode('utf-8'))
        elif parsed_path.path == '/api/install-gemini-cli':
            self.send_response(200)
            self.send_header('Content-Type', 'application/json;charset=utf-8')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            try:
                import subprocess
                # Gemini CLI 설치 (전역)
                subprocess.Popen('cmd.exe /k "echo Installing Gemini CLI... && npm install -g @google/gemini-cli"', shell=True)
                result = {"status": "success", "message": "Gemini CLI installation started in a new window."}
            except Exception as e:
                result = {"status": "error", "message": str(e)}
            self.wfile.write(json.dumps(result).encode('utf-8'))
        elif parsed_path.path == '/api/install-claude-code':
            self.send_response(200)
            self.send_header('Content-Type', 'application/json;charset=utf-8')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            try:
                import subprocess
                # Claude Code 설치 (전역)
                subprocess.Popen('cmd.exe /k "echo Installing Claude Code... && npm install -g @anthropic-ai/claude-code"', shell=True)
                result = {"status": "success", "message": "Claude Code installation started in a new window."}
            except Exception as e:
                result = {"status": "error", "message": str(e)}
            self.wfile.write(json.dumps(result).encode('utf-8'))
        elif parsed_path.path == '/api/shutdown':
            self.send_response(200)
            self.send_header('Content-Type', 'application/json;charset=utf-8')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(json.dumps({"status": "success", "message": "Server shutting down..."}).encode('utf-8'))
            print("Shutdown requested via API. Exiting in 1 second...")
            import threading
            threading.Timer(1.0, lambda: os._exit(0)).start()
        elif parsed_path.path == '/api/files':
            self.send_response(200)
            self.send_header('Content-Type', 'application/json;charset=utf-8')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            query = parse_qs(parsed_path.query)
            target_path = query.get('path', [''])[0]
            items = []
            if target_path and os.path.exists(target_path) and os.path.isdir(target_path):
                try:
                    for entry in os.scandir(target_path):
                        if not entry.name.startswith('.'):
                            items.append({
                                "name": entry.name, 
                                "path": entry.path.replace('\\', '/'),
                                "isDir": entry.is_dir()
                            })
                except Exception:
                    pass
            # 폴더가 먼저 오도록 정렬
            items.sort(key=lambda x: (not x['isDir'], x['name'].lower()))
            self.wfile.write(json.dumps(items).encode('utf-8'))
        elif parsed_path.path == '/api/install-skills':
            self.send_response(200)
            self.send_header('Content-Type', 'application/json;charset=utf-8')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            query = parse_qs(parsed_path.query)
            target_path = query.get('path', [''])[0]
            
            result = {"status": "error", "message": "Invalid path"}
            if target_path and os.path.exists(target_path) and os.path.isdir(target_path):
                try:
                    import shutil
                    # 소스 경로 (설치된 앱의 위치 기준)
                    # .gemini, scripts, GEMINI.md 등을 복사
                    source_base = BASE_DIR.parent # 프로젝트 루트로 가정
                    
                    # .gemini 복사
                    gemini_src = source_base / ".gemini"
                    if gemini_src.exists():
                        shutil.copytree(gemini_src, Path(target_path) / ".gemini", dirs_exist_ok=True)
                    
                    # scripts 복사
                    scripts_src = source_base / "scripts"
                    if scripts_src.exists():
                        shutil.copytree(scripts_src, Path(target_path) / "scripts", dirs_exist_ok=True)
                        
                    # GEMINI.md 복사
                    gemini_md_src = source_base / "GEMINI.md"
                    if gemini_md_src.exists():
                        shutil.copy(gemini_md_src, Path(target_path) / "GEMINI.md")
                        
                    result = {"status": "success", "message": f"Skills installed to {target_path}"}
                except Exception as e:
                    result = {"status": "error", "message": str(e)}
            
            self.wfile.write(json.dumps(result).encode('utf-8'))
        elif parsed_path.path == '/api/dirs':
            self.send_response(200)
            self.send_header('Content-Type', 'application/json;charset=utf-8')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            query = parse_qs(parsed_path.query)
            target_path = query.get('path', [''])[0]
            dirs = []
            if target_path and os.path.exists(target_path) and os.path.isdir(target_path):
                try:
                    for entry in os.scandir(target_path):
                        if entry.is_dir() and not entry.name.startswith('.'):
                            dirs.append({"name": entry.name, "path": entry.path.replace('\\', '/')})
                except Exception:
                    pass
            dirs.sort(key=lambda x: x['name'].lower())
            self.wfile.write(json.dumps(dirs).encode('utf-8'))
        else:
            # 정적 파일 서비스 로직 (Vite 빌드 결과물)
            # 요청 경로를 정리
            path = self.path
            if path == '/':
                path = '/index.html'
            
            # 쿼리스트링 제거
            path = path.split('?')[0]
            
            filepath = STATIC_DIR / path.lstrip('/')
            
            # 파일이 없으면 index.html로 Fallback (SPA 특성)
            if not filepath.exists() or not filepath.is_file():
                filepath = STATIC_DIR / 'index.html'
                
            if filepath.exists() and filepath.is_file():
                try:
                    with open(filepath, 'rb') as f:
                        content = f.read()
                    self.send_response(200)
                    mimetype, _ = mimetypes.guess_type(str(filepath))
                    if filepath.suffix == '.js':
                        mimetype = 'application/javascript'
                    elif filepath.suffix == '.css':
                        mimetype = 'text/css'
                    elif filepath.suffix == '.svg':
                        mimetype = 'image/svg+xml'
                    self.send_header('Content-Type', mimetype or 'application/octet-stream')
                    self.send_header('Cache-Control', 'no-cache, no-store, must-revalidate')
                    self.send_header('Pragma', 'no-cache')
                    self.send_header('Expires', '0')
                    self.end_headers()
                    self.wfile.write(content)
                except Exception as e:
                    self.send_response(500)
                    self.end_headers()
                    self.wfile.write(str(e).encode('utf-8'))
            else:
                self.send_response(404)
                self.end_headers()
                self.wfile.write(b"Not Found")

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()

    def do_POST(self):
        parsed_path = urlparse(self.path)
        if parsed_path.path == '/api/launch':
            try:
                content_length = int(self.headers['Content-Length'])
                post_data = self.rfile.read(content_length)
                data = json.loads(post_data.decode('utf-8'))
                
                agent = data.get('agent')
                target_dir = data.get('path', 'C:\\')
                
                import subprocess
                if agent == 'claude':
                    cmd = f'start "Claude Code" cmd.exe /k "cd /d {target_dir} && title [Claude Code] && echo Launching Claude Code... && claude"'
                elif agent == 'gemini':
                    cmd = f'start "Gemini CLI" cmd.exe /k "cd /d {target_dir} && title [Gemini CLI] && echo Launching Gemini CLI... && gemini"'
                else:
                    cmd = f'start "Terminal" cmd.exe /k "cd /d {target_dir}"'
                
                subprocess.Popen(cmd, shell=True)
                
                self.send_response(200)
                self.send_header('Content-Type', 'application/json;charset=utf-8')
                self.send_header('Access-Control-Allow-Origin', '*')
                self.end_headers()
                self.wfile.write(json.dumps({"status": "launched", "agent": agent}).encode('utf-8'))
            except Exception as e:
                self.send_response(500)
                self.send_header('Access-Control-Allow-Origin', '*')
                self.end_headers()
                self.wfile.write(json.dumps({"error": str(e)}).encode('utf-8'))
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        # 불필요한 콘솔 로그 제거하여 터미널 깔끔하게 유지
        pass

import asyncio
import websockets
import threading
from winpty import PtyProcess

pty_sessions = {}

async def pty_handler(websocket):
    try:
        path = websocket.request.path
        parsed = urlparse(path)
        qs = parse_qs(parsed.query)
        agent = qs.get('agent', [''])[0]
        cwd = qs.get('cwd', ['C:\\'])[0]
        try:
            cols = int(qs.get('cols', ['80'])[0])
        except ValueError:
            cols = 80
        try:
            rows = int(qs.get('rows', ['24'])[0])
        except ValueError:
            rows = 24

        pty = PtyProcess.spawn('cmd.exe', cwd=cwd, dimensions=(rows, cols))
        
        if agent == 'claude':
            pty.write('claude\r\n')
        elif agent == 'gemini':
            pty.write('gemini\r\n')

        session_id = str(id(websocket))
        pty_sessions[session_id] = pty

    except Exception as e:
        print(f"PTY Init Error: {e}")
        await websocket.close()
        return

    async def read_from_pty():
        loop = asyncio.get_running_loop()
        while True:
            try:
                data = await loop.run_in_executor(None, pty.read, 4096)
                if not data:
                    await asyncio.sleep(0.01)
                    continue
                await websocket.send(data)
            except EOFError:
                print("PTY read EOFError")
                break
            except Exception as e:
                print("PTY read Exception:", e)
                break

    async def read_from_ws():
        async for message in websocket:
            try:
                if isinstance(message, str):
                    pty.write(message)
                else:
                    pty.write(message.decode('utf-8'))
            except Exception as e:
                break

    task1 = asyncio.create_task(read_from_pty())
    task2 = asyncio.create_task(read_from_ws())
    
    done, pending = await asyncio.wait([task1, task2], return_when=asyncio.FIRST_COMPLETED)
    for task in pending:
        task.cancel()
    
    try:
        pty.terminate(force=True)
    except:
        pass
    if session_id in pty_sessions:
        del pty_sessions[session_id]

async def run_ws_server():
    try:
        async with websockets.serve(pty_handler, "0.0.0.0", 8001):
            print("WebSocket PTY Server started on port 8001")
            await asyncio.Future()
    except OSError:
        print("WebSocket Server is already running on port 8001")

def start_ws_server():
    try:
        asyncio.run(run_ws_server())
    except Exception as e:
        print(f"WebSockets Server Error: {e}")

if __name__ == '__main__':
    print(f"Vibe Coding {__version__}")

    # --- Auto-update check (non-blocking) ---
    if getattr(sys, 'frozen', False):
        from updater import check_and_update
        update_thread = threading.Thread(
            target=check_and_update,
            args=(DATA_DIR,),
            daemon=True,
        )
        update_thread.start()

    threading.Thread(target=start_ws_server, daemon=True).start()
    threading.Thread(target=monitor_heartbeat, daemon=True).start()
    port = 8000
    try:
        server = ThreadedHTTPServer(('0.0.0.0', port), SSEHandler)
        print(f"Nexus View SSE Log Server started on port {port}")
        # 로컬 웹 대시보드 앱 모드로 실행 (주소창 없이 GUI처럼)
        threading.Thread(target=lambda: open_app_window(f"http://localhost:{port}"), daemon=True).start()
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        server.server_close()
    except OSError:
        # 이미 8000번 포트가 사용 중 → 브라우저만 열고 즉시 종료
        open_app_window(f"http://localhost:{port}")
        sys.exit(0)
