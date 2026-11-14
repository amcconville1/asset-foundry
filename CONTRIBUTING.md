# Contributing

Thanks for helping. Issues and pull requests are welcome; for anything larger than a fix,
open an issue first so we can agree the shape before you build it.

## Setup

```bash
pip install -e ".[dev]"
python -m pytest        # must pass; needs no Blender
foundry doctor          # Blender 5.1+ for builds and renders
```

## Rules for every change

1. **Game- and engine-agnostic.** Nothing in this repo names a particular game, studio,
   engine path or asset. Project-specific settings belong in a profile, and project-specific
   shapes in the project's own builder module.
2. **Shapes stay plain Python.** Geometry lives in `foundry/geom.py` and `foundry/parts/`.
   Blender (`foundry/blender_side/`) only exports and renders. If a primitive truly needs
   Blender (a boolean, a remesh), propose it in an issue first.
3. **Deterministic.** The same recipe and seed must give the same `mesh_hash`. Randomness
   comes only from the `ctx.rng` a builder is given.
4. **Tests first.** Anything that does maths, checks a rule or changes state gets a test;
   a behaviour change gets a test that fails without it. Tests build their own data and
   run without Blender.
5. **Errors say how to fix.** A message a user or an agent can hit names what was wrong and
   what is allowed (valid keys, parts, anchors, ranges). Nothing unknown is ignored silently.
6. **Look at what you changed.** If a change affects a mesh or a render, build an example
   and look at its `sheet.png` before opening the PR; say what you checked.
7. **No downloading assets.** The foundry makes shapes from recipes. It does not fetch
   models, textures or add-ons, and it doesn't call generative-3D services.
8. **Dependencies.** Runtime uses the standard library only. A new dependency needs a reason
   in the PR and must be maintained, permissively licensed and installable from PyPI.
9. **Small and readable.** A function over about 50 lines, or a module over about 300, is a
   sign to split. Match the style around you.
10. **The review server stays local.** It binds to 127.0.0.1, serves only catalog files of
    known types, and refuses paths outside the catalog. Keep it that way.

## Adding a builder

See README, "Adding a builder". A new builder needs: parameters with defaults, ranges and a
one-line doc each; named anchors; its parameter axes with real spans; and an entry in the
test that every builder makes a closed, outward mesh from its defaults.

## Pull requests

- One topic per PR. Explain what changed and why, and how you checked it.
- Commit messages: `feat(parts): ...`, `fix(sheet): ...`, `docs: ...`; first line under 72
  characters.
- By contributing, you agree your work is licensed under the MIT licence of this project.

## Working with AI agents

`AGENTS.md` holds the same rules in the form agents read, plus how to run a round. Agent-made
pull requests are fine; the person opening the PR is responsible for having read and checked
it.
