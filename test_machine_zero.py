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
from test_project import make_icon

@unittest.skipUnless(Path('.cache/test-catalog.json').exists(), 'Requires cached catalog')
class FromZero(unittest.TestCase):
    def test_create_save_reopen_and_export(self):
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
            app.new_machine_tab()
            app.update_idletasks()
            tab = app.nametowidget(app.tabs.select())
            dialog = tab.start_dialog
            buttons = [w for w in dialog.winfo_children() if isinstance(w, ttk.Button)]
            self.assertNotIn('Choose template', [w.cget('text') for w in buttons])
            next(w for w in buttons if w.cget('text') == 'Create from zero').invoke()
            self.assertTrue(tab.ready)
            self.assertEqual(tab.vars['name'].get(), '')
            tab.vars['name'].set('from-zero-test')
            tab.vars['recipes'].set('iron-gear-wheel')
            self.assertFalse(tab.save_changes())
            self.assertIn('Building PNG', str(errors.call_args))
            errors.reset_mock()
            tab.vars['sprite_path'].set(str(make_icon(work / 'building.png')))
            tab.vars['visual_scale'].set('1.5')
            self.assertTrue(tab.save_changes())
            self.assertFalse(errors.called, errors.call_args_list)
            saved = Project.open(app.autosave_path)
            self.assertEqual(saved.data['machines']['from-zero-test']['template'], '__from-zero__')
            tab.load('from-zero-test')
            self.assertEqual(tab.vars['name'].get(), 'from-zero-test')
            self.assertEqual(float(tab.vars['visual_scale'].get()), 1.5)
            tab.remove_all_recipes()
            self.assertFalse(tab.selected_recipes())
            self.assertTrue(app.undo())
            self.assertEqual(tab.selected_recipes(), ['iron-gear-wheel'])
            tab.remove_all_recipes()
            self.assertTrue(tab.save_changes())
            saved = Project.open(app.autosave_path)

            if find_installation():
                archive = work / 'recipe-studio-project_1.0.0.zip'
                saved.export(archive, Catalog(app.base_raw), app.root_path, app.mods_path)
                loaded, _, _ = load_game(app.root_path, [archive], work / 'engine')
                entity = loaded.raw['assembling-machine']['from-zero-test']
                self.assertEqual(entity['crafting_speed'], 1)
                self.assertIn('animation', entity['graphics_set'])
                self.assertEqual(entity['graphics_set']['animation']['scale'], 4.5)
                self.assertEqual(entity['collision_box'], [[-1.2, -1.2], [1.2, 1.2]])
                self.assertEqual(loaded.items[('item', 'from-zero-test')]['place_result'], 'from-zero-test')
                categories = entity['crafting_categories']
                self.assertEqual(categories, ['recipe-studio-empty-from-zero-test'])
                self.assertFalse(any(r.get('category', 'crafting') in categories for r in loaded.recipes.values()))
                # Custom categories work even when another machine moves a recipe
                # into the app's per-recipe category.
                from core import Recipe
                import copy
                saved.data['categories']['custom-test-category'] = {'producers': []}
                recipe = Recipe('iron-gear-wheel', app.base_raw['recipe']['iron-gear-wheel'])
                saved.save_recipe(recipe, recipe.name, .5, True, category='custom-test-category')
                saved.data['machines']['from-zero-test']['categories'] = ['custom-test-category']
                second = copy.deepcopy(saved.data['machines']['from-zero-test'])
                second.update(categories=[], recipes=['iron-gear-wheel'])
                saved.data['machines']['individual-test'] = second
                app.project = saved
                app.refresh_catalog()
                tab.load('from-zero-test')
                self.assertEqual(tab.selected_categories(), ['custom-test-category'])
                tab.choose_categories()
                dialog = next(w for w in app.winfo_children() if isinstance(w, tk.Toplevel))
                def descendants(widget):
                    for child in widget.winfo_children():
                        yield child
                        yield from descendants(child)
                listing = next(w for w in descendants(dialog) if isinstance(w, tk.Listbox))
                self.assertIn('custom-test-category', listing.get(0, 'end'))
                dialog.destroy()
                archive = work / 'recipe-studio-project_1.0.0.zip'
                saved.export(archive, Catalog(app.base_raw), app.root_path, app.mods_path)
                loaded, _, _ = load_game(app.root_path, [archive], work / 'category-engine')
                category = loaded.recipes['iron-gear-wheel']['category']
                self.assertIn(category, loaded.raw['assembling-machine']['from-zero-test']['crafting_categories'])
                self.assertIn(category, loaded.raw['assembling-machine']['individual-test']['crafting_categories'])

