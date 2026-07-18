from __future__ import annotations
from datetime import datetime
from typing import Any, Dict

from titan.core.planner import Skill
from titan.core.memory import MultiLayerMemory
from titan.core.digital_twin import DigitalTwin
from titan.core.knowledge_engine import KnowledgeEngine
from titan.workspace.detector import WorkspaceDetector
from titan.workspace.models import BuildrootWorkspace


class BuildrootSkill(Skill):
    def can_handle(self, event_type: str, data: Dict[str, Any]) -> bool:
        return event_type in (
            "buildroot_scan",
            "buildroot_config_changed",
            "workspace_scan",
        )

    def _build_fingerprint(self, workspace: BuildrootWorkspace) -> str:
        parts = [
            workspace.type or "buildroot",
            workspace.arch or "unknown",
            workspace.toolchain_type or "unknown",
            workspace.c_library or "unknown",
        ]
        return "/".join(parts)

    async def execute(self, data: Dict[str, Any], memory: MultiLayerMemory,
                      digital_twin: DigitalTwin,
                      knowledge_engine: KnowledgeEngine) -> Any:
        detector = WorkspaceDetector()
        workspace = detector.detect()

        if isinstance(workspace, BuildrootWorkspace):
            memory.update_state("workspace", workspace.to_dict())

            digital_twin.emit_event("buildroot_workspace_scanned", {
                "workspace_type": workspace.type,
                "path": str(workspace.root_dir),
                "arch": workspace.arch,
                "toolchain_type": workspace.toolchain_type,
                "c_library": workspace.c_library,
                "hostname": workspace.hostname,
                "kernel_enabled": workspace.kernel_enabled,
            })

            for pkg in workspace.packages:
                digital_twin.emit_event("buildroot_package_added", {
                    "package": pkg,
                })

            if workspace.packages_meta:
                for pkg_name, pkg_data in workspace.packages_meta.items():
                    for dep in pkg_data.get("dependencies", []):
                        digital_twin.emit_event("buildroot_package_dependency", {
                            "package": pkg_name,
                            "depends_on": dep,
                        })

            for overlay in workspace.overlays:
                digital_twin.emit_event("buildroot_overlay_added", {
                    "overlay": overlay,
                })

            for ext in workspace.external_trees:
                digital_twin.emit_event("buildroot_external_tree", {
                    "path": ext.get("path", ""),
                    "name": ext.get("name", ""),
                    "packages": ext.get("packages", []),
                })

            for cfg in workspace.defconfigs:
                digital_twin.emit_event("buildroot_defconfig", {
                    "name": cfg.get("name", ""),
                    "source": cfg.get("source", ""),
                })

            if workspace.uboot_enabled:
                digital_twin.emit_event("buildroot_uboot_detected", {
                    "board": workspace.uboot_board,
                })

            if workspace.init_system:
                digital_twin.emit_event("buildroot_init_system", {
                    "init": workspace.init_system,
                })

            memory.update_state("packages_count", len(workspace.packages))
            memory.update_state("overlays_count", len(workspace.overlays))
            memory.update_state("external_trees", len(workspace.external_trees))
            memory.update_state("defconfigs_count", len(workspace.defconfigs))

            # ── Snapshot + regression detection ─────────────────────
            fp = self._build_fingerprint(workspace)
            snapshot_id = f"buildroot-scan-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
            regression = None
            try:
                current = digital_twin.create_snapshot(
                    snapshot_id,
                    note=f"Buildroot scan: {workspace.arch}/{workspace.toolchain_type}",
                    workspace_fingerprint=fp,
                )

                # Compare with previous snapshot (same fingerprint)
                previous = None
                all_snapshots = digital_twin.list_snapshots()
                for snap in all_snapshots:
                    if snap.id != snapshot_id and snap.workspace_fingerprint == fp:
                        previous = snap
                        break

                if previous:
                    diff = digital_twin.compare(previous.id, current.id)
                    if diff and (diff.nodes_added or diff.nodes_removed
                                 or diff.edges_added or diff.edges_removed):
                        regression = {
                            "previous_snapshot": previous.id,
                            "current_snapshot": current.id,
                            "diff_summary": diff.summary(),
                            "nodes_added": diff.nodes_added,
                            "nodes_removed": diff.nodes_removed,
                            "fingerprint_similarity": diff.fingerprint_similarity,
                        }
            except Exception:
                pass

            result = {
                "status": "indexed",
                "type": "buildroot",
                "arch": workspace.arch,
                "packages": len(workspace.packages),
                "overlays": len(workspace.overlays),
                "external_trees": len(workspace.external_trees),
                "defconfigs": len(workspace.defconfigs),
                "init_system": workspace.init_system,
                "uboot": workspace.uboot_enabled,
                "snapshot_id": snapshot_id,
                "regression": regression,
            }
            return result

        return {"status": "no_buildroot_workspace"}
