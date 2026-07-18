import re
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple


class BuildrootPackage:
    def __init__(self, name: str):
        self.name = name
        self.version: str = ""
        self.site: str = ""
        self.license: str = ""
        self.license_files: str = ""
        self.source: str = ""
        self.dependencies: List[str] = []
        self.is_host: bool = False

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "version": self.version,
            "site": self.site,
            "license": self.license,
            "dependencies": self.dependencies.copy(),
            "is_host": self.is_host,
        }


_RE_MK_VAR = re.compile(r'^(\w+)\s*[+:]?=\s*(.*)')
_RE_DEPENDS_VAR = re.compile(r'^(\w+)_DEPENDENCIES$')
_RE_VERSION_VAR = re.compile(r'^(\w+)_VERSION$')
_RE_SITE_VAR = re.compile(r'^(\w+)_SITE$')
_RE_LICENSE_VAR = re.compile(r'^(\w+)_LICENSE$')
_RE_LICENSE_FILES_VAR = re.compile(r'^(\w+)_LICENSE_FILES$')
_RE_SOURCE_VAR = re.compile(r'^(\w+)_SOURCE$')
_RE_HOST_PREFIX = re.compile(r'^HOST_(\w+)_')


def parse_mk_file(filepath: str, encoding='utf-8', errors='ignore') -> Dict[str, BuildrootPackage]:
    path = Path(filepath)
    if not path.exists():
        return {}

    content = path.read_text(encoding=encoding, errors=errors)
    return parse_mk_content(content)


def parse_mk_content(content: str) -> Dict[str, BuildrootPackage]:
    packages: Dict[str, BuildrootPackage] = {}
    raw_vars: Dict[str, str] = {}

    continue_line = ''
    for line in content.split('\n'):
        stripped = line.strip()

        if not stripped or stripped.startswith('#'):
            continue

        if continue_line:
            stripped = continue_line + ' ' + stripped.lstrip()
            continue_line = ''

        if stripped.endswith('\\'):
            continue_line = stripped.rstrip('\\').strip()
            continue

        m = _RE_MK_VAR.match(stripped)
        if m:
            raw_vars[m.group(1)] = m.group(2).strip()

    for var, value in raw_vars.items():
        m = _RE_DEPENDS_VAR.match(var)
        if m:
            _add_package_deps(packages, m.group(1), value)
            continue

        m = _RE_VERSION_VAR.match(var)
        if m:
            _get_or_create(packages, m.group(1)).version = value
            continue

        m = _RE_SITE_VAR.match(var)
        if m:
            _get_or_create(packages, m.group(1)).site = value
            continue

        m = _RE_LICENSE_VAR.match(var)
        if m:
            _get_or_create(packages, m.group(1)).license = value
            continue

        m = _RE_LICENSE_FILES_VAR.match(var)
        if m:
            _get_or_create(packages, m.group(1)).license_files = value
            continue

        m = _RE_SOURCE_VAR.match(var)
        if m:
            _get_or_create(packages, m.group(1)).source = value
            continue

    return packages


def _get_or_create(packages: Dict[str, BuildrootPackage], var_prefix: str) -> BuildrootPackage:
    m = _RE_HOST_PREFIX.match(var_prefix)
    if m:
        name = m.group(1).lower()
        if name not in packages:
            pkg = BuildrootPackage(name)
            pkg.is_host = True
            packages[name] = pkg
        return packages[name]

    name = var_prefix.lower()
    if name not in packages:
        packages[name] = BuildrootPackage(name)
    return packages[name]


def _add_package_deps(packages: Dict[str, BuildrootPackage], var_prefix: str, value: str):
    m = _RE_HOST_PREFIX.match(var_prefix)
    if m:
        name = m.group(1).lower()
    else:
        name = var_prefix.lower()

    if name not in packages:
        pkg = BuildrootPackage(name)
        pkg.is_host = bool(m)
        packages[name] = pkg

    deps = value.split()
    for dep in deps:
        dep = dep.strip()
        if dep:
            dep_name = dep.lower()
            if dep.startswith('host-'):
                if dep_name not in packages:
                    hpkg = BuildrootPackage(dep_name)
                    hpkg.is_host = True
                    packages[dep_name] = hpkg
            else:
                if dep_name not in packages:
                    packages[dep_name] = BuildrootPackage(dep_name)

            packages[name].dependencies.append(dep_name)


def discover_mk_files(root_dir: str) -> List[str]:
    path = Path(root_dir)
    mk_files = []

    package_dirs = [
        path / 'package',
    ]

    for pkg_dir in package_dirs:
        if pkg_dir.exists():
            mk_files.extend(str(f) for f in pkg_dir.rglob('*.mk'))

    ext_dirs = path / 'board'
    if ext_dirs.exists():
        mk_files.extend(str(f) for f in ext_dirs.rglob('*.mk'))

    return mk_files


def parse_all_packages(root_dir: str) -> Dict[str, BuildrootPackage]:
    all_packages: Dict[str, BuildrootPackage] = {}
    mk_files = discover_mk_files(root_dir)

    for mk_file in mk_files:
        pkgs = parse_mk_file(mk_file)
        for name, pkg in pkgs.items():
            if name not in all_packages:
                all_packages[name] = pkg
            else:
                existing = all_packages[name]
                if pkg.version:
                    existing.version = pkg.version
                if pkg.site:
                    existing.site = pkg.site
                if pkg.license:
                    existing.license = pkg.license
                if pkg.dependencies:
                    existing.dependencies = list(set(existing.dependencies + pkg.dependencies))

    return all_packages
