"""Incident Response: Automated Mitigation for Prompt Hallucinations and Spam-Flagged DIDs."""
from __future__ import annotations

import copy
import logging
from typing import Any, Optional

from .analytics import AnalyticsEngine
from .client import SimulatorClient
from .db import Database
from .governance import GovernanceEngine
from .models import step_towards_distribution

logger = logging.getLogger("controller.incidents")


class IncidentManager:
    """Detects and coordinates emergency mitigation for quality and reachability incidents."""

    def __init__(
        self,
        client: SimulatorClient,
        db: Database,
        analytics: AnalyticsEngine,
        governance: GovernanceEngine
    ):
        self.client = client
        self.db = db
        self.analytics = analytics
        self.governance = governance
        self.active_incident_prompts: dict[str, str] = {}  # wid -> prompt_version currently mitigating

    def handle_hallucination_incidents(
        self,
        workflow_spec: dict[str, Any],
        current_version: int,
        current_config: dict[str, Any],
        sim_minute: int,
        sim_hour: int
    ) -> Optional[dict[str, Any]]:
        """Detect prompt hallucination surges and execute LLM fix -> validation -> approval pipeline."""
        wid = workflow_spec["workflow_id"]
        sim_day = sim_minute // 1440
        hal_check = self.analytics.check_prompt_hallucinations(wid, sim_day, min_connected=60)

        if not hal_check["incident"]:
            return None

        spike = hal_check["spikes"][0]
        cur_pv = spike["prompt_version"]
        rate = spike["rate"]

        # Only trigger if current config is using this prompt and not already under mitigation
        if current_config.get("prompt_version") != cur_pv:
            return None
        if self.active_incident_prompts.get(wid) == cur_pv:
            return None

        logger.warning(
            f"Incident on {wid}: prompt {cur_pv} hallucination rate at {rate:.2%} "
            f"(95% lower bound: {spike['lower_bound']:.2%})"
        )

        sim_state = self.client.get_sim_state()
        credits = sim_state.get("credits_remaining", 0)
        if credits < 5:
            logger.error(f"Insufficient credits ({credits}) to run LLM fix and validation")
            return None

        # 1. Ask LLM for fix suggestions
        problem_desc = f"Prompt {cur_pv} has excessive QA hallucinations at {rate:.2%}"
        llm_res = self.client.suggest_fixes(wid, problem_desc)
        suggestions = llm_res.get("suggestions", [])
        if not suggestions:
            logger.warning(f"No LLM fix suggestions returned for {wid}")
            return None

        self.active_incident_prompts[wid] = cur_pv

        # 2. Validate suggestions synthetic safety
        gov_spec = workflow_spec.get("governance", {})
        min_pass = gov_spec.get("min_validation_pass_rate", 0.97)

        best_cand = None
        best_run_id = None
        best_pass_rate = -1.0

        for cand in suggestions[:2]:
            cand_pv = cand["prompt_version"]
            val_res = self.client.run_validation(wid, cand_pv, n=100)
            p_rate = val_res.get("pass_rate", 0.0)
            run_id = val_res.get("validation_run_id")
            logger.info(f"Validated candidate {cand_pv}: pass rate {p_rate:.3f} (threshold: {min_pass})")

            if p_rate >= min_pass and p_rate > best_pass_rate:
                best_pass_rate = p_rate
                best_cand = cand_pv
                best_run_id = run_id

        if not best_cand:
            logger.warning(f"No candidate passed safety validation threshold ({min_pass})")
            return None

        # 3. Formulate proposed config
        new_cfg = copy.deepcopy(current_config)
        new_cfg["prompt_version"] = best_cand

        summary = f"Emergency fix for hallucination spike: switch {cur_pv} -> {best_cand}"
        rationale = (
            f"Observed hallucination rate {rate:.2%} on {cur_pv} (lower bound {spike['lower_bound']:.2%}). "
            f"Selected candidate {best_cand} verified with {best_pass_rate:.1%} synthetic validation pass rate."
        )

        res = self.governance.submit_change(
            workflow_spec=workflow_spec,
            current_version=current_version,
            current_config=current_config,
            proposed_config=new_cfg,
            summary=summary,
            rationale=rationale,
            impact_score=0.95,
            affected_leads=workflow_spec.get("daily_batch", {}).get("size", 1000),
            dry_run={"prior_halluc_rate": rate, "validation_pass_rate": best_pass_rate, "expected_safe": True},
            sim_minute=sim_minute,
            sim_hour=sim_hour,
            evidence={"validation_run_id": best_run_id}
        )

        self.db.log_audit(
            sim_minute=sim_minute,
            ts=f"D{sim_day} {sim_hour:02d}:00",
            workflow_id=wid,
            event_type="incident_hallucination_mitigation",
            actor="controller_incident_responder",
            summary=f"Incident response: proposed {best_cand} (pass rate: {best_pass_rate:.1%})",
            details={"prior_prompt": cur_pv, "new_prompt": best_cand, "result": res}
        )
        return res

    def handle_caller_id_degradation(
        self,
        workflow_spec: dict[str, Any],
        current_version: int,
        current_config: dict[str, Any],
        sim_minute: int,
        sim_hour: int
    ) -> Optional[dict[str, Any]]:
        """Detect spam-flagged caller IDs and shift traffic away to healthy DIDs."""
        wid = workflow_spec["workflow_id"]
        sim_day = sim_minute // 1440
        health = self.analytics.check_caller_id_health(wid, sim_day, lookback_days=2, min_dials=80)

        flagged = health["flagged"]
        if not flagged:
            return None

        healthy = health["healthy"]
        if not healthy:
            all_opts = workflow_spec.get("options", {}).get("caller_id", [])
            healthy = [d for d in all_opts if d not in flagged]
            if not healthy:
                return None

        # Build target distribution among healthy DIDs
        healthy_weight = round(1.0 / len(healthy), 4)
        target_did_alloc = {did: healthy_weight for did in healthy}

        new_cfg = copy.deepcopy(current_config)
        allocations = new_cfg.setdefault("allocations", {})
        gov = workflow_spec.get("governance", {})
        auto_pol = gov.get("auto_apply", {})
        can_auto_did = auto_pol.get("enabled") and "caller_id" in auto_pol.get("allowed_dims", [])
        max_shift = auto_pol.get("max_shift", 0.0) if can_auto_did else 1.0

        changed = False
        default_cur_did = allocations.get("default", {}).get("caller_id", {})

        cohort_keys = list(allocations.keys()) if allocations else ["default"]
        for cid in cohort_keys:
            c_alloc = allocations.setdefault(cid, {})
            cur_did = c_alloc.get("caller_id") or default_cur_did or {d: 1.0 / len(healthy) for d in healthy}
            has_flagged = any(f in cur_did and cur_did[f] > 0.01 for f in flagged)

            if has_flagged:
                if can_auto_did and max_shift > 0:
                    stepped = step_towards_distribution(cur_did, target_did_alloc, max_shift)
                    c_alloc["caller_id"] = stepped
                else:
                    c_alloc["caller_id"] = copy.deepcopy(target_did_alloc)
                changed = True

        if not changed:
            return None

        summary = f"Rotate degraded caller IDs: withdraw {', '.join(flagged)}, route to {', '.join(healthy)}"
        rationale = f"Detected pickup degradation on {', '.join(flagged)}. Reallocating traffic to healthy pool."

        res = self.governance.submit_change(
            workflow_spec=workflow_spec,
            current_version=current_version,
            current_config=current_config,
            proposed_config=new_cfg,
            summary=summary,
            rationale=rationale,
            impact_score=0.75,
            affected_leads=workflow_spec.get("daily_batch", {}).get("size", 1000),
            dry_run={"flagged_dids": flagged, "healthy_dids": healthy, "expected_pickup_recovery": True},
            sim_minute=sim_minute,
            sim_hour=sim_hour
        )

        self.db.log_audit(
            sim_minute=sim_minute,
            ts=f"D{sim_day} {sim_hour:02d}:00",
            workflow_id=wid,
            event_type="incident_caller_id_mitigation",
            actor="controller_incident_responder",
            summary=summary,
            details={"flagged": flagged, "healthy": healthy, "result": res}
        )
        return res
