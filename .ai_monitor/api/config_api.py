import os
import json
from http import server

# .env 파일 경로
ENV_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), '.env')

def load_discord_config():
    """ .env 파일에서 디스코드 설정을 읽어옴 (T1~T8) """
    config = {
        "token": "",
        "channels": {f"T{i}": "" for i in range(1, 9)}
    }
    
    if os.path.exists(ENV_PATH):
        with open(ENV_PATH, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#'): continue
                
                if '=' in line:
                    key, val = line.split('=', 1)
                    if key == 'DISCORD_BOT_TOKEN':
                        config["token"] = val
                    elif key.startswith('DISCORD_CHANNEL_T'):
                        t_num = key.replace('DISCORD_CHANNEL_', '')
                        if t_num in config["channels"]:
                            config["channels"][t_num] = val
    return config

def save_discord_config(new_config):
    """ .env 파일에 디스코드 설정을 저장 (T1~T8) """
    lines = []
    if os.path.exists(ENV_PATH):
        with open(ENV_PATH, 'r', encoding='utf-8') as f:
            lines = f.readlines()
    
    updates = {
        'DISCORD_BOT_TOKEN': new_config.get('token', '')
    }
    for t_num, cid in new_config.get('channels', {}).items():
        if int(t_num[1:]) <= 8:
            updates[f'DISCORD_CHANNEL_{t_num}'] = cid
        
    new_lines = []
    seen_keys = set()
    
    for line in lines:
        stripped = line.strip()
        if stripped and '=' in stripped and not stripped.startswith('#'):
            key = stripped.split('=', 1)[0]
            if key in updates:
                new_lines.append(f"{key}={updates[key]}\n")
                seen_keys.add(key)
                continue
            # T9 등 8번을 넘어가는 기존 키는 제거 (필요시)
            if key.startswith('DISCORD_CHANNEL_T') and int(key.replace('DISCORD_CHANNEL_T', '')) > 8:
                continue
        new_lines.append(line)
        
    for key, val in updates.items():
        if key not in seen_keys:
            if not new_lines or not new_lines[-1].endswith('\n'):
                new_lines.append('\n')
            new_lines.append(f"{key}={val}\n")
            
    with open(ENV_PATH, 'w', encoding='utf-8') as f:
        f.writelines(new_lines)
    return True

def handle_get_config(handler):
    config = load_discord_config()
    handler.send_response(200)
    handler.send_header('Content-Type', 'application/json')
    handler.end_headers()
    handler.wfile.write(json.dumps(config).encode('utf-8'))

def handle_post_config(handler):
    content_length = int(handler.headers['Content-Length'])
    post_data = handler.rfile.read(content_length)
    new_config = json.loads(post_data.decode('utf-8'))
    
    if save_discord_config(new_config):
        handler.send_response(200)
        handler.send_header('Content-Type', 'application/json')
        handler.end_headers()
        handler.wfile.write(json.dumps({"status": "success"}).encode('utf-8'))
    else:
        handler.send_response(500)
        handler.end_headers()
