# Improvement plan — 2026-07-23

## Context
Personal single-user brokerage automation (login via Playwright + OTP-from-Messages, then direct calls to Meitav's own internal REST API). Kobi's own prior graph audit already concluded "watch, don't touch" on structure. The most important finding here: **local `main` has diverged from `origin/main`** — GitHub already has a real reliability fix (force-launching Messages.app before OTP polling) that this local checkout doesn't have. Reconcile that before anything else.

## Tasks
- [ ] **Do this first:** pull/merge `origin/main` into local `main` — GitHub's version already includes a real OTP-reliability fix this repo is missing — **Verify:** local matches origin, the Messages.app force-launch fix is present
- [ ] Add a monthly-scheduled smoke test (`login()` → `get_snapshot()` end-to-end) to catch Meitav UI drift early instead of discovering it mid-use — **Verify:** scheduled job exists and has run at least once successfully
- [ ] Add basic retry/backoff on the four httpx data calls (currently one attempt, immediate failure on any non-200) — **Verify:** a transient failure retries before surfacing an error
- [ ] Decide: is the Windows/Linux OTP gap worth closing? Check the repo shortlist for an existing cross-platform SMS-forwarding library before building one — **Verify:** decision recorded
- [ ] No urgency on: detection-evasion hardening (personal tool automating your own login — reasonable trade-off as-is), cleartext session storage (local-only, gitignored, low risk for this use case)
