from installation import find_installation
import json
import os
from pathlib import Path
import tempfile
import tkinter as tk
from tkinter import ttk
import unittest
from unittest.mock import patch

from app import App
from bulk_items import parse_items, create_items, bulk_item_dialog
from core import Catalog, load_game
from project import Project


class BulkNames(unittest.TestCase):
    def test_space_rules_and_validation(self):
        self.assertEqual(parse_items('copper plate  iron ore'), [('copper_plate', 'copper plate'), ('iron_ore', 'iron ore')])
        self.assertEqual(parse_items('  Copper Plate    iron ore\nstone\tsteel beam  '),
                         [('Copper_Plate', 'Copper Plate'), ('iron_ore', 'iron ore'), ('stone', 'stone'), ('steel_beam', 'steel beam')])
        for invalid in ('', '   ', 'copper plate  copper_plate', 'invalid/name'):
            with self.assertRaises(ValueError):
                parse_items(invalid)

    @unittest.skipUnless(Path('.cache/test-catalog.json').exists(), 'Requires cached catalog')
    def test_apply_preview_collision_persistence_and_undo(self):
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
            tab = app.nametowidget(app.tabs.select())
            dialog = bulk_item_dialog(tab)
            def descendants(widget):
                for child in widget.winfo_children():
                    yield child
                    yield from descendants(child)
            text = next(w for w in descendants(dialog) if isinstance(w, tk.Text))
            preview = next(w for w in descendants(dialog) if isinstance(w, ttk.Treeview))
            button = next(w for w in descendants(dialog) if isinstance(w, ttk.Button) and w.cget('text') == 'Apply')
            self.assertEqual(str(button.cget('state')), 'disabled')
            text.insert('1.0', 'copper plate  iron ore')
            app.update()
            self.assertEqual([preview.item(row, 'values') for row in preview.get_children()], [('copper_plate', 'copper plate'), ('iron_ore', 'iron ore')])
            self.assertEqual(str(button.cget('state')), 'normal')
            button.invoke()
            self.assertFalse(dialog.winfo_exists())
            self.assertEqual(app.project.data['items']['copper_plate']['title'], 'copper plate')
            self.assertEqual(app.project.items_missing_icons(), ['copper_plate', 'iron_ore'])
            self.assertIn(('item', 'iron_ore'), app.project.items_missing_recipes(app.catalog))
            self.assertFalse(tab.recipe.ingredients)
            self.assertFalse(tab.recipe.results)
            self.assertIn('copper_plate', Project.open(app.autosave_path).data['items'])
            with self.assertRaisesRegex(ValueError, 'already exist'):
                create_items(tab, 'copper plate  brand new item')
            self.assertNotIn('brand_new_item', app.project.data['items'])
            if os.environ.get('FACTORIO_TEST_INSTALL'):
                archive = work / 'bulk-test_1.0.0.zip'
                app.project.export(archive, Catalog(app.base_raw), app.root_path, app.mods_path, mod_name='bulk-test')
                loaded, _, _ = load_game(os.environ['FACTORIO_TEST_INSTALL'], [archive], work / 'engine')
                self.assertIn(('item', 'copper_plate'), loaded.items)
                self.assertEqual(loaded.items[('item', 'iron_ore')]['localised_name'], 'iron ore')
            self.assertTrue(app.undo())
            self.assertNotIn(('item', 'copper_plate'), app.catalog.items)
            self.assertNotIn(('item', 'iron_ore'), app.catalog.items)
            self.assertEqual(Project.open(app.autosave_path).data['items'], {})
            self.assertFalse(errors.called, errors.call_args_list)
