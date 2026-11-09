"""Governance & Proposal Engine: Auto-Apply Validation, Approval Routing, and Lifecycle Management."""
from __future__ import annotations

import logging
import uuid
from typing import Any, Optional

from .client import SimulatorClient
from .db import Database
from .models import compute_config_diff, compute_max_shift

logger = logging.getLogger("controller.governance")


class GovernanceEngine:
    """Manages the governance lifecycle: auto-apply, approval requests, and policy compliance."""

    def __init__(self, client: SimulatorClient, db: Database):
        self.client = client
        self.db = db

    def can_auto_apply(
        self,
        workflow_spec: dict[str, Any],
        current_config: dict[str, Any],
        proposed_config: dict[str, Any]
    ) -> tuple[bool, str]:
        """Check if proposed change satisfies the workflow's auto-apply policy."""
        gov = workflow_spec.get("governance", {})
        auto_pol = gov.get("auto_apply", {})
        
        if not auto_pol.get("enabled"):
            return False, "auto-apply not enabled for workflow"

        allowed_dims = set(auto_pol.get("allowed_dims", []))
        diff = compute_config_diff(current_config, proposed_config)
        
        if not diff:
            return False, "no changes detected"

        # Check dimensions
        for key in diff.keys():
            dim_name = key.split(".")[0]
            if dim_name not in allowed_dims:
                return False, f"dimension '{dim_name}' not permitted for auto-apply"

        # Check total-variation shift
        shift = compute_max_shift(current_config, proposed_config)
        max_shift = auto_pol.get("max_shift", 0.0)
        if shift > max_shift + 1e-9:
            return False, f"shift {shift:.3f} exceeds max_shift {max_shift:.3f}"

        return True, "permitted"

    def submit_change(
        self,
        workflow_spec: dict[str, Any],
        current_version: int,
        current_config: dict[str, Any],
        proposed_config: dict[str, Any],
        summary: str,
        rationale: str,
        impact_score: float,
        affected_leads: int,
        dry_run: dict[str, Any],
        sim_minute: int,
        sim_hour: int,
        evidence: Optional[dict[str, Any]] = None
    ) -> dict[str, Any]:
        """Route a change via auto-apply if allowed, or submit an approval request."""
        wid = workflow_spec["workflow_id"]
        diff = compute_config_diff(current_config, proposed_config)
        if not diff:
            return {"action": "none", "reason": "empty diff"}

        proposal_id = f"prop_{uuid.uuid4().hex[:12]}"
        can_auto, auto_reason = self.can_auto_apply(workflow_spec, current_config, proposed_config)

        # 1. Try Auto-Apply
        if can_auto:
            body = {
                "proposal_id": proposal_id,
                "base_version": current_version,
                "proposed_config": proposed_config,
                "rationale": rationale,
                "evidence": evidence
            }
            status_code, res = self.client.auto_apply(wid, body)
            if status_code == 200:
                new_ver = res.get("version", current_version + 1)
                self.db.log_audit(
                    sim_minute=sim_minute,
                    ts=f"D{sim_minute // 1440} {sim_hour:02d}:00",
                    workflow_id=wid,
                    event_type="auto_apply",
                    actor="controller_auto",
                    summary=f"Auto-applied v{new_ver}: {summary}",
                    details={"proposal_id": proposal_id, "diff": diff, "rationale": rationale}
                )
                return {"action": "auto_applied", "version": new_ver, "proposal_id": proposal_id}
            else:
                logger.warning(f"Auto-apply rejected ({status_code}): {res}")

        # 2. Approval Request Path
        gov = workflow_spec.get("governance", {})
        approver_hours = gov.get("approver_hours", [10, 19])
        
        # Check approver working hours (don't propose during off-hours to avoid queue clutter)
        if sim_hour < approver_hours[0] or sim_hour >= approver_hours[1]:
            return {"action": "deferred", "reason": f"outside approver hours {approver_hours}"}

        # Check fatigue limit
        max_24h = gov.get("max_requests_per_24h", 3)
        recent_count = self.db.get_proposals_in_last_24h(wid, sim_minute)
        if recent_count >= max_24h:
            return {"action": "throttled", "reason": f"approver fatigue limit reached ({recent_count}/{max_24h} in 24h)"}

        # Check if prompt change needs evidence
        if "prompt_version" in diff and not evidence:
            return {"action": "blocked", "reason": "prompt changes require validation evidence"}

        req_body = {
            "proposal_id": proposal_id,
            "workflow_id": wid,
            "base_version": current_version,
            "proposed_config": proposed_config,
            "change_summary": summary,
            "diff": diff,
            "affected_leads": max(0, affected_leads),
            "dry_run": dry_run,
            "impact_score": min(1.0, max(0.0, impact_score)),
            "rationale": rationale,
            "evidence": evidence
        }

        status_code, res = self.client.request_approval(req_body)
        if status_code == 200:
            aid = res.get("approval_id")
            # Store in DB
            self.db.record_proposal({
                "proposal_id": proposal_id,
                "approval_id": aid,
                "workflow_id": wid,
                "base_version": current_version,
                "status": "pending",
                "created_minute": sim_minute,
                "proposed_config": proposed_config,
                "change_summary": summary,
                "rationale": rationale,
                "diff": diff,
                "impact_score": impact_score,
                "affected_leads": affected_leads,
                "evidence": evidence
            })
            self.db.log_audit(
                sim_minute=sim_minute,
                ts=f"D{sim_minute // 1440} {sim_hour:02d}:00",
                workflow_id=wid,
                event_type="approval_requested",
                actor="controller",
                summary=f"Requested approval {aid}: {summary}",
                details={"proposal_id": proposal_id, "diff": diff, "rationale": rationale}
            )
            return {"action": "requested", "approval_id": aid, "proposal_id": proposal_id}
        else:
            logger.warning(f"Proposal submission failed ({status_code}): {res}")
            return {"action": "failed", "status_code": status_code, "response": res}

    def reconcile_and_apply(self, wid: str, sim_minute: int) -> list[dict[str, Any]]:
        """Check status of pending approvals for workflow and apply approved ones before they lapse."""
        pending = self.db.get_pending_proposals(wid)
        applied_results = []

        for p in pending:
            aid = p.get("approval_id")
            if not aid:
                continue

            try:
                ap = self.client.get_approval(aid)
            except Exception as e:
                logger.error(f"Error fetching approval {aid}: {e}")
                continue

            status = ap.get("status")
            if status == "approved":
                # Apply now
                code, res = self.client.apply_approval(wid, aid)
                if code == 200:
                    v = res.get("version")
                    self.db.update_proposal_status(p["proposal_id"], "applied", applied_version=v)
                    self.db.log_audit(
                        sim_minute=sim_minute,
                        ts=f"D{sim_minute // 1440} {sim_minute % 1440 // 60:02d}:00",
                        workflow_id=wid,
                        event_type="approval_applied",
                        actor="controller_applied",
                        summary=f"Applied approval {aid} -> v{v}: {p['change_summary']}",
                        details={"approval_id": aid, "version": v}
                    )
                    applied_results.append({"approval_id": aid, "version": v, "status": "applied"})
                elif code == 409:
                    # Stale base version (e.g. supervisor edit happened)
                    logger.warning(f"Apply conflict for {aid}: {res}")
                    self.db.update_proposal_status(p["proposal_id"], "conflict")
                    self.db.log_audit(
                        sim_minute=sim_minute,
                        ts=f"D{sim_minute // 1440} {sim_minute % 1440 // 60:02d}:00",
                        workflow_id=wid,
                        event_type="apply_conflict",
                        actor="controller",
                        summary=f"Apply conflict for {aid} (stale base version)",
                        details=res
                    )
            elif status in ("rejected", "expired", "lapsed"):
                self.db.update_proposal_status(p["proposal_id"], status)
                self.db.log_audit(
                    sim_minute=sim_minute,
                    ts=f"D{sim_minute // 1440} {sim_minute % 1440 // 60:02d}:00",
                    workflow_id=wid,
                    event_type=f"approval_{status}",
                    actor="client_approver",
                    summary=f"Approval {aid} was {status}",
                    details=ap
                )

        return applied_results
