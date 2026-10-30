from installation import find_installation
import json
import copy
import os
from pathlib import Path
import tempfile
import tkinter as tk
from tkinter import ttk
import unittest
from unittest.mock import patch

from app import App
from bulk_items import create_items
from core import Catalog, load_game
from recipe_unlocks import assign_unlock
from core import Recipe


@unittest.skipUnless(Path('.cache/test-catalog.json').exists(), 'Requires cached catalog')
class RecipeUnlocks(unittest.TestCase):
    def test_ingredient_unlocks_do_not_follow_consumer_technology(self):
        from project import Project
        raw = {'item': {name: {'type': 'item', 'stack_size': 100} for name in ('plate', 'intermediate', 'component', 'finished')},
               'recipe-category': {'crafting': {}}, 'item-subgroup': {'intermediate-product': {}},
               'tool': {'science': {'type': 'tool', 'stack_size': 100}}, 'technology': {
                   'assembly': {'type': 'technology', 'name': 'assembly', 'unit': {'count': 1, 'time': 1, 'ingredients': [['science', 1]]},
                                'effects': [{'type': 'unlock-recipe', 'recipe': 'finished_recipe'}]}}, 'recipe': {}}
        project = Project()
        for name, ingredient, product in [('intermediate_recipe', 'plate', 'intermediate'), ('component_recipe', 'intermediate', 'component'), ('finished_recipe', 'component', 'finished')]:
            proto = {'type': 'recipe', 'name': name, 'enabled': False,
                     'ingredients': [{'type': 'item', 'name': ingredient, 'amount': 1}],
                     'results': [{'type': 'item', 'name': product, 'amount': 1}]}
            project.save_recipe(Recipe(name, proto), name, .5, False, custom=True)
        before = copy.deepcopy(project.data)
        project.compile(Catalog(raw))
        self.assertEqual(project.data, before)
        merged = Catalog(project.merged_raw(raw))
        self.assertEqual(project.recipe_unlocks('component_recipe', raw), [])
        self.assertEqual(project.recipes_missing_unlocks(merged), ['component_recipe', 'intermediate_recipe'])
        # The same rule applies when all definitions came from a loaded mod.
        loaded = dict(raw, recipe={name: recipe['original'] for name, recipe in project.data['recipes'].items()})
        loaded_project = Project()
        self.assertEqual(loaded_project.recipes_missing_unlocks(Catalog(loaded), loaded['recipe']), ['component_recipe', 'intermediate_recipe'])

    def test_locked_default_assign_create_enable_and_undo(self):
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
            self.assertFalse(tab.enabled.get())
            create_items(tab, 'unlock component')
            # Its locked ingredient recipe initially has no technology.
            create_items(tab, 'unlock precursor')
            precursor = Recipe('unlock_precursor_recipe', {'ingredients': [{'type': 'item', 'name': 'iron-plate', 'amount': 1}],
                'results': [{'type': 'item', 'name': 'unlock_precursor', 'amount': 1}]})
            app.project.save_recipe(precursor, 'unlock_precursor_recipe', .5, False, custom=True)
            app.refresh_catalog()
            tab.add_entry('results', ('item', 'unlock_component'))
            tab.add_entry('ingredients', ('item', 'unlock_precursor'))
            self.assertTrue(tab.save_changes())
            name = 'unlock_component_recipe'
            self.assertFalse(app.catalog.recipes[name]['enabled'])
            app.pending_tab()
            pending = app.nametowidget(app.tabs.select())
            self.assertIn(name, pending.unlocks.get_children())
            pending.unlocks.selection_set(name)
            dialog = pending.fix_unlock()
            def descendants(widget):
                for child in widget.winfo_children():
                    yield child
                    yield from descendants(child)
            listing = next(w for w in descendants(dialog) if isinstance(w, tk.Listbox))
            index = list(listing.get(0, 'end')).index('automation-2')
            listing.selection_clear(0, 'end')
            listing.selection_set(index)
            next(w for w in descendants(dialog) if isinstance(w, ttk.Button) and w.cget('text') == 'Add to selected technology').invoke()
            self.assertFalse(errors.called, errors.call_args_list)
            self.assertEqual(app.project.recipe_unlocks(name, app.base_raw), ['automation-2'])
            self.assertEqual(app.project.recipe_unlocks('unlock_precursor_recipe', app.base_raw), [])
            self.assertIn('unlock_precursor_recipe', pending.unlocks.get_children())
            self.assertNotIn(name, pending.unlocks.get_children())
            self.assertTrue(app.undo())
            self.assertIn(name, pending.unlocks.get_children())
            self.assertIn('unlock_precursor_recipe', pending.unlocks.get_children())
            pending.unlocks.selection_set(name)
            dialog = pending.fix_unlock()
            next(w for w in descendants(dialog) if isinstance(w, ttk.Button) and w.cget('text') == 'Create new technology').invoke()
            tree = app.nametowidget(app.tabs.select())
            technology = tree.editor_vars['tech_id'].get()
            self.assertEqual(tree.editor_vars['unlocks'].get(), name)
            self.assertTrue(tree.dirty)
            self.assertTrue(tree.save_changes())
            self.assertNotIn(name, pending.unlocks.get_children())
            self.assertEqual(app.project.recipe_unlocks(name, app.base_raw), [technology])
            self.assertEqual(app.project.recipe_unlocks('unlock_precursor_recipe', app.base_raw), [])
            self.assertIn('unlock_precursor_recipe', pending.unlocks.get_children())
            assign_unlock(pending, name, 'automation-2')
            self.assertEqual(set(app.project.recipe_unlocks(name, app.base_raw)), {technology, 'automation-2'})
            if os.environ.get('FACTORIO_TEST_INSTALL'):
                self.verify_export(app, work, name, technology, False, 'locked')
            tab.load(name)
            self.assertFalse(tab.enabled.get())
            self.assertEqual(str(tab.enabled_button.cget('state')), 'normal')
            tab.enabled_button.invoke()
            self.assertTrue(tab.enabled.get())
            self.assertTrue(tab.dirty)
            self.assertTrue(tab.save_changes())
            self.assertTrue(app.catalog.recipes[name]['enabled'])
            self.assertEqual(app.project.recipe_unlocks(name, app.base_raw), [])
            self.assertNotIn(name, pending.unlocks.get_children())
            self.assertNotIn(name, tree.editor_vars['unlocks'].get().split(', '))
            if os.environ.get('FACTORIO_TEST_INSTALL'):
                self.verify_export(app, work, name, technology, True, 'available')
            self.assertTrue(app.undo())
            self.assertFalse(app.catalog.recipes[name]['enabled'])
            self.assertEqual(set(app.project.recipe_unlocks(name, app.base_raw)), {technology, 'automation-2'})
            self.assertIn(name, tree.editor_vars['unlocks'].get())
            self.assertFalse(errors.called, errors.call_args_list)

    def verify_export(self, app, work, name, technology, enabled, suffix):
        archive = work / ('unlock-' + suffix + '_1.0.0.zip')
        app.project.export(archive, Catalog(app.base_raw), app.root_path, app.mods_path, mod_name='unlock-' + suffix)
        loaded, _, _ = load_game(os.environ['FACTORIO_TEST_INSTALL'], [archive], work / ('engine-' + suffix))
        self.assertEqual(loaded.recipes[name]['enabled'], enabled)
        self.assertFalse(loaded.recipes['unlock_precursor_recipe']['enabled'])
        self.assertFalse(any(e.get('type') == 'unlock-recipe' and e.get('recipe') == 'unlock_precursor_recipe'
                             for e in loaded.raw['technology'][technology].get('effects', [])))
        for tech in (technology, 'automation-2'):
            effects = loaded.raw['technology'][tech].get('effects', [])
            has_unlock = any(e.get('type') == 'unlock-recipe' and e.get('recipe') == name for e in effects)
            self.assertEqual(has_unlock, not enabled)
