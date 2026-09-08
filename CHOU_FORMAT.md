# `.chou` — La Chouette bundle format

A `.chou` packs an **Alembic geometry cache** (the animation) together with its
**look** (flat PBR materials, optional base-color textures) in one file.
Nothing else — no `.blend`, no `.usd`.

## Container

A `.chou` is a **ZIP archive** (rename it `.zip` and it opens anywhere):

```
<name>.chou
├─ chou.json          metadata + materials + per-object slot assignment
├─ geometry.abc       the untouched Alembic cache (Ogawa)
└─ textures/          optional PNGs referenced by materials (absent if none)
    └─ *.png
```

## `chou.json`

```jsonc
{
  "format": "chou",
  "version": 1,
  "generator": "blender 5.2.0 LTS / chou_io",
  "created": "2026-09-08T06:27:04Z",

  "fps": 24.0,
  "frameStart": 0,
  "frameEnd": 20,
  "upAxis": "Z",
  "metersPerUnit": 1.0,

  "geometry": "geometry.abc",

  // one entry per unique material used by the exported meshes.
  // Materials are FLAT: a base colour OR a base-colour texture, nothing else
  // (no metallic / roughness / normal). baseColor is LINEAR RGBA (Blender values).
  "materials": [
    { "name": "Body", "baseColor": [0.85, 0.10, 0.08, 1.0] },
    { "name": "Trim", "baseColor": [0.10, 0.55, 0.95, 1.0],
      "baseColorTexture": "textures/trim_basecolor.png" }   // optional, overrides baseColor
  ],

  // object name -> ordered material-slot names.
  // The per-face slot index lives in geometry.abc (Alembic face sets); the
  // reader restores it. So multi-material meshes round-trip.
  "assignments": {
    "Cube": ["Body", "Trim"]
  }
}
```

Fields a reader may ignore: `generator`, `created`, `upAxis`, `metersPerUnit`.
Required to render: `geometry`, `materials`, `assignments`, `fps`.

## Who reads / writes it

| Tool | Role |
|---|---|
| `blender_addon/chou_io/` | Blender addon — **File > Export / Import > La Chouette Bundle (.chou)** |
| `converter/export_chou.py` | headless export (`blender --background scene.blend --python … -- --output x.chou`) |
| `converter/scene_to_sequence.py` | `.chou` → web viewer sequence (`manifest.json` + `frames/*.bin`) |
| `converter/import_server.py` | accepts `.chou` on drag-drop |
| `blender_addon/chou_io/chou_core.py` | **single source of truth** for read/write — the others call it |

## Pipeline

```
Blender scene ──(chou_io / export_chou.py)──▶  firehorn.chou
                                                   │
                          (scene_to_sequence.py)   ▼
                              viewer/models/firehorn/{manifest.json, frames/*.bin}
                                                   │
                                (alembic-viewer.js on the web)
```

The browser never reads the `.chou` or the `.abc` directly — the `.chou` is the
studio handoff file; the per-frame sequence is what the viewer loads.

## Notes / limits (v1)

- Materials are **FLAT / unlit** by design — a base colour or a base-colour
  texture, no metallic / roughness / normal, no light response. On import into
  Blender they are rebuilt as an **Emission** shader (flat there too); on the web
  the viewer uses an unlit material.
- Base-colour **textures** are packed if present (`textures/*.png`). Other maps
  are out of scope on purpose.
- `chou_core` runs inside Blender (needs `bpy`) for both read and write — it uses
  Blender's Alembic import/export and material nodes.
- The look is **constant over the sequence** (Alembic carries no shading anim).
