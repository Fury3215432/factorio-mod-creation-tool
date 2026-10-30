from installation import find_installation
import json
import os
from pathlib import Path
import tempfile
import tkinter as tk
from tkinter import ttk
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from app import App, Picker
from test_project import make_icon
from core import Catalog, load_game


@unittest.skipUnless(Path('.cache/test-catalog.json').exists(), 'Requires cached real game catalog')
class UnifiedFlow(unittest.TestCase):
    def test_create_item_recipe_load_and_undo(self):
        cache = Path('.cache').resolve()
        work = Path(tempfile.mkdtemp(dir=cache))
        with patch('tkinter.messagebox.askyesno', return_value=True), patch('tkinter.messagebox.showerror') as errors:
            app = App()
            app.withdraw()
            self.addCleanup(app.destroy)
            app.autosave_path = work / 'autosave.json'
            app.catalog = Catalog(json.loads(Path('.cache/test-catalog.json').read_text(encoding='utf-8')))
            app.root_path = (find_installation() or Path('unconfigured-factorio-installation'))
            app.mods_path = work / 'mods'
            app.mods_path.mkdir()
            app.setup_frame.destroy()
            app.workspace()
            tab = app.nametowidget(app.tabs.select())
            self.assertFalse(tab.recipe.ingredients)
            self.assertFalse(tab.recipe.results)
            self.assertEqual(tab.commit_text.get(), 'Save as new recipe')
            with patch('app.tk.Menu') as menu:
                tab.context(SimpleNamespace(x_root=0, y_root=0))
                labels = [c.kwargs['label'] for c in menu.return_value.add_command.call_args_list]
                self.assertEqual(labels, ['Add new ingredient', 'Add new result', 'Load recipe', 'Create item', 'Create item as ingredient', 'Bulk ingredient creation'])
            tab.edit_item()
            dialog = next(w for w in app.winfo_children() if isinstance(w, tk.Toplevel))
            def descendants(widget):
                for child in widget.winfo_children():
                    yield child
                    yield from descendants(child)
            def fill(label, value):
                for row in descendants(dialog):
                    children = row.winfo_children()
                    if children and isinstance(children[0], ttk.Label) and children[0].cget('text') == label:
                        entry = next(w for w in children if isinstance(w, ttk.Entry))
                        entry.delete(0, 'end')
                        entry.insert(0, value)
                        return
                self.fail('Missing field ' + label)
            fill('Item ID', 'undo-component')
            fill('Recipe result amount', '3')
            fill('PNG file', str(make_icon(work / 'icon.png')))
            create = next(w for w in descendants(dialog) if isinstance(w, ttk.Button) and w.cget('text') == 'Create item')
            self.assertEqual(create.pack_info()['side'], 'left')
            create.invoke()
            self.assertIn(('item', 'undo-component'), app.catalog.items)
            self.assertFalse(tab.recipe.results)
            self.assertIn('undo-component', json.loads(app.autosave_path.read_text())['items'])
            tab.name.set('undo-component-recipe')
            tab.add_entry('results', ('item', 'undo-component'))
            self.assertEqual(tab.recipe.results[0]['amount'], 3)
            tab.edit('results', 0)
            quantity_dialog = next(w for w in app.winfo_children() if isinstance(w, tk.Toplevel))
            quantity = next(w for w in quantity_dialog.winfo_children() if isinstance(w, ttk.Entry))
            quantity.delete(0, 'end')
            quantity.insert(0, '5')
            quantity.undo_last_edit()
            quantity.undo_last_edit()
            self.assertEqual(quantity.get(), '3')
            quantity.delete(0, 'end')
            quantity.insert(0, '5')
            next(w for w in quantity_dialog.winfo_children() if isinstance(w, ttk.Button) and w.cget('text') == 'Save changes').invoke()
            self.assertEqual(tab.recipe.results[0]['amount'], 5)
            self.assertTrue(app.undo())
            self.assertEqual(tab.recipe.results[0]['amount'], 3)
            tab.edit('results', 0)
            quantity_dialog = next(w for w in app.winfo_children() if isinstance(w, tk.Toplevel))
            next(w for w in quantity_dialog.winfo_children() if isinstance(w, ttk.Button) and w.cget('text') == 'Remove rectangle').invoke()
            self.assertFalse(tab.recipe.results)
            self.assertTrue(app.undo())
            self.assertEqual(tab.recipe.results[0]['name'], 'undo-component')
            tab.add_entry('ingredients', ('item', 'iron-plate'), 2)
            source_state = tab.snapshot()
            with patch.object(tab.canvas, 'find_withtag', return_value=(1,)), patch.object(tab.canvas, 'gettags', return_value=('ingredients_0',)), patch('app.tk.Menu') as menu:
                tab.context(SimpleNamespace(x_root=0, y_root=0))
                commands = menu.return_value.add_command.call_args_list
                self.assertEqual([c.kwargs['label'] for c in commands], ['Show recipe', 'Use as ingredient in new recipe', 'Use as product in new recipe', 'See all recipes containing this item', 'Replace ingredient in all recipes'])
                for command, side, other in zip(commands[1:], ('ingredients', 'results'), ('results', 'ingredients')):
                    command.kwargs['command']()
                    created = app.nametowidget(app.tabs.select())
                    self.assertIsNot(created, tab)
                    self.assertIsNone(created.loaded_name)
                    self.assertEqual(getattr(created.recipe, side), [{'type': 'item', 'name': 'iron-plate', 'amount': 1}])
                    self.assertFalse(getattr(created.recipe, other))
                    self.assertTrue(created.dirty)
                    created.destroy()
            current_state = tab.snapshot()
            self.assertEqual(vars(current_state.pop('recipe')), vars(source_state.pop('recipe')))
            self.assertEqual(current_state, source_state)
            app.tabs.select(tab)
            app.shortcut('undo')
            self.assertFalse(tab.recipe.ingredients)
            self.assertEqual(len(tab.recipe.results), 1)
            tab.add_entry('ingredients', ('item', 'iron-plate'), 2)
            self.assertTrue(tab.save_changes())
            self.assertIn('undo-component-recipe', app.project.data['recipes'])
            self.assertTrue(app.undo())
            self.assertNotIn('undo-component-recipe', app.project.data['recipes'])
            self.assertTrue(tab.dirty)
            self.assertTrue(tab.save_changes())
            tab.load_recipe_picker()
            picker = next(w for w in app.winfo_children() if isinstance(w, Picker))
            index = picker.matches.index(('recipe', 'iron-gear-wheel'))
            picker.list.selection_clear(0, 'end')
            picker.list.selection_set(index)
            picker.choose()
            self.assertEqual(tab.commit_text.get(), 'Apply edit')
            self.assertEqual(tab.loaded_name, 'iron-gear-wheel')
            self.assertEqual(str(tab.name_entry.cget('state')), 'readonly')
            tab.recipe.ingredients[0]['amount'] = 9
            tab.mark()
            self.assertTrue(app.undo())
            self.assertEqual(tab.recipe.ingredients[0]['amount'], 2)
            tab.recipe.ingredients[0]['amount'] = 7
            tab.mark()
            self.assertTrue(tab.save_changes())
            self.assertEqual(app.project.data['recipes']['iron-gear-wheel']['ingredients'][0]['amount'], 7)
            self.assertTrue(app.undo())
            self.assertNotIn('iron-gear-wheel', app.project.data['recipes'])
            if os.environ.get('FACTORIO_TEST_INSTALL'):
                archive = work / 'recipe-studio-project_1.0.0.zip'
                app.project.export(archive, Catalog(app.base_raw), app.root_path, app.mods_path)
                dump = work / 'engine'
                updated, _, _ = load_game(os.environ['FACTORIO_TEST_INSTALL'], [archive], dump)
                self.assertIn(('item', 'undo-component'), updated.items)
                self.assertEqual(updated.recipes['undo-component-recipe']['results'][0]['amount'], 3)
                self.assertEqual(updated.recipes['iron-gear-wheel']['ingredients'][0]['amount'], 2)
            while app.undo():
                pass
            self.assertNotIn(('item', 'undo-component'), app.catalog.items)
            self.assertEqual(app.project.data['items'], {})
            auto = app.new_tab()
            auto.add_entry('results', ('item', 'copper-ore'))
            self.assertEqual(auto.name.get(), 'copper-ore_recipe')
            auto.add_entry('results', ('item', 'stone'))
            self.assertEqual(auto.name.get(), 'copper-ore_recipe')
            auto.recipe.results[0]['name'] = 'iron-ore'
            auto.mark()
            self.assertEqual(auto.name.get(), 'iron-ore_recipe')
            self.assertTrue(app.undo())
            self.assertEqual(auto.name.get(), 'copper-ore_recipe')
            self.assertEqual(auto.recipe.results[0]['name'], 'copper-ore')
            auto.name.set('my-chosen-id')
            auto.recipe.results[0]['name'] = 'iron-ore'
            auto.mark()
            self.assertEqual(auto.name.get(), 'my-chosen-id')
            auto.edit_item(as_ingredient=True)
            dialog = next(w for w in app.winfo_children() if isinstance(w, tk.Toplevel))
            fill('Item ID', 'auto-added-ingredient')
            fill('Recipe result amount', '4')
            next(w for w in descendants(dialog) if isinstance(w, ttk.Button) and w.cget('text') == 'Create item').invoke()
            self.assertIn(('item', 'auto-added-ingredient'), app.catalog.items)
            self.assertEqual(auto.recipe.ingredients, [{'type': 'item', 'name': 'auto-added-ingredient', 'amount': 4}])
            self.assertTrue(auto.dirty)
            self.assertTrue(app.undo())
            self.assertNotIn(('item', 'auto-added-ingredient'), app.catalog.items)
            self.assertFalse(auto.recipe.ingredients)
            self.assertEqual(auto.name.get(), 'my-chosen-id')
            self.assertFalse(errors.called, errors.call_args_list)
            app.update()


if __name__ == '__main__':
    unittest.main()
