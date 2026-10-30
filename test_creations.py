from installation import find_installation
import json
import os
from pathlib import Path
import tempfile
import tkinter as tk
from tkinter import ttk
import unittest
from unittest.mock import patch

from app import App, Picker
from core import Catalog, load_game
from project import Project


@unittest.skipUnless(Path('.cache/test-catalog.json').exists(), 'Requires cached game catalog')
class CreationsTests(unittest.TestCase):
    def test_fluid_create_convert_rename_browse_and_undo(self):
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

            def descendants(widget):
                for child in widget.winfo_children():
                    yield child
                    yield from descendants(child)

            def form():
                dialog = next(w for w in app.winfo_children() if isinstance(w, tk.Toplevel))
                fields = {}
                for row in descendants(dialog):
                    children = row.winfo_children()
                    if children and isinstance(children[0], ttk.Label):
                        for child in children[1:]:
                            if isinstance(child, (ttk.Entry, ttk.Combobox)):
                                fields[children[0].cget('text')] = child
                return dialog, fields

            def fill(entry, text):
                entry.delete(0, 'end')
                entry.insert(0, text)

            def submit(dialog, text):
                next(w for w in descendants(dialog) if isinstance(w, ttk.Button) and w.cget('text') == text).invoke()
                self.assertFalse(errors.called, errors.call_args_list)
                self.assertFalse(dialog.winfo_exists())

            for name, kind in [('older-component', 'item'), ('new-fluid', 'fluid')]:
                tab.edit_item()
                dialog, fields = form()
                fill(fields['Item ID'], name)
                fields['Creation type'].set(kind)
                if kind == 'fluid':
                    fill(fields['Recipe result amount'], '2.5')
                    self.assertFalse(fields['Stack size'].master.winfo_manager())
                    self.assertEqual(fields['Default temperature'].master.winfo_manager(), 'pack')
                submit(dialog, 'Create ' + kind)
            self.assertIn(('fluid', 'new-fluid'), app.catalog.items)
            self.assertIsNotNone(app.icon(('fluid', 'new-fluid')))
            picker = Picker(app, lambda key: None)
            self.assertEqual(picker.matches[:2], [('fluid', 'new-fluid'), ('item', 'older-component')])
            picker.destroy()
            browser = app.browse_creations()
            self.assertIs(app.browse_creations(), browser)
            self.assertEqual(browser.list.get_children(), ('fluid:new-fluid', 'item:older-component'))
            browser.list.selection_set('fluid:new-fluid')
            browser.use_selected('results')
            recipe = app.nametowidget(app.tabs.select())
            self.assertEqual(recipe.recipe.results[0]['amount'], 2.5)
            recipe.name.set('new-fluid-recipe')
            recipe.category.set('chemistry')
            self.assertTrue(recipe.save_changes())
            self.assertIn('recipe:new-fluid-recipe', browser.list.get_children())
            browser.list.selection_set('recipe:new-fluid-recipe')
            browser.edit_selected()
            self.assertEqual(app.tabs.select(), str(recipe))
            browser.update_actions()
            self.assertTrue(all(str(button.cget('state')) == 'disabled' for button in browser.use_buttons))

            # Rename and convert an item, including a partial unsaved chart.
            tab.add_entry('ingredients', ('item', 'older-component'))
            browser.list.selection_set('item:older-component')
            browser.edit_selected()
            dialog, fields = form()
            fill(fields['Item ID'], 'converted-fluid')
            fields['Creation type'].set('fluid')
            submit(dialog, 'Save fluid')
            self.assertNotIn(('item', 'older-component'), app.catalog.items)
            self.assertEqual(tab.recipe.ingredients[0]['name'], 'converted-fluid')
            self.assertEqual(tab.recipe.ingredients[0]['type'], 'fluid')
            self.assertTrue(app.undo())
            self.assertIn(('item', 'older-component'), app.catalog.items)
            self.assertEqual(tab.recipe.ingredients[0]['type'], 'item')
            self.assertEqual(tab.recipe.ingredients[0]['name'], 'older-component')

            # Renaming a saved recipe product updates both saved and open data.
            browser.list.selection_set('fluid:new-fluid')
            browser.edit_selected()
            dialog, fields = form()
            fill(fields['Item ID'], 'renamed-fluid')
            submit(dialog, 'Save fluid')
            self.assertEqual(app.project.data['recipes']['new-fluid-recipe']['results'][0]['name'], 'renamed-fluid')
            self.assertEqual(recipe.recipe.results[0]['name'], 'renamed-fluid')
            browser.list.selection_set('fluid:renamed-fluid')
            browser.edit_selected()
            dialog, fields = form()
            fields['Creation type'].set('item')
            fill(fields['Recipe result amount'], '1')
            next(w for w in descendants(dialog) if isinstance(w, ttk.Button) and w.cget('text') == 'Save item').invoke()
            self.assertTrue(errors.called)  # Fractional fluid recipes cannot become item recipes.
            errors.reset_mock()
            self.assertEqual(app.project.data['items']['renamed-fluid']['kind'], 'fluid')
            dialog.destroy()
            reopened = Project.open(app.autosave_path)
            self.assertEqual(reopened.creations()[0][1], 'renamed-fluid')
            self.assertEqual(reopened.changes(Catalog(app.base_raw))[1]['type'], 'fluid')
            tab.edit_item()
            dialog, fields = form()
            fill(fields['Item ID'], 'custom-science')
            fields['Creation type'].set('science pack')
            self.assertEqual(fields['Inventory subgroup'].get(), 'science-pack')
            submit(dialog, 'Create science pack')
            self.assertIn('custom-science', app.catalog.raw['tool'])
            self.assertIn(('item', 'custom-science'), app.catalog.items)
            self.assertIn('custom-science', app.catalog.raw['lab']['lab']['inputs'])
            browser.list.selection_set('science pack:custom-science')
            browser.use_selected('results')
            science_recipe = app.nametowidget(app.tabs.select())
            science_recipe.add_entry('ingredients', ('item', 'iron-plate'))
            science_recipe.name.set('custom-science-recipe')
            self.assertTrue(science_recipe.save_changes())
            app.project.data['technologies']['custom-research'] = {'prototype': {
                'type': 'technology', 'name': 'custom-research',
                'icon': '__base__/graphics/technology/automation-1.png', 'icon_size': 256,
                'unit': {'count': 5, 'time': 10, 'ingredients': [['custom-science', 1]]}}}
            app.persist()
            browser.list.selection_set('science pack:custom-science')
            browser.edit_selected()
            dialog, fields = form()
            fill(fields['Item ID'], 'renamed-science')
            submit(dialog, 'Save science pack')
            self.assertIn('technology:custom-research', browser.list.get_children())
            browser.list.selection_set('technology:custom-research')
            browser.edit_selected()
            technology = app.nametowidget(app.tabs.select())
            self.assertEqual(technology.selected, 'custom-research')
            app.new_tab().load('iron-gear-wheel')
            loaded = app.nametowidget(app.tabs.select())
            self.assertTrue(loaded.save_changes())
            self.assertEqual(browser.list.item('recipe:iron-gear-wheel', 'values')[-1], 'Edited')
            self.assertEqual(browser.list.item('recipe:new-fluid-recipe', 'values')[-1], 'Created')
            browser.query.set('technology custom research')
            self.assertEqual(browser.list.get_children(), ('technology:custom-research',))
            browser.query.set('')
            browser.kind_filter.set('recipe')
            browser.change_filter.set('Edited')
            self.assertEqual(browser.list.get_children(), ('recipe:iron-gear-wheel',))
            browser.change_filter.set('Created')
            self.assertIn('recipe:new-fluid-recipe', browser.list.get_children())
            self.assertNotIn('recipe:iron-gear-wheel', browser.list.get_children())
            browser.kind_filter.set('fluid')
            self.assertEqual(browser.list.get_children(), ('fluid:renamed-fluid',))
            browser.clear_filters()
            self.assertIn('technology:custom-research', browser.list.get_children())
            from types import SimpleNamespace
            with patch.object(browser.list, 'identify_row', return_value='fluid:renamed-fluid'), patch('creations_ui.tk.Menu.tk_popup'):
                browser.context(SimpleNamespace(y=5, x_root=0, y_root=0))
                self.assertTrue(browser.context_menu.winfo_exists())
                self.assertEqual(browser.context_menu.entrycget(0, 'label'), 'See all recipes containing this fluid')
                browser.context_menu.invoke(0)
                dialog = next(w for w in app.winfo_children() if isinstance(w, tk.Toplevel))
            related_list = next(w for w in descendants(dialog) if isinstance(w, ttk.Treeview))
            self.assertEqual(related_list.get_children(), ('new-fluid-recipe',))
            related_list.selection_set('new-fluid-recipe')
            next(w for w in descendants(dialog) if isinstance(w, ttk.Button) and w.cget('text') == 'Open recipe').invoke()
            self.assertEqual(app.tabs.select(), str(recipe))
            from creations_ui import recipes_containing
            dialog = recipes_containing(app, ('item', 'iron-plate'))
            related_list = next(w for w in descendants(dialog) if isinstance(w, ttk.Treeview))
            self.assertIn('iron-gear-wheel', related_list.get_children())
            self.assertIn('custom-science-recipe', related_list.get_children())
            related_role = next(w for w in descendants(dialog) if isinstance(w, ttk.Combobox))
            related_role.set('Product')
            self.assertNotIn('iron-gear-wheel', related_list.get_children())
            self.assertIn('iron-plate', related_list.get_children())
            related_role.set('Ingredient')
            self.assertIn('iron-gear-wheel', related_list.get_children())
            query_entry = next(w for w in descendants(dialog) if isinstance(w, ttk.Entry))
            fill(query_entry, 'custom-science')
            self.assertEqual(related_list.get_children(), ('custom-science-recipe',))
            dialog.destroy()
            self.assertEqual(app.project.data['technologies']['custom-research']['prototype']['unit']['ingredients'], [['renamed-science', 1]])
            self.assertEqual(science_recipe.recipe.results[0]['name'], 'renamed-science')
            picker = Picker(app, lambda key: None)
            self.assertEqual(picker.matches[0], ('item', 'renamed-science'))
            picker.destroy()
            if os.environ.get('FACTORIO_TEST_INSTALL'):
                archive = work / 'creations_1.0.0.zip'
                app.project.export(archive, Catalog(app.base_raw), app.root_path, app.mods_path, mod_name='creations')
                loaded, _, _ = load_game(os.environ['FACTORIO_TEST_INSTALL'], [archive], work / 'engine')
                self.assertIn(('fluid', 'renamed-fluid'), loaded.items)
                self.assertNotIn(('item', 'renamed-fluid'), loaded.items)
                self.assertEqual(loaded.recipes['new-fluid-recipe']['results'][0]['name'], 'renamed-fluid')
                self.assertIn('renamed-science', loaded.raw['tool'])
                self.assertIn('renamed-science', loaded.raw['lab']['lab']['inputs'])
                self.assertNotIn('custom-science', loaded.raw['tool'])
                self.assertEqual(loaded.raw['technology']['custom-research']['unit']['ingredients'][0][0], 'renamed-science')
            self.assertFalse(errors.called, errors.call_args_list)
            # Deletion blocks dangling references and restores open editors on undo.
            browser.clear_filters()
            browser.list.selection_set('recipe:new-fluid-recipe', 'recipe:iron-gear-wheel')
            browser.update_actions()
            self.assertEqual(str(browser.diagram_button.cget('state')), 'normal')
            charts = browser.read_recipe_diagrams()
            self.assertEqual({chart.saved_key for chart in charts}, {'new-fluid-recipe', 'iron-gear-wheel'})
            count = len(app.tabs.tabs())
            recipe.seconds.set('4')
            self.assertTrue(recipe.dirty)
            self.assertEqual(browser.read_recipe_diagrams(), charts)
            self.assertEqual(len(app.tabs.tabs()), count)
            self.assertEqual(recipe.seconds.get(), '4')
            browser.refresh()
            self.assertEqual(set(browser.list.selection()), {'recipe:new-fluid-recipe', 'recipe:iron-gear-wheel'})
            self.assertTrue(app.undo())
            browser.list.selection_set('fluid:renamed-fluid')
            self.assertFalse(browser.delete_selected())
            self.assertIn('new-fluid-recipe', errors.call_args.args[1])
            errors.reset_mock()
            browser.list.selection_set('recipe:new-fluid-recipe')
            self.assertTrue(browser.delete_selected())
            self.assertNotIn('new-fluid-recipe', app.catalog.recipes)
            self.assertFalse(recipe.dirty)
            self.assertIsNone(recipe.loaded_name)
            self.assertFalse(recipe.recipe.results)
            browser.list.selection_set('fluid:renamed-fluid')
            self.assertTrue(browser.delete_selected())
            self.assertNotIn(('fluid', 'renamed-fluid'), app.catalog.items)
            self.assertNotIn('renamed-fluid', Project.open(app.autosave_path).data['items'])
            self.assertTrue(app.undo())
            self.assertIn(('fluid', 'renamed-fluid'), app.catalog.items)
            self.assertTrue(app.undo())
            self.assertIn('new-fluid-recipe', app.catalog.recipes)
            self.assertEqual(recipe.recipe.results[0]['name'], 'renamed-fluid')
            self.assertEqual(recipe.saved_key, 'new-fluid-recipe')
            browser.list.selection_set('recipe:iron-gear-wheel')
            self.assertTrue(browser.delete_selected())
            self.assertNotIn('iron-gear-wheel', app.project.data['recipes'])
            self.assertEqual(app.catalog.recipes['iron-gear-wheel'], app.base_raw['recipe']['iron-gear-wheel'])
            self.assertTrue(app.undo())
            self.assertIn('iron-gear-wheel', app.project.data['recipes'])
            browser.list.selection_set('science pack:renamed-science')
            self.assertFalse(browser.delete_selected())
            self.assertIn('custom-research', errors.call_args.args[1])
            errors.reset_mock()
            self.assertFalse(errors.called)


if __name__ == '__main__':
    unittest.main()
