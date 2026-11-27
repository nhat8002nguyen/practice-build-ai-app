# Operator decision log

Decisions made during the no-mistakes review / test / CI gates for PR #1 (`feature/smb-support-copilot`).
Mirrored in the PR description so Nate can review later without digging through chat.

| ID | Choice | Meaning |
| --- | --- | --- |
| A | Fix | Agent finals must go through grounding / citation-refusal. No invented policy with `refused=False` and empty citations. |
| A1 | Fix | Same rule for HITL `awaiting_human` drafts: safe non-policy placeholder only, never free-form model policy claims. |
| H2 | Fix | Keep a true weighted hybrid merge so `RETRIEVAL_DENSE_WEIGHT` stays meaningful. Align `retrieval_min_score` / scaling so defaults do not false-refuse. |
| O3 | Fix | When order lookup and grounded KB both succeed, combine: order status first, then grounded policy + matching citations. |
| T1 | Fix | Re-run the test agent for a proper JSON live-validation verdict after a prose parse failure. |
| CI-GG | Approve with override | GitGuardian fails on historical `POSTGRES_PASSWORD=postgres` in commit `a1cbeb9` `.env.example` (local Compose placeholder). Tip already uses `dev-only-change-me`. History rewrite / GG dashboard dismiss deferred. Not a live production secret. |

## Parked human pre-merge checks

- Docker Compose full-stack smoke
- Expo device / simulator UI

## Pipeline outcome

- Run id: `01M8BJHXTHRVVD13F3SHEBT542`
- Outcome: `passed-with-override` (GitGuardian history finding still red on GitHub; CI step approved with documented reason)
- PR: https://github.com/nhat8002nguyen/practice-build-ai-app/pull/1

## Follow-up if you want a green GitGuardian check

1. Dismiss / resolve the incident in the GitGuardian dashboard for the known local-dev placeholder, or
2. Rewrite history so `a1cbeb9` no longer contains `POSTGRES_PASSWORD=postgres`, then force-push the branch (destructive; do deliberately).
