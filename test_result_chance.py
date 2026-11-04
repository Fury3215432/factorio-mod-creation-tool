import copy
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

@unittest.skipUnless(Path('.cache/test-catalog.json').exists(), 'Requires catalog')
class ResultChance(unittest.TestCase):
    def test_edit_chance_root_branch_undo_and_export(self):
        work = Path(tempfile.mkdtemp(dir=Path('.cache').resolve()))
        with patch('tkinter.messagebox.askyesno', return_value=False), patch('tkinter.messagebox.showerror') as errors:
            app = App()
            app.withdraw()
            self.addCleanup(app.destroy)
            app.autosave_path = work / 'project.json'
            app.catalog = Catalog(json.loads(Path('.cache/test-catalog.json').read_text(encoding='utf-8')))
            app.root_path = find_installation() or Path('unconfigured-factorio-installation')
            app.mods_path = work / 'mods'
            app.mods_path.mkdir()
            app.setup_frame.destroy()
            app.workspace()
            tab = app.nametowidget(app.tabs.select())
            tab.load('iron-gear-wheel')
            def edit_chance(value, path=()):
                tab.edit('results', 0, path)
                dialog = next(w for w in app.winfo_children() if isinstance(w, tk.Toplevel))
                entry = [w for w in dialog.winfo_children() if isinstance(w, ttk.Entry)][-1]
                entry.delete(0, 'end')
                entry.insert(0, value)
                next(w for w in dialog.winfo_children() if isinstance(w, ttk.Button) and w.cget('text') == 'Save changes').invoke()
                return dialog
            before = copy.deepcopy(tab.recipe.results)
            dialog = edit_chance('150')
            self.assertEqual(tab.recipe.results, before)
            self.assertTrue(errors.called)
            errors.reset_mock()
            dialog.destroy()
            edit_chance('25')
            self.assertEqual(tab.recipe.results[0]['probability'], .25)
            self.assertTrue(app.undo())
            self.assertEqual(tab.recipe.results, before)
            edit_chance('25')
            self.assertTrue(tab.save_changes())
            tab.load('electronic-circuit')
            index = next(i for i, e in enumerate(tab.recipe.ingredients) if e['name'] == 'copper-cable')
            path = (index,)
            tab.show_recipe(path, ('item', 'copper-cable'), 'copper-cable')
            count = len(app.tabs.tabs())
            edit_chance('12.5', path)
            self.assertEqual(len(app.tabs.tabs()), count)
            self.assertEqual(app.project.data['recipes']['copper-cable']['results'][0]['probability'], .125)
            self.assertTrue(app.undo())
            self.assertNotIn('copper-cable', app.project.data['recipes'])
            edit_chance('100', path)
            self.assertNotIn('probability', app.project.data['recipes']['copper-cable']['results'][0])
            self.assertFalse(errors.called, errors.call_args_list)
            if find_installation():
                archive = work / 'recipe-studio-project_1.0.0.zip'
                app.project.export(archive, Catalog(app.base_raw), app.root_path, app.mods_path)
                loaded, _, _ = load_game(app.root_path, [archive], work / 'engine')
                self.assertEqual(loaded.recipes['iron-gear-wheel']['results'][0]['probability'], .25)
