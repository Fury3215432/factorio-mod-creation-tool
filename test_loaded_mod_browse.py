import os
import copy
from pathlib import Path
import tempfile
import tkinter as tk
from tkinter import ttk
import unittest
from unittest.mock import patch

from app import App
from core import Catalog, load_game
from project import Project


@unittest.skipUnless(os.environ.get('FACTORIO_TEST_INSTALL'), 'Requires Factorio engine')
class LoadedModBrowser(unittest.TestCase):
    def test_loaded_entries_edit_and_export(self):
        root = Path(os.environ['FACTORIO_TEST_INSTALL'])
        work = Path(tempfile.mkdtemp(dir=Path('.cache').resolve()))
        mod = work / 'browser-fixture'
        mod.mkdir()
        (mod / 'info.json').write_text('{"name":"browser-fixture","title":"Browser fixture","author":"Test","version":"1.0.0","factorio_version":"2.0","dependencies":["base"]}')
        (mod / 'data.lua').write_text('''
data:extend({
  {type="item",name="mod-component",icon="__base__/graphics/icons/iron-plate.png",icon_size=64,stack_size=80,subgroup="intermediate-product"},
  {type="fluid",name="mod-fluid",icon="__base__/graphics/icons/fluid/water.png",icon_size=64,default_temperature=25,base_color={r=1,g=0,b=0},flow_color={r=1,g=0,b=0},subgroup="fluid"},
  {type="recipe",name="mod-component-recipe",ingredients={{type="item",name="iron-plate",amount=1}},results={{type="item",name="mod-component",amount=1}},enabled=true}
})
data.raw.recipe["iron-gear-wheel"].energy_required=3
local tech = table.deepcopy(data.raw.technology.automation)
tech.name = "mod-research"
tech.effects = {{type="unlock-recipe",recipe="mod-component-recipe"}}
data:extend({tech})
''', encoding='utf-8')
        loaded, _, mods = load_game(root, [mod], work / 'loaded', track_mod_content=True)
        self.assertIn(('item', 'mod-component'), loaded.loaded_items)
        self.assertIn(('fluid', 'mod-fluid'), loaded.loaded_items)
        self.assertNotIn(('item', 'iron-plate'), loaded.loaded_items)
        self.assertIn('mod-component-recipe', loaded.loaded_recipes)
        self.assertIn('iron-gear-wheel', loaded.loaded_recipes)
        self.assertNotIn('copper-cable', loaded.loaded_recipes)
        with patch('tkinter.messagebox.askyesno', return_value=False), patch('tkinter.messagebox.showerror') as errors:
            app = App()
            app.withdraw()
            self.addCleanup(app.destroy)
            app.autosave_path = work / 'project.json'
            app.catalog, app.root_path, app.mods_path = loaded, root, mods
            app.setup_frame.destroy()
            app.workspace()
            browser = app.browse_creations()
            browser.change_filter.set('Loaded')
            self.assertIn('item:mod-component', browser.list.get_children())
            self.assertIn('fluid:mod-fluid', browser.list.get_children())
            self.assertIn('recipe:mod-component-recipe', browser.list.get_children())
            self.assertIn('recipe:iron-gear-wheel', browser.list.get_children())
            self.assertNotIn('item:iron-plate', browser.list.get_children())
            browser.list.selection_set('recipe:mod-component-recipe')
            browser.update_actions()
            browser.diagram_button.invoke()
            recipe = app.nametowidget(app.tabs.select())
            self.assertEqual(recipe.loaded_name, 'mod-component-recipe')
            recipe.recipe.ingredients[0]['amount'] = 4
            recipe.mark()
            self.assertTrue(recipe.save_changes())
            browser.clear_filters()
            self.assertEqual(browser.list.get_children().count('recipe:mod-component-recipe'), 1)
            self.assertEqual(browser.list.item('recipe:mod-component-recipe', 'values')[-1], 'Edited')
            browser.list.selection_set('item:mod-component')
            browser.update_actions()
            self.assertEqual(str(browser.delete_button.cget('state')), 'disabled')
            browser.edit_selected()
            dialog = next(w for w in app.winfo_children() if isinstance(w, tk.Toplevel))
            def descendants(widget):
                for child in widget.winfo_children():
                    yield child
                    yield from descendants(child)
            for widget in descendants(dialog):
                if isinstance(widget, ttk.Entry):
                    siblings = widget.master.winfo_children()
                    if siblings and isinstance(siblings[0], ttk.Label) and siblings[0].cget('text') == 'Stack size':
                        widget.delete(0, 'end')
                        widget.insert(0, '150')
            next(w for w in descendants(dialog) if isinstance(w, ttk.Button) and w.cget('text') == 'Save item').invoke()
            self.assertFalse(errors.called, errors.call_args_list)
            self.assertEqual(app.catalog.items[('item', 'mod-component')]['stack_size'], 150)
            self.assertEqual(app.catalog.items[('item', 'mod-component')]['icon'], '__base__/graphics/icons/iron-plate.png')
            self.assertFalse(app.project.items_missing_icons())
            reopened = Project.open(app.autosave_path)
            self.assertIsNone(reopened.data['items']['mod-component']['icon'])
            self.assertEqual(browser.list.get_children().count('item:mod-component'), 1)
            archive = work / 'browser-edits_1.0.0.zip'
            app.project.export(archive, Catalog(app.base_raw), root, mods, mod_name='browser-edits')
            final, _, _ = load_game(root, [mod, archive], work / 'verify')
            self.assertEqual(final.items[('item', 'mod-component')]['stack_size'], 150)
            self.assertEqual(final.recipes['mod-component-recipe']['ingredients'][0]['amount'], 4)
            browser.list.selection_set('item:mod-component')
            self.assertTrue(browser.delete_selected())
            self.assertEqual(app.catalog.items[('item', 'mod-component')]['stack_size'], 80)
            self.assertEqual(browser.list.item('item:mod-component', 'values')[-1], 'Loaded')
            self.assertTrue(app.undo())
            self.assertEqual(app.catalog.items[('item', 'mod-component')]['stack_size'], 150)
            # Remove the loaded recipe, then its item; cleanup unlock effects.
            browser.list.selection_set('item:mod-component')
            self.assertFalse(browser.delete_from_mod())
            self.assertIn('mod-component-recipe', errors.call_args.args[1])
            errors.reset_mock()
            browser.list.selection_set('recipe:mod-component-recipe')
            self.assertTrue(browser.delete_from_mod(), errors.call_args_list)
            self.assertNotIn('mod-component-recipe', app.catalog.recipes)
            self.assertFalse(recipe.recipe.results)
            self.assertFalse(any(e.get('recipe') == 'mod-component-recipe' for e in app.catalog.raw['technology']['mod-research']['effects']))
            if 'mod-component-recycling' in app.catalog.recipes:
                browser.list.selection_set('recipe:mod-component-recycling')
                self.assertTrue(browser.delete_from_mod(), errors.call_args_list)
            browser.list.selection_set('item:mod-component')
            app.pending_tab()
            pending = app.nametowidget(app.tabs.select())
            self.assertTrue(pending.delete_item(('item', 'mod-component')), errors.call_args_list)
            self.assertNotIn(('item', 'mod-component'), app.catalog.items)
            persisted = Project.open(app.autosave_path)
            self.assertIn('mod-component', persisted.data['deleted']['item'])
            self.assertIn('mod-component-recipe', persisted.data['deleted']['recipe'])
            changes = persisted.changes(Catalog(app.base_raw))
            self.assertTrue(any(c['operation'] == 'deleted' and c['name'] == 'mod-component' for c in changes))
            self.assertTrue(any(c['type'] == 'technology' and c['name'] == 'mod-research' for c in changes))
            removed = work / 'browser-deletions_1.0.0.zip'
            persisted.export(removed, Catalog(app.base_raw), root, mods, mod_name='browser-deletions')
            verified, _, _ = load_game(root, [mod, removed], work / 'verify-deletions')
            self.assertNotIn(('item', 'mod-component'), verified.items)
            self.assertNotIn('mod-component-recipe', verified.recipes)
            self.assertFalse(verified.raw['technology']['mod-research']['effects'])
            self.assertTrue(app.undo())
            self.assertIn(('item', 'mod-component'), app.catalog.items)
            if 'mod-component-recycling' in app.project.data['deleted'].get('recipe', {}):
                self.assertTrue(app.undo())
            self.assertTrue(app.undo())
            self.assertIn('mod-component-recipe', app.catalog.recipes)
            self.assertEqual(recipe.loaded_name, 'mod-component-recipe')
            self.assertEqual(recipe.recipe.ingredients[0]['amount'], 4)
            from delete_items import delete_with_recipes
            before_cascade = copy.deepcopy(app.project.data)
            self.assertTrue(delete_with_recipes(pending, ('item', 'mod-component')), errors.call_args_list)
            self.assertNotIn(('item', 'mod-component'), app.catalog.items)
            self.assertNotIn('mod-component-recipe', app.catalog.recipes)
            cascade = work / 'browser-cascade_1.0.0.zip'
            app.project.export(cascade, Catalog(app.base_raw), root, mods, mod_name='browser-cascade')
            verified, _, _ = load_game(root, [mod, cascade], work / 'verify-cascade')
            self.assertNotIn(('item', 'mod-component'), verified.items)
            self.assertNotIn('mod-component-recipe', verified.recipes)
            self.assertTrue(app.undo())
            self.assertEqual(app.project.data, before_cascade)
            self.assertEqual(recipe.recipe.ingredients[0]['amount'], 4)
            self.assertFalse(errors.called, errors.call_args_list)
