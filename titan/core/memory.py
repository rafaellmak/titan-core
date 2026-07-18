import sqlite3
import json
import os
from datetime import datetime
from typing import Any, Dict, List, Optional
from titan.core.event_bus import EventBus
from titan.core.digital_twin import DigitalTwin
from titan.core.knowledge_engine import KnowledgeEngine, KnowledgeRecord

class MultiLayerMemory:
    def __init__(self, event_bus: EventBus, base_path: str = ".titan_memory",
                 knowledge_engine: KnowledgeEngine | None = None,
                 digital_twin: Optional[DigitalTwin] = None):
        self.event_bus = event_bus
        self.base_path = base_path
        if not os.path.exists(base_path):
            os.makedirs(base_path)

        self.digital_twin = digital_twin or DigitalTwin(event_bus)
        self.knowledge_engine = knowledge_engine or KnowledgeEngine()

        # Layer 1: State & Configuration
        self.state_db = self._init_db("state.db", '''
            CREATE TABLE IF NOT EXISTS project_state (
                key TEXT PRIMARY KEY,
                value TEXT,
                updated_at TEXT
            )
        ''')

        # Layer 2: Knowledge & Experience
        self.knowledge_db = self._init_db("knowledge.db", '''
            CREATE TABLE IF NOT EXISTS knowledge_base (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                category TEXT,
                topic TEXT,
                content TEXT,
                tags TEXT,
                created_at TEXT
            )
        ''')

        # Layer 3: Audit & History
        self.audit_db = self._init_db("audit.db", '''
            CREATE TABLE IF NOT EXISTS audit_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT,
                event_type TEXT,
                details TEXT,
                status TEXT
            )
        ''')

    def _init_db(self, db_name: str, schema: str) -> str:
        db_path = os.path.join(self.base_path, db_name)
        conn = sqlite3.connect(db_path)
        conn.execute(schema)
        conn.commit()
        conn.close()
        return db_path

    def _get_conn(self, db_path: str):
        os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
        return sqlite3.connect(db_path)

    # State Methods
    def update_state(self, key: str, value: Any):
        with self._get_conn(self.state_db) as conn:
            conn.execute('''
                INSERT INTO project_state (key, value, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at
            ''', (key, json.dumps(value), datetime.now().isoformat()))

    def get_state(self, key: str) -> Optional[Any]:
        with self._get_conn(self.state_db) as conn:
            row = conn.execute('SELECT value FROM project_state WHERE key = ?', (key,)).fetchone()
            return json.loads(row[0]) if row else None

    # Knowledge Methods
    def add_knowledge(self, category: str, topic: str, content: Any, tags: List[str] = []):
        # Emit event to event bus
        self.event_bus.emit("knowledge_added", {"category": category, "topic": topic, "content": content})

        # Add to the new KnowledgeEngine
        record = KnowledgeRecord(
            problem_signature=topic, 
            root_cause="N/A", 
            action_taken="N/A", 
            outcome="N/A", 
            confidence=0.5, 
            success_rate=0.5
        )
        self.knowledge_engine.add_knowledge(record)

        # Also add to the traditional knowledge_base DB
        with self._get_conn(self.knowledge_db) as conn:
            conn.execute('''
                INSERT INTO knowledge_base (category, topic, content, tags, created_at)
                VALUES (?, ?, ?, ?, ?)
            ''', (category, topic, json.dumps(content), ",".join(tags), datetime.now().isoformat()))

    # Audit Methods
    def log_event(self, event_type: str, details: Dict[str, Any], status: str = "INFO"):
        # Emit audit events to the Digital Twin for timeline and snapshot
        self.digital_twin.emit_event(event_type, details)
        with self._get_conn(self.audit_db) as conn:
            conn.execute('''
                INSERT INTO audit_log (timestamp, event_type, details, status)
                VALUES (?, ?, ?, ?)
            ''', (datetime.now().isoformat(), event_type, json.dumps(details), status))
