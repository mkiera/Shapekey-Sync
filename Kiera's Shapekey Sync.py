bl_info = {
    "name": "Kiera's ShapeKey Sync",
    "author": "Kiera",
    "version": (1, 2),
    "blender": (4, 3, 1),
    "location": "View3D > Sidebar > ShapeKey Sync",
    "description": "Batch sync and unsync shapekey drivers with preview, tracking records internally",
    "category": "Animation",
}

import bpy
from bpy.props import BoolProperty
from bpy.app import timers
from bpy.app.handlers import persistent

# ------------------------------------------------------------------------
#    Helpers
# ------------------------------------------------------------------------

_SHAPE_KEY_OBJECT_TYPES = {'MESH', 'CURVE', 'SURFACE', 'LATTICE'}


def _get_shape_keys(obj):
    """Return an object's shape key datablock, or None if it has none."""
    if obj is None or obj.data is None:
        return None
    return getattr(obj.data, "shape_keys", None)


def _shape_key_object_poll(self, obj):
    """Restrict object pickers to types that support shape keys."""
    return obj.type in _SHAPE_KEY_OBJECT_TYPES


def _target_object_poll(self, obj):
    """Targets must support shape keys and differ from the source object."""
    if not _shape_key_object_poll(self, obj):
        return False
    scn = getattr(bpy.context, "scene", None)
    return scn is None or scn.sync_src_obj != obj


def _key_data_path(name):
    """RNA data path for a shape key's value, with the name safely escaped."""
    return f'key_blocks["{bpy.utils.escape_identifier(name)}"].value'

# ------------------------------------------------------------------------
#    Property Groups
# ------------------------------------------------------------------------

def _ensure_initial_target_slot():
    """Adds an initial target slot if the list is empty."""
    if len(bpy.context.scene.sync_targets) == 0:
        bpy.context.scene.sync_targets.add()

@persistent
def _on_file_load(_):
    """Ensure initial slot when a file is loaded."""
    _ensure_initial_target_slot()

def _target_obj_update(self, context):
    """Auto‑manage the blank slot at the end of the target list."""
    from bpy import context as _bpy_ctx  # local import to avoid shadowing
    scn = getattr(context, "scene", None) or _bpy_ctx.scene
    if not scn:
        return

    sync_targets = scn.sync_targets
    
    # If this is the last slot and the user just picked an object → add a new blank
    if self == sync_targets[-1] and self.obj:
        sync_targets.add()

    # Trim extra blank slots at the end (leave at most one)
    while len(sync_targets) > 1 and not sync_targets[-1].obj and not sync_targets[-2].obj:
        sync_targets.remove(len(sync_targets) - 1)

class SyncItem(bpy.types.PropertyGroup):
    name: bpy.props.StringProperty()
    use: bpy.props.BoolProperty(default=True)

class TargetItem(bpy.types.PropertyGroup):
    obj: bpy.props.PointerProperty(
        type=bpy.types.Object,
        poll=_target_object_poll,
        update=_target_obj_update,
    )

class RecordItem(bpy.types.PropertyGroup):
    obj: bpy.props.PointerProperty(type=bpy.types.Object)
    key: bpy.props.StringProperty()

class FoldoutItem(bpy.types.PropertyGroup):
    obj_name: bpy.props.StringProperty()
    expanded: bpy.props.BoolProperty(default=False)

# ------------------------------------------------------------------------
#    Core Sync Functions
# ------------------------------------------------------------------------
def _purge_dead_records(scn):
    """Drop tracking records whose object has been deleted from the file."""
    if all(rec.obj is not None for rec in scn.sync_records):
        return
    survivors = [(rec.obj, rec.key) for rec in scn.sync_records if rec.obj is not None]
    scn.sync_records.clear()
    for obj, key in survivors:
        rec = scn.sync_records.add()
        rec.obj = obj
        rec.key = key


def sync_shapekey_drivers(src_obj, tgt_obj, key_names, records):
    src_keys = _get_shape_keys(src_obj)
    tgt_keys = _get_shape_keys(tgt_obj)
    if not src_keys or not tgt_keys:
        return 0
    count = 0
    for name in key_names:
        if name in src_keys.key_blocks and name in tgt_keys.key_blocks:
            path = _key_data_path(name)
            try:
                tgt_keys.driver_remove(path)
            except Exception:
                pass
            fcurve = tgt_keys.driver_add(path)
            driver = fcurve.driver
            driver.type = 'AVERAGE'
            var = driver.variables.new()
            var.name = 'var'
            var.targets[0].id = src_obj
            var.targets[0].data_path = f'data.shape_keys.{_key_data_path(name)}'
            if not any(rec.obj == tgt_obj and rec.key == name for rec in records):
                rec = records.add()
                rec.obj = tgt_obj
                rec.key = name
            count += 1
    return count


def unsync_records(records):
    removed = 0
    for rec in records:
        shape_keys = _get_shape_keys(rec.obj)
        if shape_keys:
            try:
                shape_keys.driver_remove(_key_data_path(rec.key))
                removed += 1
            except Exception:
                pass
    records.clear()
    return removed


def unsync_selected(records, indices):
    removed = 0
    keep = []
    for idx, rec in enumerate(records):
        if idx in indices:
            shape_keys = _get_shape_keys(rec.obj)
            if shape_keys:
                try:
                    shape_keys.driver_remove(_key_data_path(rec.key))
                    removed += 1
                except Exception:
                    pass
        elif rec.obj is not None:
            keep.append((rec.obj, rec.key))
    records.clear()
    for obj, key in keep:
        nr = records.add()
        nr.obj = obj
        nr.key = key
    return removed


def _update_preview(context):
    scn = context.scene
    key = scn.preview_key
    val = max(0.0, min(scn.preview_value, 1.0))
    src = scn.sync_src_obj
    targets = [t.obj for t in scn.sync_targets if t.obj]
    if key:
        src_keys = _get_shape_keys(src)
        if src_keys and key in src_keys.key_blocks:
            src_keys.key_blocks[key].value = val
        for obj in targets:
            obj_keys = _get_shape_keys(obj)
            if obj_keys and key in obj_keys.key_blocks:
                obj_keys.key_blocks[key].value = val

def _refresh_key_list(context):
    """Refresh the key list based on current source and target objects."""
    scn = context.scene
    scn.sync_items.clear()
    names = set()
    src_keys = _get_shape_keys(scn.sync_src_obj)
    if src_keys:
        names.update(src_keys.key_blocks.keys())
    for t in scn.sync_targets:
        tgt_keys = _get_shape_keys(t.obj)
        if tgt_keys:
            names.update(tgt_keys.key_blocks.keys())
    for name in sorted(names):
        itm = scn.sync_items.add()
        itm.name = name
        itm.use = True

def _source_obj_update(self, context):
    """Update key list when source object changes."""
    _refresh_key_list(context)

# ------------------------------------------------------------------------
#    Foldout Helper
# ------------------------------------------------------------------------
def rebuild_foldouts(scn):
    old = {f.obj_name: f.expanded for f in scn.sync_foldouts}
    scn.sync_foldouts.clear()
    seen = []
    for rec in scn.sync_records:
        if rec.obj is None:
            continue
        name = rec.obj.name
        if name not in seen:
            seen.append(name)
            f = scn.sync_foldouts.add()
            f.obj_name = name
            f.expanded = old.get(name, False)

# ------------------------------------------------------------------------
#    Operators
# ------------------------------------------------------------------------
class SHAPEKEYSYNC_OT_refresh(bpy.types.Operator):
    bl_idname = "shapekey_sync.refresh_list"
    bl_label = "Refresh Key List"
    def execute(self, context):
        _refresh_key_list(context)
        return {'FINISHED'}

class SHAPEKEYSYNC_OT_sync(bpy.types.Operator):
    bl_idname = "shapekey_sync.sync"
    bl_label = "Sync ShapeKeys"
    bl_options = {'REGISTER', 'UNDO'}
    def execute(self, context):
        scn = context.scene
        _purge_dead_records(scn)
        src = scn.sync_src_obj
        targets = [t.obj for t in scn.sync_targets if t.obj and t.obj != src]
        keys = [i.name for i in scn.sync_items if i.use]
        recs = scn.sync_records
        if not src or not targets or not keys:
            self.report({'ERROR'}, "Set source, targets, and keys to sync.")
            return {'CANCELLED'}
        total = sum(sync_shapekey_drivers(src, obj, keys, recs) for obj in targets)
        rebuild_foldouts(scn)
        self.report({'INFO'}, f"Synced {total} drivers across {len(targets)} objects.")
        return {'FINISHED'}

class SHAPEKEYSYNC_OT_unsync_all(bpy.types.Operator):
    bl_idname = "shapekey_sync.unsync_all"
    bl_label = "Unsync All"
    bl_options = {'REGISTER', 'UNDO'}
    def execute(self, context):
        scn = context.scene
        _purge_dead_records(scn)
        removed = unsync_records(scn.sync_records)
        rebuild_foldouts(scn)
        self.report({'INFO'}, f"Removed {removed} drivers.")
        return {'FINISHED'}

class SHAPEKEYSYNC_OT_unsync_key(bpy.types.Operator):
    bl_idname = "shapekey_sync.unsync_key"
    bl_label = "Unsync Key"
    bl_options = {'REGISTER', 'UNDO'}
    obj_name: bpy.props.StringProperty()
    key_name: bpy.props.StringProperty()
    def execute(self, context):
        scn = context.scene
        _purge_dead_records(scn)
        indices = [i for i, rec in enumerate(scn.sync_records)
                   if rec.obj.name == self.obj_name and rec.key == self.key_name]
        unsync_selected(scn.sync_records, indices)
        rebuild_foldouts(scn)
        return {'FINISHED'}

class SHAPEKEYSYNC_OT_unsync_object(bpy.types.Operator):
    bl_idname = "shapekey_sync.unsync_object"
    bl_label = "Unsync Object"
    bl_options = {'REGISTER', 'UNDO'}
    obj_name: bpy.props.StringProperty()
    def execute(self, context):
        scn = context.scene
        _purge_dead_records(scn)
        indices = [i for i, rec in enumerate(scn.sync_records) if rec.obj.name == self.obj_name]
        unsync_selected(scn.sync_records, indices)
        rebuild_foldouts(scn)
        return {'FINISHED'}

class SHAPEKEYSYNC_OT_resync_object(bpy.types.Operator):
    """Resync all recorded keys for this target object
    (and pick up any NEW keys that now exist on it)."""
    bl_idname = "shapekey_sync.resync_object"
    bl_label = "Resync Object"
    bl_options = {'REGISTER', 'UNDO'}

    obj_name: bpy.props.StringProperty()

    def execute(self, context):
        scn = context.scene
        src = scn.sync_src_obj
        if not src:
            self.report({'ERROR'}, "No source object set.")
            return {'CANCELLED'}

        _purge_dead_records(scn)
        tgt = bpy.data.objects.get(self.obj_name)
        if not tgt:
            self.report({'ERROR'}, f"Target '{self.obj_name}' not found.")
            return {'CANCELLED'}

        if tgt == src:
            self.report({'ERROR'}, "Cannot resync the source object onto itself.")
            return {'CANCELLED'}

        # gather keys already tracked for this object
        keys = {rec.key for rec in scn.sync_records if rec.obj.name == self.obj_name}

        # remove existing drivers/records to avoid duplicates
        idxs = [i for i, rec in enumerate(scn.sync_records) if rec.obj.name == self.obj_name]
        if idxs:
            unsync_selected(scn.sync_records, idxs)

        # optionally pick up *new* shape keys present on the object
        tgt_keys = _get_shape_keys(tgt)
        if tgt_keys:
            for kb in tgt_keys.key_blocks:
                if kb.name not in keys:
                    keys.add(kb.name)

        sync_shapekey_drivers(src, tgt, list(keys), scn.sync_records)
        rebuild_foldouts(scn)
        self.report({'INFO'}, f"Resynced {len(keys)} keys on '{self.obj_name}'.")
        return {'FINISHED'}

# ------------------------------------------------------------------------
#    Operators (Resync All)
# ------------------------------------------------------------------------
class SHAPEKEYSYNC_OT_resync_all(bpy.types.Operator):
    """Resync every object currently listed in Synced Keys"""
    bl_idname = "shapekey_sync.resync_all"
    bl_label = "Resync All Objects"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        scn = context.scene
        src = scn.sync_src_obj
        if not src:
            self.report({'ERROR'}, "No source object set.")
            return {'CANCELLED'}

        _purge_dead_records(scn)
        # build mapping of target -> keys
        obj_keys = {}
        for rec in scn.sync_records:
            obj_keys.setdefault(rec.obj, set()).add(rec.key)

        total_keys = 0
        for tgt, keys in obj_keys.items():
            if tgt == src:
                continue

            # wipe old drivers/records for this object
            idxs = [i for i, r in enumerate(scn.sync_records) if r.obj == tgt]
            if idxs:
                unsync_selected(scn.sync_records, idxs)

            # include any new shapekeys that may have been added
            tgt_keys = _get_shape_keys(tgt)
            if tgt_keys:
                for kb in tgt_keys.key_blocks:
                    keys.add(kb.name)

            sync_shapekey_drivers(src, tgt, list(keys), scn.sync_records)
            total_keys += len(keys)

        rebuild_foldouts(scn)
        self.report({'INFO'}, f"Resynced {total_keys} keys on {len(obj_keys)} objects.")
        return {'FINISHED'}

# ------------------------------------------------------------------------
#    UI Lists
# ------------------------------------------------------------------------
class SHAPEKEYSYNC_UL_list_keys(bpy.types.UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        layout.prop(item, "use", text="")
        layout.label(text=item.name)

class SHAPEKEYSYNC_UL_list_targets(bpy.types.UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        layout.prop(item, "obj", text="")

# ------------------------------------------------------------------------
#    Panel
# ------------------------------------------------------------------------
class SHAPEKEYSYNC_PT_panel(bpy.types.Panel):
    bl_label = "Kiera's ShapeKey Sync v1.2"
    bl_idname = "SHAPEKEYSYNC_PT_panel"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'ShapeKey Sync'

    def draw(self, context):
        scn = context.scene
        layout = self.layout

        # Source & Targets
        layout.prop(scn, 'sync_src_obj', text='Source Object')
        row = layout.row()
        row.template_list('SHAPEKEYSYNC_UL_list_targets', '', scn, 'sync_targets', scn, 'sync_target_index', rows=3)

        # Key List Foldout
        row = layout.row()
        icon = 'TRIA_DOWN' if scn.sync_key_list_expanded else 'TRIA_RIGHT'
        row.prop(scn, 'sync_key_list_expanded', icon=icon, emboss=False, text='Key List')
        if scn.sync_key_list_expanded:
            box = layout.box()
            box.operator('shapekey_sync.refresh_list', icon='FILE_REFRESH', text='Refresh List')
            box.template_list('SHAPEKEYSYNC_UL_list_keys', '', scn, 'sync_items', scn, 'sync_index', rows=6)

        # Sync button always visible
        layout.operator('shapekey_sync.sync', icon='DRIVER')

        # Synced Keys Hierarchy
        layout.separator()
        layout.label(text='Synced Keys:')
        for f in scn.sync_foldouts:
            box = layout.box()
            row = box.row()
            icon = 'TRIA_DOWN' if f.expanded else 'TRIA_RIGHT'
            row.prop(f, 'expanded', icon=icon, emboss=False, text=f.obj_name)
            re_btn = row.operator('shapekey_sync.resync_object', text='', icon='FILE_REFRESH')
            re_btn.obj_name = f.obj_name
            delete_op = row.operator('shapekey_sync.unsync_object', text='', icon='X')
            delete_op.obj_name = f.obj_name

            if f.expanded:
                for rec in scn.sync_records:
                    if rec.obj and rec.obj.name == f.obj_name:
                        r = box.row(align=True)
                        r.label(text=rec.key)
                        op = r.operator('shapekey_sync.unsync_key', text='', icon='X')
                        op.obj_name = f.obj_name
                        op.key_name = rec.key

# Resync ALL objects (global button)
        layout.operator('shapekey_sync.resync_all', icon='FILE_REFRESH')
        layout.operator('shapekey_sync.unsync_all', icon='X')

        # Preview with search
        if scn.sync_items:
            layout.separator()
            layout.prop_search(scn, 'preview_key', scn, 'sync_items', text='Preview Key')
            layout.prop(scn, 'preview_value', text='Value')

# ------------------------------------------------------------------------
#    Registration
# ------------------------------------------------------------------------
classes = [
    SyncItem, TargetItem, RecordItem, FoldoutItem,
    SHAPEKEYSYNC_OT_refresh, SHAPEKEYSYNC_OT_sync,
    SHAPEKEYSYNC_OT_unsync_all,
    SHAPEKEYSYNC_OT_unsync_key, SHAPEKEYSYNC_OT_unsync_object,
    SHAPEKEYSYNC_UL_list_keys, SHAPEKEYSYNC_UL_list_targets,
    SHAPEKEYSYNC_PT_panel, SHAPEKEYSYNC_OT_resync_object, SHAPEKEYSYNC_OT_resync_all
]

def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.Scene.sync_src_obj = bpy.props.PointerProperty(
        type=bpy.types.Object,
        poll=_shape_key_object_poll,
        update=_source_obj_update
    )
    bpy.types.Scene.sync_targets = bpy.props.CollectionProperty(type=TargetItem)
    bpy.types.Scene.sync_target_index = bpy.props.IntProperty()
    bpy.types.Scene.sync_items = bpy.props.CollectionProperty(type=SyncItem)
    bpy.types.Scene.sync_index = bpy.props.IntProperty()
    bpy.types.Scene.preview_key = bpy.props.StringProperty()
    bpy.types.Scene.preview_value = bpy.props.FloatProperty(
        name='Value', min=0.0, max=1.0, update=lambda self, ctx: _update_preview(ctx)
    )
    bpy.types.Scene.sync_records = bpy.props.CollectionProperty(type=RecordItem)
    bpy.types.Scene.sync_foldouts = bpy.props.CollectionProperty(type=FoldoutItem)
    bpy.types.Scene.sync_key_list_expanded = BoolProperty(default=False)

    bpy.app.handlers.load_post.append(_on_file_load)
    timers.register(_ensure_initial_target_slot)

def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
    del bpy.types.Scene.sync_src_obj
    del bpy.types.Scene.sync_targets
    del bpy.types.Scene.sync_target_index
    del bpy.types.Scene.sync_items
    del bpy.types.Scene.sync_index
    del bpy.types.Scene.preview_key
    del bpy.types.Scene.preview_value
    del bpy.types.Scene.sync_records
    del bpy.types.Scene.sync_foldouts
    del bpy.types.Scene.sync_key_list_expanded
    
    bpy.app.handlers.load_post.remove(_on_file_load)

if __name__ == "__main__":
    register()
