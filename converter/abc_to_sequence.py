"""
abc_to_sequence.py
==================
Bake an Alembic (.abc) mesh cache into a per-frame binary geometry sequence
+ manifest.json consumed by the WEB_ALEMBIC three.js viewer.

Run with Blender headless (Blender 4.x / 5.x):

    blender --background --factory-startup --python converter/abc_to_sequence.py -- \
        --input  "Untitled.abc" \
        --outdir "viewer/models/Untitled" \
        [--decimate 1.0] [--frame-step 1] [--frame-start N] [--frame-end N] [--name NAME]

Output:
    <outdir>/manifest.json
    <outdir>/frames/frame_0000.bin, frame_0001.bin, ...

Per-frame binary layout (little-endian, geometry baked into WORLD space):
    [ positions : float32 * 3 * vertexCount   ]
    [ normals   : float32 * 3 * vertexCount   ]
    [ indices   : uint32  * 3 * triangleCount ]

Topology may change from frame to frame (fluid / pyro sims): each frame stores
its own vertexCount / triangleCount in the manifest.
"""

import bpy
import sys
import os
import json
import struct
import argparse
import math
import array


def parse_args():
    argv = sys.argv
    argv = argv[argv.index("--") + 1:] if "--" in argv else []
    p = argparse.ArgumentParser(prog="abc_to_sequence")
    p.add_argument("--input", required=True, help="path to the .abc file")
    p.add_argument("--outdir", required=True, help="output directory")
    p.add_argument("--name", default=None, help="model name (defaults to input filename)")
    p.add_argument("--decimate", type=float, default=1.0,
                   help="collapse ratio 0..1 applied per frame (1.0 = no decimation)")
    p.add_argument("--frame-step", type=int, default=1, dest="frame_step")
    p.add_argument("--frame-start", type=int, default=None, dest="frame_start")
    p.add_argument("--frame-end", type=int, default=None, dest="frame_end")
    return p.parse_args(argv)


def main():
    args = parse_args()
    inp = os.path.abspath(args.input)
    outdir = os.path.abspath(args.outdir)
    name = args.name or os.path.splitext(os.path.basename(inp))[0]
    framesdir = os.path.join(outdir, "frames")
    os.makedirs(framesdir, exist_ok=True)

    if not os.path.isfile(inp):
        print("ERROR: input not found:", inp)
        sys.exit(1)

    # --- fresh empty scene, import the cache ---
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.wm.alembic_import(filepath=inp, as_background_job=False)
    scene = bpy.context.scene

    meshes = [o for o in scene.objects if o.type == "MESH"]
    if not meshes:
        print("ERROR: no MESH objects found in", inp)
        sys.exit(1)

    if args.decimate < 1.0:
        ratio = max(1e-4, args.decimate)
        for o in meshes:
            m = o.modifiers.new("web_decimate", "DECIMATE")
            m.decimate_type = "COLLAPSE"
            m.ratio = ratio

    fs = scene.frame_start if args.frame_start is None else args.frame_start
    fe = scene.frame_end if args.frame_end is None else args.frame_end
    step = max(1, args.frame_step)
    fps = scene.render.fps / scene.render.fps_base
    out_frames = list(range(fs, fe + 1, step))

    deps = bpy.context.evaluated_depsgraph_get()
    bbmin = [math.inf, math.inf, math.inf]
    bbmax = [-math.inf, -math.inf, -math.inf]
    frames_meta = []

    for i, f in enumerate(out_frames):
        scene.frame_set(f)
        deps.update()

        pos = array.array("f")
        nrm = array.array("f")
        idx = array.array("I")
        base = 0

        for o in meshes:
            ev = o.evaluated_get(deps)
            me = ev.to_mesh()
            me.transform(o.matrix_world)
            me.calc_loop_triangles()

            try:
                vnorm = me.vertex_normals  # auto-computed, current after transform
                normals = [nv.vector.copy() for nv in vnorm]
            except AttributeError:
                normals = [v.normal.copy() for v in me.vertices]

            for vi, v in enumerate(me.vertices):
                co = v.co
                pos.extend((co.x, co.y, co.z))
                n = normals[vi]
                nrm.extend((n.x, n.y, n.z))
                if co.x < bbmin[0]: bbmin[0] = co.x
                if co.y < bbmin[1]: bbmin[1] = co.y
                if co.z < bbmin[2]: bbmin[2] = co.z
                if co.x > bbmax[0]: bbmax[0] = co.x
                if co.y > bbmax[1]: bbmax[1] = co.y
                if co.z > bbmax[2]: bbmax[2] = co.z

            for lt in me.loop_triangles:
                a, b, c = lt.vertices
                idx.extend((base + a, base + b, base + c))

            base += len(me.vertices)
            ev.to_mesh_clear()

        vcount = len(pos) // 3
        tcount = len(idx) // 3
        rel = "frames/frame_%04d.bin" % i
        with open(os.path.join(outdir, rel), "wb") as fh:
            # array is written in machine byte order; force little-endian
            if sys.byteorder != "little":
                pos.byteswap(); nrm.byteswap(); idx.byteswap()
            fh.write(pos.tobytes())
            fh.write(nrm.tobytes())
            fh.write(idx.tobytes())

        frames_meta.append({"file": rel, "vertexCount": vcount, "triangleCount": tcount})
        print("frame %d  (%d/%d)  v=%d  t=%d" % (f, i + 1, len(out_frames), vcount, tcount))

    manifest = {
        "name": name,
        "source": os.path.basename(inp),
        "fps": round(fps, 6),
        "frameStart": fs,
        "frameEnd": fe,
        "frameStep": step,
        "frameCount": len(out_frames),
        "decimate": args.decimate,
        "bbox": {"min": bbmin, "max": bbmax},
        "layout": "pos:f32*3N | nrm:f32*3N | idx:u32*3T  (little-endian, world space)",
        "frames": frames_meta,
    }
    with open(os.path.join(outdir, "manifest.json"), "w") as fh:
        json.dump(manifest, fh, indent=2)

    print("WROTE", os.path.join(outdir, "manifest.json"))
    print("frames:", len(out_frames), " fps:", round(fps, 3))


if __name__ == "__main__":
    main()
