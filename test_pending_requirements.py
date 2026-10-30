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
from core import Catalog, load_game, read_mod
from project import Project, default_icon_asset
from test_project import make_icon


@unittest.skipUnless(Path('.cache/test-catalog.json').exists(), 'Requires cached real game data')
class PendingRequirements(unittest.TestCase):
    def test_fallback_pending_export_replace_and_undo(self):
        work = Path(tempfile.mkdtemp(dir=Path('.cache').resolve()))
        with patch('tkinter.messagebox.askyesno', return_value=False), patch('tkinter.messagebox.showerror') as errors:
            app = App()
            app.withdraw()
            self.addCleanup(app.destroy)
            app.autosave_path = work / 'project.json'
            app.root_path = (find_installation() or Path('unconfigured-factorio-installation'))
            app.mods_path = work / 'mods'
            app.mods_path.mkdir()
            app.catalog = Catalog(json.loads(Path('.cache/test-catalog.json').read_text(encoding='utf-8')))
            app.setup_frame.destroy()
            app.workspace()
            self.assertFalse(app.pending_button.winfo_manager())
            recipe_tab = app.nametowidget(app.tabs.select())
            recipe_tab.edit_item()
            dialog = next(w for w in app.winfo_children() if isinstance(w, tk.Toplevel))
            def descendants(widget):
                for child in widget.winfo_children():
                    yield child
                    yield from descendants(child)
            for row in descendants(dialog):
                children = row.winfo_children()
                if children and isinstance(children[0], ttk.Label) and children[0].cget('text') == 'Item ID':
                    entry = next(w for w in children if isinstance(w, ttk.Entry))
                    entry.insert(0, 'pending-item')
                    break
            next(w for w in descendants(dialog) if isinstance(w, ttk.Button) and w.cget('text') == 'Create item').invoke()
            self.assertFalse(errors.called, errors.call_args_list)
            item = app.project.data['items']['pending-item']
            self.assertEqual(item['icon'], default_icon_asset())
            self.assertTrue(item['icon_is_default'])
            self.assertEqual(app.pending_button.winfo_manager(), 'pack')
            toolbar = app.create_machine_button.master.pack_slaves()
            self.assertEqual(toolbar.index(app.pending_button), toolbar.index(app.create_machine_button) + 1)
            self.assertIsNotNone(app.icon(('item', 'pending-item')))
            self.assertEqual(Project.open(app.autosave_path).items_missing_icons(), ['pending-item'])
            app.pending_button.invoke()
            pending = app.nametowidget(app.tabs.select())
            self.assertEqual(pending.items.get_children(), ('pending-item',))
            self.assertEqual(pending.recipes.get_children(), ('item:pending-item',))
            text = work / 'items.txt'
            self.assertTrue(pending.export_text(text))
            self.assertIn('pending-item', text.read_text(encoding='utf-8'))
            self.assertIn('Count: 1', text.read_text(encoding='utf-8'))
            # Default-icon items remain valid mod assets, not just UI placeholders.
            archive = work / 'recipe-studio-project_1.0.0.zip'
            app.project.export(archive, Catalog(app.base_raw), app.root_path, app.mods_path)
            self.assertIn('graphics/items/pending-item.png', read_mod(archive)[1])
            if os.environ.get('FACTORIO_TEST_INSTALL'):
                loaded, _, _ = load_game(os.environ['FACTORIO_TEST_INSTALL'], [archive], work / 'engine')
                self.assertEqual(loaded.items[('item', 'pending-item')]['icon_size'], 64)
            png = make_icon(work / 'real-icon.png')
            pending.items.selection_set('pending-item')
            with patch('pending_ui.filedialog.askopenfilename', return_value=str(png)):
                pending.choose_selected()
            self.assertEqual(app.project.items_missing_icons(), [])
            self.assertTrue(app.pending_button.winfo_manager())
            self.assertFalse(pending.items.get_children())
            self.assertFalse(app.project.data['items']['pending-item']['icon_is_default'])
            self.assertTrue(app.undo())
            self.assertEqual(app.project.items_missing_icons(), ['pending-item'])
            self.assertTrue(app.pending_button.winfo_manager())
            self.assertEqual(pending.items.get_children(), ('pending-item',))
            self.assertFalse(errors.called, errors.call_args_list)
            # A missing crafting recipe has a working Fix action and clears on save.
            pending.recipes.selection_set('item:pending-item')
            recipe = pending.fix_recipe()
            self.assertEqual(recipe.recipe.results[0]['name'], 'pending-item')
            self.assertEqual(recipe.name.get(), 'pending-item_recipe')
            self.assertTrue(recipe.save_changes())
            self.assertFalse(pending.recipes.get_children())
            self.assertTrue(app.project.items_missing_icons())
            self.assertTrue(app.pending_button.winfo_manager())
            self.assertTrue(app.undo())
            self.assertEqual(pending.recipes.get_children(), ('item:pending-item',))
            app.update()

    def test_loaded_recipe_can_be_saved_as_copy(self):
        work = Path(tempfile.mkdtemp(dir=Path('.cache').resolve()))
        with patch('tkinter.messagebox.askyesno', return_value=False), patch('tkinter.messagebox.showerror') as errors:
            app = App()
            app.withdraw()
            self.addCleanup(app.destroy)
            app.autosave_path = work / 'project.json'
            app.root_path = (find_installation() or Path('unconfigured-factorio-installation'))
            app.mods_path = work / 'mods'
            app.mods_path.mkdir()
            app.catalog = Catalog(json.loads(Path('.cache/test-catalog.json').read_text(encoding='utf-8')))
            app.setup_frame.destroy()
            app.workspace()
            tab = app.nametowidget(app.tabs.select())
            self.assertFalse(tab.copy_button.winfo_manager())
            tab.load('iron-gear-wheel')
            self.assertEqual(tab.copy_button.winfo_manager(), 'pack')
            self.assertEqual(tab.commit_text.get(), 'Apply edit')
            tab.recipe.ingredients[0]['amount'] = 8
            tab.mark()
            self.assertTrue(tab.save_as_new('eight-plate-gears'))
            self.assertNotIn('iron-gear-wheel', app.project.data['recipes'])
            self.assertEqual(tab.loaded_name, 'eight-plate-gears')
            self.assertFalse(tab.dirty)
            self.assertTrue(app.save_all())
            self.assertNotIn('iron-gear-wheel', app.project.data['recipes'])
            self.assertEqual(app.catalog.recipes['iron-gear-wheel']['ingredients'][0]['amount'], 2)
            self.assertEqual(app.catalog.recipes['eight-plate-gears']['ingredients'][0]['amount'], 8)
            if os.environ.get('FACTORIO_TEST_INSTALL'):
                archive = work / 'recipe-studio-project_1.0.0.zip'
                app.project.export(archive, Catalog(app.base_raw), app.root_path, app.mods_path)
                loaded, _, _ = load_game(os.environ['FACTORIO_TEST_INSTALL'], [archive], work / 'engine')
                self.assertEqual(loaded.recipes['iron-gear-wheel']['ingredients'][0]['amount'], 2)
                self.assertEqual(loaded.recipes['eight-plate-gears']['ingredients'][0]['amount'], 8)
            self.assertTrue(app.undo())
            self.assertEqual(tab.loaded_name, 'iron-gear-wheel')
            self.assertNotIn('eight-plate-gears', app.project.data['recipes'])
            self.assertEqual(tab.recipe.ingredients[0]['amount'], 8)
            self.assertFalse(errors.called, errors.call_args_list)


if __name__ == '__main__':
    unittest.main()
