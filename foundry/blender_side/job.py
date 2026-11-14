"""Runs inside Blender (`blender --background --factory-startup --python job.py -- job.json`).

Turns a built mesh (mesh.json, made in plain Python by the foundry) into the exported
models and the raw renders the sheet is laid out from. No shape-making happens here.

job.json:
  mesh          path to mesh.json (verts, faces, regions, uvs, parts, sockets)
  out_dir       where model.glb, parts.glb and renders/*.png go
  region_tints  {region: [r, g, b]} for the renders
  views         [{"name", "dir": [x, y, z] (camera toward the model), "kind": shaded|wire|silhouette}]
  extent        metres the orthographic camera shows (same for every variant of a family)
  size          render size in pixels (square)
  reference     optional path to a reference model (.glb) placed beside the asset
  reference_offset  [x, y, z] metres for it
Writes result.json in out_dir: {"ok", "files", "uv_layers", "error"}.
"""

import json
import math
import os
import sys
import time
import traceback

import bpy
from mathutils import Matrix, Vector


def main():
    job_path = sys.argv[sys.argv.index("--") + 1]
    job = json.load(open(job_path, encoding="utf-8"))
    out = job["out_dir"]
    os.makedirs(os.path.join(out, "renders"), exist_ok=True)
    result = {"ok": False, "files": []}
    try:
        data = json.load(open(job["mesh"], encoding="utf-8"))
        bpy.ops.wm.read_factory_settings(use_empty=True)
        mats = materials(data["regions"], job.get("region_tints", {}))
        model = make_object(data["name"], data, range(len(data["faces"])), mats)
        sockets = make_sockets(data, model)
        export(os.path.join(out, "model.glb"), [model, *sockets])
        result["files"].append("model.glb")
        part_objs = [make_object(p["id"], data, range(*p["faces"]), mats) for p in data["parts"]]
        export(os.path.join(out, "parts.glb"), part_objs)
        result["files"].append("parts.glb")
        for obj in part_objs:
            bpy.data.objects.remove(obj, do_unlink=True)
        result["uv_layers"] = len(model.data.uv_layers)
        if job.get("views"):
            result["files"].extend(render_views(job, model, out))
        result["ok"] = True
    except Exception:
        result["error"] = traceback.format_exc()
    json.dump(result, open(os.path.join(out, "result.json"), "w", encoding="utf-8"), indent=1)


def materials(regions, tints):
    mats = {}
    for name in sorted(set(regions)):
        mat = bpy.data.materials.new(name)
        tint = tints.get(name, [0.6, 0.6, 0.6])
        mat.diffuse_color = (*tint, 1.0)
        mats[name] = mat
    return mats


def make_object(name, data, faces, mats):
    faces = list(faces)
    used = sorted({i for f in faces for i in data["faces"][f]})
    remap = {old: new for new, old in enumerate(used)}
    verts = [data["verts"][i] for i in used]
    tris = [[remap[i] for i in data["faces"][f]] for f in faces]
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(verts, [], tris)
    order = sorted({data["regions"][f] for f in faces})
    for region in order:
        mesh.materials.append(mats[region])
    for poly, f in zip(mesh.polygons, faces):
        poly.material_index = order.index(data["regions"][f])
        poly.use_smooth = False
    uv = mesh.uv_layers.new(name="UVMap")
    for poly, f in zip(mesh.polygons, faces):
        for loop_index, corner in zip(poly.loop_indices, data["uvs"][f]):
            uv.data[loop_index].uv = corner
    mesh.update()
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.scene.collection.objects.link(obj)
    return obj


def frame_matrix(f):
    m = Matrix.Identity(4)
    for col, axis in enumerate(("x", "y", "z")):
        for row in range(3):
            m[row][col] = f[axis][row]
    for row in range(3):
        m[row][3] = f["origin"][row]
    return m


def make_sockets(data, parent):
    out = []
    for name, f in data.get("sockets", {}).items():
        empty = bpy.data.objects.new("socket_" + name, None)
        empty.empty_display_size = 0.05
        bpy.context.scene.collection.objects.link(empty)
        empty.matrix_world = frame_matrix(f)
        empty.parent = parent
        out.append(empty)
    return out


def export(path, objects):
    bpy.ops.object.select_all(action="DESELECT")
    for obj in objects:
        obj.select_set(True)
    with long_path_isdir():
        bpy.ops.export_scene.gltf(filepath=os.path.normpath(path), export_format="GLB", use_selection=True,
                                  export_apply=True, export_yup=True)


LONG_PREFIX = "\\\\?\\"  # the four characters \\?\


class long_path_isdir:
    """Blender sometimes hands the glTF exporter a long-path form (LONG_PREFIX) of the file path;
    the exporter appends "/" to its folder, which Windows rejects under that prefix, so its
    "does the folder exist" check fails and it tries to create it (seen on Blender 5.1,
    more often with several builds at once). While exporting, the check sees the folder
    through a normalised path. The folder always exists: the foundry makes it first."""

    def __enter__(self):
        self.original = os.path.isdir

        def isdir(p):
            s = os.fspath(p)
            if s.startswith(LONG_PREFIX):
                s = os.path.normpath(s[len(LONG_PREFIX):])
            return self.original(s)

        os.path.isdir = isdir
        return self

    def __exit__(self, *exc):
        os.path.isdir = self.original
        return False


def render_views(job, model, out):
    scene = bpy.context.scene
    scene.render.engine = "BLENDER_WORKBENCH"
    scene.render.resolution_x = scene.render.resolution_y = job.get("size", 512)
    world = bpy.data.worlds.new("World")
    scene.world = world
    lo, hi = bounds([model])
    extent = job.get("extent") or max(hi - lo) * 1.15
    ref = load_reference(job)
    cam = camera(extent)
    files = []
    for view in job["views"]:
        kind = view["kind"]
        with_ref = kind == "scale" and ref
        for o in ref or []:
            o.hide_render = not with_ref
        objs = [model, *(ref if with_ref else [])]
        vlo, vhi = bounds(objs)
        span = max(extent, max(vhi - vlo) * 1.1) if with_ref else extent
        style(scene, world, kind)
        wire = wire_copy(model, span * 0.002) if kind == "wire" else None
        aim(cam, (vlo + vhi) / 2, Vector(view["dir"]), span)
        path = os.path.join(out, "renders", view["name"] + ".png")
        scene.render.filepath = path
        bpy.ops.render.render(write_still=True)
        files.append("renders/" + view["name"] + ".png")
        if wire is not None:
            bpy.data.objects.remove(wire, do_unlink=True)
    return files


def load_reference(job):
    path = job.get("reference")
    if not path:
        return None
    before = set(bpy.data.objects)
    bpy.ops.import_scene.gltf(filepath=path)
    new = [o for o in bpy.data.objects if o not in before]
    off = Vector(job.get("reference_offset", [0.8, 0, 0]))
    for o in new:
        if o.parent is None:
            o.location += off
    return [o for o in new if o.type == "MESH"] or None


def bounds(objs):
    pts = [o.matrix_world @ v.co for o in objs if o.type == "MESH" for v in o.data.vertices]
    lo = Vector((min(p.x for p in pts), min(p.y for p in pts), min(p.z for p in pts)))
    hi = Vector((max(p.x for p in pts), max(p.y for p in pts), max(p.z for p in pts)))
    return lo, hi


def camera(extent):
    data = bpy.data.cameras.new("Cam")
    data.type = "ORTHO"
    data.ortho_scale = extent
    cam = bpy.data.objects.new("Cam", data)
    bpy.context.scene.collection.objects.link(cam)
    bpy.context.scene.camera = cam
    return cam


def aim(cam, centre, direction, extent):
    """Points the camera along `direction`, world up (+z) kept up; straight down keeps +y up."""
    d = direction.normalized()
    cam.data.ortho_scale = extent
    location = centre - d * extent * 3
    up = Vector((0, 1, 0)) if abs(d.z) > 0.99 else Vector((0, 0, 1))
    right = d.cross(up).normalized()
    true_up = right.cross(d).normalized()
    rot = Matrix((right, true_up, -d)).transposed()
    cam.matrix_world = Matrix.Translation(location) @ rot.to_4x4()
    cam.data.clip_end = extent * 10


def style(scene, world, kind):
    shading = scene.display.shading
    if kind == "silhouette":
        shading.light = "FLAT"
        shading.color_type = "SINGLE"
        shading.single_color = (0.0, 0.0, 0.0)
        world.color = (1.0, 1.0, 1.0)
        scene.view_settings.view_transform = "Standard"
    else:
        shading.light = "STUDIO"
        shading.color_type = "SINGLE" if kind == "scale" else "MATERIAL"
        shading.single_color = (0.7, 0.7, 0.7)
        shading.show_cavity = True
        world.color = (0.32, 0.34, 0.37)
        scene.view_settings.view_transform = "Standard"


def wire_copy(model, thickness):
    wire = model.copy()
    wire.data = model.data.copy()
    bpy.context.scene.collection.objects.link(wire)
    mod = wire.modifiers.new("wire", "WIREFRAME")
    mod.thickness = thickness  # scales with the frame, so small and large assets read alike
    mod.use_replace = True
    mat = bpy.data.materials.new("wire_black")
    mat.diffuse_color = (0.02, 0.02, 0.02, 1.0)
    wire.data.materials.clear()
    wire.data.materials.append(mat)
    return wire


if __name__ == "__main__":
    main()
