"""
scene_to_sequence.py
====================
Bake an animated mesh (Alembic .abc, USD .usd/.usdc/.usda, or .blend) into the
per-frame binary geometry sequence + manifest.json used by <alembic-viewer>,
**including flat PBR material info** (base color / metallic / roughness) and
per-material face groups.

    blender --background --factory-startup --python converter/scene_to_sequence.py -- \
        --input  "Untitled.usdc" \
        --outdir "viewer/models/Untitled" \
        [--decimate 1.0] [--frame-step 1] [--frame-start N] [--frame-end N] [--name NAME]

Per-frame binary layout (little-endian, geometry baked into WORLD space):
    [ positions : float32 * 3 * vertexCount   ]
    [ normals   : float32 * 3 * vertexCount   ]
    [ indices   : uint32  * 3 * triangleCount ]   (triangles sorted by material)

manifest.json adds:
    "materials": [ { "name", "baseColor":[r,g,b,a], "metallic", "roughness" }, ... ]
    frames[i].groups: [ [indexStart, indexCount, materialIndex], ... ]

Textures are NOT baked yet (hook left in extract_material). Alembic carries no
material, so .abc input yields a single default grey material.
"""

import bpy
import sys
import os
import json
import math
import array
import argparse
import mathutils

_ADDON = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                      "..", "blender_addon", "chou_io")
if _ADDON not in sys.path:
    sys.path.insert(0, _ADDON)

# Blender is Z-up, three.js is Y-up. Rotate -90° about X: (x, y, z) -> (x, z, -y)
ZUP_TO_YUP = mathutils.Matrix.Rotation(-math.pi / 2.0, 4, "X")


def parse_args():
    argv = sys.argv
    argv = argv[argv.index("--") + 1:] if "--" in argv else []
    p = argparse.ArgumentParser(prog="scene_to_sequence")
    p.add_argument("--input", required=True)
    p.add_argument("--outdir", required=True)
    p.add_argument("--name", default=None)
    p.add_argument("--decimate", type=float, default=1.0)
    p.add_argument("--frame-step", type=int, default=1, dest="frame_step")
    p.add_argument("--frame-start", type=int, default=None, dest="frame_start")
    p.add_argument("--frame-end", type=int, default=None, dest="frame_end")
    return p.parse_args(argv)


def import_any(path):
    ext = os.path.splitext(path)[1].lower()
    if ext == ".abc":
        bpy.ops.wm.alembic_import(filepath=path, as_background_job=False)
    elif ext in (".usd", ".usdc", ".usda", ".usdz"):
        bpy.ops.wm.usd_import(filepath=path)
    elif ext == ".blend":
        bpy.ops.wm.open_mainfile(filepath=path)
    elif ext == ".chou":
        import chou_core
        chou_core.read_chou(path)  # imports geometry.abc + rebuilds materials
    else:
        raise SystemExit(f"unsupported input: {ext}")


def derive_range(scene, meshes):
    fs, fe = scene.frame_start, scene.frame_end
    if fe > fs:
        return fs, fe
    lo, hi = math.inf, -math.inf
    for a in bpy.data.actions:
        r = a.frame_range
        lo, hi = min(lo, r[0]), max(hi, r[1])
    if hi > lo:
        return int(lo), int(hi)
    return 0, 0  # static


import chou_core  # noqa: E402  (blender_addon/chou_io on sys.path)


def extract_material(mat):
    """Flat material: base colour, or a base-colour texture image.
    Returns ({name, baseColor}, bpy.types.Image | None)."""
    out = {"name": mat.name, "baseColor": [0.8, 0.8, 0.8, 1.0]}
    nt = getattr(mat, "node_tree", None)
    sock = None
    if getattr(mat, "use_nodes", False) and nt:
        bsdf = next((n for n in nt.nodes if n.type == "BSDF_PRINCIPLED"), None)
        emis = next((n for n in nt.nodes if n.type == "EMISSION"), None)
        sock = (bsdf.inputs.get("Base Color") if bsdf
                else emis.inputs.get("Color") if emis else None)
    if sock is None:
        c = mat.diffuse_color
        out["baseColor"] = [c[0], c[1], c[2], c[3] if len(c) > 3 else 1.0]
        return out, None
    if sock.is_linked:
        node = chou_core._find_image_node(sock)
        return out, (node.image if node else None)
    v = sock.default_value
    out["baseColor"] = [v[0], v[1], v[2], v[3] if len(v) > 3 else 1.0]
    return out, None


def main():
    args = parse_args()
    inp = os.path.abspath(args.input)
    outdir = os.path.abspath(args.outdir)
    name = args.name or os.path.splitext(os.path.basename(inp))[0]
    framesdir = os.path.join(outdir, "frames")
    os.makedirs(framesdir, exist_ok=True)
    if not os.path.isfile(inp):
        raise SystemExit(f"input not found: {inp}")

    bpy.ops.wm.read_factory_settings(use_empty=True)
    import_any(inp)
    scene = bpy.context.scene
    meshes = [o for o in scene.objects if o.type == "MESH"]
    if not meshes:
        raise SystemExit("no MESH objects in input")

    if args.decimate < 1.0:
        for o in meshes:
            m = o.modifiers.new("web_decimate", "DECIMATE")
            m.decimate_type = "COLLAPSE"
            m.ratio = max(1e-4, args.decimate)

    # global material table (by name) across every mesh, packing textures
    mat_index = {}
    materials = []
    tex_by_image = {}
    for o in meshes:
        for slot in o.material_slots:
            m = slot.material
            if not m or m.name in mat_index:
                continue
            mat_index[m.name] = len(materials)
            entry, img = extract_material(m)
            if img is not None:
                rel = tex_by_image.get(img)
                if rel is None:
                    got = chou_core._image_bytes(img)
                    if got:
                        ext, data = got
                        base = "".join(ch if (ch.isalnum() or ch in "-_.") else "_"
                                       for ch in os.path.splitext(img.name)[0]) or "tex"
                        rel = "textures/%s%s" % (base, ext)
                        p = os.path.join(outdir, rel)
                        os.makedirs(os.path.dirname(p), exist_ok=True)
                        with open(p, "wb") as fh:
                            fh.write(data)
                        tex_by_image[img] = rel
                if rel:
                    entry["baseColorTexture"] = rel
            materials.append(entry)
    if not materials:
        materials = [{"name": "default", "baseColor": [0.79, 0.8, 0.82, 1.0]}]

    fs = args.frame_start if args.frame_start is not None else None
    fe = args.frame_end if args.frame_end is not None else None
    if fs is None or fe is None:
        d0, d1 = derive_range(scene, meshes)
        fs = d0 if fs is None else fs
        fe = d1 if fe is None else fe
    step = max(1, args.frame_step)
    fps = scene.render.fps / scene.render.fps_base
    out_frames = list(range(fs, fe + 1, step)) or [fs]

    deps = bpy.context.evaluated_depsgraph_get()
    bbmin = [math.inf] * 3
    bbmax = [-math.inf] * 3
    frames_meta = []

    for i, f in enumerate(out_frames):
        scene.frame_set(f)
        deps.update()

        # un-indexed: one entry per triangle corner, so per-corner UVs are exact.
        # corners = list of (globalMatIndex, [9 pos], [9 nrm], [6 uv])
        corners = []
        for o in meshes:
            ev = o.evaluated_get(deps)
            me = ev.to_mesh()
            me.transform(ZUP_TO_YUP @ o.matrix_world)   # world space, Y-up
            me.calc_loop_triangles()
            try:
                vnorm = me.vertex_normals
            except AttributeError:
                vnorm = None
            uvdata = me.uv_layers.active.data if me.uv_layers.active else None
            verts = me.vertices

            local_to_global = [mat_index.get(s.material.name, 0) if s.material else 0
                               for s in o.material_slots] or [0]

            for lt in me.loop_triangles:
                gi = local_to_global[min(lt.material_index, len(local_to_global) - 1)]
                P, N, U = [], [], []
                for k in range(3):
                    vi = lt.vertices[k]
                    li = lt.loops[k]
                    co = verts[vi].co
                    P.extend((co.x, co.y, co.z))
                    nv = vnorm[vi].vector if vnorm is not None else verts[vi].normal
                    N.extend((nv.x, nv.y, nv.z))
                    if uvdata is not None:
                        uv = uvdata[li].uv
                        U.extend((uv.x, uv.y))
                    else:
                        U.extend((0.0, 0.0))
                    if co.x < bbmin[0]: bbmin[0] = co.x
                    if co.y < bbmin[1]: bbmin[1] = co.y
                    if co.z < bbmin[2]: bbmin[2] = co.z
                    if co.x > bbmax[0]: bbmax[0] = co.x
                    if co.y > bbmax[1]: bbmax[1] = co.y
                    if co.z > bbmax[2]: bbmax[2] = co.z
                corners.append((gi, P, N, U))
            ev.to_mesh_clear()

        corners.sort(key=lambda c: c[0])
        pos = array.array("f")
        nrm = array.array("f")
        uv = array.array("f")
        groups = []
        cur_mat = None
        run_start = 0
        for gi, P, N, U in corners:
            if gi != cur_mat:
                if cur_mat is not None:
                    groups.append([run_start, len(pos) // 3 - run_start, cur_mat])
                cur_mat = gi
                run_start = len(pos) // 3
            pos.extend(P)
            nrm.extend(N)
            uv.extend(U)
        if cur_mat is not None:
            groups.append([run_start, len(pos) // 3 - run_start, cur_mat])

        vcount = len(pos) // 3          # == 3 * triangleCount (un-indexed)
        rel = "frames/frame_%04d.bin" % i
        with open(os.path.join(outdir, rel), "wb") as fh:
            if sys.byteorder != "little":
                pos.byteswap(); nrm.byteswap(); uv.byteswap()
            fh.write(pos.tobytes()); fh.write(nrm.tobytes()); fh.write(uv.tobytes())

        frames_meta.append({"file": rel, "vertexCount": vcount,
                            "triangleCount": vcount // 3, "groups": groups})
        print("frame %d (%d/%d) corners=%d groups=%d"
              % (f, i + 1, len(out_frames), vcount, len(groups)))

    manifest = {
        "name": name,
        "source": os.path.basename(inp),
        "fps": round(fps, 6),
        "frameStart": fs, "frameEnd": fe, "frameStep": step,
        "frameCount": len(out_frames),
        "decimate": args.decimate,
        "bbox": {"min": bbmin, "max": bbmax},
        "binLayout": "corners_pos_nrm_uv",
        "layout": "un-indexed: pos:f32*3N | nrm:f32*3N | uv:f32*2N  (N = 3*triangleCount, little-endian, world space)",
        "attributes": {"uv": True},
        "materials": materials,
        "frames": frames_meta,
    }
    with open(os.path.join(outdir, "manifest.json"), "w") as fh:
        json.dump(manifest, fh, indent=2)
    print("WROTE", os.path.join(outdir, "manifest.json"),
          "| frames:", len(out_frames), "| materials:", len(materials))


if __name__ == "__main__":
    main()
