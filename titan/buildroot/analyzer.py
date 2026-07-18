import os
from pathlib import Path
from .parser import parse_buildroot_config, detect_toolchain_config
from .configin_parser import parse_kconfig_file
from .mk_parser import parse_all_packages, discover_mk_files
from .scanner import scan_buildroot_workspace
from ..workspace.models import BuildrootWorkspace


def analyze_buildroot_workspace(root_dir, config_file):
    cfg = parse_buildroot_config(config_file)

    workspace = BuildrootWorkspace(
        root_dir=root_dir,
        output_dir=f'{root_dir}/output'
    )

    workspace.arch = cfg.get('BR2_ARCH', '')
    workspace.hostname = cfg.get('BR2_TARGET_GENERIC_HOSTNAME', '')

    tc = detect_toolchain_config(cfg)
    workspace.toolchain = tc.get('vendor', '')
    if not workspace.toolchain:
        if tc['type'] == 'external':
            workspace.toolchain = cfg.get('BR2_TOOLCHAIN_EXTERNAL_PATH', '')
        elif tc['type'] == 'buildroot':
            workspace.toolchain = f"buildroot-{tc['c_library']}"

    workspace.toolchain_type = tc['type']
    workspace.c_library = tc['c_library']

    workspace.kernel_enabled = bool(
        cfg.get('BR2_LINUX_KERNEL') == 'y'
    )

    workspace.packages = cfg.get('packages', [])

    overlays = cfg.get('BR2_ROOTFS_OVERLAY_SPLIT', [])
    for ov in overlays:
        ov_path = ov.strip()
        if ov_path:
            workspace.overlays.append(ov_path)

    if not overlays:
        single = cfg.get('BR2_ROOTFS_OVERLAY', '')
        if single:
            workspace.overlays.append(single)

    scripts = cfg.get('BR2_ROOTFS_POST_BUILD_SCRIPT', '')
    if scripts:
        for s in scripts.split():
            workspace.post_build_scripts.append(s)

    images = cfg.get('BR2_ROOTFS_POST_IMAGE_SCRIPT', '')
    if images:
        for s in images.split():
            workspace.post_image_scripts.append(s)

    root = Path(root_dir)
    config_in = root / 'Config.in'
    if config_in.exists():
        doc = parse_kconfig_file(str(config_in))
        workspace.kconfig_symbols = list(doc.symbols.keys())
        workspace.kconfig_sources = doc.sources

    mk_files = discover_mk_files(root_dir)
    if mk_files:
        pkgs = parse_all_packages(root_dir)
        workspace.packages_meta = {
            name: pkg.to_dict() for name, pkg in pkgs.items()
        }

    scan_result = scan_buildroot_workspace(root_dir, cfg)
    _apply_scan(workspace, scan_result)

    return workspace


def _apply_scan(workspace: BuildrootWorkspace, scan: dict):
    workspace.init_system = scan.get('init_system', '')
    workspace.filesystem_type = scan.get('filesystem_type', '')
    workspace.sdk_enabled = scan.get('sdk_enabled', False)
    workspace.uboot_enabled = scan.get('uboot_enabled', False)
    workspace.uboot_board = scan.get('uboot_board', '')
    workspace.kernel_version = scan.get('kernel_version', '')
    workspace.kernel_config = scan.get('kernel_config', '')
    workspace.kernel_patches = scan.get('kernel_patches', [])
    workspace.downloads_dir = scan.get('download_dir', '')
    workspace.mirrors = [m[1] for m in scan.get('mirrors', [])]
    workspace.external_trees = scan.get('external_trees', [])
    workspace.custom_packages = scan.get('custom_packages', [])
    workspace.board_support = scan.get('board_support', {})
    workspace.defconfigs = scan.get('defconfigs', [])
    workspace.patches = scan.get('patches', {})
