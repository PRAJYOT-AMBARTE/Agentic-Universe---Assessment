# Grade report — public_02_incidents

## Outcomes vs baseline (no-op controller)

| workflow | conclusion rate | Δ | pickup | Δ | engagement | Δ | engagement gap captured | hallucinated calls (base) |
|---|---|---|---|---|---|---|---|---|
| ks_cancel | 0.289 | +16.8% | 0.200 | +8.7% | 0.507 | +6.5% | 45% | 71 (330) |
| nw_kyc | 0.377 | +0.7% | 0.244 | +0.7% | 0.597 | +0.8% | -3% | 30 (31) |
| nw_renewal | 0.432 | +1.2% | 0.268 | +2.3% | 0.545 | -0.6% | 2% | 179 (55) |
| ALL | 0.355 | +6.4% | 0.232 | +4.4% | 0.540 | +2.0% | 24% | 280 (416) |

## Changes applied by the controller

19 applied — beneficial: 12, harmful: 4, neutral: 3

- ks_cancel v2 (controller_approved) dims=['prompt_version'] engageΔ=+0.031 didΔ=+0.000 → **beneficial**
- ks_cancel v3 (controller_approved) dims=['cohorts', 'welcome_message', 'voice'] engageΔ=+0.023 didΔ=+0.000 → **beneficial**
- nw_renewal v2 (controller_approved) dims=['cohorts', 'welcome_message', 'voice'] engageΔ=+0.040 didΔ=+0.000 → **beneficial**
- nw_kyc v2 (controller_approved) dims=['prompt_version'] engageΔ=+0.030 didΔ=+0.000 → **beneficial**
- nw_kyc v3 (controller_approved) dims=['cohorts', 'welcome_message', 'voice'] engageΔ=-0.020 didΔ=+0.000 → **harmful**
- nw_renewal v3 (controller_approved) dims=['welcome_message'] engageΔ=+0.036 didΔ=+0.000 → **beneficial**
- nw_renewal v4 (controller_approved) dims=['prompt_version'] engageΔ=+0.030 didΔ=+0.000 → **beneficial**
- ks_cancel v4 (controller_approved) dims=['prompt_version'] engageΔ=-0.165 didΔ=+0.000 → **harmful**
- ks_cancel v6 (controller_approved) dims=['prompt_version'] engageΔ=+0.102 didΔ=+0.000 → **beneficial**
- ks_cancel v7 (controller_approved) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.183 → **beneficial**
- nw_renewal v5 (controller_approved) dims=['prompt_version'] engageΔ=+0.018 didΔ=+0.000 → **beneficial**
- ks_cancel v8 (controller_approved) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.152 → **beneficial**
- nw_kyc v4 (controller_approved) dims=['prompt_version'] engageΔ=-0.029 didΔ=+0.000 → **harmful**
- ks_cancel v9 (controller_approved) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.079 → **beneficial**
- nw_kyc v5 (controller_approved) dims=['voice'] engageΔ=-0.002 didΔ=+0.000 → **neutral**
- nw_renewal v7 (controller_approved) dims=['voice'] engageΔ=-0.005 didΔ=+0.000 → **neutral**
- nw_kyc v6 (controller_approved) dims=['welcome_message'] engageΔ=+0.013 didΔ=+0.000 → **beneficial**
- nw_kyc v7 (controller_approved) dims=['welcome_message'] engageΔ=-0.014 didΔ=+0.000 → **harmful**
- nw_renewal v8 (controller_approved) dims=['voice'] engageΔ=+0.002 didΔ=+0.000 → **neutral**

## Governance

```
{
  "approval_requests": 23,
  "decisions": {
    "approved": 22,
    "rejected": 1,
    "expired": 0
  },
  "rejection_reasons": {
    "approver declined (judgement call)": 1
  },
  "applied_via_approval": 19,
  "auto_applied": 0,
  "auto_apply_rejected": 0,
  "apply_conflicts": 3,
  "lapsed": 0,
  "peak_requests_per_24h": {
    "ks_cancel": 4,
    "nw_renewal": 2,
    "nw_kyc": 2
  }
}
```

## Incidents

```
[
  {
    "type": "did_flagged",
    "workflow": "ks_cancel",
    "at": "D2 10:00",
    "flagged_did_share_by_day": {
      "2": 0.507,
      "3": 0.5,
      "4": 0.256,
      "5": 0.019,
      "6": 0.0,
      "7": 0.0,
      "8": 0.0,
      "9": 0.0
    }
  },
  {
    "type": "supervisor_edit",
    "workflow": "ks_cancel",
    "at": "D3 11:30",
    "mttr_minutes": 210,
    "fixed_by": "controller_approved"
  },
  {
    "type": "supervisor_edit",
    "workflow": "nw_renewal",
    "at": "D5 15:00"
  }
]
```

## Decaying variants — share of in-population calls still on the variant, by day after onset

```
{
  "nw_renewal:welcome_message=W3": {
    "2": 0.55,
    "3": 0.547,
    "4": 0.554,
    "5": 0.558,
    "6": 0.541,
    "7": 0.532,
    "8": 0.569,
    "9": 0.545
  }
}
```

Credits used: 47 · validation runs: 17 · LLM fix calls: 10