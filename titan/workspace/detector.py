from pathlib import Path
from typing import Optional, Union
from .models import Workspace, YoctoWorkspace, KernelWorkspace, BuildrootWorkspace
from .parsers import parse_yocto_local_conf, parse_bblayers
from ..buildroot.parser import parse_buildroot_config
from ..buildroot.analyzer import analyze_buildroot_workspace

class WorkspaceDetector:
    @staticmethod
    def detect(path: Union[str, Path] = ".") -> Optional[Workspace]:
        root = Path(path).resolve()
        
        # 1. Detectar Yocto (Kas)
        kas_file = root / "kas.yml"
        if kas_file.exists():
            return YoctoWorkspace(
                root_dir=root, build_dir=root / "build", init_script=root / "oe-init-build-env",
                uses_kas=True, kas_file=kas_file
            )

        # 2. Detectar Yocto (Tradicional)
        init_script = root / "oe-init-build-env"
        if init_script.exists():
            build_dir = root / "build"
            local_conf = build_dir / "conf" / "local.conf"
            bblayers_conf = build_dir / "conf" / "bblayers.conf"
            
            conf_data = parse_yocto_local_conf(local_conf)
            layers = parse_bblayers(bblayers_conf)
            
            return YoctoWorkspace(
                root_dir=root, build_dir=build_dir, init_script=init_script,
                machine=conf_data["MACHINE"], distro=conf_data["DISTRO"], layers=layers,
                bbmask=conf_data["BBMASK"], image_install=conf_data["IMAGE_INSTALL"],
                image_features=conf_data["IMAGE_FEATURES"], sdkmachine=conf_data["SDKMACHINE"],
                tclibc=conf_data["TCLIBC"], init_manager=conf_data["INIT_MANAGER"]
            )

        # 3. Detectar Kernel Linux
        if (root / "Kconfig").exists() and (root / "MAINTAINERS").exists():
            # TODO: Parse Makefile to get exact version
            return KernelWorkspace(root_dir=root)

        # 4. Detectar Buildroot
        if (root / "Config.in").exists() and (root / "Makefile").exists():
            content = (root / "Makefile").read_text(errors="ignore")
            if "BR2_" in content or "buildroot" in content.lower():
                config_file = root / ".config"
                if config_file.exists():
                    return analyze_buildroot_workspace(root_dir=root, config_file=str(config_file))
                return BuildrootWorkspace(root_dir=root, output_dir=root / "output")

        return None
