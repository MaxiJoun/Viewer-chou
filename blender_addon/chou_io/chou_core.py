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


def _save_image_png(img, dst):
    """Save a (possibly packed / generated) image datablock to dst as PNG,
    without mutating the original datablock."""
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    src = bpy.path.abspath(img.filepath) if img.filepath else ""
    if src and os.path.isfile(src) and src.lower().endswith(".png") and not img.packed_file:
        shutil.copyfile(src, dst)
        return
    tmp = img.copy()
    try:
        tmp.file_format = "PNG"
        tmp.filepath_raw = dst
        tmp.save()
    finally:
        bpy.data.images.remove(tmp)


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
    """bpy Material -> ({name, baseColor[, baseColorTexture]}, {relpath: Image})"""
    entry = {"name": mat.name, "baseColor": [0.8, 0.8, 0.8, 1.0]}
    images = {}
    sock = _color_socket(mat)
    if sock is None:
        c = mat.diffuse_color
        entry["baseColor"] = [c[0], c[1], c[2], c[3] if len(c) > 3 else 1.0]
        return entry, images

    if sock.is_linked and sock.links[0].from_node.type == "TEX_IMAGE" and sock.links[0].from_node.image:
        img = sock.links[0].from_node.image
        rel = "textures/" + _safe(img.name)
        if not rel.lower().endswith(".png"):
            rel += ".png"
        images[rel] = img
        entry["baseColorTexture"] = rel
    elif not sock.is_linked:
        v = sock.default_value
        entry["baseColor"] = [v[0], v[1], v[2], v[3] if len(v) > 3 else 1.0]
    return entry, images


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

        mats, images = [], {}
        seen = set()
        assigns = {}
        for ob in meshes:
            slots = []
            for slot in ob.material_slots:
                mat = slot.material
                slots.append(mat.name if mat else None)
                if mat and mat.name not in seen:
                    seen.add(mat.name)
                    entry, imgs = _mat_to_entry(mat)
                    mats.append(entry)
                    images.update(imgs)
            assigns[ob.name] = slots

        packed = []
        for rel, img in images.items():
            try:
                _save_image_png(img, os.path.join(tmp, rel))
                packed.append(rel)
            except Exception as e:
                print("chou: skipped texture %s (%s)" % (rel, e))

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
            for rel in packed:
                z.write(os.path.join(tmp, rel), rel)
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
    # per-face material_index. Rename those out of the way so our rebuilt
    # materials keep their real names, then swap slot-by-slot WITHOUT clearing
    # the list (materials.clear() would reset every polygon's material_index).
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
        want = assigns.get(o.name) or assigns.get(o.name.rsplit(".", 1)[0])
        if not want:
            continue
        slots = o.data.materials
        for i, name in enumerate(want):
            mat = matmap.get(name) if name else None
            if i < len(slots):
                slots[i] = mat          # replace in place -> material_index kept
            else:
                slots.append(mat)
        while len(slots) > len(want):
            slots.pop()

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
