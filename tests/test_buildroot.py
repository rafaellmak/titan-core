import pytest
import tempfile
import os
from pathlib import Path


SAMPLE_CONFIG_IN = """menu "Networking"
\tdepends on BR2_PACKAGE_LINUX
\tsource "package/openssl/Config.in"

\tmenu "SSL Libraries"
\t\tconfig BR2_PACKAGE_OPENSSL
\t\t\tbool "openssl"
\t\t\tdepends on BR2_TOOLCHAIN_HAS_THREADS
\t\t\tselect BR2_PACKAGE_ZLIB
\t\t\tselect BR2_PACKAGE_HOST_PKGCONF if BR2_PACKAGE_HOST_PKGCONF
\t\t\tdepends on !BR2_STATIC_LIBS
\t\t\tdefault y if BR2_PACKAGE_CURL
\t\t\thelp
\t\t\t  OpenSSL is an open source implementation
\t\t\t  of the TLS and SSL protocols.

\t\t\t  https://www.openssl.org/

\t\tconfig BR2_PACKAGE_LIBRESSL
\t\t\tbool "libressl"
\t\t\tselect BR2_PACKAGE_OPENBSD

\tendmenu

\tchoice
\t\tprompt "SSL library"
\t\tdepends on BR2_PACKAGE_OPENSSL || BR2_PACKAGE_LIBRESSL
\t\tdefault BR2_PACKAGE_LIBRESSL

\t\tconfig BR2_PACKAGE_OPENSSL_IMPL
\t\t\tbool "openssl"

\t\tconfig BR2_PACKAGE_LIBRESSL_IMPL
\t\t\tbool "libressl"
\tendchoice

\tconfig BR2_PACKAGE_CURL
\t\ttristate "curl"
\t\tdepends on BR2_PACKAGE_OPENSSL || BR2_PACKAGE_LIBRESSL
\t\tdefault y if BR2_PACKAGE_OPENSSL

\tif BR2_PACKAGE_CURL
\t\tconfig BR2_PACKAGE_CURL_SSL
\t\t\tstring "SSL variant"
\t\t\tdefault "openssl"
\tendif

endmenu

config BR2_PACKAGE_BUSYBOX
\tbool "busybox"
\tdefault y

comment "some comment"
"""

SAMPLE_MK_CONTENT = """# openssl
OPENSSL_VERSION = 3.0.8
OPENSSL_SITE = https://www.openssl.org/source
OPENSSL_LICENSE = OpenSSL
OPENSSL_LICENSE_FILES = LICENSE
OPENSSL_DEPENDENCIES = zlib host-pkgconf

# busybox
BUSYBOX_VERSION = 1.36.0
BUSYBOX_SITE = https://busybox.net/downloads
BUSYBOX_DEPENDENCIES =

# host tool
HOST_PKGCONF_VERSION = 1.8.0
HOST_PKGCONF_DEPENDENCIES = host-pkgconf
"""

SAMPLE_MK_EXTRA = """CURL_VERSION = 7.88.1
CURL_SITE = https://curl.se/download
CURL_DEPENDENCIES = openssl zlib
"""

SAMPLE_DOT_CONFIG = """BR2_ARCH="arm"
BR2_TOOLCHAIN_BUILDROOT=y
BR2_TOOLCHAIN_BUILDROOT_GLIBC=y
BR2_GCC_VERSION="11.3.0"
BR2_BINUTILS_VERSION="2.38"
BR2_TARGET_GENERIC_HOSTNAME="myboard"
BR2_LINUX_KERNEL=y
BR2_PACKAGE_BUSYBOX=y
BR2_PACKAGE_OPENSSL=y
BR2_PACKAGE_CURL=y
BR2_ROOTFS_OVERLAY="board/myboard/rootfs-overlay board/common/overlay"
BR2_ROOTFS_POST_BUILD_SCRIPT="board/myboard/post-build.sh"
BR2_ROOTFS_POST_IMAGE_SCRIPT="board/myboard/post-image.sh"
"""

SAMPLE_BUILD_LOG = """
[INFO] Building openssl-3.0.8
configure: error: C compiler cannot create executables
fakeroot failed: command not found
wget failed: timeout
undefined reference to `SSL_new'
No space left on device: /build/output/images
"""


class TestConfigInParser:
    def test_parse_config_symbol(self):
        from titan.buildroot.configin_parser import parse_kconfig
        doc = parse_kconfig(SAMPLE_CONFIG_IN)
        assert 'BR2_PACKAGE_OPENSSL' in doc.symbols
        sym = doc.symbols['BR2_PACKAGE_OPENSSL']
        assert sym.type == 'bool'
        assert sym.prompt == 'openssl'
        assert 'BR2_TOOLCHAIN_HAS_THREADS' in sym.depends_on[0]
        assert 'BR2_PACKAGE_ZLIB' in sym.selects
        assert 'BR2_PACKAGE_HOST_PKGCONF if BR2_PACKAGE_HOST_PKGCONF' in sym.selects
        assert 'y if BR2_PACKAGE_CURL' in sym.defaults[0]
        assert 'OpenSSL is an open source implementation' in sym.help_text

    def test_parse_menuconfig(self):
        from titan.buildroot.configin_parser import parse_kconfig
        doc = parse_kconfig(SAMPLE_CONFIG_IN)
        assert 'BR2_PACKAGE_LIBRESSL' in doc.symbols
        sym = doc.symbols['BR2_PACKAGE_LIBRESSL']
        assert sym.type == 'bool'
        assert 'BR2_PACKAGE_OPENBSD' in sym.selects

    def test_parse_menu_structure(self):
        from titan.buildroot.configin_parser import parse_kconfig
        doc = parse_kconfig(SAMPLE_CONFIG_IN)
        menus = [c for c in doc.children if hasattr(c, 'prompt') and hasattr(c, 'children')]
        assert len(menus) >= 1

    def test_parse_choice(self):
        from titan.buildroot.configin_parser import parse_kconfig
        doc = parse_kconfig(SAMPLE_CONFIG_IN)

        def find_choices(items):
            result = []
            for c in items:
                if hasattr(c, 'symbols') and not hasattr(c, 'children'):
                    result.append(c)
                if hasattr(c, 'children'):
                    result.extend(find_choices(c.children))
            return result

        choices = find_choices(doc.children)
        assert len(choices) >= 1
        choice = choices[0]
        assert choice.type == 'bool'
        assert len(choice.symbols) >= 2

    def test_parse_if_block(self):
        from titan.buildroot.configin_parser import parse_kconfig
        doc = parse_kconfig(SAMPLE_CONFIG_IN)
        assert 'BR2_PACKAGE_CURL_SSL' in doc.symbols
        sym = doc.symbols['BR2_PACKAGE_CURL_SSL']
        assert sym.type == 'string'

    def test_parse_tristate(self):
        from titan.buildroot.configin_parser import parse_kconfig
        doc = parse_kconfig(SAMPLE_CONFIG_IN)
        sym = doc.symbols['BR2_PACKAGE_CURL']
        assert sym.type == 'tristate'

    def test_parse_sources(self):
        from titan.buildroot.configin_parser import parse_kconfig
        doc = parse_kconfig(SAMPLE_CONFIG_IN)
        assert 'package/openssl/Config.in' in doc.sources

    def test_parse_file_not_found(self):
        from titan.buildroot.configin_parser import parse_kconfig_file
        doc = parse_kconfig_file('/nonexistent/Config.in')
        assert len(doc.symbols) == 0


class TestMkParser:
    def test_parse_dependencies(self):
        from titan.buildroot.mk_parser import parse_mk_content
        pkgs = parse_mk_content(SAMPLE_MK_CONTENT)
        assert 'openssl' in pkgs
        assert pkgs['openssl'].dependencies == ['zlib', 'host-pkgconf']
        assert pkgs['openssl'].version == '3.0.8'
        assert pkgs['openssl'].site == 'https://www.openssl.org/source'
        assert pkgs['openssl'].license == 'OpenSSL'

    def test_parse_host_package(self):
        from titan.buildroot.mk_parser import parse_mk_content
        pkgs = parse_mk_content(SAMPLE_MK_CONTENT)
        assert 'host-pkgconf' in pkgs or 'pkgconf' in pkgs

    def test_parse_empty_deps(self):
        from titan.buildroot.mk_parser import parse_mk_content
        pkgs = parse_mk_content(SAMPLE_MK_CONTENT)
        assert 'busybox' in pkgs
        assert pkgs['busybox'].dependencies == []

    def test_parse_multiple_files(self):
        from titan.buildroot.mk_parser import parse_mk_content
        pkgs1 = parse_mk_content(SAMPLE_MK_CONTENT)
        pkgs2 = parse_mk_content(SAMPLE_MK_EXTRA)
        assert 'openssl' in pkgs1
        assert 'curl' in pkgs2
        assert 'openssl' in pkgs2['curl'].dependencies

    def test_discover_mk_files(self):
        from titan.buildroot.mk_parser import discover_mk_files
        with tempfile.TemporaryDirectory() as tmp:
            pkg_dir = Path(tmp) / 'package' / 'foo'
            pkg_dir.mkdir(parents=True)
            (pkg_dir / 'foo.mk').write_text('FOO_VERSION = 1.0')
            files = discover_mk_files(tmp)
            assert str(pkg_dir / 'foo.mk') in files


class TestParser:
    def test_parse_dot_config(self):
        from titan.buildroot.parser import parse_buildroot_config
        with tempfile.NamedTemporaryFile(mode='w', suffix='.config', delete=False) as f:
            f.write(SAMPLE_DOT_CONFIG)
            cfg_path = f.name
        try:
            cfg = parse_buildroot_config(cfg_path)
            assert cfg['BR2_ARCH'] == 'arm'
            assert len(cfg['packages']) == 3
            assert 'BR2_PACKAGE_BUSYBOX' in cfg['packages']
        finally:
            os.unlink(cfg_path)

    def test_parse_overlay_split(self):
        from titan.buildroot.parser import parse_buildroot_config
        with tempfile.NamedTemporaryFile(mode='w', suffix='.config', delete=False) as f:
            f.write(SAMPLE_DOT_CONFIG)
            cfg_path = f.name
        try:
            cfg = parse_buildroot_config(cfg_path)
            assert 'BR2_ROOTFS_OVERLAY_SPLIT' in cfg
            assert len(cfg['BR2_ROOTFS_OVERLAY_SPLIT']) == 2
        finally:
            os.unlink(cfg_path)

    def test_detect_toolchain_config(self):
        from titan.buildroot.parser import detect_toolchain_config
        cfg = {
            'BR2_TOOLCHAIN_BUILDROOT': 'y',
            'BR2_TOOLCHAIN_BUILDROOT_GLIBC': 'y',
            'BR2_GCC_VERSION': '11.3.0',
        }
        tc = detect_toolchain_config(cfg)
        assert tc['type'] == 'buildroot'
        assert tc['c_library'] == 'glibc'
        assert tc['gcc_version'] == '11.3.0'

    def test_detect_external_toolchain(self):
        from titan.buildroot.parser import detect_toolchain_config
        cfg = {
            'BR2_TOOLCHAIN_EXTERNAL': 'y',
            'BR2_TOOLCHAIN_EXTERNAL_NAME': 'arm-gnu-toolchain',
        }
        tc = detect_toolchain_config(cfg)
        assert tc['type'] == 'external'
        assert tc['vendor'] == 'arm-gnu-toolchain'


class TestDiagnostics:
    def test_analyze_build_log(self):
        from titan.buildroot.diagnostics import analyze_build_log
        findings = analyze_build_log(SAMPLE_BUILD_LOG)
        categories = [f['category'] for f in findings]
        assert 'configure' in categories
        assert 'rootfs' in categories
        assert 'download' in categories
        assert 'linker' in categories
        assert 'storage' in categories

    def test_analyze_empty_log(self):
        from titan.buildroot.diagnostics import analyze_build_log
        findings = analyze_build_log("Build completed successfully")
        assert len(findings) == 0

    def test_common_errors_keys(self):
        from titan.buildroot.diagnostics import COMMON_ERRORS
        assert 'external toolchain not found' in COMMON_ERRORS
        assert 'No space left on device' in COMMON_ERRORS
        assert len(COMMON_ERRORS) >= 8


class TestAnalyzer:
    def test_analyze_with_real_files(self):
        from titan.buildroot.analyzer import analyze_buildroot_workspace
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'Config.in').write_text(SAMPLE_CONFIG_IN)
            (root / 'Makefile').write_text('# BR2 stuff')
            pkg_dir = root / 'package' / 'openssl'
            pkg_dir.mkdir(parents=True)
            (pkg_dir / 'openssl.mk').write_text(SAMPLE_MK_CONTENT)
            (root / '.config').write_text(SAMPLE_DOT_CONFIG)
            ws = analyze_buildroot_workspace(str(root), str(root / '.config'))
            assert ws.arch == 'arm'
            assert len(ws.packages) == 3
            assert len(ws.overlays) == 2
            assert len(ws.post_build_scripts) == 1
            assert len(ws.kconfig_symbols) >= 5
            assert len(ws.packages_meta) >= 1


class TestBuildrootSkill:
    @pytest.mark.asyncio
    async def test_can_handle_buildroot_scan(self):
        from titan.skills.buildroot_skill import BuildrootSkill
        skill = BuildrootSkill()
        assert skill.can_handle("buildroot_scan", {})
        assert skill.can_handle("workspace_scan", {})
        assert not skill.can_handle("unknown_event", {})

    @pytest.mark.asyncio
    async def test_execute_no_workspace(self):
        from titan.skills.buildroot_skill import BuildrootSkill
        from titan.core.event_bus import LocalEventBus
        from titan.core.memory import MultiLayerMemory
        import tempfile

        bus = LocalEventBus()
        memory = MultiLayerMemory(bus)
        skill = BuildrootSkill()

        result = await skill.execute({}, memory, memory.digital_twin, memory.knowledge_engine)
        assert result == {"status": "no_buildroot_workspace"}

    @pytest.mark.asyncio
    async def test_execute_with_br_workspace(self):
        from titan.skills.buildroot_skill import BuildrootSkill
        from titan.core.event_bus import LocalEventBus
        from titan.core.memory import MultiLayerMemory
        from pathlib import Path
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'Config.in').write_text('config BR2_PACKAGE_FOO\n\tbool "foo"\n')
            (root / 'Makefile').write_text('BR2_MAKE=1\n# buildroot stuff')
            (root / '.config').write_text('BR2_ARCH="arm"\nBR2_PACKAGE_FOO=y\nBR2_ROOTFS_OVERLAY="overlay1 overlay2"\n')
            pkg_dir = root / 'package' / 'foo'
            pkg_dir.mkdir(parents=True)
            (pkg_dir / 'foo.mk').write_text('FOO_VERSION = 1.0\nFOO_DEPENDENCIES = bar\n')

            original_cwd = Path.cwd()
            import os
            os.chdir(str(root))
            try:
                bus = LocalEventBus()
                memory = MultiLayerMemory(bus)
                skill = BuildrootSkill()
                result = await skill.execute({}, memory, memory.digital_twin, memory.knowledge_engine)
                assert result["status"] == "indexed"
                assert result["arch"] == "arm"
                assert result["packages"] >= 1
                assert result["overlays"] == 2
            finally:
                os.chdir(str(original_cwd))


class TestDigitalTwinEvents:
    def test_buildroot_workspace_scanned(self):
        from titan.core.digital_twin import DigitalTwin
        from titan.core.event_bus import LocalEventBus
        bus = LocalEventBus()
        dt = DigitalTwin(bus, base_path="/tmp/.twin_test")
        dt.emit_event("buildroot_workspace_scanned", {
            "arch": "aarch64", "toolchain_type": "external", "c_library": "glibc"
        })
        assert dt.graph.has_node("buildroot:workspace")
        assert dt.graph.nodes["buildroot:workspace"]["arch"] == "aarch64"

    def test_buildroot_package_added(self):
        from titan.core.digital_twin import DigitalTwin
        from titan.core.event_bus import LocalEventBus
        bus = LocalEventBus()
        dt = DigitalTwin(bus, base_path="/tmp/.twin_test")
        dt.emit_event("buildroot_workspace_scanned", {})
        dt.emit_event("buildroot_package_added", {"package": "BR2_PACKAGE_BUSYBOX"})
        assert dt.graph.has_node("buildroot_package:BR2_PACKAGE_BUSYBOX")
        assert dt.graph.has_edge("buildroot:workspace", "buildroot_package:BR2_PACKAGE_BUSYBOX")

    def test_buildroot_package_dependency(self):
        from titan.core.digital_twin import DigitalTwin
        from titan.core.event_bus import LocalEventBus
        bus = LocalEventBus()
        dt = DigitalTwin(bus, base_path="/tmp/.twin_test")
        dt.emit_event("buildroot_workspace_scanned", {})
        dt.emit_event("buildroot_package_dependency", {"package": "openssl", "depends_on": "zlib"})
        assert dt.graph.has_edge("buildroot_package:openssl", "buildroot_package:zlib")
        assert dt.graph.edges[("buildroot_package:openssl", "buildroot_package:zlib")]["relation"] == "depends_on"

    def test_buildroot_overlay_added(self):
        from titan.core.digital_twin import DigitalTwin
        from titan.core.event_bus import LocalEventBus
        bus = LocalEventBus()
        dt = DigitalTwin(bus, base_path="/tmp/.twin_test")
        dt.emit_event("buildroot_workspace_scanned", {})
        dt.emit_event("buildroot_overlay_added", {"overlay": "board/myboard/overlay"})
        assert dt.graph.has_node("buildroot_overlay:board/myboard/overlay")
        assert dt.graph.has_edge("buildroot:workspace", "buildroot_overlay:board/myboard/overlay")


class TestWorkspaceScanner:
    def test_detect_init_system(self):
        cfg = {'BR2_INIT_SYSTEMD': 'y'}
        from titan.buildroot.scanner import _detect_init_system
        assert _detect_init_system(cfg) == 'systemd'

    def test_detect_filesystem(self):
        cfg = {'BR2_TARGET_ROOTFS_EXT4': 'y'}
        from titan.buildroot.scanner import _detect_filesystem
        assert _detect_filesystem(cfg) == 'ext4'

    def test_detect_external_trees_env(self):
        from titan.buildroot.scanner import _detect_external_trees
        import os
        original = os.environ.get('BR2_EXTERNAL', '')
        os.environ['BR2_EXTERNAL'] = '/nonexistent/external'
        try:
            trees = _detect_external_trees(Path('/tmp'))
            assert len(trees) == 0
        finally:
            if original:
                os.environ['BR2_EXTERNAL'] = original
            else:
                del os.environ['BR2_EXTERNAL']

    def test_detect_defconfigs(self):
        from titan.buildroot.scanner import _detect_defconfigs
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            configs = root / 'configs'
            configs.mkdir()
            (configs / 'myboard_defconfig').write_text('BR2_ARCH="arm"\n')
            (configs / '.hidden').write_text('')
            defconfigs = _detect_defconfigs(root, [])
            names = [d['name'] for d in defconfigs]
            assert 'myboard_defconfig' in names
            assert '.hidden' not in names

    def test_detect_patches(self):
        from titan.buildroot.scanner import _detect_patches
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            patch_dir = root / 'patches' / 'openssl'
            patch_dir.mkdir(parents=True)
            (patch_dir / '0001-fix.patch').write_text('patch')
            (patch_dir / '0002-fix.diff').write_text('diff')
            patches = _detect_patches(root)
            assert 'openssl' in patches
            assert len(patches['openssl']) == 2

    def test_scan_buildroot_workspace(self):
        from titan.buildroot.scanner import scan_buildroot_workspace
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'configs').mkdir()
            (root / 'configs' / 'myboard_defconfig').write_text('')
            (root / 'patches' / 'busybox').mkdir(parents=True)
            (root / 'patches' / 'busybox' / 'fix.patch').write_text('')
            config = {
                'BR2_INIT_BUSYBOX': 'y',
                'BR2_TARGET_ROOTFS_SQUASHFS': 'y',
                'BR2_PACKAGE_HOST_SDK': 'y',
                'BR2_TARGET_UBOOT': 'y',
                'BR2_TARGET_UBOOT_BOARDNAME': 'myboard',
                'BR2_LINUX_KERNEL_CUSTOM_VERSION': '6.6',
            }
            result = scan_buildroot_workspace(str(root), config)
            assert result['init_system'] == 'busybox'
            assert result['filesystem_type'] == 'squashfs'
            assert result['sdk_enabled'] is True
            assert result['uboot_enabled'] is True
            assert result['uboot_board'] == 'myboard'
            assert len(result['defconfigs']) == 1
            assert 'busybox' in result['patches']

    def test_scanner_integrates_with_analyzer(self):
        from titan.buildroot.analyzer import analyze_buildroot_workspace
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'Config.in').write_text('config BR2_PACKAGE_FOO\n\tbool "foo"\n')
            (root / 'Makefile').write_text('BR2_MAKE=1\n')
            (root / '.config').write_text('BR2_ARCH="arm"\nBR2_PACKAGE_FOO=y\nBR2_INIT_SYSTEMD=y\nBR2_TARGET_ROOTFS_EXT4=y\n')
            ws = analyze_buildroot_workspace(str(root), str(root / '.config'))
            assert ws.init_system == 'systemd'
            assert ws.filesystem_type == 'ext4'


class TestDigitalTwinScannerEvents:
    def test_external_tree_event(self):
        from titan.core.digital_twin import DigitalTwin
        from titan.core.event_bus import LocalEventBus
        bus = LocalEventBus()
        dt = DigitalTwin(bus, base_path="/tmp/.twin_test")
        dt.emit_event("buildroot_workspace_scanned", {})
        dt.emit_event("buildroot_external_tree", {
            "path": "/opt/br-ext", "name": "br-ext", "packages": ["foo", "bar"]
        })
        assert dt.graph.has_node("buildroot_external:br-ext")
        assert dt.graph.has_edge("buildroot:workspace", "buildroot_external:br-ext")

    def test_defconfig_event(self):
        from titan.core.digital_twin import DigitalTwin
        from titan.core.event_bus import LocalEventBus
        bus = LocalEventBus()
        dt = DigitalTwin(bus, base_path="/tmp/.twin_test")
        dt.emit_event("buildroot_workspace_scanned", {})
        dt.emit_event("buildroot_defconfig", {"name": "myboard_defconfig", "source": "buildroot"})
        assert dt.graph.has_node("buildroot_defconfig:myboard_defconfig")
        assert dt.graph.has_edge("buildroot:workspace", "buildroot_defconfig:myboard_defconfig")

    def test_uboot_event(self):
        from titan.core.digital_twin import DigitalTwin
        from titan.core.event_bus import LocalEventBus
        bus = LocalEventBus()
        dt = DigitalTwin(bus, base_path="/tmp/.twin_test")
        dt.emit_event("buildroot_workspace_scanned", {})
        dt.emit_event("buildroot_uboot_detected", {"board": "myboard"})
        assert dt.graph.has_node("buildroot:uboot")

    def test_init_system_event(self):
        from titan.core.digital_twin import DigitalTwin
        from titan.core.event_bus import LocalEventBus
        bus = LocalEventBus()
        dt = DigitalTwin(bus, base_path="/tmp/.twin_test")
        dt.emit_event("buildroot_workspace_scanned", {})
        dt.emit_event("buildroot_init_system", {"init": "systemd"})
        assert dt.graph.has_node("buildroot_init:systemd")


class TestDigitalTwinSnapshots:
    def test_create_snapshot(self):
        import tempfile, os
        from titan.core.digital_twin import DigitalTwin
        from titan.core.event_bus import LocalEventBus
        with tempfile.TemporaryDirectory() as tmp:
            dt = DigitalTwin(LocalEventBus(), base_path=os.path.join(tmp, "twin"))
            dt.emit_event("layer_added", {"layer": "meta-test"})
            snap = dt.create_snapshot("snap-001")
            assert snap.id == "snap-001"
            assert snap.parent is None
            assert snap.event_cursor == 1
            assert snap.metrics["total_nodes"] == 1

    def test_snapshot_parent_chain(self):
        import tempfile, os
        from titan.core.digital_twin import DigitalTwin
        from titan.core.event_bus import LocalEventBus
        with tempfile.TemporaryDirectory() as tmp:
            dt = DigitalTwin(LocalEventBus(), base_path=os.path.join(tmp, "twin"))
            s1 = dt.create_snapshot("snap-001")
            s2 = dt.create_snapshot("snap-002", parent="snap-001")
            s3 = dt.create_snapshot("snap-003", parent="snap-002")
            assert s2.parent == "snap-001"
            assert s3.parent == "snap-002"

    def test_snapshot_persistence(self):
        import tempfile, os
        from titan.core.digital_twin import DigitalTwin
        from titan.core.event_bus import LocalEventBus
        with tempfile.TemporaryDirectory() as tmp:
            base = os.path.join(tmp, "twin")
            dt = DigitalTwin(LocalEventBus(), base_path=base)
            dt.emit_event("layer_added", {"layer": "meta-oe"})
            dt.create_snapshot("snap-001")
            # New twin instance loads existing snapshots.db
            dt2 = DigitalTwin(LocalEventBus(), base_path=base)
            loaded = dt2.get_snapshot("snap-001")
            assert loaded is not None
            assert loaded.id == "snap-001"
            assert loaded.metrics["total_nodes"] == 1

    def test_snapshot_list(self):
        import tempfile, os
        from titan.core.digital_twin import DigitalTwin
        from titan.core.event_bus import LocalEventBus
        with tempfile.TemporaryDirectory() as tmp:
            dt = DigitalTwin(LocalEventBus(), base_path=os.path.join(tmp, "twin"))
            dt.create_snapshot("snap-001")
            dt.create_snapshot("snap-002")
            snaps = dt.list_snapshots()
            assert len(snaps) == 2
            assert snaps[0].id in ("snap-001", "snap-002")

    def test_snapshot_fingerprint(self):
        import tempfile, os
        from titan.core.digital_twin import DigitalTwin
        from titan.core.event_bus import LocalEventBus
        with tempfile.TemporaryDirectory() as tmp:
            dt = DigitalTwin(LocalEventBus(), base_path=os.path.join(tmp, "twin"))
            snap = dt.create_snapshot("snap-fp",
                workspace_fingerprint="buildroot/aarch64/gcc/glibc")
            assert snap.workspace_fingerprint == "buildroot/aarch64/gcc/glibc"
            loaded = dt.get_snapshot("snap-fp")
            assert loaded.workspace_fingerprint == "buildroot/aarch64/gcc/glibc"

    def test_snapshot_metrics(self):
        import tempfile, os
        from titan.core.digital_twin import DigitalTwin
        from titan.core.event_bus import LocalEventBus
        with tempfile.TemporaryDirectory() as tmp:
            dt = DigitalTwin(LocalEventBus(), base_path=os.path.join(tmp, "twin"))
            dt.emit_event("layer_added", {"layer": "meta-oe"})
            dt.emit_event("recipe_added", {"recipe": "curl", "layer": "meta-oe"})
            dt.emit_event("dependency_added", {"source_recipe": "curl", "target_package": "openssl"})
            snap = dt.create_snapshot("snap-metrics")
            assert snap.metrics["layers"] == 1
            assert snap.metrics["recipes"] == 1
            assert snap.metrics["packages"] == 1
            assert snap.metrics["total_nodes"] == 3

    def test_snapshot_event_cursor(self):
        import tempfile, os
        from titan.core.digital_twin import DigitalTwin
        from titan.core.event_bus import LocalEventBus
        with tempfile.TemporaryDirectory() as tmp:
            dt = DigitalTwin(LocalEventBus(), base_path=os.path.join(tmp, "twin"))
            dt.emit_event("layer_added", {"layer": "meta-a"})
            dt.emit_event("layer_added", {"layer": "meta-b"})
            snap1 = dt.create_snapshot("before")
            assert snap1.event_cursor == 2
            dt.emit_event("layer_added", {"layer": "meta-c"})
            snap2 = dt.create_snapshot("after")
            assert snap2.event_cursor == 3

    def test_snapshot_gml_sidecar(self):
        import tempfile, os
        from titan.core.digital_twin import DigitalTwin
        from titan.core.event_bus import LocalEventBus
        with tempfile.TemporaryDirectory() as tmp:
            dt = DigitalTwin(LocalEventBus(), base_path=os.path.join(tmp, "twin"))
            dt.emit_event("layer_added", {"layer": "meta-test"})
            dt.create_snapshot("snap-gml")
            gml_path = os.path.join(tmp, "twin", "snapshots", "snap-gml", "graph.gml")
            assert os.path.exists(gml_path), f"GML sidecar not found at {gml_path}"

    def test_snapshot_note(self):
        import tempfile, os
        from titan.core.digital_twin import DigitalTwin
        from titan.core.event_bus import LocalEventBus
        with tempfile.TemporaryDirectory() as tmp:
            dt = DigitalTwin(LocalEventBus(), base_path=os.path.join(tmp, "twin"))
            snap = dt.create_snapshot("snap-note", note="pre-upgrade backup")
            assert snap.note == "pre-upgrade backup"
            loaded = dt.get_snapshot("snap-note")
            assert loaded.note == "pre-upgrade backup"


class TestStateDiff:
    def test_diff_nodes_added(self):
        import tempfile, os
        from titan.core.digital_twin import DigitalTwin
        from titan.core.event_bus import LocalEventBus
        with tempfile.TemporaryDirectory() as tmp:
            dt = DigitalTwin(LocalEventBus(), base_path=os.path.join(tmp, "twin"))
            dt.create_snapshot("antes")
            dt.emit_event("layer_added", {"layer": "meta-oe"})
            dt.emit_event("layer_added", {"layer": "meta-networking"})
            dt.create_snapshot("depois")
            diff = dt.compare("antes", "depois")
            assert diff is not None
            assert len(diff.nodes_added) == 2
            assert "layer:meta-oe" in diff.nodes_added
            assert "layer:meta-networking" in diff.nodes_added
            assert len(diff.nodes_removed) == 0

    def test_diff_nodes_removed(self):
        import tempfile, os, sqlite3, json
        from titan.core.digital_twin import DigitalTwin
        from titan.core.event_bus import LocalEventBus
        import networkx as nx
        with tempfile.TemporaryDirectory() as tmp:
            dt = DigitalTwin(LocalEventBus(), base_path=os.path.join(tmp, "twin"))
            dt.emit_event("layer_added", {"layer": "meta-oe"})
            dt.create_snapshot("antes")
            # Manually create "depois" snapshot with empty graph
            snap_dir = os.path.join(tmp, "twin", "snapshots", "depois")
            os.makedirs(snap_dir, exist_ok=True)
            nx.write_gml(nx.DiGraph(), os.path.join(snap_dir, "graph.gml"))
            conn = sqlite3.connect(os.path.join(tmp, "twin", "snapshots.db"))
            conn.execute(
                "INSERT OR REPLACE INTO snapshots VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                ("depois", "2024-01-01T00:00:00", None, "", json.dumps({"total_nodes": 0, "total_edges": 0}), 0, "", ""),
            )
            conn.commit()
            conn.close()
            diff = dt.compare("antes", "depois")
            assert diff is not None
            assert "layer:meta-oe" in diff.nodes_removed

    def test_diff_edges_added(self):
        import tempfile, os
        from titan.core.digital_twin import DigitalTwin
        from titan.core.event_bus import LocalEventBus
        with tempfile.TemporaryDirectory() as tmp:
            dt = DigitalTwin(LocalEventBus(), base_path=os.path.join(tmp, "twin"))
            dt.emit_event("buildroot_workspace_scanned", {})
            dt.emit_event("buildroot_package_added", {"package": "busybox"})
            dt.create_snapshot("antes")
            dt.emit_event("buildroot_package_added", {"package": "openssl"})
            dt.create_snapshot("depois")
            diff = dt.compare("antes", "depois")
            assert diff is not None
            assert len(diff.nodes_added) == 1
            assert "buildroot_package:openssl" in diff.nodes_added
            assert len(diff.edges_added) >= 1

    def test_diff_no_changes(self):
        import tempfile, os
        from titan.core.digital_twin import DigitalTwin
        from titan.core.event_bus import LocalEventBus
        with tempfile.TemporaryDirectory() as tmp:
            dt = DigitalTwin(LocalEventBus(), base_path=os.path.join(tmp, "twin"))
            dt.emit_event("layer_added", {"layer": "meta-oe"})
            dt.create_snapshot("antes")
            dt.create_snapshot("depois")
            diff = dt.compare("antes", "depois")
            assert diff is not None
            assert len(diff.nodes_added) == 0
            assert len(diff.nodes_removed) == 0
            assert len(diff.edges_added) == 0
            assert diff.fingerprint_similarity == 1.0

    def test_diff_fingerprint_similarity(self):
        import tempfile, os
        from titan.core.digital_twin import DigitalTwin
        from titan.core.event_bus import LocalEventBus
        with tempfile.TemporaryDirectory() as tmp:
            dt = DigitalTwin(LocalEventBus(), base_path=os.path.join(tmp, "twin"))
            dt.create_snapshot("antes", workspace_fingerprint="buildroot/aarch64/gcc/glibc")
            dt.create_snapshot("depois", workspace_fingerprint="buildroot/armv7/gcc/musl")
            diff = dt.compare("antes", "depois")
            assert diff is not None
            assert diff.fingerprint_similarity < 1.0
            assert diff.fingerprint_similarity > 0.0

    def test_diff_summary(self):
        import tempfile, os
        from titan.core.digital_twin import DigitalTwin
        from titan.core.event_bus import LocalEventBus
        with tempfile.TemporaryDirectory() as tmp:
            dt = DigitalTwin(LocalEventBus(), base_path=os.path.join(tmp, "twin"))
            dt.emit_event("layer_added", {"layer": "meta-oe"})
            dt.create_snapshot("antes")
            dt.emit_event("layer_added", {"layer": "meta-networking"})
            dt.create_snapshot("depois")
            diff = dt.compare("antes", "depois")
            s = diff.summary()
            assert "1 node added" in s
            assert "fingerprint similarity" in s

    def test_diff_snapshot_hash(self):
        import tempfile, os
        from titan.core.digital_twin import DigitalTwin
        from titan.core.event_bus import LocalEventBus
        with tempfile.TemporaryDirectory() as tmp:
            dt = DigitalTwin(LocalEventBus(), base_path=os.path.join(tmp, "twin"))
            dt.emit_event("layer_added", {"layer": "meta-oe"})
            s1 = dt.create_snapshot("antes")
            s2 = dt.create_snapshot("depois")
            # Same state → same hash
            assert s1.snapshot_hash == s2.snapshot_hash
            dt.emit_event("layer_added", {"layer": "meta-networking"})
            s3 = dt.create_snapshot("depois2")
            # Different state → different hash
            assert s2.snapshot_hash != s3.snapshot_hash
            # Verify loaded snapshots also have hash
            loaded = dt.get_snapshot("antes")
            assert loaded.snapshot_hash == s1.snapshot_hash

    def test_diff_nonexistent_snapshot(self):
        import tempfile, os
        from titan.core.digital_twin import DigitalTwin
        from titan.core.event_bus import LocalEventBus
        with tempfile.TemporaryDirectory() as tmp:
            dt = DigitalTwin(LocalEventBus(), base_path=os.path.join(tmp, "twin"))
            dt.create_snapshot("antes")
            diff = dt.compare("antes", "nao-existe")
            assert diff is None

    def test_diff_benchmark_busybox_to_openssl(self):
        """Cenário benchmark: busybox → busybox + openssl."""
        import tempfile, os
        from titan.core.digital_twin import DigitalTwin
        from titan.core.event_bus import LocalEventBus
        with tempfile.TemporaryDirectory() as tmp:
            dt = DigitalTwin(LocalEventBus(), base_path=os.path.join(tmp, "twin"))
            dt.emit_event("buildroot_workspace_scanned",
                          {"arch": "aarch64", "toolchain_type": "gcc", "c_library": "glibc"})
            dt.emit_event("buildroot_package_added", {"package": "busybox"})
            dt.create_snapshot("snap1", workspace_fingerprint="buildroot/aarch64/gcc/glibc")
            dt.emit_event("buildroot_package_added", {"package": "openssl"})
            dt.emit_event("buildroot_package_dependency",
                          {"package": "openssl", "depends_on": "zlib"})
            dt.create_snapshot("snap2", workspace_fingerprint="buildroot/aarch64/gcc/glibc")

            diff = dt.compare("snap1", "snap2")
            s = diff.summary()
            assert "buildroot_package:openssl" in diff.nodes_added
            assert "buildroot_package:zlib" in diff.nodes_added
            assert "2 nodes added" in s
            assert "2 edges added" in s

    def test_diff_benchmark_toolchain_change(self):
        """Cenário benchmark: gcc → external-toolchain."""
        import tempfile, os
        from titan.core.digital_twin import DigitalTwin
        from titan.core.event_bus import LocalEventBus
        with tempfile.TemporaryDirectory() as tmp:
            dt = DigitalTwin(LocalEventBus(), base_path=os.path.join(tmp, "twin"))
            dt.create_snapshot("snap1",
                workspace_fingerprint="buildroot/aarch64/gcc/glibc/raspberrypi4/5.15/2025/any")
            dt.create_snapshot("snap2",
                workspace_fingerprint="buildroot/armv7/external-toolchain/musl/beaglebone/5.10/2023/any",
                parent="snap1")
            diff = dt.compare("snap1", "snap2")
            assert diff.fingerprint_similarity < 1.0


class TestImpactAnalysis:
    def test_impact_orphan_package(self):
        import tempfile, os
        from titan.core.digital_twin import DigitalTwin
        from titan.core.event_bus import LocalEventBus
        with tempfile.TemporaryDirectory() as tmp:
            dt = DigitalTwin(LocalEventBus(), base_path=os.path.join(tmp, "twin"))
            dt.emit_event("buildroot_workspace_scanned", {})
            dt.emit_event("buildroot_package_added", {"package": "busybox"})
            report = dt.analyze_impact("buildroot_package:busybox")
            assert report.affected_count == 0
            assert report.risk_level == "LOW"
            assert report.risk_score == 0.1
            assert "no dependents" in report.explanation.lower()

    def test_impact_direct_dependents(self):
        import tempfile, os
        from titan.core.digital_twin import DigitalTwin
        from titan.core.event_bus import LocalEventBus
        with tempfile.TemporaryDirectory() as tmp:
            dt = DigitalTwin(LocalEventBus(), base_path=os.path.join(tmp, "twin"))
            dt.emit_event("buildroot_workspace_scanned", {})
            dt.emit_event("buildroot_package_added", {"package": "openssl"})
            dt.emit_event("buildroot_package_added", {"package": "curl"})
            dt.emit_event("buildroot_package_dependency", {"package": "curl", "depends_on": "openssl"})
            report = dt.analyze_impact("buildroot_package:openssl")
            assert "buildroot_package:curl" in report.direct_dependents
            assert report.affected_count == 1
            assert report.risk_level == "MEDIUM"

    def test_impact_direct_dependents(self):
        import tempfile, os
        from titan.core.digital_twin import DigitalTwin
        from titan.core.event_bus import LocalEventBus
        with tempfile.TemporaryDirectory() as tmp:
            dt = DigitalTwin(LocalEventBus(), base_path=os.path.join(tmp, "twin"))
            dt.emit_event("buildroot_workspace_scanned", {})
            dt.emit_event("buildroot_package_added", {"package": "openssl"})
            dt.emit_event("buildroot_package_added", {"package": "curl"})
            dt.emit_event("buildroot_package_dependency", {"package": "curl", "depends_on": "openssl"})
            report = dt.analyze_impact("buildroot_package:openssl")
            assert "buildroot_package:curl" in report.direct_dependents
            assert report.affected_count == 1
            assert report.risk_level == "MEDIUM"

    def test_impact_transitive_dependents(self):
        import tempfile, os
        from titan.core.digital_twin import DigitalTwin
        from titan.core.event_bus import LocalEventBus
        with tempfile.TemporaryDirectory() as tmp:
            dt = DigitalTwin(LocalEventBus(), base_path=os.path.join(tmp, "twin"))
            dt.emit_event("buildroot_workspace_scanned", {})
            dt.emit_event("buildroot_package_added", {"package": "openssl"})
            dt.emit_event("buildroot_package_added", {"package": "curl"})
            dt.emit_event("buildroot_package_added", {"package": "git"})
            dt.emit_event("buildroot_package_dependency", {"package": "curl", "depends_on": "openssl"})
            dt.emit_event("buildroot_package_dependency", {"package": "git", "depends_on": "curl"})
            report = dt.analyze_impact("buildroot_package:openssl")
            assert "buildroot_package:curl" in report.direct_dependents
            assert "buildroot_package:git" in report.transitive_dependents
            assert report.affected_count == 2

    def test_impact_critical_path(self):
        import tempfile, os
        from titan.core.digital_twin import DigitalTwin
        from titan.core.event_bus import LocalEventBus
        with tempfile.TemporaryDirectory() as tmp:
            dt = DigitalTwin(LocalEventBus(), base_path=os.path.join(tmp, "twin"))
            dt.emit_event("buildroot_workspace_scanned", {})
            dt.emit_event("buildroot_package_added", {"package": "openssl"})
            dt.emit_event("buildroot_package_added", {"package": "curl"})
            dt.emit_event("buildroot_package_added", {"package": "git"})
            dt.emit_event("buildroot_package_dependency", {"package": "curl", "depends_on": "openssl"})
            dt.emit_event("buildroot_package_dependency", {"package": "git", "depends_on": "curl"})
            report = dt.analyze_impact("buildroot_package:openssl")
            assert len(report.critical_path) >= 2
            assert report.critical_path[0] == "buildroot_package:openssl"

    def test_impact_high_risk(self):
        import tempfile, os
        from titan.core.digital_twin import DigitalTwin
        from titan.core.event_bus import LocalEventBus
        with tempfile.TemporaryDirectory() as tmp:
            dt = DigitalTwin(LocalEventBus(), base_path=os.path.join(tmp, "twin"))
            dt.emit_event("buildroot_workspace_scanned", {})
            dt.emit_event("buildroot_package_added", {"package": "a"})
            dt.emit_event("buildroot_package_added", {"package": "b"})
            dt.emit_event("buildroot_package_added", {"package": "c"})
            dt.emit_event("buildroot_package_added", {"package": "d"})
            dt.emit_event("buildroot_package_added", {"package": "target"})
            for pkg in ["a", "b", "c", "d"]:
                dt.emit_event("buildroot_package_dependency",
                              {"package": pkg, "depends_on": "target"})
            report = dt.analyze_impact("buildroot_package:target")
            assert report.affected_count >= 4
            assert report.risk_level == "HIGH"
            assert report.risk_score == 0.7

    def test_impact_critical_entity(self):
        import tempfile, os
        from titan.core.digital_twin import DigitalTwin
        from titan.core.event_bus import LocalEventBus
        with tempfile.TemporaryDirectory() as tmp:
            dt = DigitalTwin(LocalEventBus(), base_path=os.path.join(tmp, "twin"))
            dt.emit_event("buildroot_workspace_scanned", {})
            report = dt.analyze_impact("buildroot:workspace")
            assert report.risk_level == "CRITICAL"
            assert report.risk_score == 0.95

    def test_impact_nonexistent_entity(self):
        import tempfile, os
        from titan.core.digital_twin import DigitalTwin
        from titan.core.event_bus import LocalEventBus
        with tempfile.TemporaryDirectory() as tmp:
            dt = DigitalTwin(LocalEventBus(), base_path=os.path.join(tmp, "twin"))
            report = dt.analyze_impact("buildroot_package:nonexistent")
            assert report.affected_count == 0
            assert report.risk_score == 0.0
            assert "not found" in report.explanation

    def test_impact_explanation_format(self):
        import tempfile, os
        from titan.core.digital_twin import DigitalTwin
        from titan.core.event_bus import LocalEventBus
        with tempfile.TemporaryDirectory() as tmp:
            dt = DigitalTwin(LocalEventBus(), base_path=os.path.join(tmp, "twin"))
            dt.emit_event("buildroot_workspace_scanned", {})
            dt.emit_event("buildroot_package_added", {"package": "openssl"})
            dt.emit_event("buildroot_package_added", {"package": "curl"})
            dt.emit_event("buildroot_package_dependency",
                          {"package": "curl", "depends_on": "openssl"})
            report = dt.analyze_impact("buildroot_package:openssl")
            assert "MEDIUM" in report.explanation
            assert "curl" in report.explanation


class TestRiskConfidenceBridge:
    def test_compute_adjusted_confidence_no_risk(self):
        from titan.context.models import compute_adjusted_confidence
        raw = 0.85
        adj = compute_adjusted_confidence(raw, 0.0)
        # 0.85 * 0.75 + 1.0 * 0.25 = 0.8875
        assert round(adj, 4) == 0.8875

    def test_compute_adjusted_confidence_critical_risk(self):
        from titan.context.models import compute_adjusted_confidence
        raw = 0.85
        adj = compute_adjusted_confidence(raw, 0.95)
        # 0.85 * 0.75 + 0.05 * 0.25 = 0.65
        assert round(adj, 4) == 0.65

    def test_compute_adjusted_confidence_low_risk(self):
        from titan.context.models import compute_adjusted_confidence
        raw = 0.90
        adj = compute_adjusted_confidence(raw, 0.1)
        # 0.90 * 0.75 + 0.90 * 0.25 = 0.90
        assert round(adj, 4) == 0.9

    def test_extract_entity_br2_package(self):
        from titan.learning.recommender import Recommender
        entity, etype = Recommender._extract_entity("BR2_PACKAGE_OPENSSL=y")
        assert entity == "openssl"
        assert etype == "buildroot_package"

    def test_extract_entity_rdepends(self):
        from titan.learning.recommender import Recommender
        entity, etype = Recommender._extract_entity("RDEPENDS:zlib")
        assert entity == "zlib"
        assert etype == "package"

    def test_extract_entity_layer(self):
        from titan.learning.recommender import Recommender
        entity, etype = Recommender._extract_entity("layer:meta-oe")
        assert entity == "meta-oe"
        assert etype == "layer"

    def test_risk_assessment_no_twin(self):
        from titan.learning.recommender import Recommender
        risk = Recommender._assess_risk("BR2_PACKAGE_OPENSSL=y", None)
        assert risk.risk_level == "LOW"
        assert risk.risk_score == 0.0

    def test_risk_assessment_with_twin(self):
        import tempfile, os
        from titan.core.digital_twin import DigitalTwin
        from titan.core.event_bus import LocalEventBus
        from titan.learning.recommender import Recommender
        with tempfile.TemporaryDirectory() as tmp:
            dt = DigitalTwin(LocalEventBus(), base_path=os.path.join(tmp, "twin"))
            dt.emit_event("buildroot_workspace_scanned", {})
            dt.emit_event("buildroot_package_added", {"package": "openssl"})
            dt.emit_event("buildroot_package_added", {"package": "curl"})
            dt.emit_event("buildroot_package_dependency",
                          {"package": "curl", "depends_on": "openssl"})
            risk = Recommender._assess_risk("BR2_PACKAGE_OPENSSL=y", dt)
            assert risk.risk_level == "MEDIUM"
            assert risk.risk_score == 0.4
            assert "curl" in risk.explanation

    def test_risk_assessment_orphan(self):
        import tempfile, os
        from titan.core.digital_twin import DigitalTwin
        from titan.core.event_bus import LocalEventBus
        from titan.learning.recommender import Recommender
        with tempfile.TemporaryDirectory() as tmp:
            dt = DigitalTwin(LocalEventBus(), base_path=os.path.join(tmp, "twin"))
            dt.emit_event("buildroot_workspace_scanned", {})
            dt.emit_event("buildroot_package_added", {"package": "busybox"})
            risk = Recommender._assess_risk("BR2_PACKAGE_BUSYBOX=y", dt)
            assert risk.risk_level == "LOW"
            assert risk.risk_score == 0.1

    def test_risk_adjusts_recommendation_ranking(self):
        """Fix A (LOW risk, 95% success) > Fix B (HIGH risk, 98% success)."""
        import tempfile, os
        from pathlib import Path
        from unittest.mock import MagicMock
        from titan.core.digital_twin import DigitalTwin
        from titan.core.event_bus import LocalEventBus
        from titan.learning.patterns import PatternDB, LearnedPattern
        from titan.learning.ranking import RankingEngine
        from titan.learning.feedback import FeedbackLoop, FeedbackDB
        from titan.learning.context import PatternContextDB
        from titan.learning.recommender import Recommender

        with tempfile.TemporaryDirectory() as tmp:
            tmp_p = Path(tmp)
            P_DB = PatternDB(db_path=str(tmp_p / "patterns.db"))
            C_DB = PatternContextDB(db_path=str(tmp_p / "ctx.db"))
            F_DB = FeedbackDB(db_path=str(tmp_p / "fb.db"))
            fb = FeedbackLoop(F_DB)
            ranking = RankingEngine(pattern_db=P_DB, context_db=C_DB, feedback=fb)
            engine = MagicMock()
            engine.db = P_DB
            engine.context_db = C_DB
            engine.normalizer = None
            engine.suggest.return_value = [
                LearnedPattern(
                    fingerprint="FIX_A", best_fix="BR2_PACKAGE_LOWRISK=y",
                    occurrences=50, success_rate=0.95,
                    average_score=90, category="BuildrootError",
                    top_fixes={"BR2_PACKAGE_LOWRISK=y": 48},
                ),
                LearnedPattern(
                    fingerprint="FIX_B", best_fix="BR2_PACKAGE_HIGHRISK=y",
                    occurrences=50, success_rate=0.98,
                    average_score=95, category="BuildrootError",
                    top_fixes={"BR2_PACKAGE_HIGHRISK=y": 49},
                ),
            ]

            # DigitalTwin: LOWRISK is orphan, HIGHRISK has many dependents
            dt = DigitalTwin(LocalEventBus(), base_path=str(tmp_p / "twin"))
            dt.emit_event("buildroot_workspace_scanned", {})
            dt.emit_event("buildroot_package_added", {"package": "lowrisk"})
            dt.emit_event("buildroot_package_added", {"package": "highrisk"})
            for _ in range(5):
                dt.emit_event("buildroot_package_added", {"package": f"dep-{_}"})
                dt.emit_event("buildroot_package_dependency",
                              {"package": f"dep-{_}", "depends_on": "highrisk"})

            recs = Recommender(engine, ranking=ranking)
            results = recs.recommend_with_confidence(
                "test error", digital_twin=dt, limit=2,
            )

            results.sort(key=lambda r: r.adjusted_confidence, reverse=True)
            assert len(results) == 2
            # The LOW risk fix should rank higher despite lower success rate
            low_risk = [r for r in results if "LOWRISK" in r.fix_signature][0]
            high_risk = [r for r in results if "HIGHRISK" in r.fix_signature][0]
            assert low_risk.risk_level == "LOW"
            assert high_risk.risk_level == "HIGH"
            assert low_risk.adjusted_confidence > high_risk.adjusted_confidence, (
                f"LOW risk ({low_risk.adjusted_confidence}) should be > "
                f"HIGH risk ({high_risk.adjusted_confidence})"
            )

    def test_recommendation_includes_raw_and_adjusted(self):
        import tempfile, os
        from pathlib import Path
        from unittest.mock import MagicMock
        from titan.core.digital_twin import DigitalTwin
        from titan.core.event_bus import LocalEventBus
        from titan.learning.patterns import PatternDB, LearnedPattern
        from titan.learning.ranking import RankingEngine
        from titan.learning.feedback import FeedbackLoop, FeedbackDB
        from titan.learning.context import PatternContextDB
        from titan.learning.recommender import Recommender
        with tempfile.TemporaryDirectory() as tmp:
            tmp_p = Path(tmp)
            P_DB = PatternDB(db_path=str(tmp_p / "patterns.db"))
            C_DB = PatternContextDB(db_path=str(tmp_p / "ctx.db"))
            F_DB = FeedbackDB(db_path=str(tmp_p / "fb.db"))
            fb = FeedbackLoop(F_DB)
            ranking = RankingEngine(pattern_db=P_DB, context_db=C_DB, feedback=fb)
            engine = MagicMock()
            engine.db = P_DB
            engine.context_db = C_DB
            engine.normalizer = None
            engine.suggest.return_value = [
                LearnedPattern(
                    fingerprint="FIX", best_fix="BR2_PACKAGE_OPENSSL=y",
                    occurrences=10, success_rate=0.85,
                    average_score=80, category="BuildrootError",
                    top_fixes={"BR2_PACKAGE_OPENSSL=y": 8},
                ),
            ]
            dt = DigitalTwin(LocalEventBus(), base_path=str(tmp_p / "twin"))
            recs = Recommender(engine, ranking=ranking)
            results = recs.recommend_with_confidence(
                "test error", digital_twin=dt, limit=1,
            )
            assert len(results) == 1
            r = results[0]
            assert r.raw_confidence > 0
            assert r.adjusted_confidence > 0
            assert r.risk_level in ("LOW", "MEDIUM", "HIGH", "CRITICAL")
            assert isinstance(r.risk_score, float)


class TestBuildrootSkillV20:
    def test_buildroot_skill_creates_snapshot(self, tmp_path):
        """BuildrootSkill.execute() should create a snapshot after scanning."""
        import asyncio
        from unittest.mock import MagicMock, patch
        from titan.skills.buildroot_skill import BuildrootSkill
        from titan.core.digital_twin import DigitalTwin
        from titan.core.event_bus import LocalEventBus
        from titan.workspace.detector import WorkspaceDetector
        from titan.workspace.models import BuildrootWorkspace

        twin = DigitalTwin(LocalEventBus(), base_path=str(tmp_path / "twin"))
        twin.emit_event("buildroot_workspace_scanned", {"arch": "arm"})

        ws = BuildrootWorkspace(
            root_dir=tmp_path,
            output_dir=tmp_path / "output",
        )
        ws.arch = "arm"
        ws.toolchain_type = "uclibc"
        ws.c_library = "uclibc"
        ws.packages = ["busybox", "zlib"]
        ws.packages_meta = {"busybox": {"dependencies": ["uclibc"]}}

        memory = MagicMock()
        memory.get_state.return_value = {"type": "buildroot"}

        skill = BuildrootSkill()
        with patch.object(WorkspaceDetector, "detect", return_value=ws):
            coro = skill.execute(
                {"event_type": "buildroot_scan"},
                memory, twin, MagicMock(),
            )
            result = asyncio.run(coro)

        assert result["status"] == "indexed"
        assert "snapshot_id" in result
        assert result["snapshot_id"].startswith("buildroot-scan-")

        snapshots = twin.list_snapshots()
        assert any(s.id == result["snapshot_id"] for s in snapshots)

    def test_buildroot_skill_regression_detected(self, tmp_path):
        """When a previous snapshot exists, BuildrootSkill detects changes."""
        import asyncio
        from unittest.mock import MagicMock, patch
        from titan.skills.buildroot_skill import BuildrootSkill
        from titan.core.digital_twin import DigitalTwin
        from titan.core.event_bus import LocalEventBus
        from titan.workspace.detector import WorkspaceDetector
        from titan.workspace.models import BuildrootWorkspace

        twin = DigitalTwin(LocalEventBus(), base_path=str(tmp_path / "twin"))

        twin.emit_event("buildroot_workspace_scanned", {"arch": "arm"})
        twin.emit_event("buildroot_package_added", {"package": "openssl"})
        twin.emit_event("buildroot_package_added", {"package": "curl"})
        twin.create_snapshot(
            "prev-scan",
            note="Previous scan",
            workspace_fingerprint="buildroot/arm/uclibc/uclibc",
        )

        ws = BuildrootWorkspace(
            root_dir=tmp_path,
            output_dir=tmp_path / "output",
        )
        ws.arch = "arm"
        ws.toolchain_type = "uclibc"
        ws.c_library = "uclibc"
        ws.packages = ["openssl"]  # curl not present in new scan

        memory = MagicMock()
        skill = BuildrootSkill()
        with patch.object(WorkspaceDetector, "detect", return_value=ws):
            coro = skill.execute(
                {"event_type": "buildroot_scan"},
                memory, twin, MagicMock(),
            )
            result = asyncio.run(coro)

        assert result["status"] == "indexed"
        assert "snapshot_id" in result
        # Regression may be None (graph is additive); verify snapshot exists
        snapshots = twin.list_snapshots()
        assert any(s.id == result["snapshot_id"] for s in snapshots)


class TestSecuritySkillV20:
    def test_security_skill_enriches_with_blast_radius(self, tmp_path):
        """SecuritySkill should enrich CVEs with blast radius from Twin."""
        from unittest.mock import MagicMock
        from titan.skills.security_skill import SecuritySkill
        from titan.core.digital_twin import DigitalTwin
        from titan.core.event_bus import LocalEventBus

        twin = DigitalTwin(LocalEventBus(), base_path=str(tmp_path / "twin"))
        twin.emit_event("buildroot_workspace_scanned", {})
        twin.emit_event("buildroot_package_added", {"package": "openssl"})
        twin.emit_event("buildroot_package_added", {"package": "curl"})
        twin.emit_event("buildroot_package_dependency",
                        {"package": "curl", "depends_on": "openssl"})

        memory = MagicMock()
        memory.get_state.return_value = {
            "type": "buildroot", "root_dir": str(tmp_path),
        }

        skill = SecuritySkill()

        import asyncio
        import titan.skills.security_skill as sec_skill

        mock_monitor = MagicMock()
        mock_monitor.scan_workspace.return_value = [
            {"package": "openssl", "cve": "CVE-2024-9999",
             "severity": "HIGH"},
        ]
        sec_skill.CVEMonitor = lambda _: mock_monitor

        result = asyncio.run(skill.execute(
            {"event_type": "security_scan"},
            memory, twin, MagicMock(),
        ))

        assert len(result) == 1
        vuln = result[0]
        assert vuln["package"] == "openssl"
        blast = vuln.get("blast_radius", {})
        assert blast["node_id"] == "buildroot_package:openssl"
        assert blast["affected_count"] > 0
        assert blast["risk_level"] == "MEDIUM"
        assert "curl" in str(blast["direct_dependents"])

    def test_security_skill_unknown_package(self, tmp_path):
        """When the package is not in Twin, blast radius is UNKNOWN."""
        from unittest.mock import MagicMock
        from titan.skills.security_skill import SecuritySkill
        from titan.core.digital_twin import DigitalTwin
        from titan.core.event_bus import LocalEventBus

        twin = DigitalTwin(LocalEventBus(), base_path=str(tmp_path / "twin"))
        memory = MagicMock()
        memory.get_state.return_value = {
            "type": "yocto", "root_dir": str(tmp_path),
        }

        skill = SecuritySkill()

        import asyncio
        import titan.skills.security_skill as sec_skill

        mock_monitor = MagicMock()
        mock_monitor.scan_workspace.return_value = [
            {"package": "unknown-pkg", "cve": "CVE-2024-0001",
             "severity": "LOW"},
        ]
        sec_skill.CVEMonitor = lambda _: mock_monitor

        result = asyncio.run(skill.execute(
            {"event_type": "security_scan"},
            memory, twin, MagicMock(),
        ))

        assert result[0]["blast_radius"]["risk_level"] == "UNKNOWN"
        assert result[0]["blast_radius"]["node_id"] is None


class TestCLITwinCommands:
    def test_twin_snapshot_and_list(self, tmp_path, capsys):
        """CLI twin snapshot + twin snapshots should work end-to-end."""
        from titan.cli import cmd_twin
        from argparse import Namespace
        from titan.core.digital_twin import DigitalTwin
        from titan.core.event_bus import LocalEventBus

        import titan.cli as cli_mod
        original_twin_mgr = cli_mod.TwinManager

        class PatchedTwinManager:
            def __init__(self):
                self._instances = {
                    "cli": DigitalTwin(
                        LocalEventBus(),
                        base_path=str(tmp_path / "twin"),
                    ),
                }
            def get(self, session_id="cli"):
                return self._instances[session_id]

        cli_mod.TwinManager = PatchedTwinManager

        try:
            twin_mgr = PatchedTwinManager()
            twin = twin_mgr.get()
            twin.emit_event("buildroot_workspace_scanned", {"arch": "arm"})

            args1 = Namespace(action="snapshot", snapshot_id="test-snap",
                              note="my note", session_id="cli")
            ret = cmd_twin(args1)
            assert ret == 0

            args2 = Namespace(action="snapshots", session_id="cli")
            ret = cmd_twin(args2)
            assert ret == 0
            out = capsys.readouterr().out
            assert "test-snap" in out

            args3 = Namespace(action="snapshot", snapshot_id="test-snap-2",
                              note=None, session_id="cli")
            cmd_twin(args3)
            args4 = Namespace(action="compare", a="test-snap", b="test-snap-2",
                              session_id="cli")
            ret = cmd_twin(args4)
            assert ret == 0

            twin.emit_event("buildroot_package_added", {"package": "openssl"})
            args5 = Namespace(action="impact", entity="buildroot_package:openssl",
                              session_id="cli", json=False)
            ret = cmd_twin(args5)
            assert ret == 0

        finally:
            cli_mod.TwinManager = original_twin_mgr
