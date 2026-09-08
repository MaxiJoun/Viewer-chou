"""
chou_core — read/write the La Chouette bundle (.chou).

A .chou is a ZIP:

    <name>.chou
    ├─ chou.json          metadata + materials + slot assignments
    ├─ geometry.abc       the untouched Alembic geometry cache
    └─ textures/          optional PNGs referenced by materials

This module is the single source of truth for the format. It is imported by:
  - blender_addon/chou_io/__init__.py   (the Blender import/export addon)
  - converter/export_chou.py            (headless export)
  - converter/scene_to_sequence.py      (headless .chou -> web sequence)

All of these run inside Blender (needs `bpy`).
"""

import bpy
import os
import json
import shutil
import zipfile
import tempfile
import datetime

CHOU_VERSION = 1


# --------------------------------------------------------------------------- util
def _safe(s):
    return "".join(c if (c.isalnum() or c in "-_.") else "_" for c in (s or "tex")) or "tex"


_WEB_IMG_EXT = (".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp")


def _image_bytes(img):
    """Return (ext, bytes) for an image datablock, ready to drop in the bundle.
    Handles packed, on-disk and generated/render images. None if it can't."""
    # 1. packed — the original file bytes live in packed_file.data
    if img.packed_file and getattr(img.packed_file, "data", None):
        ext = os.path.splitext(img.filepath or img.name)[1].lower()
        if ext not in _WEB_IMG_EXT:
            ext = ".png"
        return ext, bytes(img.packed_file.data)
    # 2. on disk — copy the file as-is (three.js loads jpg/png/webp fine)
    src = bpy.path.abspath(img.filepath) if img.filepath else ""
    if src and os.path.isfile(src):
        ext = os.path.splitext(src)[1].lower()
        if ext in _WEB_IMG_EXT:
            with open(src, "rb") as f:
                return ext, f.read()
    # 3. generated / render result — save a PNG to a temp file, read it back
    try:
        d = tempfile.mkdtemp(prefix="chou_img_")
        p = os.path.join(d, "img.png")
        img.file_format = "PNG"
        try:
            img.save(filepath=p)          # Blender 3.x+
        except TypeError:
            img.filepath_raw = p
            img.save()
        with open(p, "rb") as f:
            data = f.read()
        shutil.rmtree(d, ignore_errors=True)
        return ".png", data
    except Exception as e:
        print("chou: cannot read image '%s' (%s)" % (img.name, e))
        return None


# passthrough node types we can look "through" to find the real image
_PASSTHRU = {
    "MIX", "MIX_RGB", "GAMMA", "BRIGHTCONTRAST", "HUE_SAT", "INVERT",
    "CURVE_RGB", "MAP_RANGE", "CLAMP", "SEPARATE_COLOR", "COMBINE_COLOR",
}


def _find_image_node(socket, _depth=0):
    """Follow a linked socket back through passthrough nodes to the first
    TEX_IMAGE node with an image. Returns that node or None."""
    if socket is None or not socket.is_linked or _depth > 6:
        return None
    node = socket.links[0].from_node
    if node.type == "TEX_IMAGE":
        return node if node.image else None
    if node.type in _PASSTHRU:
        for inp in node.inputs:
            if inp.is_linked and inp.type in ("RGBA", "VALUE", "VECTOR"):
                hit = _find_image_node(inp, _depth + 1)
                if hit:
                    return hit
    return None


# ----------------------------------------------------------------- material <-> json
#
# .chou materials are deliberately **FLAT**: a base colour OR a base-colour
# texture, nothing else. No metallic / roughness / normal — no PBR response.
# On import they are rebuilt as an unlit Emission material so Blender shows them
# flat too; on the web the viewer uses an unlit material.

def _color_socket(mat):
    """The socket carrying the flat colour: Principled 'Base Color', else
    Emission 'Color'. Returns None if the material has no usable node."""
    nt = getattr(mat, "node_tree", None)
    if not getattr(mat, "use_nodes", False) or nt is None:
        return None
    bsdf = next((n for n in nt.nodes if n.type == "BSDF_PRINCIPLED"), None)
    if bsdf is not None:
        return bsdf.inputs.get("Base Color")
    emis = next((n for n in nt.nodes if n.type == "EMISSION"), None)
    if emis is not None:
        return emis.inputs.get("Color")
    return None


def _mat_to_entry(mat):
    """bpy Material -> ({name, baseColor}, image_or_None).
    The caller packs the image and fills in entry['baseColorTexture']."""
    entry = {"name": mat.name, "baseColor": [0.8, 0.8, 0.8, 1.0]}
    sock = _color_socket(mat)
    if sock is None:
        c = mat.diffuse_color
        entry["baseColor"] = [c[0], c[1], c[2], c[3] if len(c) > 3 else 1.0]
        return entry, None

    if sock.is_linked:
        node = _find_image_node(sock)
        return entry, (node.image if node else None)

    v = sock.default_value
    entry["baseColor"] = [v[0], v[1], v[2], v[3] if len(v) > 3 else 1.0]
    return entry, None


def _entry_to_material(md, base_dir):
    """Build a FLAT (unlit) Blender material from a .chou entry."""
    m = bpy.data.materials.new(md.get("name", "Material"))
    m.use_nodes = True
    nt = m.node_tree
    nt.nodes.clear()
    out = nt.nodes.new("ShaderNodeOutputMaterial"); out.location = (320, 0)
    emis = nt.nodes.new("ShaderNodeEmission"); emis.location = (60, 0)
    emis.inputs["Strength"].default_value = 1.0
    nt.links.new(emis.outputs["Emission"], out.inputs["Surface"])

    bc = md.get("baseColor", [0.8, 0.8, 0.8, 1.0])
    rgba = (bc[0], bc[1], bc[2], bc[3] if len(bc) > 3 else 1.0)
    emis.inputs["Color"].default_value = rgba
    m.diffuse_color = rgba  # viewport solid shading

    tex_rel = md.get("baseColorTexture")
    if tex_rel:
        p = os.path.join(base_dir, tex_rel)
        if os.path.isfile(p):
            img = bpy.data.images.load(p)
            img.pack()  # bundle temp dir is about to be deleted
            node = nt.nodes.new("ShaderNodeTexImage")
            node.image = img
            node.location = (-260, 0)
            nt.links.new(node.outputs["Color"], emis.inputs["Color"])
    return m


# ------------------------------------------------------------------------- write
def write_chou(filepath, objects=None, frame_start=None, frame_end=None):
    """Export `objects` (default: all scene meshes) to a .chou at `filepath`."""
    scene = bpy.context.scene
    view_layer = bpy.context.view_layer
    candidates = [o for o in (objects or view_layer.objects) if o.type == "MESH"]
    if not candidates:
        raise RuntimeError("no mesh objects to export")

    fs = scene.frame_start if frame_start is None else int(frame_start)
    fe = scene.frame_end if frame_end is None else int(frame_end)
    fps = scene.render.fps / scene.render.fps_base

    tmp = tempfile.mkdtemp(prefix="chou_")
    abc_path = os.path.join(tmp, "geometry.abc")

    prev_sel = [o for o in view_layer.objects if o.select_get()]
    prev_active = view_layer.objects.active
    try:
        for o in view_layer.objects:
            try:
                o.select_set(False)
            except RuntimeError:
                pass
        # keep only meshes we can actually select (others are in excluded /
        # disabled collections and can't be exported anyway)
        meshes = []
        for o in candidates:
            try:
                o.select_set(True)
                meshes.append(o)
            except RuntimeError:
                pass
        if not meshes:
            raise RuntimeError("no selectable mesh objects — everything is in an "
                               "excluded or disabled collection")
        view_layer.objects.active = meshes[0]

        bpy.ops.wm.alembic_export(
            filepath=abc_path, start=fs, end=fe,
            selected=True, uvs=True, packuv=True, normals=True,
            vcolors=True, face_sets=True,
        )

        mats = []
        seen = set()
        assigns = {}
        tex_blobs = {}          # bundle relpath -> bytes
        tex_by_image = {}       # image datablock -> bundle relpath (dedupe)
        for ob in meshes:
            slots = []
            for slot in ob.material_slots:
                mat = slot.material
                slots.append(mat.name if mat else None)
                if mat and mat.name not in seen:
                    seen.add(mat.name)
                    entry, img = _mat_to_entry(mat)
                    if img is not None:
                        rel = tex_by_image.get(img)
                        if rel is None:
                            got = _image_bytes(img)
                            if got:
                                ext, data = got
                                base = _safe(os.path.splitext(img.name)[0])
                                rel = "textures/%s%s" % (base, ext)
                                tex_blobs[rel] = data
                                tex_by_image[img] = rel
                        if rel:
                            entry["baseColorTexture"] = rel
                    mats.append(entry)
            assigns[ob.name] = slots

        meta = {
            "format": "chou", "version": CHOU_VERSION,
            "generator": "blender %s / chou_io" % bpy.app.version_string,
            "created": datetime.datetime.utcnow().isoformat() + "Z",
            "fps": round(fps, 6), "frameStart": fs, "frameEnd": fe,
            "upAxis": "Z", "metersPerUnit": float(scene.unit_settings.scale_length),
            "geometry": "geometry.abc",
            "materials": mats,
            "assignments": assigns,
        }
        with open(os.path.join(tmp, "chou.json"), "w") as f:
            json.dump(meta, f, indent=2)

        with zipfile.ZipFile(filepath, "w", zipfile.ZIP_DEFLATED) as z:
            z.write(os.path.join(tmp, "chou.json"), "chou.json")
            z.write(abc_path, "geometry.abc")
            for rel, data in tex_blobs.items():
                z.writestr(rel, data)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
        try:
            for o in view_layer.objects:
                o.select_set(False)
            for o in prev_sel:
                o.select_set(True)
            view_layer.objects.active = prev_active
        except (ReferenceError, RuntimeError):
            pass

    return filepath


# -------------------------------------------------------------------------- read
def read_chou(filepath, into_temp=None):
    """Import a .chou: alembic geometry + rebuilt materials assigned per slot.
    Returns the list of newly created objects."""
    tmp = into_temp or tempfile.mkdtemp(prefix="chou_")
    with zipfile.ZipFile(filepath) as z:
        z.extractall(tmp)

    with open(os.path.join(tmp, "chou.json")) as f:
        meta = json.load(f)

    abc = os.path.join(tmp, meta.get("geometry", "geometry.abc"))
    scene = bpy.context.scene
    before = set(scene.objects)
    bpy.ops.wm.alembic_import(filepath=abc, as_background_job=False)
    new_objs = [o for o in scene.objects if o not in before]

    # Alembic import re-creates placeholder slots from face sets and keeps the
    # per-face material_index — BUT the slot ORDER may differ from export
    # (face sets iterate by name, not by original slot index). So we match each
    # placeholder slot to a .chou material BY NAME, not by position, and swap
    # in place (materials.clear() would wipe every polygon's material_index).
    wanted_names = {md["name"] for md in meta.get("materials", [])}
    for m in list(bpy.data.materials):
        if m.name in wanted_names:  # placeholder created by alembic_import
            m.name = m.name + ".abcslot"

    matmap = {}
    for md in meta.get("materials", []):
        matmap[md["name"]] = _entry_to_material(md, tmp)

    assigns = meta.get("assignments", {})
    for o in new_objs:
        if o.type != "MESH":
            continue
        slots = o.data.materials
        fallback = assigns.get(o.name) or assigns.get(o.name.rsplit(".", 1)[0]) or []
        for i in range(len(slots)):
            cur = slots[i]
            name = None
            if cur is not None:
                name = cur.name[:-8] if cur.name.endswith(".abcslot") else cur.name
            if name not in matmap and i < len(fallback):
                name = fallback[i]
            slots[i] = matmap.get(name) if name in matmap else slots[i]
        # object with no face-set slots at all -> use the assignment list
        if len(slots) == 0 and fallback:
            for name in fallback:
                slots.append(matmap.get(name) if name else None)

    if "frameStart" in meta:
        scene.frame_start = int(meta["frameStart"])
    if "frameEnd" in meta:
        scene.frame_end = int(meta["frameEnd"])
    if meta.get("fps"):
        scene.render.fps = int(round(meta["fps"]))
        scene.render.fps_base = 1.0

    if into_temp is None:
        shutil.rmtree(tmp, ignore_errors=True)
    return new_objs
