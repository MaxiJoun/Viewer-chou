"""
La Chouette Bundle (.chou) — Blender import/export addon.

A .chou packs an Alembic geometry cache + flat PBR materials (base color /
metallic / roughness, optional base-color texture) into one zip file, for the
WEB_ALEMBIC preview pipeline. It does NOT contain a .blend or .usd — just the
animation (geometry.abc) and the look.

Install: Edit > Preferences > Add-ons > Install… and pick this folder zipped,
or drop the `chou_io` folder in your Blender addons directory.

Then: File > Export > La Chouette Bundle (.chou)
      File > Import > La Chouette Bundle (.chou)
"""

bl_info = {
    "name": "La Chouette Bundle (.chou)",
    "author": "LACHOUETTE",
    "version": (0, 1, 0),
    "blender": (4, 0, 0),
    "location": "File > Import/Export",
    "description": "Import/Export .chou — Alembic geometry cache + materials bundle",
    "category": "Import-Export",
}

import bpy
from bpy.props import StringProperty, BoolProperty, IntProperty
from bpy_extras.io_utils import ImportHelper, ExportHelper

from . import chou_core


class EXPORT_OT_chou(bpy.types.Operator, ExportHelper):
    """Export selection or scene as a .chou bundle (Alembic + materials)"""
    bl_idname = "export_scene.chou"
    bl_label = "Export .chou"
    bl_options = {"PRESET"}

    filename_ext = ".chou"
    filter_glob: StringProperty(default="*.chou", options={"HIDDEN"})

    use_selection: BoolProperty(
        name="Selection Only", default=False,
        description="Export only selected mesh objects",
    )
    use_scene_range: BoolProperty(
        name="Scene Frame Range", default=True,
        description="Use the scene's start/end frames",
    )
    frame_start: IntProperty(name="Start", default=1)
    frame_end: IntProperty(name="End", default=250)

    def draw(self, context):
        col = self.layout.column()
        col.prop(self, "use_selection")
        col.prop(self, "use_scene_range")
        sub = col.column()
        sub.enabled = not self.use_scene_range
        sub.prop(self, "frame_start")
        sub.prop(self, "frame_end")

    def execute(self, context):
        objs = context.selected_objects if self.use_selection else None
        fs = None if self.use_scene_range else self.frame_start
        fe = None if self.use_scene_range else self.frame_end
        try:
            chou_core.write_chou(self.filepath, objs, fs, fe)
        except Exception as e:
            self.report({"ERROR"}, "chou export failed: %s" % e)
            return {"CANCELLED"}
        self.report({"INFO"}, "Exported %s" % self.filepath)
        return {"FINISHED"}


class IMPORT_OT_chou(bpy.types.Operator, ImportHelper):
    """Import a .chou bundle (Alembic geometry + rebuilt materials)"""
    bl_idname = "import_scene.chou"
    bl_label = "Import .chou"
    bl_options = {"UNDO"}

    filename_ext = ".chou"
    filter_glob: StringProperty(default="*.chou", options={"HIDDEN"})

    def execute(self, context):
        try:
            objs = chou_core.read_chou(self.filepath)
        except Exception as e:
            self.report({"ERROR"}, "chou import failed: %s" % e)
            return {"CANCELLED"}
        self.report({"INFO"}, "Imported %d object(s) from %s" % (len(objs), self.filepath))
        return {"FINISHED"}


def _menu_export(self, context):
    self.layout.operator(EXPORT_OT_chou.bl_idname, text="La Chouette Bundle (.chou)")


def _menu_import(self, context):
    self.layout.operator(IMPORT_OT_chou.bl_idname, text="La Chouette Bundle (.chou)")


_classes = (EXPORT_OT_chou, IMPORT_OT_chou)


def register():
    for c in _classes:
        bpy.utils.register_class(c)
    bpy.types.TOPBAR_MT_file_export.append(_menu_export)
    bpy.types.TOPBAR_MT_file_import.append(_menu_import)


def unregister():
    bpy.types.TOPBAR_MT_file_export.remove(_menu_export)
    bpy.types.TOPBAR_MT_file_import.remove(_menu_import)
    for c in reversed(_classes):
        bpy.utils.unregister_class(c)


if __name__ == "__main__":
    register()
