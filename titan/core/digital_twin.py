from __future__ import annotations
import asyncio
import hashlib
import json
import os
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple
import networkx as nx

from titan.core.event_bus import EventBus, LocalEventBus


@dataclass
class TwinSnapshot:
    """Metadados estruturados de um snapshot do DigitalTwin.

    Armazena apenas metadados — o grafo completo permanece
    no arquivo GML (snapshots/<id>/graph.gml).
    """
    id: str
    timestamp: str
    parent: Optional[str] = None
    workspace_fingerprint: str = ""
    metrics: Dict[str, Any] = field(default_factory=dict)
    event_cursor: int = 0
    note: Optional[str] = None
    snapshot_hash: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "timestamp": self.timestamp,
            "parent": self.parent,
            "workspace_fingerprint": self.workspace_fingerprint,
            "metrics": self.metrics,
            "event_cursor": self.event_cursor,
            "note": self.note,
            "snapshot_hash": self.snapshot_hash,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> TwinSnapshot:
        return cls(**data)


@dataclass
class StateDiff:
    """Diferença estrutural entre dois snapshots.

    Layer 1 — conjuntos: nodes_added, nodes_removed, edges_added, edges_removed.
    Layer 2 — semântica: fingerprint_similarity.
    """
    nodes_added: List[str] = field(default_factory=list)
    nodes_removed: List[str] = field(default_factory=list)
    edges_added: List[Tuple[str, str, str]] = field(default_factory=list)
    edges_removed: List[Tuple[str, str, str]] = field(default_factory=list)
    fingerprint_similarity: float = 1.0

    def summary(self) -> str:
        parts = []
        if self.nodes_added:
            n = len(self.nodes_added)
            parts.append(f"{n} {'node' if n == 1 else 'nodes'} added")
        if self.nodes_removed:
            n = len(self.nodes_removed)
            parts.append(f"{n} {'node' if n == 1 else 'nodes'} removed")
        if self.edges_added:
            n = len(self.edges_added)
            parts.append(f"{n} {'edge' if n == 1 else 'edges'} added")
        if self.edges_removed:
            n = len(self.edges_removed)
            parts.append(f"{n} {'edge' if n == 1 else 'edges'} removed")
        if not parts:
            parts.append("no changes")
        parts.append(f"fingerprint similarity: {self.fingerprint_similarity:.0%}")
        return ", ".join(parts)


class TwinManager:
    """Gerencia instâncias de DigitalTwin por session_id.

    Não é um singleton global — cada ponto de entrada (CLI, daemon, teste)
    cria seu próprio TwinManager. Dentro de um processo, o mesmo session_id
    retorna a mesma instância de DigitalTwin.

    Uso:
        mgr = TwinManager()
        twin = mgr.get()                         # session \"default\"
        twin = mgr.get(session_id=\"run-42\")    # sessão isolada
        mgr.reset()                               # libera todas
        mgr.reset(\"run-42\")                     # libera específica
    """

    def __init__(self):
        self._instances: Dict[str, DigitalTwin] = {}

    def get(self, session_id: str = "default",
            event_bus: Optional[EventBus] = None) -> DigitalTwin:
        if session_id not in self._instances:
            self._instances[session_id] = DigitalTwin(
                event_bus or LocalEventBus(),
            )
        return self._instances[session_id]

    def reset(self, session_id: Optional[str] = None):
        if session_id:
            self._instances.pop(session_id, None)
        else:
            self._instances.clear()


class DigitalTwin:
    def __init__(self, event_bus: EventBus, base_path: str = ".titan_digital_twin"):
        self.event_bus = event_bus
        self.base_path = base_path
        if not os.path.exists(base_path):
            os.makedirs(base_path)

        self.event_log_path = os.path.join(self.base_path, "event_log.jsonl")
        self.graph = nx.DiGraph()
        self._event_count = 0
        self._snapshot_db_path = os.path.join(self.base_path, "snapshots.db")
        self._init_snapshot_db()
        self._load_events()

    def _init_snapshot_db(self):
        conn = sqlite3.connect(self._snapshot_db_path)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS snapshots (
                id TEXT PRIMARY KEY,
                timestamp TEXT NOT NULL,
                parent TEXT,
                workspace_fingerprint TEXT DEFAULT '',
                metrics TEXT DEFAULT '{}',
                event_cursor INTEGER DEFAULT 0,
                note TEXT,
                snapshot_hash TEXT DEFAULT ''
            )
        """)
        conn.commit()
        # Migration: add snapshot_hash column to existing databases
        try:
            conn.execute("ALTER TABLE snapshots ADD COLUMN snapshot_hash TEXT DEFAULT ''")
            conn.commit()
        except sqlite3.OperationalError:
            pass  # column already exists
        conn.close()

    @staticmethod
    def _compute_hash(fingerprint: str, total_nodes: int,
                      total_edges: int, event_cursor: int) -> str:
        raw = f"{fingerprint}|{total_nodes}|{total_edges}|{event_cursor}"
        return hashlib.sha256(raw.encode()).hexdigest()[:16]

    def _load_events(self):
        if os.path.exists(self.event_log_path):
            with open(self.event_log_path, 'r') as f:
                for line in f:
                    event = json.loads(line)
                    self._apply_event(event)
                    self._event_count += 1

    def emit_event(self, event_type: str, data: Dict[str, Any]) -> None:
        """Atualiza o grafo interno. NÃO emite no EventBus.

        O DigitalTwin é um modelo de dados, não um produtor de eventos.
        Quem chama emit_event() deve emitir no bus separadamente se necessário.
        """
        event = {
            "event": event_type,
            "data": data,
            "timestamp": datetime.now().isoformat()
        }
        with open(self.event_log_path, 'a') as f:
            f.write(json.dumps(event) + '\n')
        self._apply_event(event)
        self._event_count += 1

    def _apply_event(self, event: Dict[str, Any]):
        event_type = event["event"]
        data = event["data"]

        if event_type == "layer_added":
            layer_name = data["layer"]
            self.graph.add_node(f"layer:{layer_name}", type="layer", name=layer_name)
        elif event_type == "recipe_added":
            recipe_name = data["recipe"]
            layer_name = data["layer"]
            if not self.graph.has_node(f"recipe:{recipe_name}"):
                self.graph.add_node(f"recipe:{recipe_name}", type="recipe", name=recipe_name)
            if not self.graph.has_node(f"layer:{layer_name}"):
                self.graph.add_node(f"layer:{layer_name}", type="layer", name=layer_name)
            self.graph.add_edge(f"layer:{layer_name}", f"recipe:{recipe_name}", relation="contains")
        elif event_type == "dependency_added":
            source_recipe = data["source_recipe"]
            target_package = data["target_package"]
            if not self.graph.has_node(f"package:{target_package}"):
                self.graph.add_node(f"package:{target_package}", type="package", name=target_package)
            if not self.graph.has_node(f"recipe:{source_recipe}"):
                self.graph.add_node(f"recipe:{source_recipe}", type="recipe", name=source_recipe)
            self.graph.add_edge(f"recipe:{source_recipe}", f"package:{target_package}", relation="depends_on")

        # Buildroot events
        elif event_type == "buildroot_workspace_scanned":
            self.graph.add_node("buildroot:workspace", type="buildroot_workspace",
                                arch=data.get("arch", ""),
                                toolchain_type=data.get("toolchain_type", ""),
                                c_library=data.get("c_library", ""))

        elif event_type == "buildroot_package_added":
            pkg = data["package"]
            if not self.graph.has_node(f"buildroot_package:{pkg}"):
                self.graph.add_node(f"buildroot_package:{pkg}", type="buildroot_package", name=pkg)
            self.graph.add_edge("buildroot:workspace", f"buildroot_package:{pkg}", relation="contains")

        elif event_type == "buildroot_package_dependency":
            pkg = data["package"]
            dep = data["depends_on"]
            for node in [f"buildroot_package:{pkg}", f"buildroot_package:{dep}"]:
                if not self.graph.has_node(node):
                    self.graph.add_node(node, type="buildroot_package", name=pkg if node.endswith(pkg) else dep)
            self.graph.add_edge(f"buildroot_package:{pkg}", f"buildroot_package:{dep}", relation="depends_on")

        elif event_type == "buildroot_overlay_added":
            overlay = data["overlay"]
            self.graph.add_node(f"buildroot_overlay:{overlay}", type="buildroot_overlay", name=overlay)
            self.graph.add_edge("buildroot:workspace", f"buildroot_overlay:{overlay}", relation="uses")

        # Buildroot scanner events
        elif event_type == "buildroot_external_tree":
            name = data.get("name", "unknown")
            self.graph.add_node(f"buildroot_external:{name}", type="buildroot_external", name=name,
                                path=data.get("path", ""))
            self.graph.add_edge("buildroot:workspace", f"buildroot_external:{name}", relation="extends")

        elif event_type == "buildroot_defconfig":
            name = data.get("name", "unknown")
            source = data.get("source", "")
            self.graph.add_node(f"buildroot_defconfig:{name}", type="buildroot_defconfig", name=name, source=source)
            self.graph.add_edge("buildroot:workspace", f"buildroot_defconfig:{name}", relation="has_defconfig")

        elif event_type == "buildroot_uboot_detected":
            board = data.get("board", "")
            self.graph.add_node("buildroot:uboot", type="buildroot_uboot", board=board)
            self.graph.add_edge("buildroot:workspace", "buildroot:uboot", relation="uses")

        elif event_type == "buildroot_init_system":
            init = data.get("init", "")
            self.graph.add_node(f"buildroot_init:{init}", type="buildroot_init", name=init)
            self.graph.add_edge("buildroot:workspace", f"buildroot_init:{init}", relation="uses")
        # Add more event types and their graph manipulation logic here

    def get_graph(self) -> nx.DiGraph:
        return self.graph

    def query_dependencies(self, node_id: str) -> List[str]:
        return list(self.graph.successors(node_id))

    def query_impact(self, node_id: str) -> Dict[str, int]:
        affected_recipes = set()
        affected_packages = set()

        # Include the node itself if it matches the criteria
        nodes_to_check = list(nx.descendants(self.graph, node_id))
        # No longer using dfs_successors as it returns an adjacency dict, descendants is better here

        for n in nodes_to_check:
            node_type = self.graph.nodes[n].get("type")
            if node_type == "recipe":
                affected_recipes.add(self.graph.nodes[n].get("name"))
            elif node_type == "package":
                affected_packages.add(self.graph.nodes[n].get("name"))

        return {
            "affected_recipes": len(affected_recipes),
            "affected_packages": len(affected_packages)
        }

    def get_workspace_health(self) -> int:
        # Placeholder for complex health calculation based on graph analysis
        # e.g., detect cycles, broken dependencies, CVEs (if integrated)
        return 100  # For now, assume perfect health

    def get_timeline(self, hours: int = 24) -> List[Dict[str, Any]]:
        # This would require more sophisticated event storage with indexing by timestamp
        # For now, it reads the last N events from the log
        events = []
        if os.path.exists(self.event_log_path):
            with open(self.event_log_path, 'r') as f:
                for line in reversed(list(f)):
                    event = json.loads(line)
                    event_time = datetime.fromisoformat(event["timestamp"])
                    if (datetime.now() - event_time).total_seconds() / 3600 < hours:
                        events.append(event)
                    else:
                        break
        return list(reversed(events))  # Return in chronological order

    # ── Snapshot structured metadata (SQLite) ──────────────────────

    def _compute_metrics(self) -> Dict[str, Any]:
        layers = 0
        recipes = 0
        packages = 0
        buildroot_packages = 0
        for _, data in self.graph.nodes(data=True):
            t = data.get("type", "")
            if t == "layer":
                layers += 1
            elif t == "recipe":
                recipes += 1
            elif t == "package":
                packages += 1
            elif t == "buildroot_package":
                buildroot_packages += 1
        return {
            "layers": layers,
            "recipes": recipes,
            "packages": packages,
            "buildroot_packages": buildroot_packages,
            "total_nodes": self.graph.number_of_nodes(),
            "total_edges": self.graph.number_of_edges(),
        }

    def create_snapshot(
        self,
        snapshot_id: str,
        note: Optional[str] = None,
        parent: Optional[str] = None,
        workspace_fingerprint: str = "",
    ) -> TwinSnapshot:
        metrics = self._compute_metrics()
        snapshot = TwinSnapshot(
            id=snapshot_id,
            timestamp=datetime.now().isoformat(),
            parent=parent,
            workspace_fingerprint=workspace_fingerprint,
            metrics=metrics,
            event_cursor=self._event_count,
            note=note,
            snapshot_hash=self._compute_hash(
                workspace_fingerprint,
                metrics["total_nodes"],
                metrics["total_edges"],
                self._event_count,
            ),
        )

        # SQLite metadata — ensure base_path still exists (may have been cleaned)
        os.makedirs(self.base_path, exist_ok=True)
        self._init_snapshot_db()
        conn = sqlite3.connect(self._snapshot_db_path)
        conn.execute(
            """INSERT OR REPLACE INTO snapshots
               (id, timestamp, parent, workspace_fingerprint,
                metrics, event_cursor, note, snapshot_hash)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (snapshot.id, snapshot.timestamp, snapshot.parent,
             snapshot.workspace_fingerprint, json.dumps(snapshot.metrics),
             snapshot.event_cursor, snapshot.note, snapshot.snapshot_hash),
        )
        conn.commit()
        conn.close()

        # GML graph snapshot (sidecar — kept for backward compat + full restore)
        snapshot_dir = os.path.join(self.base_path, "snapshots", snapshot_id)
        os.makedirs(snapshot_dir, exist_ok=True)
        nx.write_gml(self.graph, os.path.join(snapshot_dir, "graph.gml"))

        print(f"Snapshot {snapshot_id} created at {snapshot_dir}")
        return snapshot

    def get_snapshot(self, snapshot_id: str) -> Optional[TwinSnapshot]:
        if not os.path.exists(self._snapshot_db_path):
            return None
        conn = sqlite3.connect(self._snapshot_db_path)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM snapshots WHERE id = ?", (snapshot_id,)
        ).fetchone()
        conn.close()
        if not row:
            return None
        return self._row_to_snapshot(row)

    def list_snapshots(self) -> List[TwinSnapshot]:
        if not os.path.exists(self._snapshot_db_path):
            return []
        conn = sqlite3.connect(self._snapshot_db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM snapshots ORDER BY timestamp DESC"
        ).fetchall()
        conn.close()
        return [self._row_to_snapshot(row) for row in rows]

    @staticmethod
    def _row_to_snapshot(row: sqlite3.Row) -> TwinSnapshot:
        data = dict(row)
        data["metrics"] = json.loads(data["metrics"])
        return TwinSnapshot.from_dict(data)

    # ── Legacy GML snapshot API (preserved) ───────────────────────

    def load_snapshot(self, snapshot_id: str):
        """Carrega o grafo completo de um snapshot GML.

        Nota: para acessar metadados estruturados, use get_snapshot().
        """
        snapshot_dir = os.path.join(self.base_path, "snapshots", snapshot_id)
        if not os.path.exists(snapshot_dir):
            raise FileNotFoundError(f"Snapshot {snapshot_id} not found.")

        self.graph = nx.read_gml(os.path.join(snapshot_dir, "graph.gml"))
        # Optionally, reload event log from snapshot if needed for timeline features
        self.event_log_path = os.path.join(snapshot_dir, "event_log.jsonl")
        print(f"Snapshot {snapshot_id} loaded.")

    # ── State Diff (Phase 3) ───────────────────────────────────────

    def _graph_from_snapshot(self, snapshot_id: str) -> Optional[nx.DiGraph]:
        gml_path = os.path.join(
            self.base_path, "snapshots", snapshot_id, "graph.gml",
        )
        if not os.path.exists(gml_path):
            return None
        return nx.read_gml(gml_path)

    def compare(self, snapshot_a_id: str,
                snapshot_b_id: str) -> Optional[StateDiff]:
        """Retorna a diferença estrutural entre dois snapshots."""
        g_a = self._graph_from_snapshot(snapshot_a_id)
        g_b = self._graph_from_snapshot(snapshot_b_id)
        if g_a is None or g_b is None:
            return None

        nodes_a = set(g_a.nodes())
        nodes_b = set(g_b.nodes())

        edges_a = set(
            (u, v, g_a.edges[u, v].get("relation", ""))
            for u, v in g_a.edges()
        )
        edges_b = set(
            (u, v, g_b.edges[u, v].get("relation", ""))
            for u, v in g_b.edges()
        )

        # Fingerprint similarity
        snap_a = self.get_snapshot(snapshot_a_id)
        snap_b = self.get_snapshot(snapshot_b_id)
        fp_sim = 1.0
        if snap_a and snap_b and snap_a.workspace_fingerprint and snap_b.workspace_fingerprint:
            from titan.context.fingerprint import parse as fp_parse
            from titan.context.similarity import compare as ctx_compare
            try:
                fp_a = fp_parse(snap_a.workspace_fingerprint)
                fp_b = fp_parse(snap_b.workspace_fingerprint)
                match = ctx_compare(fp_a, fp_b)
                fp_sim = match.score / 100.0
            except Exception:
                fp_sim = 1.0 if snap_a.snapshot_hash == snap_b.snapshot_hash else 0.0

        return StateDiff(
            nodes_added=sorted(nodes_b - nodes_a),
            nodes_removed=sorted(nodes_a - nodes_b),
            edges_added=sorted(edges_b - edges_a),
            edges_removed=sorted(edges_a - edges_b),
            fingerprint_similarity=round(fp_sim, 4),
        )

    # ── Impact Analysis (Phase 4) ──────────────────────────────────

    def analyze_impact(self, entity_id: str) -> ImpactReport:
        """Estima o impacto de alterar uma entidade no grafo.

        Retorna dependentes diretos, transitivos, critical_path,
        risk_level e risk_score.

        Considera apenas arestas com relation='depends_on' como
        dependências reais (exclui arestas 'contains' da workspace).
        """
        g = self.graph
        if not g.has_node(entity_id):
            return ImpactReport(
                entity=entity_id,
                direct_dependents=[],
                transitive_dependents=[],
                affected_count=0,
                critical_path=[],
                risk_level=ImpactReport.LOW,
                risk_score=0.0,
                explanation=f"Entity '{entity_id}' not found in graph.",
            )

        # Direct dependents = predecessors with "depends_on" edge
        direct = [
            pred for pred in g.predecessors(entity_id)
            if g.has_edge(pred, entity_id)
            and g.edges[pred, entity_id].get("relation") == "depends_on"
        ]

        # Transitive dependents = ancestors via only "depends_on" edges
        transitive = []
        visited = set(direct) | {entity_id}
        stack = list(direct)
        while stack:
            node = stack.pop()
            for pred in g.predecessors(node):
                if (g.has_edge(pred, node)
                        and g.edges[pred, node].get("relation") == "depends_on"
                        and pred not in visited):
                    visited.add(pred)
                    transitive.append(pred)
                    stack.append(pred)

        # critical_path = longest chain from entity_id outward
        # BFS from entity_id following predecessor edges
        critical_path = self._critical_path(g, entity_id)

        affected = len(set(direct + transitive))
        risk_score, risk_level = ImpactReport._compute_risk(
            entity_id, g, affected,
        )

        if risk_level == ImpactReport.LOW:
            explanation = (
                f"Entity '{entity_id}' has no dependents. "
                "Impact is minimal."
            )
        elif risk_level == ImpactReport.CRITICAL:
            explanation = (
                f"Entity '{entity_id}' is a critical system component "
                f"(toolchain/kernel/libc). Changing it affects "
                f"{affected} {'entity' if affected == 1 else 'entities'}."
            )
        else:
            dependent_list = ", ".join(direct[:5])
            if len(direct) > 5:
                dependent_list += f" and {len(direct) - 5} more"
            dep_label = "dependent" if len(direct) == 1 else "dependents"
            explanation = (
                f"Entity '{entity_id}' has {len(direct)} direct "
                f"{dep_label} ({dependent_list}) and {len(transitive)} "
                f"transitive dependents ({affected} total). "
                f"Risk level: {risk_level}."
            )

        return ImpactReport(
            entity=entity_id,
            direct_dependents=direct,
            transitive_dependents=list(transitive),
            affected_count=affected,
            critical_path=critical_path,
            risk_level=risk_level,
            risk_score=risk_score,
            explanation=explanation,
        )

    @staticmethod
    def _critical_path(g: nx.DiGraph, entity_id: str) -> List[str]:
        """Maior cadeia de dependência a partir de entity_id,
        seguindo apenas arestas 'depends_on'."""
        longest: List[str] = []
        stack = [(entity_id, [entity_id])]
        visited = set()
        while stack:
            node, path = stack.pop()
            if node in visited and len(path) <= 1:
                continue
            visited.add(node)
            for pred in g.predecessors(node):
                if (g.has_edge(pred, node)
                        and g.edges[pred, node].get("relation") == "depends_on"):
                    new_path = path + [pred]
                    if len(new_path) > len(longest):
                        longest = new_path
                    stack.append((pred, new_path))
        return longest


@dataclass
class ImpactReport:
    """Relatório de impacto de alteração em uma entidade do grafo.

    Risk levels:
        LOW (0.1)      — 0 dependentes
        MEDIUM (0.4)   — 1-3 dependentes
        HIGH (0.7)     — 4+ dependentes
        CRITICAL (0.95) — toolchain, kernel ou libc
    """
    entity: str
    direct_dependents: List[str] = field(default_factory=list)
    transitive_dependents: List[str] = field(default_factory=list)
    affected_count: int = 0
    critical_path: List[str] = field(default_factory=list)
    risk_level: str = "LOW"
    risk_score: float = 0.0
    explanation: str = ""

    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"

    _CRITICAL_KEYWORDS = {"toolchain", "kernel", "libc", "gcc", "linux",
                          "glibc", "musl", "external-toolchain", "gcc_external"}

    @staticmethod
    def _compute_risk(entity_id: str, graph: nx.DiGraph,
                      affected_count: int) -> Tuple[float, str]:
        # Check for critical system entities
        node_data = graph.nodes.get(entity_id)
        if node_data:
            ntype = node_data.get("type", "")
            is_workspace = ntype == "buildroot_workspace"
            name_lower = entity_id.lower()
        else:
            is_workspace = False
            name_lower = entity_id.lower()

        if is_workspace or any(kw in name_lower for kw in
                               ImpactReport._CRITICAL_KEYWORDS):
            return 0.95, ImpactReport.CRITICAL

        if affected_count == 0:
            return 0.1, ImpactReport.LOW
        elif affected_count <= 3:
            return 0.4, ImpactReport.MEDIUM
        else:
            return 0.7, ImpactReport.HIGH
