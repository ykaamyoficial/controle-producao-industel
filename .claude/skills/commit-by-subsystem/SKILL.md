---
name: commit-by-subsystem
description: Split a large pile of uncommitted changes into coherent per-subsystem git commits, in this project's Portuguese commit-message style. Use when there are many uncommitted files spanning multiple features/areas that need to be committed.
---

1. Run `git status` (never `-uall`) and `git diff` to see the full scope. Do not assume small scope — work in this repo often arrives in huge uncommitted batches spanning multiple feature phases at once.

2. Group changed/untracked files by directory/module boundary first — this is fast and low-risk. A whole new package/feature that lives in its own tree (e.g. a new `api/app/modules/<x>/` directory, a new `app/ui/<feature>/` directory) becomes one commit.

3. For genuinely cross-cutting files (core config, error codes, shared wiring like `main.py`, shared services touched by many features), either:
   - bundle them into one small "foundation"/"wiring" commit, or
   - fold them into whichever single feature commit most plausibly needed the change.
   Do not try to `git add -p` hundreds of files for perfect line-level attribution — it doesn't scale and the value is marginal once the code was written together in one continuous effort.

4. Fixes made to files that are themselves brand-new/untracked (never committed before) cannot be split into a separate "fix" commit — there is no prior version to diff against. Fold the fix into that area's commit and describe what was corrected in the commit message instead of forcing an artificial split.

5. Before committing, propose the grouping plan to the user: a list of commits, each with the files/dirs it will contain and a one-line description. Get explicit confirmation before running any `git add`/`git commit` — this is a git operation with real repo history impact. Always confirm the grouping first unless the user has already explicitly approved proceeding without review.

6. Write each commit message in the project's existing style: Portuguese, imperative mood, explaining what the subsystem does and why (not just "add X" or "update Y"). Check recent `git log` output in this repo to match tone/format before writing messages.

7. Stage files per group with explicit paths (`git add <specific files/dirs>`) — never `git add -A` or `git add .`. Run `git status` after each `git add` to confirm only the intended files are staged before committing.

8. After the full reorganization, re-run the project's test suite once (`python -m pytest tests api/tests -q`, or a narrower subset if the full suite is impractically slow) against the final committed tree to confirm nothing was lost or misattributed in the split.

9. Follow standard git safety rules: never use `--no-verify`/`--no-gpg-sign`, never force-push, never `git add -A`, always create new commits (do not amend unless explicitly asked).
