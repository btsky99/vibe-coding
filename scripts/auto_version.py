import sys
import os
import re

def increment_version(version_path):
    if not os.path.exists(version_path):
        print(f"Error: {version_path} not found.")
        return None

    with open(version_path, 'r', encoding='utf-8') as f:
        content = f.read()

    # __version__ = "3.5.1" 형태 찾기
    pattern = r'__version__\s*=\s*["\']([^"\']+)["\']'
    match = re.search(pattern, content)
    if not match:
        print("Error: Could not find version string.")
        return None

    current_version = match.group(1)
    parts = current_version.split('.')
    
    new_parts = []
    for p in parts:
        try:
            new_parts.append(int(p))
        except ValueError:
            new_parts.append(0)

    # 마지막 자리(Patch) 증가
    if len(new_parts) >= 3:
        new_parts[-1] += 1
    else:
        new_parts.append(1)

    new_version = '.'.join(map(str, new_parts))
    new_content = re.sub(pattern, f'__version__ = "{new_version}"', content)
    
    with open(version_path, 'w', encoding='utf-8') as f:
        f.write(new_content)
    
    print(f"{current_version} -> {new_version}")
    return new_version

def sync_package_json(new_version: str, pkg_path: str = ".ai_monitor/vibe-view/package.json"):
    """package.json의 version 필드를 _version.py와 동기화합니다."""
    if not os.path.exists(pkg_path):
        return
    with open(pkg_path, 'r', encoding='utf-8') as f:
        content = f.read()
    new_content = re.sub(r'"version"\s*:\s*"[^"]+"', f'"version": "{new_version}"', content)
    with open(pkg_path, 'w', encoding='utf-8') as f:
        f.write(new_content)
    print(f"package.json 버전 동기화: {new_version}")


if __name__ == "__main__":
    v_path = ".ai_monitor/_version.py"
    new_ver = increment_version(v_path)
    if new_ver:
        sync_package_json(new_ver)
