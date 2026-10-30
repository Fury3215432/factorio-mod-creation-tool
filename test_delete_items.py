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
from bulk_items import create_items
from core import Catalog, Recipe, load_game
from delete_items import delete_with_recipes
from recipe_unlocks import assign_unlock


@unittest.skipUnless(Path('.cache/test-catalog.json').exists(), 'Requires cached catalog')
class CascadeItemDeletion(unittest.TestCase):
    def test_menu_deletes_recipes_and_undo_restores_drafts(self):
        work = Path(tempfile.mkdtemp(dir=Path('.cache').resolve()))
        with patch('tkinter.messagebox.askyesno', return_value=False), patch('tkinter.messagebox.showerror') as errors:
            app = App()
            app.withdraw()
            self.addCleanup(app.destroy)
            app.autosave_path = work / 'project.json'
            app.catalog = Catalog(json.loads(Path('.cache/test-catalog.json').read_text(encoding='utf-8')))
            app.root_path = (find_installation() or Path('unconfigured-factorio-installation'))
            app.mods_path = work / 'mods'
            app.mods_path.mkdir()
            app.setup_frame.destroy()
            app.workspace()
            root = app.nametowidget(app.tabs.select())
            create_items(root, 'test component')
            producer = Recipe('produce-component', {'ingredients': [{'type': 'item', 'name': 'iron-plate', 'amount': 1}],
                'results': [{'type': 'item', 'name': 'test_component', 'amount': 1}, {'type': 'item', 'name': 'stone', 'amount': 1}]})
            consumer = Recipe('consume-component', {'ingredients': [{'type': 'item', 'name': 'test_component', 'amount': 1}],
                'results': [{'type': 'item', 'name': 'steel-plate', 'amount': 1}]})
            app.project.save_recipe(producer, 'produce-component', .5, False, custom=True)
            app.project.save_recipe(consumer, 'consume-component', .5, False, custom=True)
            app.refresh_catalog()
            app.pending_tab()
            pending = app.nametowidget(app.tabs.select())
            assign_unlock(pending, 'consume-component', 'automation-2')
            root.load('consume-component')
            root.show_recipe((0,), ('item', 'test_component'), 'produce-component')
            root.recipe.ingredients[0]['amount'] = 9
            root.mark()
            draft = app.new_tab()
            draft.add_entry('ingredients', ('item', 'test_component'), 3)
            project_before = copy.deepcopy(app.project.data)
            tab_count = len(app.tabs.tabs())
            with patch.object(pending.items, 'identify_region', return_value='cell'), patch.object(pending.items, 'identify_row', return_value='test_component'), patch('pending_ui.tk.Menu.tk_popup'):
                pending.context(SimpleNamespace(widget=pending.items, x=5, y=5, x_root=0, y_root=0))
            self.assertEqual(pending.context_menu.entrycget(3, 'label'), 'Delete item and recipes containing it')
            pending.context_menu.invoke(3)
            self.assertFalse(errors.called, errors.call_args_list)
            self.assertNotIn(('item', 'test_component'), app.catalog.items)
            for name in ('produce-component', 'consume-component'):
                self.assertNotIn(name, app.catalog.recipes)
            self.assertFalse(root.recipe.ingredients)
            self.assertFalse(draft.recipe.ingredients)
            self.assertFalse(root.dirty)
            self.assertEqual(len(app.tabs.tabs()), tab_count)
            self.assertFalse(any(e.get('recipe') in ('produce-component', 'consume-component') for e in app.catalog.raw['technology']['automation-2']['effects']))
            if os.environ.get('FACTORIO_TEST_INSTALL'):
                path = work / 'cascade-test_1.0.0.zip'
                app.project.export(path, Catalog(app.base_raw), app.root_path, app.mods_path, mod_name='cascade-test')
                loaded, _, _ = load_game(os.environ['FACTORIO_TEST_INSTALL'], [path], work / 'engine')
                self.assertNotIn(('item', 'test_component'), loaded.items)
                self.assertNotIn('consume-component', loaded.recipes)
                self.assertNotIn('produce-component', loaded.recipes)
            self.assertTrue(app.undo())
            self.assertEqual(app.project.data, project_before)
            self.assertIn(('item', 'test_component'), app.catalog.items)
            self.assertEqual(root.recipe.ingredients[0]['amount'], 9)
            self.assertEqual(draft.recipe.ingredients[0]['amount'], 3)
            self.assertTrue(root.dirty)
            self.assertIn((0,), root.expanded_recipes)
            # Non-recipe references still block deletion without partial changes.
            app.base_raw.setdefault('resource', {})['test-dependent-resource'] = {'type': 'resource', 'name': 'test-dependent-resource',
                'minable': {'result': 'test_component', 'mining_time': 1}}
            app.base_raw['item']['test_component'] = dict(app.catalog.items[('item', 'test_component')], type='item')
            app.loaded_items.add(('item', 'test_component'))
            app.refresh_catalog()
            before_block = copy.deepcopy(app.project.data)
            self.assertFalse(delete_with_recipes(pending, ('item', 'test_component')))
            self.assertIn('test-dependent-resource', errors.call_args.args[1])
            self.assertEqual(app.project.data, before_block)
            self.assertEqual(root.recipe.ingredients[0]['amount'], 9)
            self.assertIn('consume-component', app.catalog.recipes)
