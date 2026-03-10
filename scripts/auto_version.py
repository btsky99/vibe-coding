import os
import re


def increment_version(version_path):
    if not os.path.exists(version_path):
        print(f"Error: {version_path} not found.")
        return None

    with open(version_path, 'r', encoding='utf-8') as f:
        content = f.read()

    pattern = r'__version__\s*=\s*["\']([^"\']+)["\']'
    match = re.search(pattern, content)
    if not match:
        print("Error: Could not find version string.")
        return None

    current_version = match.group(1)
    parts = current_version.split('.')

    new_parts = []
    for part in parts:
        try:
            new_parts.append(int(part))
        except ValueError:
            new_parts.append(0)

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


def sync_package_json(new_version, pkg_path=".ai_monitor/vibe-view/package.json"):
    if not os.path.exists(pkg_path):
        return
    with open(pkg_path, 'r', encoding='utf-8') as f:
        content = f.read()
    new_content = re.sub(r'"version"\s*:\s*"[^"]+"', f'"version": "{new_version}"', content)
    with open(pkg_path, 'w', encoding='utf-8') as f:
        f.write(new_content)
    print(f"package.json synced -> {new_version}")


def sync_installer_version(new_version, iss_path="vibe-coding-setup.iss"):
    if not os.path.exists(iss_path):
        return
    with open(iss_path, 'r', encoding='utf-8') as f:
        content = f.read()
    new_content = re.sub(
        r'(#define\s+MyAppVersion\s+")([^"]+)(")',
        rf'\g<1>{new_version}\g<3>',
        content,
    )
    with open(iss_path, 'w', encoding='utf-8') as f:
        f.write(new_content)
    print(f"installer synced -> {new_version}")


if __name__ == "__main__":
    version_path = ".ai_monitor/_version.py"
    new_version = increment_version(version_path)
    if new_version:
        sync_package_json(new_version)
        sync_installer_version(new_version)
