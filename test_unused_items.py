from installation import find_installation
import json
from pathlib import Path
import tempfile
import tkinter as tk
from tkinter import ttk
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app import App
from bulk_items import create_items
from core import Catalog, Recipe
from project import Project


class UnusedItems(unittest.TestCase):
    def test_finished_and_ingredient_detection(self):
        catalog = Catalog({'item': {
            'unused': {'type': 'item', 'stack_size': 100},
            'used': {'type': 'item', 'stack_size': 100},
            'belt': {'type': 'item', 'stack_size': 100, 'place_result': 'belt'},
            'equipment': {'type': 'item', 'stack_size': 100, 'placed_as_equipment_result': 'battery'},
            'marked': {'type': 'item', 'stack_size': 100}},
            'tool': {'science': {'type': 'tool', 'stack_size': 100}},
            'recipe': {'produce': {'ingredients': [['used', 2]], 'results': [{'type': 'item', 'name': 'unused', 'amount': 1}]}}})
        project = Project()
        project.data['items']['marked'] = {'kind': 'item', 'finished_product': True}
        self.assertEqual(project.items_unused(catalog, catalog.items), [('item', 'unused')])

    @unittest.skipUnless(Path('.cache/test-catalog.json').exists(), 'Requires cached catalog')
    def test_mark_finished_from_pending_persists_and_undoes(self):
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
            owner = app.nametowidget(app.tabs.select())
            create_items(owner, 'loose component')
            app.loaded_items.update({('item', 'inserter'), ('item', 'transport-belt'), ('item', 'assembling-machine-1')})
            app.refresh_catalog()
            app.pending_tab()
            pending = app.nametowidget(app.tabs.select())
            self.assertEqual(pending.unused.get_children(), ('item:loose_component',))
            tab_count = len(app.tabs.tabs())
            with patch.object(pending.unused, 'identify_region', return_value='cell'), patch.object(pending.unused, 'identify_row', return_value='item:loose_component'), patch('pending_ui.tk.Menu.tk_popup'):
                pending.context(SimpleNamespace(widget=pending.unused, x=5, y=5, x_root=0, y_root=0))
            self.assertEqual(pending.context_menu.entrycget(2, 'label'), 'Delete item')
            pending.context_menu.invoke(2)
            self.assertNotIn(('item', 'loose_component'), app.catalog.items)
            self.assertFalse(pending.unused.get_children())
            self.assertEqual(len(app.tabs.tabs()), tab_count)
            self.assertEqual(app.tabs.select(), str(pending))
            self.assertNotIn('loose_component', Project.open(app.autosave_path).data['items'])
            self.assertTrue(app.undo())
            self.assertEqual(pending.unused.get_children(), ('item:loose_component',))
            pending.unused.selection_set('item:loose_component')
            pending.edit_unused()
            dialog = next(w for w in app.winfo_children() if isinstance(w, tk.Toplevel))
            def descendants(widget):
                for child in widget.winfo_children():
                    yield child
                    yield from descendants(child)
            checkbox = next(w for w in descendants(dialog) if isinstance(w, ttk.Checkbutton) and w.cget('text') == 'Mark as finished product')
            checkbox.invoke()
            next(w for w in descendants(dialog) if isinstance(w, ttk.Button) and w.cget('text') == 'Save item').invoke()
            self.assertFalse(errors.called, errors.call_args_list)
            self.assertFalse(pending.unused.get_children())
            self.assertTrue(Project.open(app.autosave_path).data['items']['loose_component']['finished_product'])
            self.assertTrue(pending.items.get_children())
            self.assertIn('item:loose_component', pending.recipes.get_children())
            self.assertNotIn('finished_product', app.project.item_prototype('loose_component'))
            self.assertTrue(app.undo())
            self.assertEqual(pending.unused.get_children(), ('item:loose_component',))
            consume = Recipe('consume-component', {'ingredients': [{'type': 'item', 'name': 'loose_component', 'amount': 1}], 'results': [{'type': 'item', 'name': 'iron-plate', 'amount': 1}]})
            app.project.save_recipe(consume, 'consume-component', .5, True, custom=True)
            app.refresh_catalog()
            self.assertFalse(pending.unused.get_children())
            def check_context(tree, row_id, expected_recipe):
                with patch.object(tree, 'identify_region', return_value='cell'), patch.object(tree, 'identify_row', return_value=row_id), patch('pending_ui.tk.Menu.tk_popup'):
                    pending.context(SimpleNamespace(widget=tree, x=5, y=5, x_root=0, y_root=0))
                self.assertTrue(pending.context_menu.winfo_exists())
                self.assertEqual(pending.context_menu.entrycget(0, 'label'), 'See recipes containing this item')
                pending.context_menu.invoke(0)
                popup = next(w for w in app.winfo_children() if isinstance(w, tk.Toplevel))
                listing = next(w for w in descendants(popup) if isinstance(w, ttk.Treeview))
                self.assertIn(expected_recipe, listing.get_children())
                popup.destroy()
            check_context(pending.items, 'loose_component', 'consume-component')
            check_context(pending.recipes, 'item:loose_component', 'consume-component')
            app.project.data['recipes'].pop('consume-component')
            app.refresh_catalog()
            self.assertEqual(pending.unused.get_children(), ('item:loose_component',))
            produce = Recipe('produce-component', {'ingredients': [{'type': 'item', 'name': 'iron-plate', 'amount': 1}], 'results': [{'type': 'item', 'name': 'loose_component', 'amount': 1}]})
            app.project.save_recipe(produce, 'produce-component', .5, True, custom=True)
            app.refresh_catalog()
            check_context(pending.unused, 'item:loose_component', 'produce-component')
            path = work / 'requirements.txt'
            self.assertTrue(pending.export_text(path))
            self.assertIn('Items not used as recipe ingredients', path.read_text(encoding='utf-8'))
