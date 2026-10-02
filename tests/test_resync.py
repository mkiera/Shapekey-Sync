import importlib.util
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest

import bpy


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('shapekey_sync', ROOT / 'shapekey_sync.py')
addon = importlib.util.module_from_spec(spec)
spec.loader.exec_module(addon)


class PanelLayout:
    def __init__(self, actions=None, labels=None, context=None):
        self.actions = actions if actions is not None else []
        self.labels = labels if labels is not None else []
        self.context = dict(context or {})

    def row(self, **kwargs):
        return PanelLayout(self.actions, self.labels, self.context)

    def box(self):
        return self.row()

    def context_pointer_set(self, name, value):
        self.context[name] = value

    def operator(self, name, **kwargs):
        properties = SimpleNamespace()
        self.actions.append((name, properties, dict(self.context)))
        return properties

    def prop(self, data, name, **kwargs):
        self.labels.append(kwargs.get('text'))

    def label(self, **kwargs):
        self.labels.append(kwargs.get('text'))

    def template_list(self, *args, **kwargs):
        pass

    def separator(self):
        pass

    def prop_search(self, *args, **kwargs):
        pass


def panel_layout():
    layout = PanelLayout()
    addon.SHAPEKEYSYNC_PT_panel.draw(SimpleNamespace(layout=layout), bpy.context)
    return layout


def panel_action(name, index=0):
    return [action for action in panel_layout().actions if action[0] == name][index]


def invoke(action):
    name, properties, context = action
    category, operator = name.split('.')
    with bpy.context.temp_override(**context):
        return getattr(getattr(bpy.ops, category), operator)(**vars(properties))


def mesh_object(name):
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata([(0, 0, 0)], [], [])
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.scene.collection.objects.link(obj)
    for key in ('Basis', 'Smile', 'Blink'):
        obj.shape_key_add(name=key)
    return obj


def driver_state(obj, key):
    keys = obj.data.shape_keys
    if not keys.animation_data:
        return None
    curve = keys.animation_data.drivers.find(addon._key_data_path(key))
    if curve is None:
        return None
    driver = curve.driver
    variables = tuple(
        (variable.name, variable.type, tuple(
            (target.id_type, target.id.name_full if target.id else None, target.data_path)
            for target in variable.targets
        ))
        for variable in driver.variables
    )
    return driver.type, driver.expression, driver.use_self, variables


class ResyncTests(unittest.TestCase):
    def setUp(self):
        bpy.ops.wm.read_factory_settings(use_empty=True)
        self.source = mesh_object('Source')
        self.target = mesh_object('Target')
        self.control = bpy.data.objects.new('RigControl', None)
        bpy.context.scene.collection.objects.link(self.control)
        self.control['amount'] = 0.4
        bpy.context.scene.sync_src_obj = self.source

    def rig_driver(self, obj, key):
        curve = obj.data.shape_keys.driver_add(addon._key_data_path(key))
        driver = curve.driver
        driver.type = 'SCRIPTED'
        variable = driver.variables.new()
        variable.name = 'amount'
        variable.type = 'SINGLE_PROP'
        variable.targets[0].id = self.control
        variable.targets[0].data_path = '["amount"]'
        driver.expression = 'amount * 0.5 + 0.1'
        return driver_state(obj, key)

    def sync(self, obj, names):
        scene = bpy.context.scene
        scene.sync_targets.clear()
        scene.sync_targets.add().obj = obj
        bpy.ops.shapekey_sync.refresh_list()
        for item in scene.sync_items:
            item.use = item.name in names
        self.assertEqual(bpy.ops.shapekey_sync.sync(), {'FINISHED'})

    def assert_synced(self, obj, key):
        state = driver_state(obj, key)
        self.assertIsNotNone(state)
        self.assertEqual(state[0], 'AVERAGE')
        self.assertEqual(state[3], (('var', 'SINGLE_PROP', (
            ('OBJECT', self.source.name_full, f'data.shape_keys.{addon._key_data_path(key)}'),
        )),))

    def test_renamed_target_resync_preserves_reused_name_object(self):
        self.sync(self.target, ['Smile'])
        bpy.context.scene.sync_foldouts[0].expanded = True
        self.target.name = 'TargetRenamed'
        unrelated = mesh_object('Target')
        before = self.rig_driver(unrelated, 'Smile')
        self.assertEqual(invoke(panel_action('shapekey_sync.resync_object')), {'FINISHED'})
        self.assertEqual(driver_state(unrelated, 'Smile'), before)
        self.assert_synced(self.target, 'Smile')
        self.assertEqual([(r.obj, r.key) for r in bpy.context.scene.sync_records],
                         [(self.target, 'Smile')])
        self.assertIn('TargetRenamed', panel_layout().labels)
        self.assertTrue(bpy.context.scene.sync_foldouts[0].expanded)

    def test_button_created_before_rename_keeps_target_identity(self):
        self.sync(self.target, ['Smile'])
        action = panel_action('shapekey_sync.resync_object')
        self.target.name = 'TargetRenamed'
        unrelated = mesh_object('Target')
        before = self.rig_driver(unrelated, 'Smile')
        self.assertEqual(invoke(action), {'FINISHED'})
        self.assertEqual(driver_state(unrelated, 'Smile'), before)
        self.assert_synced(self.target, 'Smile')

    def test_resync_without_reused_name_after_rename(self):
        self.sync(self.target, ['Smile'])
        self.target.name = 'TargetRenamed'
        self.assertEqual(invoke(panel_action('shapekey_sync.resync_object')), {'FINISHED'})
        self.assert_synced(self.target, 'Smile')

    def test_renamed_target_unsync_object(self):
        self.sync(self.target, ['Smile'])
        self.target.name = 'TargetRenamed'
        unrelated = mesh_object('Target')
        before = self.rig_driver(unrelated, 'Smile')
        self.assertEqual(invoke(panel_action('shapekey_sync.unsync_object')), {'FINISHED'})
        self.assertIsNone(driver_state(self.target, 'Smile'))
        self.assertEqual(driver_state(unrelated, 'Smile'), before)
        self.assertEqual(len(bpy.context.scene.sync_records), 0)

    def test_renamed_target_unsync_key(self):
        self.sync(self.target, ['Smile'])
        bpy.context.scene.sync_foldouts[0].expanded = True
        action = panel_action('shapekey_sync.unsync_key')
        self.target.name = 'TargetRenamed'
        unrelated = mesh_object('Target')
        before = self.rig_driver(unrelated, 'Smile')
        self.assertEqual(invoke(action), {'FINISHED'})
        self.assertIsNone(driver_state(self.target, 'Smile'))
        self.assertEqual(driver_state(unrelated, 'Smile'), before)

    def test_individual_resync_preserves_excluded_driver(self):
        before = self.rig_driver(self.target, 'Blink')
        self.sync(self.target, ['Smile'])
        self.assertEqual(driver_state(self.target, 'Blink'), before)
        self.assertEqual(invoke(panel_action('shapekey_sync.resync_object')), {'FINISHED'})
        self.assertEqual(driver_state(self.target, 'Blink'), before)
        self.assert_synced(self.target, 'Smile')
        self.assertFalse(bpy.context.scene.sync_items['Blink'].use)
        self.assertEqual([r.key for r in bpy.context.scene.sync_records], ['Smile'])

    def test_batch_resync_preserves_each_targets_selection(self):
        before_blink = self.rig_driver(self.target, 'Blink')
        self.sync(self.target, ['Smile'])
        other = mesh_object('OtherTarget')
        before_smile = self.rig_driver(other, 'Smile')
        self.sync(other, ['Blink'])
        self.assertEqual(bpy.ops.shapekey_sync.resync_all(), {'FINISHED'})
        self.assertEqual(driver_state(self.target, 'Blink'), before_blink)
        self.assertEqual(driver_state(other, 'Smile'), before_smile)
        self.assert_synced(self.target, 'Smile')
        self.assert_synced(other, 'Blink')
        self.assertEqual({(r.obj, r.key) for r in bpy.context.scene.sync_records},
                         {(self.target, 'Smile'), (other, 'Blink')})

    def test_new_keys_require_explicit_sync(self):
        self.sync(self.target, ['Smile'])
        for obj in (self.source, self.target):
            obj.shape_key_add(name='NewKey')
        before = self.rig_driver(self.target, 'NewKey')
        bpy.ops.shapekey_sync.refresh_list()
        self.assertEqual(invoke(panel_action('shapekey_sync.resync_object')), {'FINISHED'})
        self.assertEqual(bpy.ops.shapekey_sync.resync_all(), {'FINISHED'})
        self.assertEqual(driver_state(self.target, 'NewKey'), before)
        self.sync(self.target, ['Smile', 'NewKey'])
        self.assert_synced(self.target, 'NewKey')

    def test_save_reload_preserves_identity_and_exclusions(self):
        before = self.rig_driver(self.target, 'Blink')
        self.sync(self.target, ['Smile'])
        bpy.context.scene.sync_foldouts[0].expanded = True
        self.target.name = 'TargetRenamed'
        unrelated = mesh_object('Target')
        unrelated_before = self.rig_driver(unrelated, 'Smile')
        with tempfile.TemporaryDirectory() as directory:
            blend_path = str(Path(directory) / 'resync.blend')
            bpy.ops.wm.save_as_mainfile(filepath=blend_path)
            bpy.ops.wm.open_mainfile(filepath=blend_path)
        self.source = bpy.data.objects['Source']
        self.target = bpy.data.objects['TargetRenamed']
        unrelated = bpy.data.objects['Target']
        self.assertTrue(bpy.context.scene.sync_foldouts[0].expanded)
        self.assertEqual(invoke(panel_action('shapekey_sync.resync_object')), {'FINISHED'})
        self.assertEqual(bpy.ops.shapekey_sync.resync_all(), {'FINISHED'})
        self.assertEqual(driver_state(self.target, 'Blink'), before)
        self.assertEqual(driver_state(unrelated, 'Smile'), unrelated_before)
        self.assert_synced(self.target, 'Smile')

    def test_untracked_and_missing_context_are_rejected(self):
        self.sync(self.target, ['Smile'])
        unrelated = mesh_object('Untracked')
        before = self.rig_driver(unrelated, 'Smile')
        for operator, properties in (
            (bpy.ops.shapekey_sync.resync_object, {}),
            (bpy.ops.shapekey_sync.unsync_object, {}),
            (bpy.ops.shapekey_sync.unsync_key, {'key_name': 'Smile'}),
        ):
            with self.subTest(operator=operator.idname()):
                self.assertEqual(operator(**properties), {'CANCELLED'})
                with bpy.context.temp_override(sync_target=unrelated):
                    self.assertEqual(operator(**properties), {'CANCELLED'})
                self.assertEqual(driver_state(unrelated, 'Smile'), before)
                self.assert_synced(self.target, 'Smile')

    def test_deleted_target_has_no_panel_action_for_reused_name(self):
        self.sync(self.target, ['Smile'])
        bpy.data.objects.remove(self.target, do_unlink=True)
        unrelated = mesh_object('Target')
        before = self.rig_driver(unrelated, 'Smile')
        actions = panel_layout().actions
        self.assertFalse(any(name == 'shapekey_sync.resync_object'
                             for name, properties, context in actions))
        self.assertEqual(bpy.ops.shapekey_sync.resync_all(), {'FINISHED'})
        self.assertEqual(driver_state(unrelated, 'Smile'), before)

    def test_legacy_foldouts_rebuild_on_load(self):
        before = self.rig_driver(self.target, 'Blink')
        self.sync(self.target, ['Smile'])
        foldout = bpy.context.scene.sync_foldouts[0]
        foldout.property_unset('obj')
        foldout['obj_name'] = 'Target'
        self.target.name = 'TargetRenamed'
        unrelated = mesh_object('Target')
        unrelated_before = self.rig_driver(unrelated, 'Smile')
        with tempfile.TemporaryDirectory() as directory:
            blend_path = str(Path(directory) / 'legacy.blend')
            bpy.ops.wm.save_as_mainfile(filepath=blend_path)
            bpy.ops.wm.open_mainfile(filepath=blend_path)
        self.source = bpy.data.objects['Source']
        self.target = bpy.data.objects['TargetRenamed']
        self.assertEqual(bpy.context.scene.sync_foldouts[0].obj, self.target)
        self.assertEqual(invoke(panel_action('shapekey_sync.resync_object')), {'FINISHED'})
        self.assertEqual(driver_state(bpy.data.objects['Target'], 'Smile'), unrelated_before)
        self.assertEqual(driver_state(self.target, 'Blink'), before)

    def test_reenable_rebuilds_legacy_foldouts_and_cleans_handler(self):
        self.sync(self.target, ['Smile'])
        foldout = bpy.context.scene.sync_foldouts[0]
        foldout.property_unset('obj')
        foldout['obj_name'] = 'Target'
        self.target.name = 'TargetRenamed'
        addon.unregister()
        self.assertNotIn(addon._rebuild_loaded_foldouts, bpy.app.handlers.load_post)
        addon.register()
        self.assertEqual(bpy.context.scene.sync_foldouts[0].obj, self.target)
        self.assertEqual(bpy.app.handlers.load_post.count(addon._rebuild_loaded_foldouts), 1)
        self.assertEqual(invoke(panel_action('shapekey_sync.resync_object')), {'FINISHED'})

    def test_resynced_driver_evaluates_from_changed_source(self):
        before = self.rig_driver(self.target, 'Blink')
        self.sync(self.target, ['Smile'])
        self.source = mesh_object('NewSource')
        bpy.context.scene.sync_src_obj = self.source
        self.source.data.shape_keys.key_blocks['Smile'].value = 0.75
        self.assertEqual(invoke(panel_action('shapekey_sync.resync_object')), {'FINISHED'})
        bpy.context.view_layer.update()
        self.assertAlmostEqual(self.target.data.shape_keys.key_blocks['Smile'].value, 0.75)
        self.assertEqual(driver_state(self.target, 'Blink'), before)
        self.assert_synced(self.target, 'Smile')

    def test_empty_file_does_not_gain_foldout_data(self):
        self.assertFalse(bpy.context.scene.is_property_set('sync_foldouts'))
        self.assertFalse(bpy.context.scene.is_property_set('sync_targets'))


if __name__ == '__main__':
    addon.register()
    try:
        result = unittest.TextTestRunner(verbosity=2).run(
            unittest.defaultTestLoader.loadTestsFromTestCase(ResyncTests)
        )
    finally:
        addon.unregister()
    if not result.wasSuccessful():
        sys.exit(1)
