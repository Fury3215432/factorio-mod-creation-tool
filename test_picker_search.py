from installation import find_installation
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from app import App, Picker
from core import Catalog, load_game
from project import default_icon_asset


@unittest.skipUnless(Path('.cache/test-catalog.json').exists(), 'Requires cached catalog')
class PickerSearch(unittest.TestCase):
    def test_motor_search_add_to_inserter_save_and_export(self):
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
            name = 'Early_Electrical_Motor'
            app.project.data['items'][name] = {'name': name, 'kind': 'item', 'title': 'Early Electrical Motor',
                'stack_size': 100, 'subgroup': 'intermediate-product', 'default_amount': 1, 'icon': default_icon_asset()}
            app.refresh_catalog()
            tab = app.nametowidget(app.tabs.select())
            tab.load('inserter')
            tab.add('ingredients')
            picker = next(w for w in app.winfo_children() if isinstance(w, Picker))
            for query in ('early_electric_motor', 'EARLY ELECTRICAL MOTOR', 'Early_Electrical_Motor', 'early-electric-motor'):
                picker.query.set(query)
                self.assertIn(('item', name), picker.matches, query)
            picker.list.selection_clear(0, 'end')
            picker.list.selection_set(picker.matches.index(('item', name)))
            picker.choose()
            self.assertEqual(tab.recipe.ingredients[-1], {'type': 'item', 'name': name, 'amount': 1})
            self.assertTrue(tab.save_changes())
            self.assertEqual(app.project.data['recipes']['inserter']['ingredients'][-1]['name'], name)
            self.assertFalse(errors.called, errors.call_args_list)
            if os.environ.get('FACTORIO_TEST_INSTALL'):
                path = work / 'motor-search-test_1.0.0.zip'
                app.project.export(path, Catalog(app.base_raw), app.root_path, app.mods_path, mod_name='motor-search-test')
                loaded, _, _ = load_game(os.environ['FACTORIO_TEST_INSTALL'], [path], work / 'engine')
                self.assertTrue(any(e['name'] == name for e in loaded.recipes['inserter']['ingredients']))
