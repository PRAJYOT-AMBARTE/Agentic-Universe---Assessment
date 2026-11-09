"""Statistical Analytics Engine: Confidence Intervals, Hypothesis Testing, and Anomaly Detection."""
from __future__ import annotations

import math
from typing import Any, Optional
from .db import Database


def wilson_score_interval(successes: int, trials: int, confidence: float = 0.95) -> tuple[float, float, float]:
    """Calculate the Wilson score interval for a Bernoulli proportion.
    
    Returns (center, lower_bound, upper_bound).
    """
    if trials <= 0:
        return 0.0, 0.0, 0.0
    
    # z for 95% confidence is 1.96
    z = 1.96 if confidence == 0.95 else 2.576  # 99%
    p_hat = successes / trials
    denom = 1.0 + (z ** 2) / trials
    center = (p_hat + (z ** 2) / (2 * trials)) / denom
    margin = (z * math.sqrt((p_hat * (1 - p_hat) / trials) + (z ** 2) / (4 * (trials ** 2)))) / denom
    
    return p_hat, max(0.0, center - margin), min(1.0, center + margin)


def two_sample_proportion_test(s1: int, n1: int, s2: int, n2: int) -> tuple[float, float]:
    """Two-sample z-test for difference in proportions (p1 vs p2).
    
    Returns (z_score, p_value).
    """
    if n1 <= 0 or n2 <= 0:
        return 0.0, 1.0
    
    p1 = s1 / n1
    p2 = s2 / n2
    p_pool = (s1 + s2) / (n1 + n2)
    
    if p_pool == 0 or p_pool == 1:
        return 0.0, 1.0
    
    se = math.sqrt(p_pool * (1.0 - p_pool) * (1.0 / n1 + 1.0 / n2))
    if se == 0:
        return 0.0, 1.0
    
    z = (p1 - p2) / se
    p_val = 0.5 * math.erfc(abs(z) / math.sqrt(2)) * 2  # two-sided
    return z, p_val


class AnalyticsEngine:
    """Evaluates metrics, caller ID health, prompt safety, and statistical significance."""

    def __init__(self, db: Database):
        self.db = db

    def evaluate_variants(
        self,
        workflow_id: str,
        cohort_id: str,
        dim: str,
        kpi_type: str = "engagement_rate",
        min_trials: int = 100,
        significance_level: float = 0.05
    ) -> dict[str, Any]:
        """Determine if any variant in the cohort significantly beats other variants."""
        # Use recent data (last 4 days) if sufficient, else all
        totals = self.db.get_variant_totals(workflow_id, cohort_id, dim, min_day=0)
        if not totals:
            return {"has_winner": False, "reason": "no data"}

        metrics: dict[str, dict[str, Any]] = {}
        for var, stats in totals.items():
            if kpi_type == "engagement_rate":
                trials = stats["connected"]
                successes = stats["engaged"]
            else:
                trials = stats["dials"]
                successes = stats["connected"]

            rate, lower, upper = wilson_score_interval(successes, trials)
            metrics[var] = {
                "trials": trials,
                "successes": successes,
                "rate": rate,
                "lower": lower,
                "upper": upper,
                "hallucinations": stats["hallucinations"]
            }

        eligible = {v: m for v, m in metrics.items() if m["trials"] >= min_trials}
        if len(eligible) < 2:
            return {
                "has_winner": False,
                "reason": f"insufficient samples (need >= {min_trials} per variant)",
                "metrics": metrics
            }

        best_var = max(eligible.keys(), key=lambda v: eligible[v]["rate"])
        best_metric = eligible[best_var]

        num_comparisons = len(eligible) - 1
        alpha_corrected = significance_level / max(num_comparisons, 1)

        is_statistically_superior = True
        comparisons = {}

        for var, m in eligible.items():
            if var == best_var:
                continue
            z, p_val = two_sample_proportion_test(
                best_metric["successes"], best_metric["trials"],
                m["successes"], m["trials"]
            )
            comparisons[var] = {"z": round(z, 3), "p_value": round(p_val, 4)}
            # Candidate must have positive z and p_val < alpha_corrected
            if z <= 0 or p_val > alpha_corrected:
                is_statistically_superior = False

        return {
            "has_winner": is_statistically_superior,
            "winner": best_var if is_statistically_superior else None,
            "best_var": best_var,
            "metrics": metrics,
            "comparisons": comparisons
        }

    def check_caller_id_health(
        self,
        workflow_id: str,
        current_day: int,
        lookback_days: int = 2,
        min_dials: int = 80
    ) -> dict[str, Any]:
        """Detect caller IDs (DIDs) whose pickup rate has dropped severely (e.g. spam-flagged)."""
        min_day = max(0, current_day - lookback_days)
        did_health = self.db.get_recent_did_health(workflow_id, min_day)
        
        if not did_health:
            return {"flagged": [], "healthy": [], "details": {}}

        total_dials = sum(s["dials"] for s in did_health.values())
        total_conn = sum(s["connected"] for s in did_health.values())
        overall_pickup = total_conn / total_dials if total_dials > 0 else 0.30

        flagged = []
        healthy = []

        for did, stats in did_health.items():
            dials = stats["dials"]
            rate = stats["pickup_rate"]
            # A DID is flagged if it has sufficient dials and pickup rate is < 65% of overall average
            if dials >= min_dials and rate < overall_pickup * 0.65:
                flagged.append(did)
            else:
                healthy.append(did)

        return {
            "flagged": flagged,
            "healthy": healthy,
            "overall_pickup": round(overall_pickup, 4),
            "details": did_health
        }

    def check_prompt_hallucinations(
        self,
        workflow_id: str,
        current_day: int,
        min_connected: int = 60
    ) -> dict[str, Any]:
        """Statistically detect prompt versions experiencing a true surge in QA hallucination flags.
        
        Uses Wilson lower bound > 0.010 (1.0%) to prevent false positives from benign prompts (0.3% - 0.6%).
        """
        recent_qa = self.db.get_recent_prompt_qa(workflow_id, min_day=max(0, current_day - 1))
        spikes = []

        for pv, stats in recent_qa.items():
            conn = stats["connected"]
            halluc = stats["hallucinations"]
            if conn >= min_connected and halluc >= 3:
                rate, lower_bound, _ = wilson_score_interval(halluc, conn, confidence=0.95)
                # If 95% confident that true hallucination rate exceeds 1.0%
                if lower_bound > 0.010:
                    spikes.append({
                        "prompt_version": pv,
                        "connected": conn,
                        "hallucinations": halluc,
                        "rate": round(rate, 4),
                        "lower_bound": round(lower_bound, 4)
                    })

        return {
            "incident": len(spikes) > 0,
            "spikes": spikes
        }

    def check_variant_decay(
        self,
        workflow_id: str,
        cohort_id: str,
        dim: str,
        variant: str,
        current_day: int
    ) -> bool:
        """Check if an active variant has decayed in the last 2 days vs other variants or its earlier peak."""
        if current_day < 3:
            return False

        # Recent 2 days stats
        recent_stats = self.db.get_variant_totals(workflow_id, cohort_id, dim, min_day=max(0, current_day - 2))
        v_recent = recent_stats.get(variant)
        if not v_recent or v_recent["connected"] < 60:
            return False

        v_recent_rate = v_recent["engaged"] / v_recent["connected"]

        # Check against other variants in recent 2 days
        other_rates = [
            s["engaged"] / s["connected"]
            for v, s in recent_stats.items()
            if v != variant and s["connected"] >= 40
        ]

        if other_rates:
            max_other_rate = max(other_rates)
            # If recent engagement has fallen noticeably below alternative arms
            if v_recent_rate < max_other_rate * 0.90:
                return True

        # Check against its own prior performance (day 0 to day current_day - 2)
        all_stats = self.db.get_variant_totals(workflow_id, cohort_id, dim, min_day=0)
        v_all = all_stats.get(variant)
        if v_all and v_all["connected"] >= 150:
            all_rate = v_all["engaged"] / v_all["connected"]
            if v_recent_rate < all_rate * 0.85:
                return True

        return False
