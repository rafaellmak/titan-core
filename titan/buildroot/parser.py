from pathlib import Path
from typing import Dict, List


def parse_buildroot_config(config_path: str) -> Dict:
    config = {}
    packages = []

    path = Path(config_path)

    if not path.exists():
        return {}

    with open(path, 'r', encoding='utf-8', errors='ignore') as f:
        for line in f:
            line = line.strip()

            if not line:
                continue

            if line.startswith('#'):
                continue

            if '=' not in line:
                continue

            key, value = line.split('=', 1)
            value = value.strip('"')

            config[key] = value

            if key.startswith('BR2_PACKAGE_') and value == 'y':
                packages.append(key)

    config['packages'] = packages

    overlay = config.get('BR2_ROOTFS_OVERLAY', '')
    if overlay:
        config['BR2_ROOTFS_OVERLAY_SPLIT'] = overlay.split()

    return config


def parse_buildroot_config_in(config_in_path: str) -> List[Dict]:
    packages = []
    path = Path(config_in_path)
    if not path.exists():
        return packages

    content = path.read_text(errors='ignore')
    for match in __import__('re').finditer(
        r'config\s+(BR2\w+)\s*\n\s*bool\s+"([^"]+)"', content
    ):
        packages.append({
            "symbol": match.group(1),
            "title": match.group(2)
        })
    return packages


def detect_toolchain_config(config: Dict) -> Dict:
    result = {
        'type': 'unknown',
        'vendor': '',
        'c_library': '',
        'gcc_version': '',
        'binutils_version': '',
    }

    if config.get('BR2_TOOLCHAIN_BUILDROOT') == 'y':
        result['type'] = 'buildroot'

        if config.get('BR2_TOOLCHAIN_BUILDROOT_GLIBC') == 'y':
            result['c_library'] = 'glibc'
        elif config.get('BR2_TOOLCHAIN_BUILDROOT_MUSL') == 'y':
            result['c_library'] = 'musl'
        elif config.get('BR2_TOOLCHAIN_BUILDROOT_UCLIBC') == 'y':
            result['c_library'] = 'uclibc'

        result['gcc_version'] = config.get('BR2_GCC_VERSION', '')
        result['binutils_version'] = config.get('BR2_BINUTILS_VERSION', '')

    elif config.get('BR2_TOOLCHAIN_EXTERNAL') == 'y':
        result['type'] = 'external'
        result['vendor'] = config.get('BR2_TOOLCHAIN_EXTERNAL_NAME', '')
        result['gcc_version'] = config.get('BR2_TOOLCHAIN_EXTERNAL_GCC_VERSION', '')

    elif config.get('BR2_TOOLCHAIN_USES_NONE') == 'y':
        result['type'] = 'none'

    return result
