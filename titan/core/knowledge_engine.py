import json
import os
from datetime import datetime
from typing import Any, Dict, List, Optional
import sqlite3

class KnowledgeRecord:
    def __init__(self, problem_signature: str, root_cause: str, action_taken: str, outcome: str, confidence: float, success_rate: float, created_at: str = None, last_used: str = None, usage_count: int = 0):
        self.problem_signature = problem_signature
        self.root_cause = root_cause
        self.action_taken = action_taken
        self.outcome = outcome
        self.confidence = confidence
        self.success_rate = success_rate
        self.created_at = created_at if created_at else datetime.now().isoformat()
        self.last_used = last_used if last_used else datetime.now().isoformat()
        self.usage_count = usage_count

    def to_dict(self):
        return self.__dict__

    @staticmethod
    def from_dict(data: Dict[str, Any]):
        return KnowledgeRecord(**data)

class KnowledgeEngine:
    def __init__(self, base_path: str = ".titan_knowledge"):
        self.base_path = base_path
        if not os.path.exists(base_path):
            os.makedirs(base_path)
        self.db_path = os.path.join(self.base_path, "knowledge.db")
        self._init_db()

    def _init_db(self):
        conn = sqlite3.connect(self.db_path)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS knowledge_records (
                problem_signature TEXT PRIMARY KEY,
                root_cause TEXT,
                action_taken TEXT,
                outcome TEXT,
                confidence REAL,
                success_rate REAL,
                created_at TEXT,
                last_used TEXT,
                usage_count INTEGER
            )
        """)
        conn.commit()
        conn.close()

    def _get_conn(self):
        os.makedirs(os.path.dirname(self.db_path) or ".", exist_ok=True)
        return sqlite3.connect(self.db_path)

    def add_knowledge(self, record: KnowledgeRecord):
        with self._get_conn() as conn:
            conn.execute("""
                INSERT OR REPLACE INTO knowledge_records (
                    problem_signature, root_cause, action_taken, outcome, 
                    confidence, success_rate, created_at, last_used, usage_count
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                record.problem_signature, record.root_cause, record.action_taken, 
                record.outcome, record.confidence, record.success_rate, 
                record.created_at, record.last_used, record.usage_count
            ))
            conn.commit()

    def get_knowledge(self, problem_signature: str) -> Optional[KnowledgeRecord]:
        with self._get_conn() as conn:
            cursor = conn.execute("SELECT * FROM knowledge_records WHERE problem_signature = ?", (problem_signature,))
            row = cursor.fetchone()
            if row:
                return KnowledgeRecord(
                    problem_signature=row[0], root_cause=row[1], action_taken=row[2],
                    outcome=row[3], confidence=row[4], success_rate=row[5],
                    created_at=row[6], last_used=row[7], usage_count=row[8]
                )
            return None

    def find_similar_knowledge(self, problem_description: str, limit: int = 5) -> List[KnowledgeRecord]:
        # This is a placeholder for a more sophisticated similarity engine.
        # In a real scenario, this would involve NLP techniques, embeddings, etc.
        
        # Split problem_description into keywords
        keywords = problem_description.lower().split()
        
        # Build a dynamic query to search for keywords in problem_signature or root_cause
        query_parts = []
        params = []
        for keyword in keywords:
            query_parts.append("(problem_signature LIKE ? OR root_cause LIKE ?)")
            params.append(f"%{keyword}%")
            params.append(f"%{keyword}%")
        
        where_clause = " AND ".join(query_parts)
        if not where_clause:
            return []

        # Add match_score to the SELECT statement and order by it
        select_clause = "*, (" + " + ".join([f"CASE WHEN problem_signature LIKE ? THEN 1 ELSE 0 END + CASE WHEN root_cause LIKE ? THEN 1 ELSE 0 END" for _ in keywords]) + ") AS match_score"
        
        sql_query = f"SELECT {select_clause} FROM knowledge_records WHERE {where_clause} ORDER BY match_score DESC, confidence DESC, success_rate DESC LIMIT ?"
        
        # Prepare parameters for the match_score calculation and the WHERE clause
        full_params = []
        for keyword in keywords:
            full_params.append(f"%{keyword}%")
            full_params.append(f"%{keyword}%")
        full_params.extend(params) # Add parameters for the WHERE clause
        full_params.append(limit)

        with self._get_conn() as conn:
            cursor = conn.execute(sql_query, tuple(full_params))
            
            results = []
            for row in cursor.fetchall():
                # Exclude the last column (match_score) when creating KnowledgeRecord
                record = KnowledgeRecord(
                    problem_signature=row[0], root_cause=row[1], action_taken=row[2],
                    outcome=row[3], confidence=row[4], success_rate=row[5],
                    created_at=row[6], last_used=row[7], usage_count=row[8]
                )
                results.append(record)
            return results

    def update_knowledge_usage(self, problem_signature: str, success: bool, notes: Optional[str] = None):
        record = self.get_knowledge(problem_signature)
        if record:
            record.usage_count += 1
            record.last_used = datetime.now().isoformat()

            if notes:
                if not hasattr(record, "operator_notes") or record.operator_notes is None:
                    record.operator_notes = []
                record.operator_notes.append({"ts": datetime.now().isoformat(), "note": notes})

            if success:
                record.success_rate = (record.success_rate * (record.usage_count - 1) + 1) / record.usage_count
            else:
                record.success_rate = (record.success_rate * (record.usage_count - 1) + 0) / record.usage_count
            record.confidence = record.success_rate # Simplified for now
            
            self.add_knowledge(record) # Update the record

    def get_ranked_knowledge(self, limit: int = 10) -> List[KnowledgeRecord]:
        with self._get_conn() as conn:
            cursor = conn.execute("SELECT * FROM knowledge_records ORDER BY confidence DESC, success_rate DESC, last_used DESC, usage_count DESC LIMIT ?", (limit,))
            return [
                KnowledgeRecord(
                    problem_signature=row[0], root_cause=row[1], action_taken=row[2],
                    outcome=row[3], confidence=row[4], success_rate=row[5],
                    created_at=row[6], last_used=row[7], usage_count=row[8]
                ) for row in cursor.fetchall()
            ]

    def explain_knowledge(self, record: KnowledgeRecord) -> str:
        return f"Esta solução para \'{record.problem_signature}\' possui {record.success_rate:.2%} de sucesso em {record.usage_count} ocorrências semelhantes, com confiança de {record.confidence:.2%}."

    def recognize_failure_patterns(self, min_occurrences: int = 15) -> List[Dict[str, Any]]:
        with self._get_conn() as conn:
            cursor = conn.execute("SELECT problem_signature, usage_count, success_rate FROM knowledge_records WHERE usage_count >= ? ORDER BY usage_count DESC", (min_occurrences,))
            patterns = []
            for row in cursor.fetchall():
                patterns.append({
                    "problem_signature": row[0],
                    "usage_count": row[1],
                    "success_rate": row[2]
                })
            return patterns
