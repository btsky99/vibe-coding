"""
FILE: scripts/agent_protocol.py
DESCRIPTION: 에이전트 간 협업을 위한 RFC(Request for Comments) 관리 프로토콜.
             Gemini와 Claude 간의 명확한 역할 분담과 작업 승인을 지원합니다.

REVISION HISTORY:
- 2026-02-26 Gemini-1: 초기 구현 (하이브 에볼루션 v5.0 Task 5)
"""

import os
import sys
import json
import time
from datetime import datetime
from pathlib import Path

# 프로젝트 루트 경로 설정
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RFC_DIR = os.path.join(BASE_DIR, ".ai_monitor", "data", "rfcs")

class AgentProtocol:
    def __init__(self):
        os.makedirs(RFC_DIR, exist_ok=True)

    def create_rfc(self, title: str, description: str, author: str, assigned_to: str) -> str:
        """새로운 작업 요청서(RFC)를 생성합니다."""
        rfc_id = f"RFC-{int(time.time())}"
        rfc_data = {
            "id": rfc_id,
            "title": title,
            "description": description,
            "author": author,
            "assigned_to": assigned_to,
            "status": "PENDING",
            "created_at": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat(),
            "comments": []
        }
        
        file_path = os.path.join(RFC_DIR, f"{rfc_id}.json")
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(rfc_data, f, indent=2, ensure_ascii=False)
            
        print(f"📄 [RFC 생성] {rfc_id}: {title} (From: {author} -> To: {assigned_to})")
        return rfc_id

    def update_rfc_status(self, rfc_id: str, status: str, comment: str, author: str):
        """RFC의 상태를 업데이트하고 댓글을 남깁니다."""
        file_path = os.path.join(RFC_DIR, f"{rfc_id}.json")
        if not os.path.exists(file_path):
            print(f"[ERROR] RFC를 찾을 수 없습니다: {rfc_id}")
            return
            
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            
        data["status"] = status
        data["updated_at"] = datetime.now().isoformat()
        data["comments"].append({
            "author": author,
            "comment": comment,
            "timestamp": datetime.now().isoformat()
        })
        
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            
        print(f"🔄 [RFC 업데이트] {rfc_id} 상태 변경: {status} by {author}")

    def list_rfcs(self, status: str = None) -> list:
        """RFC 목록을 조회합니다."""
        rfcs = []
        for filename in os.listdir(RFC_DIR):
            if filename.endswith(".json"):
                with open(os.path.join(RFC_DIR, filename), "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if status is None or data["status"] == status:
                        rfcs.append(data)
        return sorted(rfcs, key=lambda x: x["created_at"], reverse=True)

if __name__ == "__main__":
    # 간단한 CLI 인터페이스
    protocol = AgentProtocol()
    if len(sys.argv) < 2:
        print("Usage: python agent_protocol.py [create|list|update]")
        sys.exit(1)
        
    cmd = sys.argv[1]
    if cmd == "create":
        # 예: python agent_protocol.py create "UI 리팩토링" "상세 내용..." gemini claude
        protocol.create_rfc(sys.argv[2], sys.argv[3], sys.argv[4], sys.argv[5])
    elif cmd == "list":
        for rfc in protocol.list_rfcs():
            print(f"[{rfc['status']}] {rfc['id']} - {rfc['title']} ({rfc['author']} -> {rfc['assigned_to']})")
