# AGENTS.md — asset-foundry

Rules for any agent working in this repo or using it. Read `README.md` first; people
contributing follow the same rules in `CONTRIBUTING.md`.

## Building the foundry

- **Game-agnostic.** Nothing here names a game, its paths or its engine. Anything
  project-specific goes in that project's profile or its own builder module.
- **Shapes stay plain Python.** Geometry lives in `foundry/geom.py` and `foundry/parts/`;
  Blender (`foundry/blender_side/`) only exports and renders. A primitive that truly needs
  Blender (boolean, remesh) is a separate, documented exception.
- **Tests first** for anything that does maths, checks or changes state: `python -m pytest`
  runs without Blender. A behaviour change needs a test that fails on the old code.
- Every error a person or agent can hit says what was wrong and what is allowed.
- No new dependency without checking it is maintained. Runtime needs none; the sheet needs
  Pillow.
- Commits: `feat(parts): ...`, `fix(sheet): ...`, `docs: ...`; first line under 72
  characters.
- Clean up only processes and files you started; output goes under `out/` (ignored).

## Making assets with it

The loop: `foundry feedback <collection>` (skip on round 1) -> write one recipe per variant,
each with a `brief` and, after round 1, `lineage` naming its parents and the notes it answers
-> `foundry round new` -> read every sheet, `round fix` / `round drop` what's wrong ->
`foundry round submit`. Round size: the family's `round_first` / `round_next` in the
profile, unless the person asked for a number.

- **Fan out.** In a round, every variant is a different take on the form, written as a
  one-line brief before building. Variants differ in outline, proportion or part choice,
  not only size or colour.
- **Look before you hand on.** Read every variant's `sheet.png`; numbers passing is not
  the check. Fix and rebuild what's wrong; a round goes to the person only when every
  variant passes its rules.
- **Answer every mark.** In `foundry feedback`, an arrow reads "arrow +0.23 m along to_tip
  (changes length)": change that parameter by about that much, scaled to the axis (a span
  measured from the middle, like a guard's, changes by twice the arrow). A pin or a lasso
  names a place ("guard: along_span 0.95"; "parts grip, pommel"); its note says what to do
  there. Name the mark you answered in the child variant's `lineage.answers`.
- Change the recipe, never the exported `.glb`.
- Don't download meshes, textures or add-ons; describe the quality you mean in briefs and
  notes.
- Taste belongs to the person reviewing: give a recommendation per variant, never a
  decision.
