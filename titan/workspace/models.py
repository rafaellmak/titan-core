from abc import ABC, abstractmethod
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import List, Optional, Any, Dict, Union

def _to_serializable(obj: Any) -> Any:
    if isinstance(obj, Path):
        return str(obj)
    if isinstance(obj, list):
        return [_to_serializable(i) for i in obj]
    if isinstance(obj, dict):
        return {k: _to_serializable(v) for k, v in obj.items()}
    return obj

@dataclass
class Workspace(ABC):
    root_dir: Path

    @property
    @abstractmethod
    def type(self) -> str:
        pass

    def to_dict(self) -> Dict[str, Any]:
        d = _to_serializable(asdict(self))
        d["type"] = self.type
        return d

@dataclass
class YoctoWorkspace(Workspace):
    build_dir: Path
    init_script: Path
    machine: str = "unknown"
    distro: str = "unknown"
    layers: List[Path] = field(default_factory=list)
    uses_kas: bool = False
    kas_file: Optional[Path] = None

    # Novas variáveis de contexto profundo
    bbmask: str = ""
    image_install: str = ""
    image_features: str = ""
    sdkmachine: str = ""
    tclibc: str = ""
    init_manager: str = ""

    @property
    def type(self) -> str:
        return "yocto"

@dataclass
class KernelWorkspace(Workspace):
    arch: str = "x86_64"
    cross_compile: Optional[str] = None
    version: str = "unknown"
    defconfig: Optional[str] = None

    @property
    def type(self) -> str:
        return "kernel"

@dataclass
class BuildrootWorkspace(Workspace):
    output_dir: Path
    defconfig: Optional[str] = None
    arch: str = ""
    toolchain: str = ""
    toolchain_type: str = ""
    c_library: str = ""
    hostname: str = ""
    kernel_enabled: bool = False
    packages: List[str] = field(default_factory=list)
    overlays: List[str] = field(default_factory=list)
    post_build_scripts: List[str] = field(default_factory=list)
    post_image_scripts: List[str] = field(default_factory=list)
    kconfig_symbols: List[str] = field(default_factory=list)
    kconfig_sources: List[str] = field(default_factory=list)
    packages_meta: Dict[str, Any] = field(default_factory=dict)

    init_system: str = ""
    filesystem_type: str = ""
    sdk_enabled: bool = False
    uboot_enabled: bool = False
    uboot_board: str = ""
    kernel_version: str = ""
    kernel_config: str = ""
    kernel_patches: List[str] = field(default_factory=list)
    downloads_dir: str = ""
    mirrors: List[str] = field(default_factory=list)
    external_trees: List[Dict[str, Any]] = field(default_factory=list)
    custom_packages: List[Dict[str, Any]] = field(default_factory=list)
    board_support: Dict[str, Any] = field(default_factory=dict)
    defconfigs: List[Dict[str, Any]] = field(default_factory=list)
    patches: Dict[str, List[str]] = field(default_factory=dict)

    @property
    def type(self) -> str:
        return "buildroot"
