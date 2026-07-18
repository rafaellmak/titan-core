import re
from pathlib import Path
from typing import List, Optional, Dict, Any, Union


class KconfigSource:
    def __init__(self, path: str):
        self.path = path

    def to_dict(self) -> Dict[str, Any]:
        return {"source": self.path}


class KconfigSymbol:
    def __init__(self, name: str, is_menuconfig: bool = False):
        self.name = name
        self.is_menuconfig = is_menuconfig
        self.type: str = ""
        self.prompt: str = ""
        self.depends_on: List[str] = []
        self.selects: List[str] = []
        self.implies: List[str] = []
        self.defaults: List[str] = []
        self.ranges: List[str] = []
        self.help_text: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "is_menuconfig": self.is_menuconfig,
            "type": self.type,
            "prompt": self.prompt,
            "depends_on": self.depends_on.copy(),
            "selects": self.selects.copy(),
            "implies": self.implies.copy(),
            "defaults": self.defaults.copy(),
        }


class KconfigChoice:
    def __init__(self):
        self.prompt: str = ""
        self.type: str = "bool"
        self.depends_on: List[str] = []
        self.symbols: List[KconfigSymbol] = []

    def to_dict(self) -> Dict[str, Any]:
        return {
            "choice": True,
            "type": self.type,
            "prompt": self.prompt,
            "depends_on": self.depends_on.copy(),
            "symbols": [s.to_dict() for s in self.symbols],
        }


class KconfigMenu:
    def __init__(self, prompt: str = ""):
        self.prompt = prompt
        self.depends_on: List[str] = []
        self.children: List[Any] = []

    def to_dict(self) -> Dict[str, Any]:
        return {
            "menu": self.prompt,
            "depends_on": self.depends_on.copy(),
            "children": [c.to_dict() if hasattr(c, 'to_dict') else str(c) for c in self.children],
        }


class KconfigIfBlock:
    def __init__(self, condition: str = ""):
        self.condition = condition
        self.children: List[Any] = []

    def to_dict(self) -> Dict[str, Any]:
        return {
            "if": self.condition,
            "children": [c.to_dict() if hasattr(c, 'to_dict') else str(c) for c in self.children],
        }


class KconfigDocument:
    def __init__(self):
        self.children: List[Any] = []
        self.symbols: Dict[str, KconfigSymbol] = {}
        self.sources: List[str] = []

    def index(self):
        self.symbols = {}
        self.sources = []
        self._index(self.children)

    def _index(self, items: List[Any]):
        for item in items:
            if isinstance(item, KconfigSymbol):
                self.symbols[item.name] = item
            elif isinstance(item, (KconfigMenu, KconfigIfBlock)):
                self._index(item.children)
            elif isinstance(item, KconfigChoice):
                self._index(item.symbols)
            elif isinstance(item, KconfigSource):
                self.sources.append(item.path)


_RE_CONFIG = re.compile(r'^(menu)?config\s+(\S+)')
_RE_MENU = re.compile(r'^menu\s+"(.*)"')
_RE_CHOICE = re.compile(r'^choice\s*$')
_RE_IF = re.compile(r'^if\s+(.+)')
_RE_SOURCE = re.compile(r'^source\s+"(.+)"')
_RE_COMMENT = re.compile(r'^comment\s+"(.*)"')
_RE_ENDMENU = re.compile(r'^endmenu')
_RE_ENDCHOICE = re.compile(r'^endchoice')
_RE_ENDIF = re.compile(r'^endif')

_RE_TYPE = re.compile(r'^\t+(bool|tristate|string|int|hex)\s*(?:"(.*)")?\s*$')
_RE_PROMPT = re.compile(r'^\t+prompt\s+"(.*)"')
_RE_DEPENDS = re.compile(r'^\t+depends\s+on\s+(.+)')
_RE_SELECT = re.compile(r'^\t+select\s+(\S+)(?:\s+if\s+(.+))?')
_RE_IMPLY = re.compile(r'^\t+imply\s+(\S+)(?:\s+if\s+(.+))?')
_RE_DEFAULT = re.compile(r'^\t+default\s+(.+?)(?:\s+if\s+(.+))?$')
_RE_RANGE = re.compile(r'^\t+range\s+(\S+)\s+(\S+)')
_RE_HELP = re.compile(r'^\t+(---)?help|---help---')


def parse_kconfig(content: str, filepath: str = "") -> KconfigDocument:
    doc = KconfigDocument()
    lines = content.split('\n')
    children, _ = _parse_block(lines, 0, [])
    doc.children = children
    doc.index()
    return doc


def parse_kconfig_file(filepath: str, encoding='utf-8', errors='ignore') -> KconfigDocument:
    path = Path(filepath)
    if not path.exists():
        return KconfigDocument()
    content = path.read_text(encoding=encoding, errors=errors)
    return parse_kconfig(content, filepath)


def _get_indent(line: str) -> int:
    return len(line) - len(line.lstrip('\t'))


def _parse_block(lines: List[str], start: int, parent: List) -> tuple:
    items = []
    i = start
    current_sym: Optional[KconfigSymbol] = None

    while i < len(lines):
        raw = lines[i]
        line = raw.strip()

        if not line or line.startswith('#'):
            i += 1
            continue

        if _RE_ENDMENU.match(line) or _RE_ENDCHOICE.match(line) or _RE_ENDIF.match(line):
            current_sym = None
            return items, i + 1

        m = re.match(r'^menuconfig\s+(\S+)', line)
        if m:
            current_sym = None
            sym = KconfigSymbol(m.group(1), is_menuconfig=True)
            config_indent = _get_indent(raw)
            i += 1
            sym, i = _parse_symbol_properties(lines, i, sym, config_indent)
            items.append(sym)
            current_sym = None
            continue

        m = re.match(r'^config\s+(\S+)', line)
        if m:
            current_sym = None
            sym = KconfigSymbol(m.group(1))
            config_indent = _get_indent(raw)
            i += 1
            sym, i = _parse_symbol_properties(lines, i, sym, config_indent)
            items.append(sym)
            current_sym = None
            continue

        m = _RE_MENU.match(line)
        if m:
            current_sym = None
            menu = KconfigMenu(m.group(1))
            i += 1
            menu.children, i = _parse_block(lines, i, items)
            items.append(menu)
            continue

        m = _RE_CHOICE.match(line)
        if m:
            current_sym = None
            choice = KconfigChoice()
            i += 1
            choice, i = _parse_choice_body(lines, i, choice)
            items.append(choice)
            continue

        m = _RE_IF.match(line)
        if m:
            current_sym = None
            ifblock = KconfigIfBlock(m.group(1).strip())
            i += 1
            ifblock.children, i = _parse_block(lines, i, items)
            items.append(ifblock)
            continue

        m = _RE_SOURCE.match(line)
        if m:
            current_sym = None
            items.append(KconfigSource(m.group(1)))
            i += 1
            continue

        m = _RE_COMMENT.match(line)
        if m:
            current_sym = None
            i += 1
            continue

        i += 1

    current_sym = None
    return items, i


def _parse_choice_body(lines: List[str], start: int, choice: KconfigChoice) -> tuple:
    i = start
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        if stripped == 'endchoice':
            return choice, i + 1

        if not stripped or stripped.startswith('#'):
            i += 1
            continue

        m = _RE_TYPE.match(line)
        if m:
            choice.type = m.group(1)
            if m.group(2):
                choice.prompt = m.group(2)
            i += 1
            continue

        m = _RE_PROMPT.match(line)
        if m:
            choice.prompt = m.group(1)
            i += 1
            continue

        m = _RE_DEPENDS.match(line)
        if m:
            choice.depends_on.append(m.group(1).strip())
            i += 1
            continue

        if stripped.startswith('optional'):
            choice.type = 'optional'
            i += 1
            continue

        m = re.match(r'^config\s+(\S+)', stripped)
        if m:
            sym = KconfigSymbol(m.group(1))
            config_indent = _get_indent(lines[i])
            i += 1
            sym, i = _parse_symbol_properties(lines, i, sym, config_indent)
            choice.symbols.append(sym)
            continue

        i += 1

    return choice, i


def _parse_symbol_properties(lines: List[str], start: int, sym: KconfigSymbol, config_indent: int = 0) -> tuple:
    i = start
    in_help = False
    help_lines: List[str] = []

    while i < len(lines):
        raw = lines[i]
        line = raw.strip()

        if not line:
            i += 1
            if in_help:
                help_lines.append('')
            continue

        if in_help:
            indent = _get_indent(raw)
            if indent <= config_indent:
                in_help = False
                sym.help_text = '\n'.join(help_lines).strip()
                continue
            help_lines.append(line)
            i += 1
            continue

        if re.match(r'^(menu)?config\s+', line) or \
           re.match(r'^(menu|endmenu|choice|endchoice|if|endif|source|comment)\b', line):
            break

        m = _RE_TYPE.match(raw)
        if m:
            sym.type = m.group(1)
            if m.group(2):
                sym.prompt = m.group(2)
            i += 1
            continue

        m = _RE_PROMPT.match(raw)
        if m:
            sym.prompt = m.group(1)
            i += 1
            continue

        m = _RE_DEPENDS.match(raw)
        if m:
            sym.depends_on.append(m.group(1).strip())
            i += 1
            continue

        m = _RE_SELECT.match(raw)
        if m:
            cond = f' if {m.group(2)}' if m.group(2) else ''
            sym.selects.append(m.group(1) + cond)
            i += 1
            continue

        m = _RE_IMPLY.match(raw)
        if m:
            cond = f' if {m.group(2)}' if m.group(2) else ''
            sym.implies.append(m.group(1) + cond)
            i += 1
            continue

        m = _RE_DEFAULT.match(raw)
        if m:
            val = m.group(1)
            if m.group(2):
                val += f' if {m.group(2)}'
            sym.defaults.append(val)
            i += 1
            continue

        m = _RE_RANGE.match(raw)
        if m:
            sym.ranges.append(f'{m.group(1)} {m.group(2)}')
            i += 1
            continue

        m = _RE_HELP.match(raw)
        if m:
            in_help = True
            help_lines = []
            i += 1
            continue

        i += 1

    if in_help:
        sym.help_text = '\n'.join(help_lines).strip()

    return sym, i
