from installation import find_installation
import copy
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from app import App
from equations import plan_equations
from core import Catalog, load_game
from project import Project


@unittest.skipUnless(Path('.cache/test-catalog.json').exists(), 'Requires cached catalog')
class EquationsTests(unittest.TestCase):
    def fixture(self):
        raw = json.loads(Path('.cache/test-catalog.json').read_text(encoding='utf-8'))
        return SimpleNamespace(catalog=Catalog(raw), base_raw=raw, project=Project())

    def test_parser(self):
        app = self.fixture()
        plan = plan_equations(app, 'copper plate + iron plate = metal alloy')
        self.assertEqual(plan['items'], {'metal_alloy': 'metal alloy'})
        recipe = plan['recipes'][0]
        self.assertEqual(recipe['name'], 'metal_alloy_recipe')
        self.assertEqual([e['name'] for e in recipe['prototype']['ingredients']], ['copper-plate', 'iron-plate'])
        plan = plan_equations(app, '2 * iron plate + iron plate = 3 metal alloy\nmetal alloy + 0.5 water = wet alloy', category='chemistry')
        self.assertEqual(plan['recipes'][0]['prototype']['ingredients'][0]['amount'], 3)
        self.assertEqual(plan['recipes'][0]['prototype']['results'][0]['amount'], 3)
        self.assertEqual(plan['recipes'][1]['prototype']['ingredients'][1], {'type': 'fluid', 'name': 'water', 'amount': .5})
        for text in ('', 'iron plate', 'iron plate =', 'iron plate == metal', 'iron plate + = metal', '-2 iron plate = metal', '0 iron plate = metal', '0.5 iron plate = metal', 'iron  plate = metal', 'iron plate = metal\niron plate = metal'):
            with self.subTest(text=text), self.assertRaises(ValueError):
                plan_equations(app, text)
        app.catalog.recipes['metal_alloy_recipe'] = {}
        plan = plan_equations(app, 'iron plate = metal alloy\ncopper plate = metal alloy')
        self.assertEqual([r['name'] for r in plan['recipes']], ['metal_alloy_recipe_2', 'metal_alloy_recipe_3'])

    def test_preview_apply_roundtrip_and_undo(self):
        work = Path(tempfile.mkdtemp(dir=Path('.cache').resolve()))
        with patch('tkinter.messagebox.askyesno', return_value=False), patch('tkinter.messagebox.showerror') as errors:
            app = App()
            app.withdraw()
            self.addCleanup(app.destroy)
            app.autosave_path = work / 'project.json'
            app.catalog = self.fixture().catalog
            app.root_path = (find_installation() or Path('unconfigured-factorio-installation'))
            app.mods_path = work / 'mods'
            app.mods_path.mkdir()
            app.setup_frame.destroy()
            app.workspace()
            tab = app.equations_tab()
            self.assertIs(app.equations_tab(), tab)
            tab.text.insert('1.0', 'copper plate + iron plate = metal alloy\n2 metal alloy = alloy block + alloy scrap')
            app.update()
            tab.refresh()
            self.assertTrue(tab.dirty)
            self.assertEqual(tab.preview.get_children(), ('metal_alloy_recipe', 'alloy_block_recipe'))
            self.assertFalse(app.project.data['items'])
            self.assertTrue(tab.save_changes())
            self.assertEqual(set(app.project.data['items']), {'metal_alloy', 'alloy_block', 'alloy_scrap'})
            self.assertEqual(app.project.data['items']['metal_alloy']['title'], 'metal alloy')
            self.assertIn(('item', 'metal_alloy'), app.catalog.items)
            self.assertEqual(app.catalog.recipes['alloy_block_recipe']['main_product'], 'alloy_block')
            self.assertEqual(len(app.project.data['recipes']), 2)
            self.assertFalse(tab.dirty)
            self.assertEqual(str(tab.apply_button.cget('state')), 'disabled')
            self.assertTrue(tab.save_changes())
            self.assertEqual(len(app.project.data['recipes']), 2)
            tab.preview.selection_set('metal_alloy_recipe')
            chart = tab.open_selected()
            self.assertEqual(chart.loaded_name, 'metal_alloy_recipe')
            self.assertEqual(chart.recipe.results[0]['name'], 'metal_alloy')
            # Closing this clean chart does not change the applied equation batch.
            chart.destroy()
            reopened = Project.open(app.autosave_path)
            self.assertEqual(reopened.data['recipes']['alloy_block_recipe']['ingredients'][0]['name'], 'metal_alloy')
            if os.environ.get('FACTORIO_TEST_INSTALL'):
                archive = work / 'equations-test_1.0.0.zip'
                app.project.export(archive, Catalog(app.base_raw), app.root_path, app.mods_path, mod_name='equations-test')
                loaded, _, _ = load_game(os.environ['FACTORIO_TEST_INSTALL'], [archive], work / 'engine')
                self.assertEqual(loaded.items[('item', 'metal_alloy')]['localised_name'], 'metal alloy')
                self.assertEqual(loaded.recipes['alloy_block_recipe']['main_product'], 'alloy_block')
            self.assertTrue(app.undo())
            self.assertNotIn(('item', 'metal_alloy'), app.catalog.items)
            self.assertNotIn('metal_alloy_recipe', app.catalog.recipes)
            self.assertTrue(tab.dirty)
            self.assertEqual(tab.preview.get_children(), ('metal_alloy_recipe', 'alloy_block_recipe'))
            self.assertEqual(Project.open(app.autosave_path).data['items'], {})
            # Errors on a later line leave the entire batch unapplied.
            before = copy.deepcopy(app.project.data)
            tab.text.insert('end', '\ninvalid equation')
            self.assertFalse(tab.save_changes())
            self.assertEqual(app.project.data, before)
            self.assertIn('Line 3', errors.call_args.args[1])
