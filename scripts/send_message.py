"""
?ì´?„íŠ¸ ê°?ë©”ì‹œì§€ ì±„ë„ ?¬í¼ ?¤í¬ë¦½íŠ¸
---------------------------------------
?¬ìš©ë²?
  python scripts/send_message.py <from> <to> <type> <content>

?ˆì‹œ:
  python scripts/send_message.py claude gemini handoff "DB ?¤í‚¤ë§?ë¶„ì„ ?„ë£Œ. API êµ¬í˜„ ?œì‘?´ë„ ?©ë‹ˆ??"
  python scripts/send_message.py gemini claude task_complete "UI ì»´í¬?ŒíŠ¸ ëª¨ë‘ ?‘ì„± ?„ë£Œ."
  python scripts/send_message.py claude all info "ê³µí†µ ? í‹¸ ?¨ìˆ˜ utils.py??ì¶”ê??ˆìŠµ?ˆë‹¤."

type ëª©ë¡:
  info          - ?¼ë°˜ ?•ë³´ ê³µìœ 
  handoff       - ?¤ìŒ ?‘ì—…???ë??ê²Œ ?„ì„
  request       - ?¹ì • ?‘ì—… ?”ì²­
  task_complete - ?‘ì—… ?„ë£Œ ?Œë¦¼
  warning       - ê²½ê³  (ì¶©ëŒ, ?ëŸ¬ ??

?œë²„ ?¬íŠ¸:
  ê°œë°œ ëª¨ë“œ: 8000 / ë°°í¬ ëª¨ë“œ: 8005
  ?ë™ ê°ì??˜ê±°??--port ?Œë˜ê·¸ë¡œ ì§€??ê°€??
"""

import sys
import json
import urllib.request
import urllib.error
import os

# ?œë²„ ?¬íŠ¸ ?ë™ ê°ì? (ê°œë°œ: 8000, ë°°í¬: 8005)
DEFAULT_PORTS = [8005, 8000]


def send_message(from_agent: str, to_agent: str, msg_type: str, content: str, port: int = None) -> bool:
    """
    ¹ÙÀÌºê ÄÚµù(Vibe Coding) ?œë²„??/api/message ?”ë“œ?¬ì¸?¸ì— ë©”ì‹œì§€ë¥??„ì†¡?©ë‹ˆ??
    ?œë²„ê°€ ?¤í–‰ ì¤‘ì´ì§€ ?Šìœ¼ë©?ì§ì ‘ ?Œì¼??ê¸°ë¡?©ë‹ˆ???´ë°±).
    """
    # ?¬íŠ¸ ëª©ë¡ ê²°ì •
    ports_to_try = [port] if port else DEFAULT_PORTS

    payload = json.dumps({
        'from': from_agent,
        'to': to_agent,
        'type': msg_type,
        'content': content,
    }).encode('utf-8')

    # API ?„ì†¡ ?œë„
    for p in ports_to_try:
        try:
            req = urllib.request.Request(
                f'http://localhost:{p}/api/message',
                data=payload,
                headers={'Content-Type': 'application/json'},
                method='POST',
            )
            with urllib.request.urlopen(req, timeout=3) as resp:
                result = json.loads(resp.read().decode('utf-8'))
                if result.get('status') == 'success':
                    print(f"[OK] ë©”ì‹œì§€ ?„ì†¡ ?„ë£Œ (?¬íŠ¸ {p}): {from_agent} ??{to_agent} [{msg_type}]")
                    return True
        except (urllib.error.URLError, Exception):
            continue

    # ?´ë°±: ?œë²„ê°€ êº¼ì ¸?ˆì„ ê²½ìš° ì§ì ‘ ?Œì¼??ê¸°ë¡
    return _fallback_write(from_agent, to_agent, msg_type, content)


def _fallback_write(from_agent: str, to_agent: str, msg_type: str, content: str) -> bool:
    """?œë²„ ë¯¸ì‹¤????messages.jsonl??ì§ì ‘ ê¸°ë¡?˜ëŠ” ?´ë°± ?¨ìˆ˜"""
    import time

    # .ai_monitor/data/messages.jsonl ê²½ë¡œ ?ìƒ‰
    script_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(script_dir)
    data_dir = os.path.join(project_root, '.ai_monitor', 'data')

    os.makedirs(data_dir, exist_ok=True)
    messages_file = os.path.join(data_dir, 'messages.jsonl')

    msg = {
        'id': str(int(time.time() * 1000)),
        'timestamp': time.strftime('%Y-%m-%dT%H:%M:%S'),
        'from': from_agent,
        'to': to_agent,
        'type': msg_type,
        'content': content,
        'read': False,
    }

    try:
        with open(messages_file, 'a', encoding='utf-8') as f:
            f.write(json.dumps(msg, ensure_ascii=False) + '\n')
        print(f"[OK] ë©”ì‹œì§€ ?Œì¼ ì§ì ‘ ê¸°ë¡ ?„ë£Œ: {from_agent} ??{to_agent} [{msg_type}]")
        return True
    except Exception as e:
        print(f"[FAIL] ë©”ì‹œì§€ ê¸°ë¡ ?¤íŒ¨: {e}", file=sys.stderr)
        return False


if __name__ == '__main__':
    # ?¸ì ?Œì‹±
    port_override = None
    args = sys.argv[1:]

    # --port ?Œë˜ê·?ì²˜ë¦¬
    if '--port' in args:
        idx = args.index('--port')
        try:
            port_override = int(args[idx + 1])
            args = args[:idx] + args[idx + 2:]
        except (IndexError, ValueError):
            pass

    if len(args) < 4:
        print(__doc__)
        print("Usage: python scripts/send_message.py <from> <to> <type> <content>")
        sys.exit(1)

    from_a, to_a, m_type, *content_parts = args
    content_str = ' '.join(content_parts)

    ok = send_message(from_a, to_a, m_type, content_str, port=port_override)
    sys.exit(0 if ok else 1)
