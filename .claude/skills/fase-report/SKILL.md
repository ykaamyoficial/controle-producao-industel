---
name: fase-report
description: Generate a docs/architecture/FASEn_*.md phase-closing report for work just finished, following the project's current lean template with real test-run numbers. Use when the user says a phase/fase is done and needs its architecture doc.
---

Generates a phase-closing report at `docs/architecture/FASEn_<SLUG>.md` for "Controle de Producao Industel" (PySide6 Desktop + FastAPI/PostgreSQL), following the CURRENT lean template (confirmed from `FASE8_CHAT_NOTIFICACOES.md`, `FASE9_RESILIENCIA_EXPERIENCIA_USUARIO.md`, `FASE10_TESTES_DESEMPENHO_REGRESSAO.md`, all 2026-08-17 — the most recent convention).

Do NOT imitate older, more verbose docs (e.g. `FASE8_CONSOLIDACAO_FINAL_ACTION_CENTER.md`) — those are superseded. The current style has no line-number citations and no full diffs.

## Template skeleton

`# Fase N — <título curto>`, then `##` sections:

1. **Objetivo** (or **Escopo validado** / **Regras técnicas**, pick whichever fits how the phase is best described) — short paragraph or bullets: what this phase set out to do.
2. **Implementação** (or equivalent heading) — bullet list of what was actually built/changed. Name concrete files/classes/modules (e.g. `` `ChatRealtimeClient` ``, `app/ui/background_worker.py`). No line numbers, no diffs.
3. **Garantias** (or **Critérios de segurança**) — NUMBERED list of invariants that must hold after this phase: the "this can never happen" / "this must always be true" contract.
4. **Validação** — exact commands run, verbatim, plus the REAL pass/skip/fail counts from actually executing them. Never fabricate or estimate these numbers.
5. Optional, only if validation is incomplete or something is still open: extra sections such as **Resultados reproduzíveis**, **Metas cobertas por teste**, **Pendência encontrada**, **Conclusão**. Use these to report partial/blocked results honestly instead of forcing a clean sign-off.

Tone: Brazilian Portuguese, dense technical prose, bullets over paragraphs, no marketing language.

## Procedure

1. **Determine phase number/slug.** If not obvious from the conversation, ask the user. Run `ls docs/architecture | grep -i FASE` (or Glob `docs/architecture/FASE*.md`) to see existing numbers/slugs and avoid colliding with one already used. Match the existing naming style: `FASEn_SLUG_EM_MAIUSCULAS_COM_UNDERSCORE.md`.
2. **Verify what actually changed** — do not rely on conversation memory alone:
   - `git status`
   - `git diff` (and `git diff --stat` for a quick overview)
   - `git log --oneline -10`
   Cross-check the changed files against what the conversation claims was built.
3. **Draft the doc** following the skeleton above, grounded in the real diff — cite the actual files/classes touched.
4. **Run tests for real** and capture the exact result line(s) to paste into Validação:
   - Desktop suite: `python -m pytest tests -q`
   - API suite: `python -m pytest api/tests -q`
   - Or a narrower, targeted subset matching the files touched (see FASE8/9 examples: they list specific test files rather than the whole suite).
   - Also typically: `python -m compileall -q app api/app`.
   If the user says tests were already run earlier this session, prefer re-running for a fresh, accurate count — unless the suite is impractically slow, in which case reuse the earlier number but state explicitly in the doc/response that it's from an earlier run this session, not fabricated.
   If a suite is not fully green, do not paper over it — use the optional "Pendência encontrada" / "Conclusão" sections to report exactly what failed and why, as FASE10 does.
5. **Write the file** to `docs/architecture/FASEn_<SLUG>.md`.
6. **Read the file back** once to confirm it saved correctly.
7. **Show the drafted doc to the user** and ask if anything about the phase description needs correcting — scope/intent details may not be fully visible from the diff alone.
