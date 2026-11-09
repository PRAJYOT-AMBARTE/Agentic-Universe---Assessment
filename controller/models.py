"""Core data structures and domain logic for cohorts and configurations."""
from __future__ import annotations

import copy
from typing import Any


def matches_cohort(features: dict[str, Any], where: dict[str, list[Any]]) -> bool:
    """Evaluate if a lead's features match a cohort's 'where' clause.
    
    Rule: AND across distinct feature keys, OR within the list of values for each key.
    """
    for key, allowed_vals in where.items():
        val = features.get(key)
        if val is None or val not in allowed_vals:
            return False
    return True


def assign_cohort(features: dict[str, Any], cohorts: list[dict[str, Any]]) -> str:
    """Find the first matching cohort id in order, or return 'default'."""
    for c in cohorts:
        cid = c.get("id")
        where = c.get("where", {})
        if cid and matches_cohort(features, where):
            return cid
    return "default"


def compute_config_diff(old_cfg: dict[str, Any], new_cfg: dict[str, Any]) -> dict[str, Any]:
    """Compute a human-readable diff dictionary between two configurations."""
    diff: dict[str, Any] = {}
    
    # Prompt version
    if old_cfg.get("prompt_version") != new_cfg.get("prompt_version"):
        diff["prompt_version"] = {
            "from": old_cfg.get("prompt_version"),
            "to": new_cfg.get("prompt_version")
        }
    
    # Cohorts
    if old_cfg.get("cohorts") != new_cfg.get("cohorts"):
        diff["cohorts"] = {
            "from": [c.get("id") for c in old_cfg.get("cohorts", [])],
            "to": [c.get("id") for c in new_cfg.get("cohorts", [])]
        }
        
    # Allocations
    old_alloc = old_cfg.get("allocations", {})
    new_alloc = new_cfg.get("allocations", {})
    all_cohorts = set(old_alloc.keys()) | set(new_alloc.keys())
    
    for cid in all_cohorts:
        old_c = old_alloc.get(cid, {})
        new_c = new_alloc.get(cid, {})
        for dim in ("welcome_message", "voice", "caller_id"):
            if old_c.get(dim) != new_c.get(dim):
                diff[f"allocations.{cid}.{dim}"] = {
                    "from": old_c.get(dim),
                    "to": new_c.get(dim)
                }

    # Schedule
    old_sched = old_cfg.get("schedule", {})
    new_sched = new_cfg.get("schedule", {})
    if old_sched.get("hour_weights") != new_sched.get("hour_weights"):
        diff["schedule.hour_weights"] = {
            "from": old_sched.get("hour_weights"),
            "to": new_sched.get("hour_weights")
        }
    if old_sched.get("lead_preferred_hour") != new_sched.get("lead_preferred_hour"):
        diff["schedule.lead_preferred_hour"] = {
            "count_from": len(old_sched.get("lead_preferred_hour", {})),
            "count_to": len(new_sched.get("lead_preferred_hour", {}))
        }

    return diff


def total_variation_distance(p: dict[str, float], q: dict[str, float]) -> float:
    """Compute Total Variation Distance between two categorical probability distributions."""
    all_keys = set(p.keys()) | set(q.keys())
    sum_p = sum(p.values()) or 1.0
    sum_q = sum(q.values()) or 1.0
    
    norm_p = {k: p.get(k, 0.0) / sum_p for k in all_keys}
    norm_q = {k: q.get(k, 0.0) / sum_q for k in all_keys}
    
    return 0.5 * sum(abs(norm_p[k] - norm_q[k]) for k in all_keys)


def step_towards_distribution(
    current: dict[str, float],
    target: dict[str, float],
    max_shift: float
) -> dict[str, float]:
    """Shift distribution towards target such that TV distance does not exceed max_shift."""
    tv = total_variation_distance(current, target)
    if tv <= max_shift + 1e-9:
        return copy.deepcopy(target)
    
    # Safe convex combination step (alpha < 1.0)
    # Slight safety margin (0.95) to prevent floating point rounding from breaching max_shift
    alpha = (max_shift * 0.95) / tv
    all_keys = set(current.keys()) | set(target.keys())
    
    # Normalise current and target
    sum_cur = sum(current.values()) or 1.0
    sum_tgt = sum(target.values()) or 1.0
    
    stepped = {}
    for k in all_keys:
        p = current.get(k, 0.0) / sum_cur
        q = target.get(k, 0.0) / sum_tgt
        val = (1.0 - alpha) * p + alpha * q
        stepped[k] = round(max(0.0, val), 4)

    # Re-normalize to exact sum 1.0
    total = sum(stepped.values())
    if total > 0:
        stepped = {k: round(v / total, 4) for k, v in stepped.items()}
    return stepped


def compute_max_shift(old_cfg: dict[str, Any], new_cfg: dict[str, Any]) -> float:
    """Compute the maximum total variation distance shift across all cohorts and allocation dimensions."""
    max_shift = 0.0
    old_alloc = old_cfg.get("allocations", {})
    new_alloc = new_cfg.get("allocations", {})
    all_cohorts = set(old_alloc.keys()) | set(new_alloc.keys())
    
    for cid in all_cohorts:
        old_c = old_alloc.get(cid, {})
        new_c = new_alloc.get(cid, {})
        for dim in ("welcome_message", "voice", "caller_id"):
            p = old_c.get(dim, {})
            q = new_c.get(dim, {})
            if p or q:
                tv = total_variation_distance(p, q)
                if tv > max_shift:
                    max_shift = tv
    return max_shift
