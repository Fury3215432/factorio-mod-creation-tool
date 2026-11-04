import copy
import json
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from tkinter import ttk

from app import App
from core import Catalog
from installation import find_installation


@unittest.skipUnless(Path('.cache/test-catalog.json').exists(), 'Requires cached catalog')
class BrowseBulk(unittest.TestCase):
    def test_mixed_selection_atomic_validation_and_undo(self):
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
            for key in [('item', 'iron-plate'), ('fluid', 'water')]:
                app.project.data['items'][key[1]] = app.project.editable_item(key, app.catalog)
            app.project.data['technologies']['automation'] = {'prototype': copy.deepcopy(app.catalog.raw['technology']['automation'])}
            app.loaded_recipes = {'iron-gear-wheel'}
            app.refresh_catalog()
            browser = app.browse_creations()
            ids = ['item:iron-plate', 'fluid:water', 'recipe:iron-gear-wheel', 'technology:automation']
            browser.list.selection_set(*ids)
            rows = [browser.rows[i] for i in ids]
            before = copy.deepcopy(app.project.data)
            # Validation is atomic even when an earlier selected item was valid.
            self.assertFalse(browser.apply_bulk_edits(rows, {'items': {'description': 'No partial update'}, 'recipes': {'seconds': '0'}}))
            self.assertEqual(app.project.data, before)
            errors.reset_mock()
            count = len(app.undo_stack)
            self.assertTrue(browser.apply_bulk_edits(rows, {
                'items': {'stack_size': '75', 'description': 'Shared description'},
                'recipes': {'seconds': '3'}, 'technologies': {'count': '23', 'time': '12'}}))
            self.assertEqual(app.catalog.items['item', 'iron-plate']['stack_size'], 75)
            self.assertEqual(app.project.data['items']['water']['stack_size'], before['items']['water']['stack_size'])
            self.assertEqual(app.project.data['items']['water']['description'], 'Shared description')
            self.assertEqual(app.project.data['recipes']['iron-gear-wheel']['seconds'], 3)
            self.assertEqual(app.catalog.raw['technology']['automation']['unit']['count'], 23)
            self.assertEqual(len(app.undo_stack), count + 1)
            self.assertTrue(app.undo())
            self.assertEqual(app.project.data, before)
            browser.list.selection_set(*ids)
            with patch.object(browser.list, 'identify_row', return_value=ids[0]), patch('creations_ui.tk.Menu.tk_popup'):
                browser.context(SimpleNamespace(y=0, x_root=0, y_root=0))
            self.assertEqual(len(browser.list.selection()), 4)
            labels = [browser.context_menu.entrycget(i, 'label') for i in range(browser.context_menu.index('end') + 1)
                      if browser.context_menu.type(i) == 'command']
            self.assertIn('Edit in bulk', labels)
            dialog = browser.bulk_edit()
            def children(widget):
                for child in widget.winfo_children():
                    yield child
                    yield from children(child)
            # All unchecked means no accidental default overwrite.
            next(w for w in children(dialog) if isinstance(w, ttk.Button) and w.cget('text') == 'Apply to selected').invoke()
            self.assertEqual(app.project.data, before)
            self.assertFalse(errors.called, errors.call_args_list)

