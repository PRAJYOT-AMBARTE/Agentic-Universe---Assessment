"""High-Throughput Ingestion Engine for Simulator Event Chunks."""
from __future__ import annotations

import datetime as dt
import json
import logging
from typing import Any, Callable, Optional

from .client import SimulatorClient
from .db import Database

logger = logging.getLogger("controller.ingest")

BASE_DATE = dt.date(2027, 1, 4)


def parse_sim_day_and_hour(ts: str) -> tuple[int, int]:
    """Parse ISO timestamp into sim_day (relative to 2027-01-04) and hour-of-day."""
    try:
        date_str, time_str = ts.split("T")
        parts = date_str.split("-")
        y, m, d = int(parts[0]), int(parts[1]), int(parts[2])
        sim_day = (dt.date(y, m, d) - BASE_DATE).days
        hour = int(time_str.split(":")[0])
        return sim_day, hour
    except Exception:
        return 0, 12


class EventIngestor:
    """Consumes NDJSON event chunks, aggregates metrics into DB, and handles checkpoints."""

    def __init__(self, client: SimulatorClient, db: Database):
        self.client = client
        self.db = db
        self.person_success_hours: dict[str, dict[int, int]] = {}

    def get_last_ingested_chunk(self) -> int:
        val = self.db.get_meta("last_ingested_chunk", "-1")
        return int(val) if val is not None else -1

    def ingest_history(self):
        """Bootstrap statistics from historical chunks available before D0."""
        last = self.get_last_ingested_chunk()
        history_chunks = self.client.list_chunks(kind="history", after=last)
        if not history_chunks:
            return
        logger.info(f"Ingesting {len(history_chunks)} historical event chunks...")
        for ch in history_chunks:
            self._process_chunk(ch["chunk"])

    def ingest_new_chunks(self, new_chunks: list[dict[str, Any]], on_event: Optional[Callable[[dict[str, Any]], None]] = None):
        """Process any new chunks returned by advancing the simulation."""
        for ch in new_chunks:
            chunk_no = ch.get("chunk", ch) if isinstance(ch, dict) else ch
            self._process_chunk(chunk_no, on_event)

    def _process_chunk(self, chunk_no: int, on_event: Optional[Callable[[dict[str, Any]], None]] = None):
        calls_batch: list[dict[str, Any]] = []

        for line in self.client.iter_chunk_lines(chunk_no):
            ev = json.loads(line)
            ev_type = ev.get("type")

            if ev_type == "call":
                sim_day, hour = parse_sim_day_and_hour(ev.get("ts", ""))
                ev["sim_day"] = sim_day
                ev["hour"] = hour
                calls_batch.append(ev)

                # Track preferred hours for returning persons
                if ev.get("connected") and ev.get("person_id"):
                    pid = ev["person_id"]
                    if pid not in self.person_success_hours:
                        self.person_success_hours[pid] = {}
                    self.person_success_hours[pid][hour] = self.person_success_hours[pid].get(hour, 0) + 1

            elif ev_type == "config_changed":
                actor = ev.get("actor", "unknown")
                wid = ev.get("workflow_id", "")
                version = ev.get("version", 0)
                changed_dims = ev.get("changed_dims", [])
                summary = f"Config changed to v{version} by {actor} (dims: {', '.join(changed_dims)})"
                self.db.log_audit(
                    sim_minute=0,
                    ts=ev.get("ts", ""),
                    workflow_id=wid,
                    event_type="config_changed",
                    actor=actor,
                    summary=summary,
                    details=ev
                )

            elif ev_type == "approval_decided":
                aid = ev.get("approval_id", "")
                wid = ev.get("workflow_id", "")
                status = ev.get("status", "")
                reasons = ev.get("reasons", [])
                summary = f"Approval {aid} {status}"
                if reasons:
                    summary += f" ({'; '.join(reasons)})"
                self.db.log_audit(
                    sim_minute=0,
                    ts=ev.get("ts", ""),
                    workflow_id=wid,
                    event_type="approval_decided",
                    actor="client_approver",
                    summary=summary,
                    details=ev
                )
                self.db.update_proposal_status(
                    proposal_id=ev.get("proposal_id", aid),
                    status=status,
                    approval_id=aid
                )

            if on_event:
                on_event(ev)

        if calls_batch:
            self.db.record_call_events_batch(calls_batch)
            calls_batch.clear()

        self.db.set_meta("last_ingested_chunk", str(chunk_no))
