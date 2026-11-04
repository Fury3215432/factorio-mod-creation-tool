import json
from pathlib import Path
import tempfile
import tkinter as tk
from tkinter import ttk
import unittest
from unittest.mock import patch
from app import App
from core import Catalog, load_game
from installation import find_installation
from project import Project

@unittest.skipUnless(Path('.cache/test-catalog.json').exists(), 'Requires cached catalog')
class RecipeCategories(unittest.TestCase):
    def test_create_select_save_export_and_undo(self):
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
            tab = app.nametowidget(app.tabs.select())
            tab.load('iron-gear-wheel')
            other = app.new_tab()
            dialog = tab.create_category()
            def children(widget):
                for child in widget.winfo_children():
                    yield child
                    yield from children(child)
            entry = next(w for w in children(dialog) if isinstance(w, ttk.Entry))
            entry.insert(0, 'test-special-crafting')
            listing = next(w for w in children(dialog) if isinstance(w, tk.Listbox))
            index = list(listing.get(0, 'end')).index('assembling-machine-1 (assembling-machine)')
            listing.selection_set(index)
            count = len(app.undo_stack)
            next(w for w in children(dialog) if isinstance(w, ttk.Button) and w.cget('text') == 'Create category').invoke()
            self.assertFalse(errors.called, errors.call_args_list)
            self.assertEqual(len(app.undo_stack), count + 1)
            self.assertEqual(tab.category.get(), 'test-special-crafting')
            self.assertIn('test-special-crafting', other.category_labels)
            self.assertIn('test-special-crafting', app.catalog.raw['assembling-machine']['assembling-machine-1']['crafting_categories'])
            self.assertIn('test-special-crafting', Project.open(app.autosave_path).data['categories'])
            self.assertTrue(app.undo())
            self.assertNotIn('test-special-crafting', app.catalog.raw['recipe-category'])
            self.assertNotIn('test-special-crafting', other.category_labels)
            self.assertEqual(tab.category.get(), 'crafting')
            app.project.data['categories']['test-special-crafting'] = {'producers': [['assembling-machine', 'assembling-machine-1']]}
            app.refresh_catalog()
            tab.category.set('test-special-crafting')
            self.assertTrue(tab.save_changes())
            if find_installation():
                archive = work / 'recipe-studio-project_1.0.0.zip'
                app.project.export(archive, Catalog(app.base_raw), app.root_path, app.mods_path)
                loaded, _, _ = load_game(app.root_path, [archive], work / 'engine')
                self.assertIn('test-special-crafting', loaded.raw['recipe-category'])
                self.assertEqual(loaded.recipes['iron-gear-wheel']['category'], 'test-special-crafting')
                self.assertIn('test-special-crafting', loaded.raw['assembling-machine']['assembling-machine-1']['crafting_categories'])
