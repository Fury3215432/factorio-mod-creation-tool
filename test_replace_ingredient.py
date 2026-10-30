from installation import find_installation
import copy
import json
import os
from pathlib import Path
import tempfile
import tkinter as tk
from tkinter import ttk
import unittest
from unittest.mock import patch

from app import App, Picker
from core import Catalog, Recipe, load_game, entries
from replace_ingredient import replace_entries, replacement_plan, apply_replacement, replacement_dialog


class IngredientReplacement(unittest.TestCase):
    def test_merge_and_settings(self):
        old, new = ('item', 'old'), ('item', 'new')
        ingredients, changed = replace_entries([{'type': 'item', 'name': 'old', 'amount': 2}, {'type': 'item', 'name': 'new', 'amount': 3}], old, new, 'test')
        self.assertTrue(changed)
        self.assertEqual(ingredients, [{'type': 'item', 'name': 'new', 'amount': 5}])
        with self.assertRaisesRegex(ValueError, 'different ingredient settings'):
            replace_entries([{'type': 'fluid', 'name': 'old', 'amount': 2, 'temperature': 100}, {'type': 'fluid', 'name': 'new', 'amount': 3, 'temperature': 200}], ('fluid', 'old'), ('fluid', 'new'), 'fluid-test')

    @unittest.skipUnless(Path('.cache/test-catalog.json').exists(), 'Requires cached catalog')
    def test_all_recipes_drafts_preview_export_and_undo(self):
        work = Path(tempfile.mkdtemp(dir=Path('.cache').resolve()))
        with patch('tkinter.messagebox.askyesno', return_value=False), patch('tkinter.messagebox.showerror') as errors, patch('tkinter.messagebox.showinfo'):
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
            owner = app.nametowidget(app.tabs.select())
            owner.load('iron-gear-wheel')
            owner.seconds.set('9')
            draft = app.new_tab()
            draft.add_entry('ingredients', ('item', 'iron-plate'), 6)
            custom = Recipe('test-alloy', {'ingredients': [{'type': 'item', 'name': 'iron-plate', 'amount': 2}, {'type': 'item', 'name': 'copper-plate', 'amount': 3}],
                'results': [{'type': 'item', 'name': 'steel-plate', 'amount': 1}]})
            app.project.save_recipe(custom, 'test-alloy', 4, True, custom=True)
            app.refresh_catalog()
            old, new = ('item', 'iron-plate'), ('item', 'copper-plate')
            plan = replacement_plan(app, old, new)
            self.assertIn('iron-gear-wheel', plan)
            self.assertIn('test-alloy', plan)
            before = copy.deepcopy(app.project.data)
            original_gear = copy.deepcopy(app.catalog.recipes['iron-gear-wheel'])
            count, drafts = apply_replacement(owner, old, new)
            self.assertEqual(count, len(plan))
            self.assertGreaterEqual(drafts, 2)
            self.assertEqual(owner.seconds.get(), '9')
            self.assertTrue(owner.dirty)
            self.assertEqual(owner.recipe.ingredients[0]['name'], 'copper-plate')
            self.assertEqual(draft.recipe.ingredients[0]['name'], 'copper-plate')
            self.assertEqual(app.project.data['recipes']['test-alloy']['ingredients'], [{'type': 'item', 'name': 'copper-plate', 'amount': 5}])
            self.assertEqual(app.catalog.recipes['iron-gear-wheel']['results'], original_gear['results'])
            for name in plan:
                self.assertFalse(any((entry['type'], entry['name']) == old for entry in entries(app.catalog.recipes[name], 'ingredients')))
            if os.environ.get('FACTORIO_TEST_INSTALL'):
                # Restrict engine export to base-game recipes; the UI fixture includes expansions.
                selected = {'iron-gear-wheel', 'test-alloy', 'advanced-circuit'}
                engine_project = type(app.project)(app.project.data)
                engine_project.data['recipes'] = {n: r for n, r in engine_project.data['recipes'].items() if n in selected}
                archive = work / 'replacement-test_1.0.0.zip'
                engine_project.export(archive, Catalog(app.base_raw), app.root_path, app.mods_path, mod_name='replacement-test')
                loaded, _, _ = load_game(os.environ['FACTORIO_TEST_INSTALL'], [archive], work / 'engine')
                self.assertEqual(loaded.recipes['iron-gear-wheel']['ingredients'][0]['name'], 'copper-plate')
                self.assertEqual(loaded.recipes['test-alloy']['ingredients'][0]['amount'], 5)
                self.assertEqual(loaded.recipes['iron-gear-wheel']['results'], original_gear['results'])
            self.assertTrue(app.undo())
            self.assertEqual(app.project.data, before)
            self.assertEqual(owner.recipe.ingredients[0]['name'], 'iron-plate')
            self.assertEqual(owner.seconds.get(), '9')
            self.assertEqual(draft.recipe.ingredients[0]['name'], 'iron-plate')
            dialog = replacement_dialog(owner, old)
            next(w for w in dialog.winfo_children() if isinstance(w, ttk.Button)).invoke()
            picker = next(w for w in app.winfo_children() if isinstance(w, Picker))
            self.assertTrue(all(key[0] == 'item' for key in picker.matches))
            index = picker.matches.index(new)
            picker.list.selection_clear(0, 'end')
            picker.list.selection_set(index)
            picker.choose()
            def descendants(widget):
                for child in widget.winfo_children():
                    yield child
                    yield from descendants(child)
            table = next(w for w in descendants(dialog) if isinstance(w, ttk.Treeview))
            self.assertEqual(len(table.get_children()), len(plan))
            apply_button = next(w for w in descendants(dialog) if isinstance(w, ttk.Button) and w.cget('text') == 'Apply replacement')
            self.assertEqual(str(apply_button.cget('state')), 'normal')
            apply_button.invoke()
            self.assertFalse(dialog.winfo_exists())
            self.assertFalse(errors.called, errors.call_args_list)
