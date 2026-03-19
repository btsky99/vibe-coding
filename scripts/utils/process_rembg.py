"""
FILE: scripts/utils/process_rembg.py
DESCRIPTION: 배경 제거(rembg) 이미지 처리 유틸리티 (일회용 도구).

REVISION HISTORY:
- 2026-03-19 Claude: 표준 헤더 형식 적용 (RULES.md 섹션 2 준수)
"""
from rembg import remove
from PIL import Image
import sys

def remove_bg(input_path, output_path):
    print("Removing background using AI...")
    input = Image.open(input_path)
    output = remove(input)
    output.save(output_path)
    print("AI Background removal complete.")

if __name__ == "__main__":
    remove_bg(sys.argv[1], sys.argv[2])
