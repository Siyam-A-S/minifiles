---
name: milestone-check
description: Verify a MiniFiles roadmap milestone against its acceptance criteria, update the roadmap, and draft the earned resume bullet. Use when the user asks whether a milestone is done, wants to close out a milestone, or asks which resume bullets are earned.
---

# Milestone check

This project backs resume claims (see CLAUDE.md): a milestone's resume bullet
is earned **only** when its acceptance criteria pass for real, in this
environment, now — not from memory of a past run.

## Steps

1. Read the milestone's section in `docs/roadmap.md`. The **Acceptance** line is
   the contract; the checkboxes are the sub-tasks.
2. Execute the acceptance criteria literally:
   - M0: `make test` and `make lint` green.
   - M1: `make accept-m1` prints PASS (end-to-end on kind; use the
     `deploy-local` skill first if the cluster is down).
   - M2+: per the roadmap's Acceptance line for that milestone.
3. Record results honestly. A partial pass is a fail — report exactly which
   step broke and stop; do not tick anything.
4. On a full pass:
   - Tick the milestone's checkboxes in `docs/roadmap.md` (edit `- [ ]` → `- [x]`).
   - Draft the resume bullet(s) this milestone earns, phrased from what was
     *actually demonstrated* (numbers from the real run, not projections).
     Present them to the user in the final message — do **not** edit anything
     in `~/personal/resume` unless the user explicitly asks.

## Rules

- Never tick a checkbox for work that "should" pass — only for what just passed.
- Never write resume bullets for unfinished milestones, and never inflate
  scale (e.g. say "single-node kind/AKS cluster" plainly if asked about scale).
- If acceptance requires Azure resources, re-read `docs/azure-cost-guardrails.md`
  first and tear down when done.
