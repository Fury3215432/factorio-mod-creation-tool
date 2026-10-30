from installation import find_installation
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from app import App
from core import Catalog


@unittest.skipUnless(Path('.cache/test-catalog.json').exists(), 'Requires cached catalog')
class BrowseUndoEdit(unittest.TestCase):
    def test_original_item_recipe_technology_and_machine(self):
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
            browser = app.browse_creations()
            def revert(row_id):
                with patch.object(browser.list, 'identify_row', return_value=row_id), patch('creations_ui.tk.Menu.tk_popup'):
                    browser.context(SimpleNamespace(y=5, x_root=0, y_root=0))
                labels = {browser.context_menu.entrycget(i, 'label'): i for i in range(browser.context_menu.index('end') + 1) if browser.context_menu.type(i) == 'command'}
                self.assertIn('Undo edit', labels)
                browser.context_menu.invoke(labels['Undo edit'])
                self.assertFalse(errors.called, errors.call_args_list)
            item = app.project.editable_item(('item', 'iron-plate'), app.catalog)
            item['title'] = 'Edited Iron Plate'
            app.project.data['items']['iron-plate'] = item
            app.persist()
            app.refresh_catalog()
            revert('item:iron-plate')
            self.assertNotIn('iron-plate', app.project.data['items'])
            self.assertEqual(app.catalog.items[('item', 'iron-plate')], app.base_raw['item']['iron-plate'])
            self.assertTrue(app.undo())
            self.assertEqual(app.catalog.items[('item', 'iron-plate')]['localised_name'], 'Edited Iron Plate')
            recipe = app.new_tab()
            recipe.load('iron-gear-wheel')
            recipe.recipe.ingredients[0]['amount'] = 9
            recipe.mark()
            self.assertTrue(recipe.save_changes())
            revert('recipe:iron-gear-wheel')
            self.assertNotIn('iron-gear-wheel', app.project.data['recipes'])
            self.assertEqual(recipe.recipe.ingredients[0]['amount'], 2)
            self.assertTrue(app.undo())
            self.assertEqual(recipe.recipe.ingredients[0]['amount'], 9)
            tree = app.tech_tab()
            tree.edit('automation-2')
            tree.editor_vars['count'].set('321')
            self.assertTrue(tree.save_changes())
            revert('technology:automation-2')
            self.assertNotIn('automation-2', app.project.data['technologies'])
            self.assertEqual(int(tree.editor_vars['count'].get()), app.base_raw['technology']['automation-2']['unit']['count'])
            self.assertTrue(app.undo())
            self.assertEqual(tree.editor_vars['count'].get(), '321')
            app.new_machine_tab(source=('assembling-machine', 'assembling-machine-1'), mode='edit')
            machine = app.nametowidget(app.tabs.select())
            machine.vars['health'].set('777')
            self.assertTrue(machine.save_changes())
            self.assertIn('machine:assembling-machine-1', browser.list.get_children())
            revert('machine:assembling-machine-1')
            self.assertNotIn('assembling-machine-1', app.project.data['machines'])
            self.assertEqual(int(machine.vars['health'].get()), app.base_raw['assembling-machine']['assembling-machine-1']['max_health'])
            self.assertTrue(app.undo())
            self.assertEqual(machine.vars['health'].get(), '777')
            self.assertFalse(errors.called, errors.call_args_list)
