"""HTTP API Client for the Outcome-Loop Simulator."""
from __future__ import annotations

import logging
from typing import Any, Iterator
import httpx

logger = logging.getLogger("controller.client")


class SimulatorClient:
    """Robust client communicating with the Simulator HTTP API."""

    def __init__(self, base_url: str = "http://127.0.0.1:8700", timeout: float = 120.0):
        self.base_url = base_url.rstrip("/")
        self.client = httpx.Client(base_url=self.base_url, timeout=timeout)

    def close(self):
        self.client.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def get_health(self) -> dict[str, Any]:
        resp = self.client.get("/health")
        resp.raise_for_status()
        return resp.json()

    def get_sim_state(self) -> dict[str, Any]:
        resp = self.client.get("/sim/state")
        resp.raise_for_status()
        return resp.json()

    def advance_sim(self, minutes: int = 15) -> dict[str, Any]:
        resp = self.client.post("/sim/advance", json={"minutes": minutes})
        resp.raise_for_status()
        return resp.json()

    def list_chunks(self, kind: str = "events", after: int = -1) -> list[dict[str, Any]]:
        resp = self.client.get("/events/chunks", params={"kind": kind, "after": after})
        resp.raise_for_status()
        return resp.json()

    def iter_chunk_lines(self, chunk_no: int) -> Iterator[str]:
        with self.client.stream("GET", f"/events/chunks/{chunk_no}") as resp:
            resp.raise_for_status()
            for line in resp.iter_lines():
                if line and line.strip():
                    yield line

    def get_workflows(self) -> list[dict[str, Any]]:
        resp = self.client.get("/workflows")
        resp.raise_for_status()
        return resp.json()

    def get_workflow(self, wid: str) -> dict[str, Any]:
        resp = self.client.get(f"/workflows/{wid}")
        resp.raise_for_status()
        return resp.json()

    def get_config(self, wid: str) -> dict[str, Any]:
        resp = self.client.get(f"/workflows/{wid}/config")
        resp.raise_for_status()
        return resp.json()

    def get_config_history(self, wid: str) -> list[dict[str, Any]]:
        resp = self.client.get(f"/workflows/{wid}/config/history")
        resp.raise_for_status()
        return resp.json()

    def auto_apply(self, wid: str, body: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        resp = self.client.put(f"/workflows/{wid}/config", json=body)
        return resp.status_code, resp.json()

    def request_approval(self, body: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        resp = self.client.post("/approvals", json=body)
        return resp.status_code, resp.json()

    def list_approvals(self, wid: str | None = None, status: str | None = None) -> list[dict[str, Any]]:
        params = {}
        if wid:
            params["workflow_id"] = wid
        if status:
            params["status"] = status
        resp = self.client.get("/approvals", params=params)
        resp.raise_for_status()
        return resp.json()

    def get_approval(self, aid: str) -> dict[str, Any]:
        resp = self.client.get(f"/approvals/{aid}")
        resp.raise_for_status()
        return resp.json()

    def apply_approval(self, wid: str, aid: str) -> tuple[int, dict[str, Any]]:
        resp = self.client.post(f"/workflows/{wid}/apply", json={"approval_id": aid})
        return resp.status_code, resp.json()

    def suggest_fixes(self, wid: str, problem: str) -> dict[str, Any]:
        resp = self.client.post("/llm/suggest-fixes", json={"workflow_id": wid, "problem": problem})
        resp.raise_for_status()
        return resp.json()

    def run_validation(self, wid: str, pv: str, n: int = 100) -> dict[str, Any]:
        resp = self.client.post("/validation/runs", json={"workflow_id": wid, "prompt_version": pv, "n": n})
        resp.raise_for_status()
        return resp.json()
