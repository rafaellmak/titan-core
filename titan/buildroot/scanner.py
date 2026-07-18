import os
import re
from pathlib import Path
from typing import Dict, List, Optional


def scan_buildroot_workspace(root_dir: str, config: Dict) -> Dict:
    root = Path(root_dir)
    result = {
        'external_trees': [],
        'custom_packages': [],
        'board_support': {},
        'defconfigs': [],
        'patches': {},
        'init_system': '',
        'filesystem_type': '',
        'sdk_enabled': False,
        'uboot_enabled': False,
        'uboot_board': '',
        'kernel_version': '',
        'kernel_config': '',
        'kernel_patches': [],
        'download_dir': '',
        'mirrors': [],
    }

    result['init_system'] = _detect_init_system(config)
    result['filesystem_type'] = _detect_filesystem(config)
    result['sdk_enabled'] = config.get('BR2_PACKAGE_HOST_SDK') == 'y'
    result['uboot_enabled'] = config.get('BR2_TARGET_UBOOT') == 'y'
    result['uboot_board'] = config.get('BR2_TARGET_UBOOT_BOARDNAME', '')
    result['kernel_version'] = config.get('BR2_LINUX_KERNEL_CUSTOM_VERSION', '')
    result['kernel_config'] = config.get('BR2_LINUX_KERNEL_CUSTOM_CONFIG', '')
    result['download_dir'] = config.get('BR2_DL_DIR', '')

    kernel_patches = config.get('BR2_LINUX_KERNEL_PATCH', '')
    if kernel_patches:
        result['kernel_patches'] = [p.strip() for p in kernel_patches.split() if p.strip()]

    primary = config.get('BR2_PRIMARY_SITE', '')
    backup = config.get('BR2_BACKUP_SITE', '')
    if primary:
        result['mirrors'].append(('primary', primary))
    if backup:
        result['mirrors'].append(('backup', backup))

    result['external_trees'] = _detect_external_trees(root)
    result['custom_packages'] = _detect_custom_packages(root, result['external_trees'])
    result['board_support'] = _detect_board_support(root)
    result['defconfigs'] = _detect_defconfigs(root, result['external_trees'])
    result['patches'] = _detect_patches(root)

    return result


def _detect_init_system(config: Dict) -> str:
    if config.get('BR2_INIT_SYSTEMD') == 'y':
        return 'systemd'
    if config.get('BR2_INIT_BUSYBOX') == 'y':
        return 'busybox'
    if config.get('BR2_INIT_OPENRC') == 'y':
        return 'openrc'
    if config.get('BR2_INIT_NONE') == 'y':
        return 'none'
    if config.get('BR2_INIT_CUSTOM') == 'y':
        return 'custom'
    return ''


def _detect_filesystem(config: Dict) -> str:
    for fs in ('EXT2', 'EXT3', 'EXT4', 'SQUASHFS', 'CPIO', 'TAR', 'UBIFS', 'JFFS2', 'BTRFS', 'EROFS', 'F2FS', 'YAFFS2'):
        if config.get(f'BR2_TARGET_ROOTFS_{fs}') == 'y':
            return fs.lower()
    if config.get('BR2_TARGET_ROOTFS_INITRAMFS') == 'y':
        return 'initramfs'
    return ''


def _detect_external_trees(root: Path) -> List[Dict]:
    trees = []

    br2_external_file = root / 'BR2_EXTERNAL'
    if br2_external_file.exists():
        try:
            content = br2_external_file.read_text(errors='ignore').strip()
            for line in content.splitlines():
                line = line.strip()
                if line and not line.startswith('#'):
                    ext_path = Path(line)
                    if not ext_path.is_absolute():
                        ext_path = root / ext_path
                    if ext_path.exists():
                        trees.append(_scan_external_tree(ext_path))
        except Exception:
            pass

    env_ext = os.environ.get('BR2_EXTERNAL', '')
    if env_ext:
        for path_str in env_ext.split(':'):
            ext_path = Path(path_str)
            if ext_path.exists() and ext_path != root:
                if not any(t['path'] == str(ext_path) for t in trees):
                    trees.append(_scan_external_tree(ext_path))

    return trees


def _scan_external_tree(path: Path) -> Dict:
    info = {
        'path': str(path),
        'name': path.name,
        'packages': [],
        'configs': [],
        'has_config_in': False,
    }

    config_in = path / 'Config.in'
    if config_in.exists():
        info['has_config_in'] = True

    pkg_dir = path / 'package'
    if pkg_dir.exists():
        info['packages'] = sorted([
            d.name for d in pkg_dir.iterdir()
            if d.is_dir() and not d.name.startswith('.')
        ])

    configs_dir = path / 'configs'
    if configs_dir.exists():
        info['configs'] = sorted([
            f.name for f in configs_dir.iterdir()
            if f.suffix in ('', '.config') and not f.name.startswith('.')
        ])

    return info


def _detect_custom_packages(root: Path, external_trees: List[Dict]) -> List[Dict]:
    custom = []

    board_pkg = root / 'board'
    if board_pkg.exists():
        for d in board_pkg.iterdir():
            if d.is_dir() and not d.name.startswith('.'):
                pkg_info = {'name': d.name, 'source': 'board'}
                mk_files = list(d.rglob('*.mk'))
                if mk_files:
                    pkg_info['mk_files'] = [str(f.relative_to(root)) for f in mk_files]
                patches = list(d.rglob('*.patch'))
                if patches:
                    pkg_info['patches_count'] = len(patches)
                custom.append(pkg_info)

    for ext in external_trees:
        ext_path = Path(ext['path'])
        pkg_dir = ext_path / 'package'
        if pkg_dir.exists():
            for d in pkg_dir.iterdir():
                if d.is_dir() and not d.name.startswith('.'):
                    custom.append({
                        'name': d.name,
                        'source': f'external:{ext["name"]}',
                    })

    return custom


def _detect_board_support(root: Path) -> Dict:
    board_dir = root / 'board'
    if not board_dir.exists():
        return {}

    boards = []
    for vendor_dir in board_dir.iterdir():
        if vendor_dir.is_dir() and not vendor_dir.name.startswith('.'):
            board_info = {
                'vendor': vendor_dir.name,
                'boards': [],
                'patches_count': 0,
            }
            for board_item in vendor_dir.iterdir():
                if board_item.is_dir():
                    board_info['boards'].append(board_item.name)
                elif board_item.suffix == '.patch':
                    board_info['patches_count'] += 1

            dts_files = list(vendor_dir.rglob('*.dts')) + list(vendor_dir.rglob('*.dtsi'))
            if dts_files:
                board_info['device_trees'] = [str(f.relative_to(board_dir)) for f in dts_files]

            uboot_scr = list(vendor_dir.rglob('*.scr')) + list(vendor_dir.rglob('boot.cmd'))
            if uboot_scr:
                board_info['boot_scripts'] = [str(f.relative_to(board_dir)) for f in uboot_scr]

            boards.append(board_info)

    return {
        'board_dir': str(board_dir),
        'vendors': boards,
    }


def _detect_defconfigs(root: Path, external_trees: List[Dict]) -> List[Dict]:
    defconfigs = []

    configs_dir = root / 'configs'
    if configs_dir.exists():
        for f in sorted(configs_dir.iterdir()):
            if f.is_file() and not f.name.startswith('.'):
                size = f.stat().st_size
                defconfigs.append({
                    'name': f.name,
                    'path': str(f.relative_to(root)),
                    'size': size,
                    'source': 'buildroot',
                })

    for ext in external_trees:
        ext_path = Path(ext['path'])
        ext_configs = ext_path / 'configs'
        if ext_configs.exists():
            for f in sorted(ext_configs.iterdir()):
                if f.is_file() and not f.name.startswith('.'):
                    defconfigs.append({
                        'name': f.name,
                        'path': str(f.relative_to(ext_path)),
                        'size': f.stat().st_size,
                        'source': f'external:{ext["name"]}',
                    })

    return defconfigs


def _detect_patches(root: Path) -> Dict[str, List[str]]:
    patches = {}

    patches_dir = root / 'patches'
    if patches_dir.exists():
        for pkg_dir in patches_dir.iterdir():
            if pkg_dir.is_dir() and not pkg_dir.name.startswith('.'):
                pkg_patches = sorted([
                    str(f.relative_to(root))
                    for f in pkg_dir.iterdir()
                    if f.suffix in ('.patch', '.diff') or f.name.endswith('.patch')
                ])
                if pkg_patches:
                    patches[pkg_dir.name] = pkg_patches

    return patches
