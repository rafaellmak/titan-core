import re
from dataclasses import dataclass
from typing import List, Optional, Pattern

@dataclass
class DiagnosticRule:
    id: str
    severity: str
    description: str
    pattern: Pattern
    suggestion: str
    fixable: bool = False

# Regras Determinísticas para Yocto Build
YOCTO_RULES = [
    DiagnosticRule(
        id="YOC-001",
        severity="Critical",
        description="Nothing PROVIDES target",
        pattern=re.compile(r"ERROR: Nothing PROVIDES '(?P<target>[^']+)'"),
        suggestion="O target '{target}' não foi encontrado. Verifique se a layer que contém este recipe está no bblayers.conf ou se o nome está correto.",
        fixable=False
    ),
    DiagnosticRule(
        id="YOC-002",
        severity="Error",
        description="Task failed",
        pattern=re.compile(r"ERROR: Task\s+(?P<task_id>\d+)\s+\((?P<task>[^)]+)\) failed with exit code '(?P<code>\d+)'"),
        suggestion="A tarefa {task} (id {task_id}) falhou com exit code {code}. Verifique os logs detalhados em tmp/work/... para o erro específico.",
        fixable=False
    ),
    DiagnosticRule(
        id="YOC-002-alt",
        severity="Error",
        description="Task failed (no ID)",
        pattern=re.compile(r"ERROR: Task \((?P<task>[^)]+)\) failed with exit code '(?P<code>\d+)'"),
        suggestion="A tarefa {task} falhou com exit code {code}. Verifique os logs detalhados em tmp/work/... para o erro específico.",
        fixable=False
    ),
    DiagnosticRule(
        id="YOC-003",
        severity="Error",
        description="Fetch failed",
        pattern=re.compile(r"ERROR: Fetcher failure: Fetch command failed for url '(?P<url>[^']+)'"),
        suggestion="Falha ao baixar código fonte de {url}. Verifique sua conexão ou se a URL ainda é válida.",
        fixable=False
    ),
    DiagnosticRule(
        id="YOC-004",
        severity="Warning",
        description="QA Issue: non-standard dependencies",
        pattern=re.compile(r"WARNING: (?P<context>[^:]+): QA Issue: (?P<pn>\S+)\s+rdepends on (?P<dep>[^,]+), but it isn't a build-time dependency\?"),
        suggestion="O pacote {pn} depende de {dep} em runtime, mas não em build-time. Adicione {dep} ao RDEPENDS de {pn}.",
        fixable=True
    )
]

# Regras Determinísticas para C/C++ (Compilação)
C_CPP_RULES = [
    DiagnosticRule(
        id="CPP-001",
        severity="Error",
        description="Missing header file",
        pattern=re.compile(r"(?P<file>[^:]+):(?P<line>\d+):(?P<col>\d+): fatal error: (?P<header>[^:]+): No such file or directory"),
        suggestion="O arquivo de header '{header}' não foi encontrado. Verifique se a dependência correta está no DEPENDS do recipe.",
        fixable=False
    ),
    DiagnosticRule(
        id="CPP-002",
        severity="Error",
        description="Undefined reference",
        pattern=re.compile(r"undefined reference to `(?P<symbol>[^']+)'"),
        suggestion="Referência indefinida para '{symbol}'. Provavelmente falta linkar uma biblioteca no LDFLAGS ou adicionar ao DEPENDS.",
        fixable=False
    )
]
