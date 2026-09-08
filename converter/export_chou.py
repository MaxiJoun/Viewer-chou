"""
export_chou.py — headless .chou export from Blender.

Bundle a Blender scene's animation + look into one file:

    <name>.chou  =  geometry.abc (the anim)  +  chou.json (materials/colour)  +  textures/

Usage
-----
From a .blend on disk:

    blender --background "scene.blend" \
        --python converter/export_chou.py -- --output "out.chou" [--selection] \
        [--frame-start N --frame-end N]

Or run it from Blender's Text Editor (uses the currently open file / scene).

It does NOT put the .blend or a .usd inside the .chou — only the Alembic cache
and the material definitions.
"""

import bpy
import sys
import os
import argparse

# reuse the single source-of-truth format code
_ADDON = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                      "..", "blender_addon", "chou_io")
if _ADDON not in sys.path:
    sys.path.insert(0, _ADDON)
import chou_core  # noqa: E402


def _args():
    argv = sys.argv
    argv = argv[argv.index("--") + 1:] if "--" in argv else []
    p = argparse.ArgumentParser(prog="export_chou")
    p.add_argument("--output", required=True, help="path to write the .chou")
    p.add_argument("--selection", action="store_true",
                   help="only selected mesh objects (default: all scene meshes)")
    p.add_argument("--frame-start", type=int, default=None, dest="frame_start")
    p.add_argument("--frame-end", type=int, default=None, dest="frame_end")
    return p.parse_args(argv)


def main():
    a = _args()
    out = os.path.abspath(a.output)
    os.makedirs(os.path.dirname(out), exist_ok=True)

    objs = None
    if a.selection:
        objs = [o for o in bpy.context.selected_objects if o.type == "MESH"]
        if not objs:
            raise SystemExit("--selection given but no mesh objects selected")

    path = chou_core.write_chou(out, objs, a.frame_start, a.frame_end)
    print("WROTE", path)


if __name__ == "__main__":
    main()
