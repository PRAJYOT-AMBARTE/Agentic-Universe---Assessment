"""SQLite State & Audit Store for Crash-Safe Controller Operation."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Optional


class Database:
    """Manages transactional state persistence and audit logging."""

    def __init__(self, db_path: str | Path = "controller_state.db"):
        self.db_path = Path(db_path)
        self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self._init_db()

    def _init_db(self):
        with self.conn:
            self.conn.execute("PRAGMA journal_mode = WAL;")
            self.conn.execute("PRAGMA synchronous = NORMAL;")
            
            # Metadata checkpoint table
            self.conn.execute("""
                CREATE TABLE IF NOT EXISTS meta (
                    key TEXT PRIMARY KEY,
                    value TEXT
                )
            """)

            # Audit log table
            self.conn.execute("""
                CREATE TABLE IF NOT EXISTS audit_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    sim_minute INTEGER,
                    ts TEXT,
                    workflow_id TEXT,
                    event_type TEXT,
                    actor TEXT,
                    summary TEXT,
                    details TEXT
                )
            """)
            self.conn.execute("CREATE INDEX IF NOT EXISTS idx_audit_wf_ts ON audit_log (workflow_id, sim_minute);")

            # Proposals & Approvals tracking table
            self.conn.execute("""
                CREATE TABLE IF NOT EXISTS proposals (
                    proposal_id TEXT PRIMARY KEY,
                    approval_id TEXT,
                    workflow_id TEXT NOT NULL,
                    base_version INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    created_minute INTEGER NOT NULL,
                    decided_minute INTEGER,
                    expires_minute INTEGER,
                    proposed_config TEXT NOT NULL,
                    change_summary TEXT NOT NULL,
                    rationale TEXT NOT NULL,
                    diff TEXT,
                    impact_score REAL,
                    affected_leads INTEGER,
                    evidence TEXT,
                    applied_version INTEGER
                )
            """)
            self.conn.execute("CREATE INDEX IF NOT EXISTS idx_proposals_wf_status ON proposals (workflow_id, status);")

            # Daily variant statistics: workflow x cohort x dim x variant x day
            self.conn.execute("""
                CREATE TABLE IF NOT EXISTS daily_variant_stats (
                    workflow_id TEXT NOT NULL,
                    cohort_id TEXT NOT NULL,
                    dim TEXT NOT NULL,
                    variant TEXT NOT NULL,
                    sim_day INTEGER NOT NULL,
                    dials INTEGER DEFAULT 0,
                    connected INTEGER DEFAULT 0,
                    engaged INTEGER DEFAULT 0,
                    hallucinations INTEGER DEFAULT 0,
                    PRIMARY KEY (workflow_id, cohort_id, dim, variant, sim_day)
                )
            """)

            # DID / Caller ID statistics: workflow x did x day
            self.conn.execute("""
                CREATE TABLE IF NOT EXISTS did_stats (
                    workflow_id TEXT NOT NULL,
                    did TEXT NOT NULL,
                    sim_day INTEGER NOT NULL,
                    dials INTEGER DEFAULT 0,
                    connected INTEGER DEFAULT 0,
                    PRIMARY KEY (workflow_id, did, sim_day)
                )
            """)

            # Hour-of-day response statistics: workflow x cohort x hour
            self.conn.execute("""
                CREATE TABLE IF NOT EXISTS hour_stats (
                    workflow_id TEXT NOT NULL,
                    cohort_id TEXT NOT NULL,
                    hour INTEGER NOT NULL,
                    dials INTEGER DEFAULT 0,
                    connected INTEGER DEFAULT 0,
                    PRIMARY KEY (workflow_id, cohort_id, hour)
                )
            """)

            # Prompt QA statistics: workflow x prompt_version x day
            self.conn.execute("""
                CREATE TABLE IF NOT EXISTS prompt_qa_stats (
                    workflow_id TEXT NOT NULL,
                    prompt_version TEXT NOT NULL,
                    sim_day INTEGER NOT NULL,
                    connected INTEGER DEFAULT 0,
                    hallucinations INTEGER DEFAULT 0,
                    PRIMARY KEY (workflow_id, prompt_version, sim_day)
                )
            """)

            # Workflow current state tracker
            self.conn.execute("""
                CREATE TABLE IF NOT EXISTS workflow_state (
                    workflow_id TEXT PRIMARY KEY,
                    current_version INTEGER,
                    last_applied_minute INTEGER,
                    last_auto_applied_minute INTEGER,
                    last_proposal_minute INTEGER,
                    active_config TEXT
                )
            """)

    def close(self):
        self.conn.close()

    # Meta getters/setters
    def get_meta(self, key: str, default: Optional[str] = None) -> Optional[str]:
        cur = self.conn.execute("SELECT value FROM meta WHERE key = ?", (key,))
        row = cur.fetchone()
        return row["value"] if row else default

    def set_meta(self, key: str, value: str):
        with self.conn:
            self.conn.execute("INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)", (key, str(value)))

    # Audit logging
    def log_audit(self, sim_minute: int, ts: str, workflow_id: str, event_type: str, actor: str, summary: str, details: Any):
        details_str = json.dumps(details) if not isinstance(details, str) else details
        with self.conn:
            self.conn.execute(
                """INSERT INTO audit_log (sim_minute, ts, workflow_id, event_type, actor, summary, details)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (sim_minute, ts, workflow_id, event_type, actor, summary, details_str)
            )

    def query_audit_log(self, workflow_id: Optional[str] = None, limit: int = 50) -> list[dict[str, Any]]:
        query = "SELECT * FROM audit_log"
        params = []
        if workflow_id:
            query += " WHERE workflow_id = ?"
            params.append(workflow_id)
        query += " ORDER BY id DESC LIMIT ?"
        params.append(limit)
        cur = self.conn.execute(query, tuple(params))
        return [dict(row) for row in cur.fetchall()]

    # Proposals
    def record_proposal(self, p: dict[str, Any]):
        with self.conn:
            self.conn.execute(
                """INSERT OR REPLACE INTO proposals (
                    proposal_id, approval_id, workflow_id, base_version, status,
                    created_minute, decided_minute, expires_minute, proposed_config,
                    change_summary, rationale, diff, impact_score, affected_leads, evidence, applied_version
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    p["proposal_id"],
                    p.get("approval_id"),
                    p["workflow_id"],
                    p["base_version"],
                    p.get("status", "pending"),
                    p["created_minute"],
                    p.get("decided_minute"),
                    p.get("expires_minute"),
                    json.dumps(p["proposed_config"]),
                    p["change_summary"],
                    p["rationale"],
                    json.dumps(p.get("diff", {})),
                    p.get("impact_score", 0.0),
                    p.get("affected_leads", 0),
                    json.dumps(p.get("evidence")) if p.get("evidence") else None,
                    p.get("applied_version")
                )
            )

    def update_proposal_status(self, proposal_id: str, status: str, **kwargs):
        set_clauses = ["status = ?"]
        params = [status]
        for k, v in kwargs.items():
            set_clauses.append(f"{k} = ?")
            params.append(json.dumps(v) if isinstance(v, (dict, list)) else v)
        params.append(proposal_id)
        with self.conn:
            self.conn.execute(f"UPDATE proposals SET {', '.join(set_clauses)} WHERE proposal_id = ?", tuple(params))

    def get_pending_proposals(self, workflow_id: Optional[str] = None) -> list[dict[str, Any]]:
        query = "SELECT * FROM proposals WHERE status = 'pending'"
        params = []
        if workflow_id:
            query += " AND workflow_id = ?"
            params.append(workflow_id)
        cur = self.conn.execute(query, tuple(params))
        out = []
        for r in cur.fetchall():
            d = dict(r)
            d["proposed_config"] = json.loads(d["proposed_config"])
            d["diff"] = json.loads(d["diff"]) if d["diff"] else {}
            if d["evidence"]:
                d["evidence"] = json.loads(d["evidence"])
            out.append(d)
        return out

    def get_proposals_in_last_24h(self, workflow_id: str, current_minute: int) -> int:
        cur = self.conn.execute(
            "SELECT COUNT(*) as cnt FROM proposals WHERE workflow_id = ? AND created_minute > ?",
            (workflow_id, current_minute - 1440)
        )
        row = cur.fetchone()
        return row["cnt"] if row else 0

    # Ingestion Batch Upserts
    def record_call_events_batch(self, events: list[dict[str, Any]]):
        """Batch update call statistics for variants, DIDs, hours, and prompt QA."""
        if not events:
            return
        
        variant_updates: dict[tuple, list[int]] = {}  # (wf, cohort, dim, var, day) -> [dials, conn, eng, hal]
        did_updates: dict[tuple, list[int]] = {}      # (wf, did, day) -> [dials, conn]
        hour_updates: dict[tuple, list[int]] = {}     # (wf, cohort, hour) -> [dials, conn]
        qa_updates: dict[tuple, list[int]] = {}       # (wf, pv, day) -> [conn, hal]

        for ev in events:
            wid = ev["workflow_id"]
            cohort = ev.get("cohort_id", "default")
            day = ev.get("sim_day", 0)
            connected = 1 if ev.get("connected") else 0
            engaged = 1 if ev.get("engaged") else 0
            var = ev.get("variant", {})
            hour = ev.get("hour", 12)

            qa = ev.get("qa")
            halluc = 1 if (qa and qa.get("hallucination_flag")) else 0

            # 1. Variant stats across dimensions
            for dim in ("welcome_message", "voice"):
                val = var.get(dim)
                if val:
                    key = (wid, cohort, dim, val, day)
                    if key not in variant_updates:
                        variant_updates[key] = [0, 0, 0, 0]
                    variant_updates[key][0] += 1
                    variant_updates[key][1] += connected
                    variant_updates[key][2] += engaged
                    variant_updates[key][3] += halluc

            # 2. DID stats
            did = var.get("caller_id")
            if did:
                key = (wid, did, day)
                if key not in did_updates:
                    did_updates[key] = [0, 0]
                did_updates[key][0] += 1
                did_updates[key][1] += connected

            # 3. Hour stats
            key = (wid, cohort, hour)
            if key not in hour_updates:
                hour_updates[key] = [0, 0]
            hour_updates[key][0] += 1
            hour_updates[key][1] += connected

            # 4. Prompt QA stats
            pv = var.get("prompt_version")
            if pv and connected:
                key = (wid, pv, day)
                if key not in qa_updates:
                    qa_updates[key] = [0, 0]
                qa_updates[key][0] += 1
                qa_updates[key][1] += halluc

        with self.conn:
            # Upsert variants
            self.conn.executemany("""
                INSERT INTO daily_variant_stats (workflow_id, cohort_id, dim, variant, sim_day, dials, connected, engaged, hallucinations)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(workflow_id, cohort_id, dim, variant, sim_day) DO UPDATE SET
                    dials = dials + excluded.dials,
                    connected = connected + excluded.connected,
                    engaged = engaged + excluded.engaged,
                    hallucinations = hallucinations + excluded.hallucinations
            """, [(k[0], k[1], k[2], k[3], k[4], v[0], v[1], v[2], v[3]) for k, v in variant_updates.items()])

            # Upsert DIDs
            self.conn.executemany("""
                INSERT INTO did_stats (workflow_id, did, sim_day, dials, connected)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(workflow_id, did, sim_day) DO UPDATE SET
                    dials = dials + excluded.dials,
                    connected = connected + excluded.connected
            """, [(k[0], k[1], k[2], v[0], v[1]) for k, v in did_updates.items()])

            # Upsert Hours
            self.conn.executemany("""
                INSERT INTO hour_stats (workflow_id, cohort_id, hour, dials, connected)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(workflow_id, cohort_id, hour) DO UPDATE SET
                    dials = dials + excluded.dials,
                    connected = connected + excluded.connected
            """, [(k[0], k[1], k[2], v[0], v[1]) for k, v in hour_updates.items()])

            # Upsert QA
            self.conn.executemany("""
                INSERT INTO prompt_qa_stats (workflow_id, prompt_version, sim_day, connected, hallucinations)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(workflow_id, prompt_version, sim_day) DO UPDATE SET
                    connected = connected + excluded.connected,
                    hallucinations = hallucinations + excluded.hallucinations
            """, [(k[0], k[1], k[2], v[0], v[1]) for k, v in qa_updates.items()])

    # Analytics queries
    def get_variant_totals(self, workflow_id: str, cohort_id: str, dim: str, min_day: int = 0) -> dict[str, dict[str, int]]:
        cur = self.conn.execute("""
            SELECT variant, SUM(dials) as d, SUM(connected) as c, SUM(engaged) as e, SUM(hallucinations) as h
            FROM daily_variant_stats
            WHERE workflow_id = ? AND cohort_id = ? AND dim = ? AND sim_day >= ?
            GROUP BY variant
        """, (workflow_id, cohort_id, dim, min_day))
        out = {}
        for row in cur.fetchall():
            out[row["variant"]] = {
                "dials": row["d"] or 0,
                "connected": row["c"] or 0,
                "engaged": row["e"] or 0,
                "hallucinations": row["h"] or 0
            }
        return out

    def get_recent_did_health(self, workflow_id: str, min_day: int) -> dict[str, dict[str, float]]:
        cur = self.conn.execute("""
            SELECT did, SUM(dials) as d, SUM(connected) as c
            FROM did_stats
            WHERE workflow_id = ? AND sim_day >= ?
            GROUP BY did
        """, (workflow_id, min_day))
        out = {}
        for row in cur.fetchall():
            d = row["d"] or 0
            c = row["c"] or 0
            out[row["did"]] = {
                "dials": d,
                "connected": c,
                "pickup_rate": c / d if d > 0 else 0.0
            }
        return out

    def get_recent_prompt_qa(self, workflow_id: str, min_day: int) -> dict[str, dict[str, float]]:
        cur = self.conn.execute("""
            SELECT prompt_version, SUM(connected) as c, SUM(hallucinations) as h
            FROM prompt_qa_stats
            WHERE workflow_id = ? AND sim_day >= ?
            GROUP BY prompt_version
        """, (workflow_id, min_day))
        out = {}
        for row in cur.fetchall():
            c = row["c"] or 0
            h = row["h"] or 0
            out[row["prompt_version"]] = {
                "connected": c,
                "hallucinations": h,
                "hallucination_rate": h / c if c > 0 else 0.0
            }
        return out

    def get_hourly_pickup_distribution(self, workflow_id: str, cohort_id: str) -> dict[int, float]:
        cur = self.conn.execute("""
            SELECT hour, SUM(dials) as d, SUM(connected) as c
            FROM hour_stats
            WHERE workflow_id = ? AND cohort_id = ?
            GROUP BY hour
        """, (workflow_id, cohort_id))
        out = {}
        for row in cur.fetchall():
            d = row["d"] or 0
            c = row["c"] or 0
            out[row["hour"]] = c / d if d > 0 else 0.0
        return out
