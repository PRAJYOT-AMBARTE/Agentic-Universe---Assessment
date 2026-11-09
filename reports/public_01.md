# Grade report — public_01_dev

## Outcomes vs baseline (no-op controller)

| workflow | conclusion rate | Δ | pickup | Δ | engagement | Δ | engagement gap captured | hallucinated calls (base) |
|---|---|---|---|---|---|---|---|---|
| ks_cancel | 0.341 | +2.4% | 0.238 | +0.0% | 0.498 | +1.5% | 8% | 65 (47) |
| nw_kyc | 0.403 | +10.9% | 0.238 | -1.5% | 0.652 | +10.4% | 50% | 14 (21) |
| nw_renewal | 0.416 | -1.0% | 0.255 | -3.2% | 0.562 | +3.0% | 18% | 45 (42) |
| ALL | 0.379 | +2.9% | 0.244 | -1.4% | 0.550 | +3.8% | 22% | 124 (110) |

## Changes applied by the controller

9 applied — beneficial: 5, neutral: 3, harmful: 1

- nw_kyc v2 (controller_approved) dims=['cohorts', 'welcome_message', 'voice'] engageΔ=+0.075 didΔ=+0.000 → **beneficial**
- ks_cancel v2 (controller_approved) dims=['cohorts', 'welcome_message', 'voice'] engageΔ=-0.002 didΔ=+0.000 → **neutral**
- nw_renewal v2 (controller_approved) dims=['cohorts', 'welcome_message', 'voice'] engageΔ=+0.067 didΔ=+0.000 → **beneficial**
- nw_kyc v3 (controller_approved) dims=['prompt_version'] engageΔ=+0.030 didΔ=+0.000 → **beneficial**
- nw_kyc v4 (controller_approved) dims=['voice'] engageΔ=+0.013 didΔ=+0.000 → **beneficial**
- nw_kyc v5 (controller_approved) dims=['welcome_message'] engageΔ=+0.009 didΔ=+0.000 → **neutral**
- ks_cancel v3 (controller_approved) dims=['welcome_message'] engageΔ=+0.030 didΔ=+0.000 → **beneficial**
- ks_cancel v4 (controller_approved) dims=['welcome_message'] engageΔ=+0.004 didΔ=+0.000 → **neutral**
- nw_kyc v6 (controller_approved) dims=['welcome_message'] engageΔ=-0.011 didΔ=+0.000 → **harmful**

## Governance

```
{
  "approval_requests": 12,
  "decisions": {
    "approved": 11,
    "rejected": 1,
    "expired": 0
  },
  "rejection_reasons": {
    "approver declined (judgement call)": 1
  },
  "applied_via_approval": 9,
  "auto_applied": 0,
  "auto_apply_rejected": 0,
  "apply_conflicts": 2,
  "lapsed": 0,
  "peak_requests_per_24h": {
    "nw_renewal": 1,
    "nw_kyc": 2,
    "ks_cancel": 2
  }
}
```

## Incidents

```
[]
```

## Decaying variants — share of in-population calls still on the variant, by day after onset

```
{
  "nw_renewal:welcome_message=W3": {
    "3": 0.329,
    "4": 0.322,
    "5": 0.335,
    "6": 0.329,
    "7": 0.321
  }
}
```

Credits used: 18 · validation runs: 6 · LLM fix calls: 4