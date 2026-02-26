"""
FILE: scripts/vector_memory.py
DESCRIPTION: 외부 API(Gemini/Claude) 없이 로컬에서 100% 작동하는 벡터 메모리 엔진.
             ChromaDB의 기본 임베딩 엔진을 사용하여 키 설정 없이 작동합니다.

REVISION HISTORY:
- 2026-02-26 Gemini-1: 100% 로컬 모드로 전환 (API 키 의존성 제거)
"""

import os
import sys
import json
import chromadb
from typing import List, Dict, Any, Optional
from datetime import datetime

# 프로젝트 루트 경로 설정
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(BASE_DIR, ".ai_monitor", "data", "vector_db")

class VectorMemory:
    def __init__(self, collection_name: str = "hive_local_memory"):
        # 로컬 저장소 설정
        self.client = chromadb.PersistentClient(path=DB_PATH)
        
        # 별도의 API 키 없이 ChromaDB가 내장한 기본 로컬 모델(Sentence Transformers) 사용
        # 인터넷 연결 없이도 내 컴퓨터 안에서 텍스트를 숫자로 변환합니다.
        self.collection = self.client.get_or_create_collection(
            name=collection_name,
            metadata={"hnsw:space": "cosine"}
        )

    def add_memory(self, key: str, content: str, metadata: Dict[str, Any]):
        """메모리를 로컬 벡터 DB에 추가합니다. (API 키 불필요)"""
        # 메타데이터 정리
        clean_metadata = {}
        for k, v in metadata.items():
            if isinstance(v, (list, dict)):
                clean_metadata[k] = str(v)
            else:
                clean_metadata[k] = v
        
        # documents에 텍스트만 넣으면 ChromaDB가 내부 로컬 모델로 알아서 벡터화합니다.
        self.collection.add(
            ids=[key],
            documents=[content],
            metadatas=[clean_metadata]
        )

    def search(self, query: str, n_results: int = 5) -> List[Dict[str, Any]]:
        """유사한 메모리를 검색합니다. (로컬 엔진 사용)"""
        results = self.collection.query(
            query_texts=[query],
            n_results=n_results
        )
        
        formatted_results = []
        if results['ids']:
            for i in range(len(results['ids'][0])):
                formatted_results.append({
                    "id": results['ids'][0][i],
                    "content": results['documents'][0][i],
                    "metadata": results['metadatas'][0][i],
                    "distance": results['distances'][0][i]
                })
        return formatted_results

    def delete_memory(self, key: str):
        """특정 키의 메모리를 삭제합니다."""
        self.collection.delete(ids=[key])

if __name__ == "__main__":
    # 테스트 코드 (키 없이 바로 실행)
    if len(sys.argv) > 1 and sys.argv[1] == "--test":
        try:
            vm = VectorMemory()
            print("[INFO] 로컬 벡터 엔진 초기화 완료 (API 키 불필요)")
            
            test_key = "local_test_1"
            test_content = "이것은 API 키 없이 로컬에서 저장된 기억입니다."
            vm.add_memory(test_key, test_content, {"type": "local_test"})
            
            print("[ACT] 로컬 검색 테스트 중...")
            res = vm.search("API 키 없이 저장된 게 뭐야?")
            if res:
                print(f"🔍 검색 결과: {res[0]['content']}")
        except Exception as e:
            print(f"[ERROR] 로컬 엔진 오류: {e}")
