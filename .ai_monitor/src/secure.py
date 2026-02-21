import os
import sys
import json
import base64
import shlex
import re

# 마스킹할 정규식 패턴 모음 (API 키, Bearer 토큰, 패스워드 등)
MASKING_PATTERNS = [
    re.compile(r'sk-[a-zA-Z0-9]{32,}'),
    re.compile(r'Bearer\s+[a-zA-Z0-9\-\._~+/]+=*'),
    re.compile(r'(?i)password["\']?\s*[:=]\s*["\']?[a-zA-Z0-9!@#\$%\^&\*]*["\']?')
]

def mask_sensitive_data(text: str) -> str:
    """텍스트 내의 민감 정보를 [MASKED]로 치환합니다."""
    if not isinstance(text, str):
        return text
    
    masked_text = text
    for pattern in MASKING_PATTERNS:
        masked_text = pattern.sub('[MASKED]', masked_text)
    return masked_text

def validate_path(base_paths: list, target_path: str) -> bool:
    """target_path가 허용된 base_paths 내부인지 디렉토리 탐색(Traveral) 공격을 검증합니다."""
    try:
        target_abs = os.path.abspath(target_path)
        for base in base_paths:
            base_abs = os.path.abspath(base)
            if target_abs.startswith(base_abs):
                return True
    except Exception:
        pass
    return False

def parse_secure_payload(payload: str) -> dict:
    """Base64로 인코딩된 JSON 페이로드를 안전하게 디코딩하고 파싱합니다."""
    try:
        decoded_bytes = base64.b64decode(payload)
        decoded_str = decoded_bytes.decode('utf-8')
        # 데이터 마스킹 적용
        safe_str = mask_sensitive_data(decoded_str)
        return json.loads(safe_str)
    except Exception as e:
        raise ValueError(f"Invalid secure payload: {e}")

if __name__ == "__main__":
    # 테스트 로직
    test_str = "My api key is sk-1234567890abcdef1234567890abcdef12345678 and Bearer abcdefg123"
    print("Original:", test_str)
    print("Masked:", mask_sensitive_data(test_str))
