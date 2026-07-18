import shutil
import subprocess
from pathlib import Path
from typing import Callable, List
from ..workspace.models import Workspace

class FixTransaction:
    """Gerenciador de Transações de Workspace de forma isolada."""
    
    def __init__(self, workspace):
        self.workspace = workspace
        self.backup_dir = Path(".titan_sandbox_backup")
        self.mutated_files: List[Path] = []

    def __enter__(self):
        if self.backup_dir.exists():
            shutil.rmtree(self.backup_dir)
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        return self

    def register_mutation(self, file_path: Path):
        """Cria um snapshot do arquivo antes da mutação."""
        if file_path not in self.mutated_files and file_path.exists():
            try:
                relative_path = file_path.relative_to(self.workspace.root_dir)
                backup_file = self.backup_dir / relative_path
                backup_file.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(file_path, backup_file)
                self.mutated_files.append(file_path)
            except ValueError:
                # Arquivo fora do root_dir, ignorar para sandbox
                pass

    def rollback(self):
        """Restaura os arquivos modificados para seu estado íntegro original."""
        print("🔄 Erro detectado na Sandbox. Iniciando Rollback automático...")
        for file_path in self.mutated_files:
            relative_path = file_path.relative_to(self.workspace.root_dir)
            backup_file = self.backup_dir / relative_path
            if backup_file.exists():
                shutil.copy2(backup_file, file_path)
                print(f"✅ Restaurado: {relative_path}")
        self.cleanup()

    def cleanup(self):
        if self.backup_dir.exists():
            shutil.rmtree(self.backup_dir)

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.cleanup()
