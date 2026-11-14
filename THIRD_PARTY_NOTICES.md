# Third-party notices

## three.js 0.170.0 (MIT)

Vendored, unmodified, in `foundry/review/static/vendor/` for the review page's 3D view:
`three.module.min.js`, `loaders/GLTFLoader.js`, `controls/OrbitControls.js`,
`utils/BufferGeometryUtils.js`. Source: https://github.com/mrdoob/three.js (npm `three@0.170.0`).
Its licence is in `foundry/review/static/vendor/LICENSE-three.txt`.

## Blender (GPL-2.0-or-later), not included

The foundry runs a separately installed Blender as a subprocess. One file,
`foundry/blender_side/job.py`, executes inside Blender and uses its Python API (`bpy`).
Blender is not distributed with this project. This project's MIT licence is compatible
with the GPL.

## Python packages

Runtime: the standard library only. The sheet uses [Pillow](https://python-pillow.org/)
(MIT-CMU), and the tests use [pytest](https://pytest.org/) (MIT); both are installed by pip,
not vendored.
