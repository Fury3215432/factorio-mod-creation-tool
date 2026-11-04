import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from app import App
from core import Catalog
from installation import find_installation


@unittest.skipUnless(Path('.cache/test-catalog.json').exists(), 'Requires cached catalog')
class RecipeReplacement(unittest.TestCase):
    def test_cancel_replace_loaded_and_custom_undo_and_failure(self):
        work = Path(tempfile.mkdtemp(dir=Path('.cache').resolve()))
        with patch('tkinter.messagebox.askyesno', return_value=False) as confirm, patch('tkinter.messagebox.showerror') as errors:
            app = App(); app.withdraw(); self.addCleanup(app.destroy)
            app.autosave_path = work / 'project.json'
            app.catalog = Catalog(json.loads(Path('.cache/test-catalog.json').read_text(encoding='utf-8')))
            app.root_path = find_installation() or Path('unconfigured-factorio-installation')
            app.mods_path = work / 'mods'; app.mods_path.mkdir()
            app.setup_frame.destroy(); app.workspace()
            old = app.nametowidget(app.tabs.select()); old.load('iron-gear-wheel')
            old.recipe.ingredients[0]['amount'] = 9; old.mark()
            old_state = old.snapshot()
            new = app.new_tab()
            new.add_entry('ingredients', ('item', 'copper-plate'))
            new.add_entry('results', ('item', 'iron-gear-wheel'), amount=2)
            new.name.set('iron-gear-wheel'); new.seconds.set('4')
            before = copy.deepcopy(app.project.data); count = len(app.undo_stack)
            self.assertFalse(new.save_changes())
            self.assertEqual(app.project.data, before); self.assertEqual(len(app.undo_stack), count)
            self.assertEqual(old.recipe.ingredients, old_state['recipe'].ingredients)
            confirm.return_value = True
            with patch.object(app.project, 'compile', side_effect=ValueError('Test failure')):
                self.assertFalse(new.save_changes())
            self.assertEqual(app.project.data, before); self.assertEqual(len(app.undo_stack), count)
            errors.reset_mock()
            self.assertTrue(new.save_changes())
            saved = app.project.data['recipes']['iron-gear-wheel']
            self.assertFalse(saved['custom']); self.assertEqual(saved['source'], 'iron-gear-wheel')
            self.assertEqual(saved['seconds'], 4)
            self.assertEqual(old.recipe.ingredients[0]['name'], 'copper-plate')
            self.assertFalse(old.dirty)
            self.assertEqual(len(app.undo_stack), count + 1)
            self.assertTrue(app.undo()); self.assertEqual(app.project.data, before)
            self.assertEqual(old.recipe.ingredients, old_state['recipe'].ingredients); self.assertTrue(old.dirty)
            # Replacing a project-created ID remains a custom recipe. Saving
            # further edits to that same saved draft does not prompt a conflict.
            new.name.set('replace-custom'); self.assertTrue(new.save_changes())
            confirm.reset_mock()
            new.recipe.ingredients[0]['amount'] = 3; new.mark()
            self.assertTrue(new.save_changes()); confirm.assert_not_called()
            before = copy.deepcopy(app.project.data)
            copy_tab = app.new_tab(); copy_tab.load('copper-cable')
            self.assertTrue(copy_tab.save_as_new('replace-custom'))
            self.assertTrue(app.project.data['recipes']['replace-custom']['custom'])
            self.assertEqual(copy_tab.loaded_name, 'replace-custom')
            self.assertEqual(new.recipe.ingredients[0]['name'], 'copper-plate')
            self.assertEqual(new.recipe.ingredients[0]['amount'], 1)
            self.assertTrue(app.undo()); self.assertEqual(app.project.data, before)
            self.assertEqual(new.recipe.ingredients[0]['amount'], 3)
            from delete_items import delete_recipe
            self.assertTrue(delete_recipe(new, 'iron-gear-wheel'))
            fresh = app.new_tab()
            fresh.add_entry('ingredients', ('item', 'copper-plate'))
            fresh.add_entry('results', ('item', 'iron-gear-wheel'))
            fresh.name.set('iron-gear-wheel')
            confirm.return_value = False; confirm.reset_mock()
            self.assertTrue(fresh.save_changes())
            confirm.assert_not_called()
            self.assertFalse(app.project.data['recipes']['iron-gear-wheel']['custom'])
            self.assertNotIn('iron-gear-wheel', app.project.data['deleted']['recipe'])
            self.assertFalse(errors.called, errors.call_args_list)

