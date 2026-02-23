import os
import sys
from PIL import Image
from pathlib import Path

def convert_to_ico(png_path: str, ico_path: str):
    if not os.path.exists(png_path):
        print(f"Error: {png_path} not found.")
        return False
    
    try:
        img = Image.open(png_path)
        # 여러 사이즈 아이콘 포함 (256x256, 128x128 등)
        icon_sizes = [(256, 256), (128, 128), (64, 64), (32, 32), (16, 16)]
        # 배경 투명 처리 등을 유지 (RGBA)
        img.save(ico_path, format="ICO", sizes=icon_sizes)
        print(f"Successfully converted to {ico_path}")
        return True
    except Exception as e:
        print(f"Conversion failed: {e}")
        return False

if __name__ == "__main__":
    base_dir = Path(r"D:\vibe-coding")
    png_source = base_dir / "assets" / "vibe_coding_icon.png"
    ico_dest = base_dir / ".ai_monitor" / "bin" / "app_icon.ico"
    
    convert_to_ico(str(png_source), str(ico_dest))
