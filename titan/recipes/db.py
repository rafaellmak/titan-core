import sqlite3
from pathlib import Path
from typing import List, Dict, Optional

class RecipeDB:
    def __init__(self, workspace_root: Path):
        self.db_dir = workspace_root / ".titan"
        self.db_dir.mkdir(exist_ok=True)
        self.db_path = self.db_dir / "recipes.db"
        self._init_db()

    def _init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS recipes (
                    pn TEXT PRIMARY KEY,
                    pv TEXT,
                    license TEXT,
                    depends TEXT,
                    rdepends TEXT,
                    src_uri TEXT,
                    inherits TEXT,
                    file_path TEXT
                )
            """)
            # Índices para buscas rápidas
            conn.execute("CREATE INDEX IF NOT EXISTS idx_depends ON recipes(depends)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_rdepends ON recipes(rdepends)")

    def upsert_recipe(self, data: Dict[str, str]):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT INTO recipes (pn, pv, license, depends, rdepends, src_uri, inherits, file_path)
                VALUES (:pn, :pv, :license, :depends, :rdepends, :src_uri, :inherits, :file_path)
                ON CONFLICT(pn) DO UPDATE SET
                    pv=excluded.pv, license=excluded.license, depends=excluded.depends,
                    rdepends=excluded.rdepends, src_uri=excluded.src_uri, 
                    inherits=excluded.inherits, file_path=excluded.file_path
            """, data)

    def get_recipe(self, pn: str) -> Optional[Dict]:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cur = conn.execute("SELECT * FROM recipes WHERE pn = ?", (pn,))
            row = cur.fetchone()
            return dict(row) if row else None

    def search_recipes(self, query: str) -> List[Dict]:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cur = conn.execute("SELECT pn, pv, license, file_path FROM recipes WHERE pn LIKE ?", (f"%{query}%",))
            return [dict(row) for row in cur.fetchall()]

    def get_all_recipes(self) -> List[Dict]:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cur = conn.execute("SELECT pn, depends, rdepends, file_path FROM recipes")
            return [dict(row) for row in cur.fetchall()]
