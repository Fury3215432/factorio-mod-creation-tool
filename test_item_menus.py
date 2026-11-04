import json
from pathlib import Path
import tempfile
import tkinter as tk
from tkinter import ttk
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from app import App, Picker
from bulk_items import create_items
from core import Catalog, Recipe
from installation import find_installation


@unittest.skipUnless(Path('.cache/test-catalog.json').exists(), 'Requires cached catalog')
class ItemMenus(unittest.TestCase):
    def test_edit_menus_and_unused_open_recipe(self):
        work = Path(tempfile.mkdtemp(dir=Path('.cache').resolve()))
        with patch('tkinter.messagebox.askyesno', return_value=False), patch('tkinter.messagebox.showerror') as errors:
            app = App(); app.withdraw(); self.addCleanup(app.destroy)
            app.autosave_path = work / 'project.json'
            app.catalog = Catalog(json.loads(Path('.cache/test-catalog.json').read_text(encoding='utf-8')))
            app.root_path = find_installation() or Path('unconfigured-factorio-installation')
            app.mods_path = work / 'mods'; app.mods_path.mkdir()
            app.setup_frame.destroy(); app.workspace()
            chart = app.nametowidget(app.tabs.select())
            create_items(chart, 'menu unused a  menu unused b')
            key = ('item', 'menu_unused_a')
            recipe = Recipe('menu-producer', {'ingredients': [{'type': 'item', 'name': 'iron-plate', 'amount': 1}],
                'results': [{'type': 'item', 'name': key[1], 'amount': 1}]})
            app.project.save_recipe(recipe, recipe.name, 1, False, custom=True)
            app.persist(); app.refresh_catalog()
            app.pending_tab()
            pending = app.nametowidget(app.tabs.select())
            pending.unused.selection_set('item:' + key[1])
            opened = pending.open_unused_recipe()
            self.assertEqual(opened.loaded_name, recipe.name)
            pending.unused.selection_set('item:menu_unused_b')
            empty = pending.open_unused_recipe()
            self.assertIsNone(empty.loaded_name)
            self.assertEqual(empty.recipe.results[0]['name'], 'menu_unused_b')
            app.project.save_recipe(recipe, 'menu-alternative', 2, False, custom=True)
            app.persist(); app.refresh_catalog()
            pending.unused.selection_set('item:' + key[1])
            chooser = pending.open_unused_recipe()
            self.assertIsInstance(chooser, tk.Toplevel)
            next(w for w in chooser.winfo_children() if isinstance(w, ttk.Button)).invoke()
            self.assertEqual(app.nametowidget(app.tabs.select()).loaded_name, 'menu-alternative')
            def invoke_edit(menu):
                index = next(i for i in range(menu.index('end') + 1)
                             if menu.type(i) == 'command' and menu.entrycget(i, 'label') == 'Edit item')
                menu.invoke(index)
            with patch('editors.item_dialog') as edit, patch('tkinter.Menu.tk_popup'):
                menu = tk.Menu(chart, tearoff=False)
                chart.item_context(menu, {'type': key[0], 'name': key[1]}, 'ingredients', (0,))
                invoke_edit(menu); self.assertEqual(edit.call_args.args[1]['name'], key[1])
                pending.item_menu(SimpleNamespace(widget=pending.unused, x_root=0, y_root=0), key)
                invoke_edit(pending.context_menu); self.assertEqual(edit.call_args.args[0], pending)
                picker = Picker(app, lambda value: None, initial=key[1])
                picker.item_context(SimpleNamespace(y=0, x_root=0, y_root=0))
                invoke_edit(picker.context_menu); self.assertEqual(edit.call_args.args[1]['name'], key[1])
                picker.destroy()
                equations = app.equations_tab()
                equations.item_context(SimpleNamespace(x_root=0, y_root=0), key)
                invoke_edit(equations.item_context_menu); self.assertEqual(edit.call_args.args[0], equations)
            self.assertFalse(errors.called, errors.call_args_list)
            from creations_ui import rename_item
            before = json.loads(json.dumps(app.project.data))
            self.assertTrue(rename_item(pending, key, 'Renamed ingredient', 'renamed_ingredient'))
            self.assertNotIn(key[1], app.project.data['items'])
            self.assertEqual(app.project.data['items']['renamed_ingredient']['title'], 'Renamed ingredient')
            self.assertEqual(app.project.data['recipes']['menu-producer']['results'][0]['name'], 'renamed_ingredient')
            self.assertEqual(opened.recipe.results[0]['name'], 'renamed_ingredient')
            self.assertTrue(app.undo()); self.assertEqual(app.project.data, before)
            self.assertEqual(opened.recipe.results[0]['name'], key[1])
            self.assertFalse(rename_item(pending, key, 'Conflict', 'menu_unused_b'))
            self.assertEqual(app.project.data, before); errors.reset_mock()
            self.assertTrue(rename_item(pending, ('item', 'iron-plate'), 'Iron Sheet'))
            self.assertEqual(app.catalog.items['item', 'iron-plate']['localised_name'], 'Iron Sheet')
            self.assertTrue(app.undo()); self.assertEqual(app.project.data, before)
            dialog = rename_item(pending, key)
            self.assertIsInstance(dialog, tk.Toplevel)
            dialog.destroy()
            self.assertFalse(errors.called, errors.call_args_list)

