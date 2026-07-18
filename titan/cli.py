import argparse
import json
import sys
import os
from pathlib import Path
from importlib.metadata import version, PackageNotFoundError
from .workspace.detector import WorkspaceDetector
from .diagnostics.engine import DiagnosticEngine
from .recipes.indexer import RecipeIndexer
from .recipes.db import RecipeDB
from .recipes.graph import GraphEngine
from .actions.modifier import WorkspaceModifier
from .actions.recipe import RecipeModifier
from .autofix.engine import AutoFixEngine
from .llm_assist.engine import LLMAssistEngine, OllamaAgent, OpenRouterAgent, DeterministicLLMMock
from .core.core import TitanCore
from .core.session import TitanSession
from .core.digital_twin import TwinManager
from .core.event_bus import LocalEventBus

# Novos módulos Enterprise
from .security.cve_monitor import CVEMonitor
from .hardware.dt_analyzer import DeviceTreeAnalyzer
from .runtime.dmesg_analyzer import DmesgAnalyzer
from .enterprise.exporter import EnterpriseExporter
from .explain.engine import ExplainEngine

def cmd_info(args):
    workspace = WorkspaceDetector.detect(args.workspace)
    if not workspace:
        print(f"❌ Nenhum workspace reconhecido encontrado em '{args.workspace}'.")
        return 1
    print(f"✅ Workspace detectado: {workspace.type.upper()}")
    print(f"📂 Diretório: {workspace.root_dir}")
    return 0

def cmd_diagnose(args):
    session = getattr(args, "session", None)
    workspace = session.workspace if session else WorkspaceDetector.detect(args.workspace)
    if not workspace:
        print(f"❌ Nenhum workspace Yocto/Buildroot detectado em '{args.workspace}'")
        return 1
    engine = DiagnosticEngine(workspace, core=session.core if session else None)
    try:
        findings = engine.analyze_log(Path(args.log))
    except FileNotFoundError:
        print(f"❌ Erro: Arquivo '{args.log}' não encontrado.")
        return 1

    if not findings:
        print("ℹ️  Nenhum problema conhecido detectado neste log.")
        print("   (Titan reconhece padrões YOC-001..004, YOC-002-alt, YOC-003, CPP-001..002.)")
    else:
        for f in findings:
            print(f"[{f['severity']}] {f['rule_id']} (Linha {f['line']}) - {f['description']}\n💡 {f['suggestion']}\n")

    has_critical = any(f.get("severity", "").lower() in ("critical", "error") for f in findings)

    # Atualizar métricas da sessão
    if session:
        session.metrics.diagnoses += 1

    return 1 if has_critical else 0

def cmd_recipe(args):
    workspace = WorkspaceDetector.detect(args.workspace)
    if not workspace:
        print("❌ Nenhum workspace Yocto/Buildroot detectado em '.'")
        return 1

    session = getattr(args, "session", None)
    digital_twin = session.digital_twin if session else None

    if args.action == "index":
        indexer = RecipeIndexer(workspace, digital_twin=digital_twin)
        indexer.index_all()
        db = RecipeDB(workspace.root_dir)
        GraphEngine(db).sync_from_recipes()
        return 0

    db = RecipeDB(workspace.root_dir)

    if args.action == "search":
        if not args.target or not args.target.strip():
            recipes = db.search_recipes("")
        else:
            recipes = db.search_recipes(args.target.strip())
        if not recipes:
            if args.target:
                print(f"❌ Nenhuma receita encontrada para: '{args.target}'")
                print(f"   Dica: rode 'titan recipe index' se nunca indexou, ou verifique o PN.")
            else:
                print("ℹ️  Banco vazio. Rode 'titan recipe index' primeiro.")
            return 1
        if getattr(args, 'json', False):
            import json
            print(json.dumps(recipes, indent=2, default=str))
            return 0
        for r in recipes:
            print(f"📦 {r['pn']} (v{r['pv']})")
        return 0

    if args.action == "show":
        if not args.target or not args.target.strip():
            print("❌ 'titan recipe show' requer o PN da receita")
            print("   Exemplo: titan recipe show openssl")
            return 1
        recipe = db.get_recipe(args.target.strip())
        if not recipe:
            print(f"❌ Receita '{args.target}' não encontrada no banco.")
            print(f"   Dica: rode 'titan recipe index' se nunca indexou.")
            return 1
        if getattr(args, 'json', False):
            import json
            print(json.dumps(recipe, indent=2, default=str))
            return 0
        print(f"📦 {recipe['pn']}")
        print(f"   PV:     {recipe.get('pv', '?')}")
        print(f"   License: {recipe.get('license') or '(não declarada)'}")
        if recipe.get("depends"):
            print(f"   DEPENDS: {recipe['depends']}")
        if recipe.get("rdepends"):
            print(f"   RDEPENDS: {recipe['rdepends']}")
        if recipe.get("src_uri"):
            print(f"   SRC_URI: {recipe['src_uri']}")
        if recipe.get("inherits"):
            print(f"   INHERITS: {recipe['inherits']}")
        print(f"   Arquivo: {recipe.get('file_path', '?')}")
        return 0

    if args.action == "deps":
        if not args.target:
            print("❌ 'titan recipe deps' requer o PN da receita")
            return 1
        engine = GraphEngine(db)
        if getattr(args, 'json', False):
            import json
            print(json.dumps({"recipe": args.target, "dependencies": engine.get_deps_list(args.target)}, indent=2))
            return 0
        engine.print_tree(args.target)
        return 0

    if args.action == "impact":
        if not args.target:
            print("❌ 'titan recipe impact' requer o PN da receita")
            return 1
        engine = GraphEngine(db)
        if getattr(args, 'json', False):
            import json
            print(json.dumps({"recipe": args.target, "impacted": engine.get_impact_list(args.target)}, indent=2))
            return 0
        engine.print_tree(args.target, reverse=True)
        return 0

    return 0

def cmd_action(args):
    workspace = WorkspaceDetector.detect(args.workspace)
    if not workspace:
        print(f"❌ Nenhum workspace Yocto/Buildroot detectado em '{args.workspace}'")
        return 1

    if args.type == "append-conf":
        ok = WorkspaceModifier(workspace).append_local_conf(args.content)
        return 0 if ok else 1
    elif args.type == "add-layer":
        ok = WorkspaceModifier(workspace).add_layer(args.path)
        return 0 if ok else 1
    elif args.type == "patch-recipe":
        value = args.value
        if isinstance(value, list):
            while value and value[0] == "--":
                value = value[1:]
            value = " ".join(value) if value else ""
        if not value:
            print("❌ patch-recipe: value é obrigatório")
            print("   Exemplo: titan action patch-recipe openssl EXTRA_OECONF '--with-test'")
            return 1
        if not args.yes:
            prompt = f"⚠️ Deseja modificar a recipe '{args.recipe}' ({args.variable} += \"{value}\")? (y/N): "
            if sys.stdin.isatty():
                try:
                    confirm = input(prompt).strip().lower()
                except (EOFError, KeyboardInterrupt):
                    print()
                    confirm = "n"
            else:
                print("ℹ️  Modificação cancelada (TTY não disponível). Use --yes para forçar.")
                return 1
            if confirm != "y":
                print("❌ Modificação cancelada pelo engenheiro.")
                return 1
        db = RecipeDB(workspace.root_dir)
        rm = RecipeModifier(db, workspace=workspace)
        ok = rm.append_variable(args.recipe, args.variable, value)
        return 0 if ok else 1
    return 0

def cmd_fix(args):
    session = getattr(args, "session", None)
    workspace = session.workspace if session else WorkspaceDetector.detect(args.workspace)
    if not workspace:
        print(f"❌ Nenhum workspace Yocto/Buildroot detectado em '{args.workspace}'")
        return 1
    engine = AutoFixEngine(workspace, core=session.core if session else None)
    engine.run_fix(Path(args.log))
    if session:
        session.metrics.fixes += 1
    return 0

def cmd_security(args):
    workspace = WorkspaceDetector.detect(args.workspace)
    if not workspace:
        print(f"❌ Nenhum workspace Yocto/Buildroot detectado em '{args.workspace}'")
        return 1

    if not args.online and not args.stub:
        print("❌ Nenhuma fonte CVE disponível. Use --online (requer internet) ou --stub (dados de exemplo).")
        return 2

    monitor = CVEMonitor(RecipeDB(workspace.root_dir), workspace=workspace)
    findings = monitor.scan_workspace(online=args.online, include_stub=args.stub)

    if args.severity:
        wanted = {s.lower() for s in args.severity}
        allowed = {"low", "medium", "high", "critical"}
        unknown = wanted - allowed
        if unknown:
            print(f"❌ Severidades inválidas: {unknown}. Aceitas: {sorted(allowed)}")
            return 1
        findings = [f for f in findings if f.get("severity", "").lower() in wanted]

    monitor.generate_report(findings)

    if args.export_json:
        EnterpriseExporter.to_json(findings, Path(args.export_json))
    return 0

def cmd_hardware(args):
    workspace = WorkspaceDetector.detect(args.workspace)
    if not workspace:
        print(f"❌ Nenhum workspace Yocto/Buildroot detectado em '{args.workspace}'")
        return 1
    analyzer = DeviceTreeAnalyzer(workspace)
    try:
        findings = analyzer.analyze_dts(Path(args.dts))
    except FileNotFoundError:
        print(f"❌ Arquivo DTS '{args.dts}' não encontrado.")
        return 1
    analyzer.report_findings(findings)
    has_error = any(f.get("severity", "").lower() in ("error", "critical") for f in findings)
    return 1 if has_error else 0

def cmd_runtime(args):
    analyzer = DmesgAnalyzer()
    try:
        content = Path(args.log).read_text()
    except FileNotFoundError:
        print(f"❌ Erro: Arquivo de log '{args.log}' não encontrado.")
        return 1
    findings = analyzer.analyze_log(content)
    analyzer.report_findings(findings)
    has_error = any(f.get("severity", "").lower() in ("error", "critical") for f in findings)
    return 1 if has_error else 0

def cmd_explain(args):
    workspace = WorkspaceDetector.detect(args.workspace)
    if not workspace:
        print(f"❌ Nenhum workspace Yocto/Buildroot detectado em '{args.workspace}'")
        return 1
    if not args.target or not args.target.strip():
        print("❌ 'titan explain' requer o PN da receita")
        print("   Exemplo: titan explain openssl")
        return 1
    db = RecipeDB(workspace.root_dir)
    engine = ExplainEngine(db)
    out = engine.explain_recipe(args.target.strip())
    if getattr(args, 'json', False):
        import json
        print(json.dumps({"recipe": args.target.strip(), "explanation": out}, indent=2, default=str))
        return 0
    print(out)
    if "❌" in out.splitlines()[0] or "não indexado" in out:
        return 1
    return 0

def cmd_llm_assist(args):
    agent = None
    prompt = args.prompt
    if not prompt:
        if not sys.stdin.isatty():
            try:
                prompt = sys.stdin.read().strip()
            except (EOFError, KeyboardInterrupt):
                prompt = ""
        if not prompt:
            print("❌ 'titan llm-assist' requer um prompt (argumento posicional ou stdin).")
            print("   Exemplo: titan llm-assist 'diagnosticar problema no openssl'")
            return 1

    if args.provider == "ollama":
        model = args.model or "qwen2.5:7b"
        url = args.url or "http://localhost:11434"
        print(f"🌐 Conectando ao Ollama ({model}) em {url}...")
        try:
            agent = OllamaAgent(model=model, base_url=url)
        except Exception as e:
            print(f"⚠️ Falha de comunicação com o Ollama local: {e}. Usando Mock determinístico.")
            agent = DeterministicLLMMock()
            
    elif args.provider == "openrouter":
        model = args.model or "meta-llama/llama-3-8b-instruct:free"
        url = args.url or "https://openrouter.ai/api/v1"
        api_key = args.key or os.environ.get("OPENROUTER_API_KEY")
        
        if not api_key:
            print("❌ Chave de API do OpenRouter não encontrada. Forneça com --key ou defina a variável OPENROUTER_API_KEY.")
            return 1
            
        print(f"🌐 Conectando à API do OpenRouter ({model})...")
        try:
            agent = OpenRouterAgent(api_key=api_key, model=model, base_url=url)
        except Exception as e:
            print(f"⚠️ Falha de comunicação com o OpenRouter: {e}. Usando Mock determinístico.")
            agent = DeterministicLLMMock()
    else:
        print("📦 Usando motor de mock offline local...")
        agent = DeterministicLLMMock()

    engine = LLMAssistEngine(agent)
    result = engine.route_query(prompt)
    
    print(f"\n🤖 Sugestão do Assistente: {result.get('explanation', 'Sem explicações adicionais.')}")
    if not result.get("command"):
        print("ℹ️  Nenhum comando Titan pôde ser mapeado a partir do prompt.")
        return

    if sys.stdout.isatty():
        print(f"➡️  Comando Titan mapeado: \033[1mtitan {result['command']}\033[0m")
    else:
        print(f"➡️  Comando Titan mapeado: titan {result['command']}")

    if args.yes:
        confirm = "y"
    elif not sys.stdin.isatty():
        print("ℹ️  Stdin não é TTY — pulando confirmação. Use -y para forçar execução.")
        confirm = "n"
    else:
        try:
            confirm = input("⚠️ Deseja executar o comando sugerido acima? (y/N): ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print()
            confirm = "n"

    if confirm == 'y':
        print("🚀 Executando comando sugerido...")
        sys.argv = [sys.argv[0]] + result["command"].split()
        main()
    else:
        print("❌ Comando cancelado pelo engenheiro.")
        return 1
    return 0

def cmd_telemetry(args):
    """Mostra métricas da sessão atual."""
    session = getattr(args, "session", None)
    if not session:
        print("ℹ️  Nenhuma sessão ativa.")
        return 0
    m = session.metrics.to_dict()
    print("📊 Titan Telemetry")
    print(f"   Diagnoses:    {m['diagnoses']}")
    print(f"   Fixes:        {m['fixes']}")
    print(f"   Successes:    {m['successes']}")
    print(f"   Failures:     {m['failures']}")
    print(f"   Success Rate: {m['success_rate']}%")
    print(f"   Elapsed:      {m['elapsed_seconds']:.1f}s")
    if args.save:
        trace_file = session.metrics.save_trace()
        print(f"   Trace saved:  {trace_file}")
    return 0


def cmd_twin(args):
    """Operações no DigitalTwin."""
    twin_mgr = TwinManager()
    twin = twin_mgr.get(session_id=getattr(args, "session_id", "cli"))
    bus = LocalEventBus()

    if args.action == "snapshot":
        snapshot_id = args.snapshot_id
        note = args.note
        snap = twin.create_snapshot(snapshot_id, note=note)
        print(f"✓ Snapshot '{snapshot_id}' created at {snap.timestamp}")
        print(f"  Nodes: {snap.metrics.get('total_nodes', 0)}")
        print(f"  Edges: {snap.metrics.get('total_edges', 0)}")
        print(f"  Hash:  {snap.snapshot_hash}")
        return 0

    if args.action == "snapshots":
        snapshots = twin.list_snapshots()
        if not snapshots:
            print("ℹ️  Nenhum snapshot encontrado.")
            return 0
        print(f"📸 {len(snapshots)} snapshot(s):")
        for snap in snapshots:
            parent = f" ← {snap.parent}" if snap.parent else ""
            note = f" — {snap.note}" if snap.note else ""
            print(f"  [{snap.id}]{parent} {snap.timestamp[:19]}{note}")
            print(f"    nodes={snap.metrics.get('total_nodes', 0)} "
                  f"edges={snap.metrics.get('total_edges', 0)} "
                  f"hash={snap.snapshot_hash}")
        return 0

    if args.action == "compare":
        diff = twin.compare(args.a, args.b)
        if diff is None:
            print(f"❌ Could not compare: one or both snapshots not found.")
            return 1
        print(f"🔄 Diff {args.a} ↔ {args.b}")
        print(f"  {diff.summary()}")
        if diff.nodes_added:
            print(f"  Nodes added ({len(diff.nodes_added)}):")
            for n in diff.nodes_added[:10]:
                print(f"    + {n}")
            if len(diff.nodes_added) > 10:
                print(f"    ... and {len(diff.nodes_added) - 10} more")
        if diff.nodes_removed:
            print(f"  Nodes removed ({len(diff.nodes_removed)}):")
            for n in diff.nodes_removed[:10]:
                print(f"    - {n}")
            if len(diff.nodes_removed) > 10:
                print(f"    ... and {len(diff.nodes_removed) - 10} more")
        return 0

    if args.action == "impact":
        entity = args.entity
        report = twin.analyze_impact(entity)
        if report.affected_count == 0 and "not found" in report.explanation:
            workspace = getattr(session, "workspace", None)
            if not workspace:
                print(f"❌ Entidade '{entity}' não encontrada no Digital Twin.")
                return 1
            from .recipes.db import RecipeDB
            db = RecipeDB(workspace.root_dir)
            recipe = db.get_recipe(entity)
            if not recipe:
                print(f"❌ Entidade '{entity}' não encontrada no Digital Twin nem no RecipeDB.")
                return 1
            print(f"📊 Impact Analysis: {entity}")
            deps_report = _fallback_twin_impact(entity, session)
            print(f"  Direct dependents: {len(deps_report['direct'])}")
            print(f"  {deps_report['explanation']}")
        else:
            print(f"📊 Impact Analysis: {entity}")
            print(f"  Risk level: {report.risk_level} (score: {report.risk_score})")
            print(f"  Direct dependents: {len(report.direct_dependents)}")
            print(f"  Transitive dependents: {len(report.transitive_dependents)}")
            print(f"  Total affected: {report.affected_count}")
            if report.direct_dependents:
                print(f"  Direct: {', '.join(report.direct_dependents[:10])}")
            if report.critical_path:
                print(f"  Critical path: {' → '.join(report.critical_path)}")
            print(f"  {report.explanation}")
        if args.json:
            import json
            print(json.dumps({
                "entity": entity,
                "risk_level": getattr(report, 'risk_level', 'LOW'),
                "risk_score": getattr(report, 'risk_score', 0),
                "affected_count": report.affected_count,
                "direct_dependents": report.direct_dependents,
                "transitive_dependents": report.transitive_dependents,
                "critical_path": report.critical_path,
                "explanation": report.explanation,
            }, indent=2))
        return 0

    print(f"❌ Unknown twin action: {args.action}")
    return 1


def _fallback_twin_impact(entity: str, session) -> dict:
    """Busca dependentes de uma entidade diretamente no RecipeDB (fallback do DigitalTwin)."""
    from .recipes.db import RecipeDB
    workspace = getattr(session, "workspace", None)
    if not workspace:
        return {"direct": [], "explanation": "Nenhum workspace disponível."}
    db = RecipeDB(workspace.root_dir)
    all_recipes = db.get_all_recipes()
    dependents = []
    for r in all_recipes:
        deps = (r.get("depends") or "") + " " + (r.get("rdepends") or "")
        if entity in deps.split():
            dependents.append(r["pn"])
    if dependents:
        return {"direct": dependents, "explanation": f"Pode afetar: {', '.join(dependents)}."}
    return {"direct": [], "explanation": "Nenhum outro recipe indexado depende diretamente deste."}

def main():
    parser = argparse.ArgumentParser(
        prog="titan",
        description="Titan Core — Motor de Inteligência para Engenharia Embarcada (Yocto/Buildroot)",
        epilog="Documentação: https://github.com/tecmak/titan-core  |  Reporte bugs: https://github.com/tecmak/titan-core/issues",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--workspace", "-w", default=".",
                        help="Caminho do workspace Yocto/Buildroot (default: diretório atual)")
    parser.add_argument("--version", "-v", action="store_true", help="Exibe a versão e sai")
    subparsers = parser.add_subparsers(dest="command", title="comandos", metavar="COMANDO")

    # ── Diagnóstico e Informação ────────────────────────────────
    p_info = subparsers.add_parser("info", help="Detecta e exibe informações do workspace")
    p_info.set_defaults(func=cmd_info)

    p_diag = subparsers.add_parser("diagnose", help="Analisa log de build do Yocto/Buildroot")
    p_diag.add_argument("log", help="Caminho do arquivo de log de build")
    p_diag.add_argument("--export-json", metavar="ARQUIVO", help="Exporta relatório para JSON")
    p_diag.add_argument("--export-pdf", metavar="ARQUIVO", help="Exporta relatório para PDF")
    p_diag.set_defaults(func=cmd_diagnose)

    p_explain = subparsers.add_parser("explain", help="Explica o propósito e impacto de uma recipe")
    p_explain.add_argument("target", help="PN da recipe (ex: openssl)")
    p_explain.add_argument("--json", action="store_true", help="Saída em JSON")
    p_explain.set_defaults(func=cmd_explain)

    # ── Gerenciamento de Recipes ─────────────────────────────────
    p_recipe = subparsers.add_parser("recipe", help="Gerencia recipes do workspace")
    recipe_sub = p_recipe.add_subparsers(dest="action", required=True, metavar="AÇÃO")

    p_recipe_index = recipe_sub.add_parser("index", help="Indexa todas as recipes do workspace no banco local")
    p_recipe_index.set_defaults(func=cmd_recipe)

    p_recipe_search = recipe_sub.add_parser("search", help="Busca recipes pelo nome (PN)")
    p_recipe_search.add_argument("target", nargs="?", default="", help="PN ou parte do nome para buscar")
    p_recipe_search.add_argument("--json", action="store_true", help="Saída em JSON")
    p_recipe_search.set_defaults(func=cmd_recipe)

    p_recipe_show = recipe_sub.add_parser("show", help="Exibe detalhes completos de uma recipe")
    p_recipe_show.add_argument("target", nargs="?", default="", help="PN da recipe (ex: openssl)")
    p_recipe_show.add_argument("--json", action="store_true", help="Saída em JSON")
    p_recipe_show.set_defaults(func=cmd_recipe)

    p_recipe_deps = recipe_sub.add_parser("deps", help="Exibe a árvore de dependências")
    p_recipe_deps.add_argument("target", nargs="?", default="", help="PN da recipe")
    p_recipe_deps.add_argument("--json", action="store_true", help="Saída em JSON")
    p_recipe_deps.set_defaults(func=cmd_recipe)

    p_recipe_impact = recipe_sub.add_parser("impact", help="Exibe quem depende de uma recipe")
    p_recipe_impact.add_argument("target", nargs="?", default="", help="PN da recipe")
    p_recipe_impact.add_argument("--json", action="store_true", help="Saída em JSON")
    p_recipe_impact.set_defaults(func=cmd_recipe)

    # ── Ações no Workspace ─────────────────────────────────────
    p_action = subparsers.add_parser("action", help="Executa ações de edição no workspace")
    action_sub = p_action.add_subparsers(dest="type", required=True, metavar="AÇÃO")

    p_append = action_sub.add_parser("append-conf", help="Adiciona linha ao conf/local.conf")
    p_append.add_argument("content", help="Conteúdo da linha a adicionar")
    p_append.set_defaults(func=cmd_action)

    p_addlayer = action_sub.add_parser("add-layer", help="Adiciona layer ao bblayers.conf")
    p_addlayer.add_argument("path", help="Caminho absoluto para a layer")
    p_addlayer.set_defaults(func=cmd_action)

    p_patch = action_sub.add_parser("patch-recipe", help="Aplica patch (bbappend) em uma recipe")
    p_patch.add_argument("-y", "--yes", action="store_true", help="Pula confirmação")
    p_patch.add_argument("recipe", help="PN da receita (ex: openssl)")
    p_patch.add_argument("variable", help="Nome da variável (ex: EXTRA_OECONF)")
    p_patch.add_argument("value", nargs=argparse.REMAINDER,
                         help="Valor a atribuir. Use -- antes se começar com hífen (ex: -- --with-test)")
    p_patch.set_defaults(func=cmd_action)

    # ── Segurança ─────────────────────────────────────────────
    p_security = subparsers.add_parser("security", help="Varre vulnerabilidades CVE no workspace")
    p_security.add_argument("--stub", action="store_true",
                           help="Usa dados de exemplo offline (demo, sem internet)")
    p_security.add_argument("--online", action="store_true",
                           help="Consulta API do NVD (requer internet, com cache local de 24h)")
    p_security.add_argument("--severity", nargs="+", choices=["low", "medium", "high", "critical"],
                           metavar="NÍVEL", help="Filtra por severidade (pode repetir: --severity high critical)")
    p_security.add_argument("--export-json", metavar="ARQUIVO", help="Exporta relatório para JSON")
    p_security.set_defaults(func=cmd_security)

    # ── Hardware e Runtime ─────────────────────────────────────
    p_hardware = subparsers.add_parser("hardware", help="Analisa Device Tree (.dts)")
    p_hardware.add_argument("dts", help="Caminho do arquivo .dts")
    p_hardware.set_defaults(func=cmd_hardware)

    p_runtime = subparsers.add_parser("runtime", help="Analisa log do kernel (dmesg)")
    p_runtime.add_argument("log", help="Caminho do arquivo de log dmesg")
    p_runtime.set_defaults(func=cmd_runtime)

    # ── Auto-Fix ──────────────────────────────────────────────
    p_fix = subparsers.add_parser("fix", help="Tenta corrigir automaticamente um erro de build")
    p_fix.add_argument("log", help="Caminho do log de build com erro")
    p_fix.set_defaults(func=cmd_fix)

    # ── LLM Assist ────────────────────────────────────────────
    p_llm_assist = subparsers.add_parser("llm-assist", help="Assistente por IA para engenharia embarcada")
    p_llm_assist.add_argument("prompt", nargs="?", default=None,
                              help="Pergunta natural. Se omitido, lê da stdin.")
    p_llm_assist.add_argument("--provider", choices=["offline", "ollama", "openrouter"], default="offline",
                              help="Provedor de IA (default: offline/determinístico)")
    p_llm_assist.add_argument("--model", help="Nome do modelo (ex: qwen2.5:7b)")
    p_llm_assist.add_argument("--url", help="URL customizada do endpoint")
    p_llm_assist.add_argument("--key", help="API Key para OpenRouter")
    p_llm_assist.add_argument("-y", "--yes", action="store_true", help="Pula confirmação")
    p_llm_assist.set_defaults(func=cmd_llm_assist)

    # ── Digital Twin ──────────────────────────────────────────
    p_twin = subparsers.add_parser("twin", help="Gerencia o Digital Twin do workspace")
    twin_sub = p_twin.add_subparsers(dest="action", required=True, metavar="AÇÃO")

    p_twin_snap = twin_sub.add_parser("snapshot", help="Cria um snapshot do estado atual")
    p_twin_snap.add_argument("snapshot_id", help="Identificador do snapshot")
    p_twin_snap.add_argument("--note", help="Descrição opcional do snapshot")
    p_twin_snap.set_defaults(func=cmd_twin)

    p_twin_list = twin_sub.add_parser("snapshots", help="Lista todos os snapshots")
    p_twin_list.set_defaults(func=cmd_twin)

    p_twin_cmp = twin_sub.add_parser("compare", help="Compara dois snapshots")
    p_twin_cmp.add_argument("a", help="ID do snapshot A")
    p_twin_cmp.add_argument("b", help="ID do snapshot B")
    p_twin_cmp.set_defaults(func=cmd_twin)

    p_twin_impact = twin_sub.add_parser("impact", help="Analisa o impacto de alterar uma entidade")
    p_twin_impact.add_argument("entity", help="ID da entidade (ex: buildroot_package:openssl)")
    p_twin_impact.add_argument("--json", action="store_true", help="Saída em JSON")
    p_twin_impact.set_defaults(func=cmd_twin)

    # ── Telemetria ────────────────────────────────────────────
    p_telemetry = subparsers.add_parser("telemetry", help="Exibe métricas de desempenho da sessão")
    p_telemetry.add_argument("--save", action="store_true", help="Salva trace em arquivo")
    p_telemetry.set_defaults(func=cmd_telemetry)

    args, remaining = parser.parse_known_args()

    if args.version:
        try:
            ver = version("titan-core")
        except PackageNotFoundError:
            ver = "12.0.0"
        print(f"Titan Core v{ver}")
        return

    args = parser.parse_args()

    # Criar sessão compartilhada (core + workspace + métricas)
    core = TitanCore()
    session = TitanSession(core, workspace_path=args.workspace)
    args.session = session

    if hasattr(args, 'func'):
        result = args.func(args)
        if isinstance(result, int):
            sys.exit(result)

if __name__ == "__main__":
    main()
