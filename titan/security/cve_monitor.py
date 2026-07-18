import json
import sqlite3
import time
import urllib.request
from pathlib import Path
from typing import List, Dict, Any
from datetime import datetime, timedelta

class CVEMonitor:
    """Analisador de CVEs real integrado à API do NVD e aos relatórios do Yocto, com cache SQLite."""
    
    def __init__(self, recipe_db, workspace=None):
        self.db = recipe_db
        self.workspace = workspace
        self._init_cache_table()

    def _init_cache_table(self):
        with sqlite3.connect(self.db.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS cve_cache (
                    package TEXT,
                    cve_id TEXT,
                    severity TEXT,
                    description TEXT,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (package, cve_id)
                )
            """)

    def _fetch_from_cache(self, package: str) -> List[Dict[str, Any]]:
        with sqlite3.connect(self.db.db_path) as conn:
            conn.row_factory = sqlite3.Row
            # Validade do cache: 24 horas
            threshold = (datetime.now() - timedelta(hours=24)).strftime("%Y-%m-%d %H:%M:%S")
            cursor = conn.execute("""
                SELECT cve_id, severity, description FROM cve_cache 
                WHERE package = ? AND updated_at > ?
            """, (package, threshold))
            return [dict(row)             for row in cursor.fetchall()]

    def _save_to_cache(self, package: str, cves: List[Dict[str, Any]]):
        with sqlite3.connect(self.db.db_path) as conn:
            for cve in cves:
                conn.execute("""
                    INSERT OR REPLACE INTO cve_cache (package, cve_id, severity, description, updated_at)
                    VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
                """, (package, cve.get('cve_id', cve.get('id')), cve['severity'], cve['description']))

    def _fetch_nvd_api(self, keyword: str) -> List[Dict[str, Any]]:
        # Verifica se o cache é válido antes de consultar a API externa
        cached = self._fetch_from_cache(keyword)
        if cached:
            return cached

        url = f"https://services.nvd.nist.gov/rest/json/cves/2.0?keywordSearch={keyword}"
        try:
            req = urllib.request.Request(
                url,
                headers={
                    'User-Agent': 'Titan-Embedded-Framework',
                    'Content-Type': 'application/json'
                }
            )
            with urllib.request.urlopen(req, timeout=5) as response:
                data = json.loads(response.read().decode('utf-8'))
                findings = []
                for vuln in data.get("vulnerabilities", []):
                    cve = vuln.get("cve", {})
                    findings.append({
                        "cve_id": cve.get("id"),
                        "severity": cve.get("metrics", {}).get("cvssMetricV31", [{}])[0].get("cvssData", {}).get("baseSeverity", "Medium"),
                        "description": cve.get("descriptions", [{}])[0].get("value", "Sem descrição disponível.")
                    })
                if findings:
                    self._save_to_cache(keyword, findings)
                return findings
        except Exception:
            return []

    def scan_workspace(self, online: bool = False, include_stub: bool = False) -> List[Dict[str, Any]]:
        findings: List[Dict[str, Any]] = []
        recipes = self.db.search_recipes("")

        if self.workspace and self.workspace.type == "yocto":
            cve_file = Path(self.workspace.build_dir) / "tmp" / "log" / "cve" / "cve-summary.json"
            if cve_file.exists():
                print(f"📊 Lendo manifesto de segurança local: {cve_file.name}")
                try:
                    data = json.loads(cve_file.read_text(encoding='utf-8', errors='ignore'))
                    for pkg in data.get("package", []):
                        pn = pkg.get("name")
                        version = pkg.get("version")
                        for issue in pkg.get("issue", []):
                            if issue.get("status") == "Unpatched":
                                findings.append({
                                    "source": "cve-check",
                                    "package": pn,
                                    "version": version,
                                    "cve_id": issue.get("id"),
                                    "severity": issue.get("severity", "High"),
                                    "description": "Vulnerabilidade não mitigada reportada pelo cve-check do Yocto.",
                                })
                    return findings
                except Exception:
                    pass

        if online:
            print("🌐 Consultando API pública do NVD (com cache local de 24h)...")
            total = len(recipes)
            for i, r in enumerate(recipes, 1):
                pn = r['pn']
                cached = self._fetch_from_cache(pn)
                if cached:
                    for cve in cached:
                        findings.append({
                            "source": "nvd",
                            "package": pn,
                            "version": r['pv'],
                            "cve_id": cve.get('cve_id', cve.get('id')),
                            "severity": cve['severity'],
                            "description": cve['description'],
                        })
                else:
                    print(f"  [{i}/{total}] {pn}...")
                    for cve in self._fetch_nvd_api(pn):
                        findings.append({
                            "source": "nvd",
                            "package": pn,
                            "version": r['pv'],
                            "cve_id": cve['cve_id'],
                            "severity": cve['severity'],
                            "description": cve['description'],
                        })
                    if i < total:
                        time.sleep(0.6)
            return findings

        if include_stub:
            print("⚠️  Modo offline com dados de stub (apenas para demo). Use --online para NVD real.")
            for r in recipes:
                pn = r['pn']
                for cve in _OFFLINE_STUB_DB.get(pn, []):
                    findings.append({
                        "source": "offline-stub",
                        "package": pn,
                        "version": r['pv'],
                        "cve_id": cve.get('cve_id', cve.get('id')),
                        "severity": cve['severity'],
                        "description": cve['description'],
                    })
            return findings

        print("ℹ️  Modo offline sem stub. Sem fontes CVE ativas. Opções:")
        print("   • Rode 'bitbake -c cve_check' para gerar tmp/log/cve/cve-summary.json")
        print("   • Use --online para consultar a API do NVD")
        print("   • Use --stub para demo com dados de exemplo")
        return findings

    def generate_report(self, findings: List[Dict[str, Any]]):
        if not findings:
            print("✅ Nenhuma vulnerabilidade ativa detectada.")
            return
        source_label = {
            "cve-check": "Yocto cve-check",
            "nvd": "NVD API",
            "offline-stub": "OFFLINE STUB (demo)",
        }
        primary_source = findings[0].get("source", "unknown")
        print(f"⚠️  Encontradas {len(findings)} vulnerabilidades ativas [fonte: {source_label.get(primary_source, primary_source)}]:")
        for f in findings:
            cve_id = f.get("cve_id") or f.get("id", "?")
            color = "\033[91m" if f['severity'] in ["High", "Critical"] else "\033[93m"
            reset = "\033[0m"
            print(f"{color}[{f['severity']}] {cve_id}{reset} em {f['package']} (v{f['version']})")
            print(f"   📝 {f['description']}\n")


_OFFLINE_STUB_DB: Dict[str, List[Dict[str, str]]] = {
    "openssl": [
        {"cve_id": "CVE-2022-3602", "severity": "High",     "description": "SpookSSL: X.509 Email Address Variable Length Buffer Overflow."},
        {"cve_id": "CVE-2023-0286", "severity": "High",     "description": "X.400 address type confusion in GENERAL_NAME_cmp."},
        {"cve_id": "CVE-2023-0464", "severity": "Medium",   "description": "Excessive time to check RSA keys (DoS)."},
        {"cve_id": "CVE-2023-3817", "severity": "Medium",   "description": "Excessively long X.509 chain may cause DoS."},
        {"cve_id": "CVE-2024-0727", "severity": "Medium",   "description": "PKCS12 NULL pointer dereference (DoS via crafted PKCS12)."},
    ],
    "zlib": [
        {"cve_id": "CVE-2018-25032", "severity": "Medium",   "description": "Memory corruption in deflate via large gzip header extra field."},
        {"cve_id": "CVE-2022-37434", "severity": "Critical", "description": "Heap-based buffer over-read in inflateGetHeader (gzip header)."},
    ],
    "glibc": [
        {"cve_id": "CVE-2023-4911",  "severity": "Critical", "description": "Looney Tunables: buffer overflow in ld.so (GLIBC_TUNABLES parsing)."},
    ],
    "busybox": [
        {"cve_id": "CVE-2021-42380", "severity": "High",     "description": "Out-of-bounds read in awk (BZ #14781)."},
        {"cve_id": "CVE-2022-30065", "severity": "High",     "description": "Integer overflow in awk getvar_s()."},
    ],
    "curl": [
        {"cve_id": "CVE-2023-38039", "severity": "High",     "description": "HTTP header injection via CRLF in URL."},
        {"cve_id": "CVE-2023-38545", "severity": "Critical", "description": "Heap buffer overflow in SOCKS5 hostname parsing."},
    ],
    "sqlite": [
        {"cve_id": "CVE-2022-35737", "severity": "Critical", "description": "Array bound overflow in concatFrames (RCE potencial)."},
    ],
}
