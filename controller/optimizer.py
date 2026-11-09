"""Optimization Engine: Cohort Formation, Controlled Experimentation, and Schedule Optimization."""
from __future__ import annotations

import copy
import logging
from typing import Any, Optional

from .analytics import AnalyticsEngine
from .client import SimulatorClient
from .db import Database
from .governance import GovernanceEngine
from .models import compute_config_diff

logger = logging.getLogger("controller.optimizer")


class WorkflowOptimizer:
    """Orchestrates variant testing, cohort formation, schedule tuning, and decay rollbacks."""

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
        self.last_schedule_day: dict[str, int] = {}

    def get_standard_cohorts(self, workflow_spec: dict[str, Any]) -> list[dict[str, Any]]:
        """Construct a clean, shared set of demographic and linguistic cohorts."""
        langs = set(workflow_spec.get("languages", []))
        cohorts = []

        if "ta" in langs:
            cohorts.append({
                "id": "senior_ta",
                "where": {"age_band": ["60+"], "lang": ["ta"]}
            })
            cohorts.append({
                "id": "ta",
                "where": {"lang": ["ta"]}
            })

        if "hi" in langs:
            cohorts.append({
                "id": "senior_hi",
                "where": {"age_band": ["60+"], "lang": ["hi"]}
            })
            cohorts.append({
                "id": "hi",
                "where": {"lang": ["hi"]}
            })

        if "kn" in langs:
            cohorts.append({
                "id": "kn",
                "where": {"lang": ["kn"]}
            })

        cohorts.append({
            "id": "seniors",
            "where": {"age_band": ["60+"]}
        })
        cohorts.append({
            "id": "young",
            "where": {"age_band": ["18-30"]}
        })

        return cohorts[:15]

    def optimize_workflow(
        self,
        workflow_spec: dict[str, Any],
        current_version: int,
        current_config: dict[str, Any],
        sim_minute: int,
        sim_hour: int
    ) -> Optional[dict[str, Any]]:
        """Evaluate variants, form hypotheses, tune schedules, and submit proposals."""
        wid = workflow_spec["workflow_id"]
        sim_day = sim_minute // 1440
        options = workflow_spec.get("options", {})
        objective = workflow_spec.get("objective", {})
        primary_kpi = objective.get("primary", "engagement_rate")

        new_cfg = copy.deepcopy(current_config)

        # 1. Establish shared cohorts if not present
        if not new_cfg.get("cohorts"):
            new_cfg["cohorts"] = self.get_standard_cohorts(workflow_spec)

        allocations = new_cfg.setdefault("allocations", {})
        all_cohort_ids = [c["id"] for c in new_cfg.get("cohorts", [])] + ["default"]

        changed_dimensions = set()
        rationale_notes = []
        dry_run_details = {}

        # 2. Experiment & Optimize for each cohort across dimensions
        for cid in all_cohort_ids:
            c_alloc = allocations.setdefault(cid, {})

            for dim in ("welcome_message", "voice"):
                avail_variants = options.get(dim, [])
                if len(avail_variants) <= 1:
                    continue

                eval_res = self.analytics.evaluate_variants(
                    workflow_id=wid,
                    cohort_id=cid,
                    dim=dim,
                    kpi_type=primary_kpi,
                    min_trials=100,
                    significance_level=0.05
                )

                cur_dim_alloc = c_alloc.get(dim, {})

                if eval_res.get("has_winner"):
                    winner = eval_res["winner"]

                    # Check for decay on the winner
                    decayed = self.analytics.check_variant_decay(
                        workflow_id=wid,
                        cohort_id=cid,
                        dim=dim,
                        variant=winner,
                        current_day=sim_day
                    )

                    if decayed:
                        logger.warning(f"Decay detected on {wid}/{cid}/{dim}={winner}! Rolling back allocation.")
                        alt_variants = [v for v in avail_variants if v != winner]
                        weight = round(1.0 / len(alt_variants), 4)
                        c_alloc[dim] = {v: weight for v in alt_variants}
                        changed_dimensions.add(f"{cid}.{dim}")
                        rationale_notes.append(f"Rolled back decaying variant {winner} in {cid} for {dim}.")
                    else:
                        # Exploit winner (85%) with continuous exploration (15%)
                        target_alloc: dict[str, float] = {}
                        explore_pool = [v for v in avail_variants if v != winner]
                        explore_weight = round(0.15 / max(len(explore_pool), 1), 4) if explore_pool else 0.0

                        for v in avail_variants:
                            if v == winner:
                                target_alloc[v] = round(1.0 - (explore_weight * len(explore_pool)), 4)
                            else:
                                target_alloc[v] = explore_weight

                        # Check if target allocation differs meaningfully from current
                        if cur_dim_alloc != target_alloc:
                            c_alloc[dim] = target_alloc
                            changed_dimensions.add(f"{cid}.{dim}")
                            rationale_notes.append(
                                f"Promoted verified winner {winner} (85% traffic) in {cid} for {dim} (p < 0.05)."
                            )
                            dry_run_details[f"{cid}.{dim}"] = {
                                "winner": winner,
                                "winner_rate": eval_res["metrics"][winner]["rate"],
                                "comparisons": eval_res.get("comparisons", {})
                            }
                else:
                    # Still in exploration phase: uniform allocation if not exploring all arms
                    if not cur_dim_alloc or len(cur_dim_alloc) < len(avail_variants):
                        eq_weight = round(1.0 / len(avail_variants), 4)
                        target_alloc = {v: eq_weight for v in avail_variants}
                        if cur_dim_alloc != target_alloc:
                            c_alloc[dim] = target_alloc
                            changed_dimensions.add(f"{cid}.{dim}")
                            rationale_notes.append(f"Balanced exploration across all {dim} options in {cid}.")

        # 3. Schedule Tuning: Optimize hourly weights at most once per day after day 1
        dial_win = workflow_spec.get("dialling_window", [9, 21])
        start_h, end_h = dial_win
        sched = new_cfg.setdefault("schedule", {})
        hour_weights = sched.setdefault("hour_weights", {})

        if sim_day >= 2 and self.last_schedule_day.get(wid, -1) < sim_day:
            default_dist = self.db.get_hourly_pickup_distribution(wid, "default")
            if default_dist and len(default_dist) >= (end_h - start_h):
                avg_rate = sum(default_dist.values()) / max(len(default_dist), 1)
                target_weights = {}
                max_diff = 0.0
                cur_weights = hour_weights.get("default", {})

                for h in range(start_h, end_h):
                    h_str = str(h)
                    rate = default_dist.get(h, avg_rate)
                    multiplier = 1.0 + max(0.0, min(1.0, (rate - avg_rate) / max(avg_rate, 0.01))) if avg_rate > 0 else 1.0
                    multiplier = round(multiplier, 2)
                    target_weights[h_str] = multiplier
                    cur_val = cur_weights.get(h_str, 1.0)
                    diff = abs(multiplier - cur_val)
                    if diff > max_diff:
                        max_diff = diff

                if max_diff >= 0.20:
                    hour_weights["default"] = target_weights
                    changed_dimensions.add("schedule.hour_weights")
                    rationale_notes.append("Tuned hourly dial weights to emphasize peak responsiveness hours.")
                    self.last_schedule_day[wid] = sim_day

        diff = compute_config_diff(current_config, new_cfg)
        if not diff:
            return None

        summary = f"Optimization update: {', '.join(sorted(changed_dimensions))}"
        rationale = " ".join(rationale_notes) or "Routine statistical optimization update."
        impact_score = min(0.85, 0.35 + 0.1 * len(changed_dimensions))

        return self.governance.submit_change(
            workflow_spec=workflow_spec,
            current_version=current_version,
            current_config=current_config,
            proposed_config=new_cfg,
            summary=summary,
            rationale=rationale,
            impact_score=impact_score,
            affected_leads=workflow_spec.get("daily_batch", {}).get("size", 1000),
            dry_run=dry_run_details or {"note": "simulated cohort distribution updated"},
            sim_minute=sim_minute,
            sim_hour=sim_hour
        )
