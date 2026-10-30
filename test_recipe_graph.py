from installation import find_installation
import copy
import json
from pathlib import Path
import tempfile
import tkinter as tk
from tkinter import ttk
import unittest
from unittest.mock import patch

from app import App
from core import Catalog, Recipe


@unittest.skipUnless(Path('.cache/test-catalog.json').exists(), 'Requires cached catalog')
class MultiRecipeGraph(unittest.TestCase):
    def test_expand_nested_choose_collapse_refresh_and_undo(self):
        work = Path(tempfile.mkdtemp(dir=Path('.cache').resolve()))
        with patch('tkinter.messagebox.askyesno', return_value=False), patch('tkinter.messagebox.showerror') as errors, patch('tkinter.messagebox.showinfo') as info:
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
            tab = app.nametowidget(app.tabs.select())
            tab.load('electronic-circuit')
            original = copy.deepcopy(vars(tab.recipe))
            count = len(app.tabs.tabs())
            index = next(i for i, e in enumerate(tab.recipe.ingredients) if e['name'] == 'copper-cable')
            path = (index,)
            self.assertTrue(tab.show_recipe(path, ('item', 'copper-cable'), 'copper-cable'))
            self.assertEqual(len(app.tabs.tabs()), count)
            self.assertEqual(tab.expanded_recipes[path]['name'], 'copper-cable')
            self.assertEqual(len(tab.canvas.find_withtag('recipe-link')), 1)
            self.assertFalse(tab.dirty)
            self.assertEqual(vars(tab.recipe), original)
            child_path = path + (0,)
            self.assertTrue(tab.show_recipe(child_path, ('item', 'copper-plate'), 'copper-plate'))
            self.assertEqual(len(tab.expanded_recipes), 2)
            self.assertEqual(len(tab.canvas.find_withtag('recipe-link')), 2)
            self.assertEqual(tab.graph_width, 3120)
            self.assertTrue(tab.canvas.find_withtag('craft:' + '.'.join(map(str, child_path))))
            tab.collapse_recipes(path)
            self.assertFalse(tab.expanded_recipes)
            self.assertTrue(app.undo())
            self.assertEqual(len(tab.expanded_recipes), 2)
            self.assertEqual(len(tab.canvas.find_withtag('recipe-link')), 2)
            self.assertEqual(vars(tab.recipe), original)
            self.assertFalse(tab.show_recipe(child_path + (0,), ('item', 'unobtainable-test-item')))
            self.assertTrue(info.called)
            alternate = Recipe('alternate-cable', {'ingredients': [{'type': 'item', 'name': 'copper-plate', 'amount': 2}],
                'results': [{'type': 'item', 'name': 'copper-cable', 'amount': 4}, {'type': 'item', 'name': 'stone', 'amount': 1}]})
            app.project.save_recipe(alternate, 'alternate-cable', 2, True, custom=True)
            app.refresh_catalog()
            tab.show_recipe(path, ('item', 'copper-cable'))
            dialog = next(w for w in app.winfo_children() if isinstance(w, tk.Toplevel))
            listing = next(w for w in dialog.winfo_children() if isinstance(w, tk.Listbox))
            names = list(listing.get(0, 'end'))
            listing.selection_clear(0, 'end')
            listing.selection_set(names.index('alternate-cable'))
            next(w for w in dialog.winfo_children() if isinstance(w, ttk.Button)).invoke()
            self.assertEqual(tab.expanded_recipes[path]['name'], 'alternate-cable')
            self.assertNotIn(child_path, tab.expanded_recipes)
            products = [node['value']['name'] for node in tab.graph_nodes.values() if node.get('path') == path and node['side'] == 'results']
            self.assertEqual(products, ['copper-cable', 'stone'])
            # Editing the expanded source updates its display on the original graph.
            source = tab.edit_expanded_recipe(path)
            source.recipe.ingredients[0]['amount'] = 7
            source.mark()
            self.assertTrue(source.save_changes())
            node = next(n for n in tab.graph_nodes.values() if n['path'] == path and n['side'] == 'ingredients')
            self.assertEqual(node['value']['amount'], 7)
            self.assertEqual(vars(tab.recipe), original)
            self.assertFalse(tab.dirty)
            # Quantities in the primary recipe remain editable with expansions open.
            tab.recipe.ingredients[index]['amount'] = 11
            tab.mark()
            tab.draw()
            self.assertTrue(app.undo())
            self.assertEqual(vars(tab.recipe), original)
            self.assertIn(path, tab.expanded_recipes)
            # Loaded recipes cannot expand recursively into themselves.
            self.assertFalse(tab.show_recipe(path + (0,), ('item', 'copper-cable'), 'alternate-cable'))
            tab.load('iron-gear-wheel')
            self.assertFalse(tab.expanded_recipes)
            self.assertFalse(errors.called, errors.call_args_list)
