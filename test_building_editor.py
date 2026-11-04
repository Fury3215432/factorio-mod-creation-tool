import json
from pathlib import Path
import tempfile
import unittest
from core import Catalog, load_game
from installation import find_installation
from machine_model import editable_buildings, source_config, validate_machine, prototypes, MACHINE_TYPES
from project import Project

@unittest.skipUnless(Path('.cache/test-catalog.json').exists(), 'Requires catalog')
class BuildingEditor(unittest.TestCase):
    def test_boiler_form_and_undo(self):
        from app import App
        from unittest.mock import patch
        work = Path(tempfile.mkdtemp(dir=Path('.cache').resolve()))
        with patch('tkinter.messagebox.askyesno', return_value=False), patch('tkinter.messagebox.showerror') as errors:
            app = App()
            app.withdraw()
            self.addCleanup(app.destroy)
            app.autosave_path = work / 'project.json'
            app.root_path = find_installation() or Path('unconfigured-factorio-installation')
            app.mods_path = work / 'mods'
            app.mods_path.mkdir()
            app.catalog = Catalog(json.loads(Path('.cache/test-catalog.json').read_text(encoding='utf-8')))
            app.setup_frame.destroy()
            app.workspace()
            app.new_machine_tab(source=('boiler', 'boiler'), mode='edit')
            tab = app.nametowidget(app.tabs.select())
            self.assertFalse(tab.recipes_panel.winfo_manager())
            self.assertFalse(tab.field_rows['speed'][0].winfo_manager())
            stats = json.loads(tab.advanced_text.get('1.0', 'end'))
            stats['target_temperature'] = 200
            tab.advanced_text.delete('1.0', 'end')
            tab.advanced_text.insert('1.0', json.dumps(stats))
            tab.vars['health'].set('555')
            self.assertTrue(tab.save_changes())
            self.assertFalse(errors.called, errors.call_args_list)
            self.assertEqual(app.catalog.raw['boiler']['boiler']['target_temperature'], 200)
            self.assertEqual(app.catalog.raw['boiler']['boiler']['max_health'], 555)
            self.assertEqual(app.catalog.raw['boiler']['boiler']['energy_consumption'], app.base_raw['boiler']['boiler']['energy_consumption'])
            self.assertNotIn('crafting_speed', app.catalog.raw['boiler']['boiler'])
            self.assertTrue(app.undo())
            self.assertEqual(app.catalog.raw['boiler']['boiler']['max_health'], app.base_raw['boiler']['boiler']['max_health'])

    def test_discovery_preservation_and_engine(self):
        catalog = Catalog(json.loads(Path('.cache/test-catalog.json').read_text(encoding='utf-8')))
        choices = editable_buildings(catalog)
        for key in [('boiler', 'boiler'), ('generator', 'steam-engine'), ('generator', 'steam-turbine')]:
            self.assertIn(key, choices)
        project = Project()
        for kind, name in choices:
            if kind in MACHINE_TYPES:
                continue
            value = source_config(kind, name, catalog)
            value.update(operation='edit', health=value['health'] + 1)
            validate_machine(name, value, catalog, project)
            entity, item = prototypes(name, value, catalog.raw)
            original = catalog.raw[kind][name]
            for field in ('energy_source', 'energy_usage', 'fluid_box', 'output_fluid_box', 'minable', 'crafting_categories', 'module_slots', 'collision_box', 'selection_box'):
                self.assertEqual(entity.get(field), original.get(field), (kind, name, field))
            self.assertEqual(item['type'], value['item_type'])
            project.data['machines'][name] = value
        self.assertGreater(len(project.data['machines']), 30)
        root = find_installation()
        if root:
            work = Path(tempfile.mkdtemp(dir=Path('.cache').resolve()))
            mods = work / 'mods'
            mods.mkdir()
            archive = work / 'recipe-studio-project_1.0.0.zip'
            project.export(archive, catalog, root, mods)
            loaded, _, _ = load_game(root, [archive], work / 'engine')
            for kind, name in [('boiler', 'boiler'), ('generator', 'steam-engine'), ('generator', 'steam-turbine')]:
                self.assertEqual(loaded.raw[kind][name]['max_health'], catalog.raw[kind][name]['max_health'] + 1)
                self.assertEqual(loaded.raw[kind][name]['fluid_box'], catalog.raw[kind][name]['fluid_box'])
