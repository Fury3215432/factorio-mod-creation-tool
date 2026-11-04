from installation import find_installation
import copy
import json
from pathlib import Path
import tempfile
import tkinter as tk
from tkinter import ttk
import unittest
from unittest.mock import patch

from app import App
from core import Catalog, Recipe


@unittest.skipUnless(Path('.cache/test-catalog.json').exists(), 'Requires cached catalog')
class MultiRecipeGraph(unittest.TestCase):
    def test_direct_recipes_in_one_editable_flowchart(self):
        from creations_ui import load_direct_recipes, open_all_recipes_containing
        work = Path(tempfile.mkdtemp(dir=Path('.cache').resolve()))
        with patch('tkinter.messagebox.askyesno', return_value=False), patch('tkinter.messagebox.showerror') as errors:
            app = App(); app.withdraw(); self.addCleanup(app.destroy)
            app.autosave_path = work / 'project.json'
            app.catalog = Catalog(json.loads(Path('.cache/test-catalog.json').read_text(encoding='utf-8')))
            app.root_path = find_installation() or Path('unconfigured-factorio-installation')
            app.mods_path = work / 'mods'; app.mods_path.mkdir()
            app.setup_frame.destroy(); app.workspace()
            for name in ('direct-a', 'direct-b', 'direct-mixed'):
                ingredients = [{'type': 'item', 'name': 'copper-ore', 'amount': 2}]
                if name == 'direct-mixed':
                    ingredients.append({'type': 'item', 'name': 'iron-plate', 'amount': 1})
                recipe = Recipe(name, {'ingredients': ingredients, 'results': [{'type': 'item', 'name': 'copper-plate', 'amount': 1}]})
                app.project.save_recipe(recipe, name, 3, False, custom=True)
            app.persist(); app.refresh_catalog()
            before = copy.deepcopy(app.project.data); count = len(app.tabs.tabs())
            tab = load_direct_recipes(app, ('item', 'copper-ore'))
            self.assertEqual(len(app.tabs.tabs()), count + 1)
            self.assertTrue({'direct-a', 'direct-b'} <= set(tab.direct_roots.values()))
            self.assertNotIn('direct-mixed', tab.direct_roots.values())
            self.assertEqual(app.project.data, before)
            self.assertEqual(len([tag for tag in tab.graph_nodes if tag.startswith('craft:')]), len(tab.direct_roots))
            path = next(path for path, name in tab.direct_roots.items() if name == 'direct-a')
            # Edit the actual recipe within this chart, rather than generating
            # a combined recipe or opening additional tabs.
            dialog = tab.edit('ingredients', 0, path)
            dialog = next(w for w in app.winfo_children() if isinstance(w, tk.Toplevel))
            entry = next(w for w in dialog.winfo_children() if isinstance(w, ttk.Entry))
            entry.delete(0, 'end'); entry.insert(0, '7')
            next(w for w in dialog.winfo_children() if isinstance(w, ttk.Button) and w.cget('text') == 'Save changes').invoke()
            self.assertEqual(app.project.data['recipes']['direct-a']['ingredients'][0]['amount'], 7)
            self.assertEqual(app.project.data['recipes']['direct-b'], before['recipes']['direct-b'])
            self.assertEqual(len(app.tabs.tabs()), count + 1)
            self.assertTrue(app.undo()); self.assertEqual(app.project.data, before)
            all_tab = open_all_recipes_containing(app, ('item', 'copper-plate'))
            self.assertEqual(len(app.tabs.tabs()), count + 2)
            names = set(all_tab.direct_roots.values())
            self.assertTrue({'direct-a', 'direct-b', 'direct-mixed', 'copper-cable'} <= names)
            self.assertNotIn('iron-gear-wheel', names)
            self.assertEqual(app.project.data, before)
            self.assertTrue(app.tabs.tab(all_tab, 'text').startswith('Recipes containing:'))
            with patch('tkinter.messagebox.showinfo') as info:
                self.assertIsNone(load_direct_recipes(app, ('item', 'no-such-item')))
                info.assert_called_once()
            self.assertFalse(errors.called, errors.call_args_list)

    def test_delete_item_context_root_chain_and_undo(self):
        work = Path(tempfile.mkdtemp(dir=Path('.cache').resolve()))
        with patch('tkinter.messagebox.askyesno', return_value=False), patch('tkinter.messagebox.showerror') as errors:
            app = App(); app.withdraw(); self.addCleanup(app.destroy)
            app.autosave_path = work / 'project.json'
            app.catalog = Catalog(json.loads(Path('.cache/test-catalog.json').read_text(encoding='utf-8')))
            app.root_path = find_installation() or Path('unconfigured-factorio-installation')
            app.mods_path = work / 'mods'; app.mods_path.mkdir()
            app.setup_frame.destroy(); app.workspace()
            tab = app.nametowidget(app.tabs.select())
            tab.load('electronic-circuit'); tab.expand_all_recipes()
            prior = tab.snapshot()
            menu = tk.Menu(tab, tearoff=False)
            tab.item_context(menu, tab.recipe.ingredients[0], 'ingredients', (0,))
            labels = {menu.entrycget(i, 'label'): i for i in range(menu.index('end') + 1) if menu.type(i) == 'command'}
            self.assertIn('Delete item', labels)
            remaining_name = tab.recipe.ingredients[1]['name']
            menu.invoke(labels['Delete item'])
            self.assertEqual([e['name'] for e in tab.recipe.ingredients], [remaining_name])
            self.assertEqual(tab.expanded_recipes[(0,)]['key'][1], remaining_name)
            self.assertNotIn((1,), tab.expanded_recipes)
            self.assertTrue(app.undo())
            self.assertEqual(tab.recipe.ingredients, prior['recipe'].ingredients)
            self.assertEqual(tab.expanded_recipes, prior['expanded_recipes'])
            path = next(p for p, entry in tab.expanded_recipes.items() if entry['name'] == 'copper-cable')
            self.assertTrue(tab.add_entry('ingredients', ('item', 'iron-plate'), path=path))
            before = copy.deepcopy(app.project.data)
            _, chain, _ = tab.chain_recipe(path)
            index = len(chain.ingredients) - 1
            menu = tk.Menu(tab, tearoff=False)
            tab.item_context(menu, chain.ingredients[index], 'ingredients', path + (index,))
            label_index = next(i for i in range(menu.index('end') + 1) if menu.type(i) == 'command' and menu.entrycget(i, 'label') == 'Delete item')
            menu.invoke(label_index)
            self.assertEqual(len(app.project.data['recipes']['copper-cable']['ingredients']), index)
            self.assertTrue(app.undo()); self.assertEqual(app.project.data, before)
            self.assertFalse(errors.called, errors.call_args_list)

    def test_expand_all_and_undo(self):
        work = Path(tempfile.mkdtemp(dir=Path('.cache').resolve()))
        with patch('tkinter.messagebox.askyesno', return_value=False), patch('tkinter.messagebox.showinfo'):
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
            tab.load('electronic-circuit')
            before = copy.deepcopy(app.project.data)
            tabs = len(app.tabs.tabs())
            count = len(app.undo_stack)
            self.assertTrue(tab.expand_all_recipes())
            self.assertEqual(len(app.undo_stack), count + 1)
            self.assertEqual(len(app.tabs.tabs()), tabs)
            names = {entry['name'] for entry in tab.expanded_recipes.values()}
            self.assertTrue({'copper-cable', 'iron-plate'} <= names, names)
            self.assertNotIn('copper-plate', names)
            self.assertTrue(all(len(path) == 1 for path in tab.expanded_recipes))
            first_expansion = copy.deepcopy(tab.expanded_recipes)
            self.assertTrue(tab.expand_all_recipes())
            self.assertIn('copper-plate', {entry['name'] for entry in tab.expanded_recipes.values()})
            self.assertTrue(all(len(path) <= 2 for path in tab.expanded_recipes))
            self.assertNotIn('electronic-circuit', names)
            self.assertEqual(app.project.data, before)
            for path, entry in tab.expanded_recipes.items():
                ancestors = {tab.loaded_name} | {other['name'] for prefix, other in tab.expanded_recipes.items() if len(prefix) < len(path) and path[:len(prefix)] == prefix}
                self.assertNotIn(entry['name'], ancestors)
            self.assertFalse(tab.expand_all_recipes())
            self.assertTrue(app.undo())
            self.assertEqual(tab.expanded_recipes, first_expansion)
            self.assertTrue(app.undo())
            self.assertFalse(tab.expanded_recipes)

    def test_delete_recipe_and_restore_charts(self):
        from delete_items import delete_recipe
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
            tab.load('electronic-circuit')
            index = next(i for i, e in enumerate(tab.recipe.ingredients) if e['name'] == 'copper-cable')
            path = (index,)
            tab.show_recipe(path, ('item', 'copper-cable'), 'copper-cable')
            menu = tk.Menu(tab, tearoff=False)
            self.addCleanup(menu.destroy)
            tab.recipe_delete_menu(menu, path)
            labels = {menu.entrycget(i, 'label'): i for i in range(menu.index('end') + 1)}
            self.assertIn('Rename recipe', labels)
            self.assertIn('Delete this recipe', labels)
            other = app.new_tab()
            other.load('copper-cable')
            menu.invoke(labels['Delete this recipe'])
            self.assertNotIn('copper-cable', app.catalog.recipes)
            self.assertFalse(tab.expanded_recipes)
            self.assertIsNone(other.loaded_name)
            self.assertTrue(app.undo())
            self.assertIn('copper-cable', app.catalog.recipes)
            self.assertIn(path, tab.expanded_recipes)
            self.assertEqual(other.loaded_name, 'copper-cable')
            before = copy.deepcopy(app.project.data)
            with patch.object(app.project, 'compile', side_effect=ValueError('Blocked')):
                self.assertFalse(delete_recipe(tab, 'copper-cable'))
            self.assertEqual(app.project.data, before)
            errors.reset_mock()
            custom = Recipe('delete-test', {'ingredients': [], 'results': [{'type': 'item', 'name': 'copper-cable', 'amount': 1}]})
            app.project.save_recipe(custom, 'delete-test', 1, True, custom=True)
            app.refresh_catalog()
            other.load('delete-test')
            self.assertTrue(delete_recipe(other, 'delete-test'))
            self.assertNotIn('delete-test', app.catalog.recipes)
            self.assertNotIn('delete-test', app.project.data['recipes'])
            self.assertTrue(app.undo())
            self.assertEqual(other.loaded_name, 'delete-test')
            self.assertIn('delete-test', app.catalog.recipes)
            self.assertFalse(errors.called, errors.call_args_list)

    def test_delete_recipe_removes_machine_assignment_atomically(self):
        from delete_items import delete_recipe
        from machine_model import source_config
        work=Path(tempfile.mkdtemp(dir=Path('.cache').resolve()))
        with patch('tkinter.messagebox.askyesno',return_value=False),patch('tkinter.messagebox.showerror') as errors:
            app=App();app.withdraw();self.addCleanup(app.destroy)
            app.autosave_path=work/'project.json'
            app.catalog=Catalog(json.loads(Path('.cache/test-catalog.json').read_text(encoding='utf-8')))
            app.root_path=find_installation() or Path('unconfigured-factorio-installation')
            app.mods_path=work/'mods';app.mods_path.mkdir();app.setup_frame.destroy();app.workspace()
            record=source_config('assembling-machine','assembling-machine-1',app.catalog)
            record.update(operation='edit',recipes=['iron-gear-wheel'])
            app.project.data['machines']['assembling-machine-1']=record
            app.refresh_catalog()
            chart=app.new_tab();chart.load('iron-gear-wheel')
            app.new_machine_tab(source=('assembling-machine','assembling-machine-1'),mode='edit')
            machine=app.nametowidget(app.tabs.select())
            machine.vars['health'].set('777')
            before=copy.deepcopy(app.project.data)
            self.assertFalse(delete_recipe(chart,'iron-gear-wheel'))
            self.assertEqual(app.project.data,before)
            with patch('tkinter.messagebox.askyesno',return_value=True):
                with patch.object(app.project,'compile',side_effect=ValueError('Blocked')):
                    self.assertFalse(delete_recipe(chart,'iron-gear-wheel'))
                self.assertEqual(app.project.data,before)
                errors.reset_mock()
                count=len(app.undo_stack)
                self.assertTrue(delete_recipe(chart,'iron-gear-wheel'))
            self.assertEqual(len(app.undo_stack),count+1)
            self.assertNotIn('iron-gear-wheel',app.catalog.recipes)
            self.assertEqual(app.project.data['machines']['assembling-machine-1']['recipes'],[])
            self.assertEqual(machine.selected_recipes(),[])
            self.assertEqual(machine.vars['health'].get(),'777')
            self.assertTrue(app.undo())
            self.assertEqual(app.project.data,before)
            self.assertIn('iron-gear-wheel',machine.selected_recipes())
            self.assertEqual(machine.vars['health'].get(),'777')
            self.assertEqual(chart.loaded_name,'iron-gear-wheel')
            self.assertFalse(errors.called,errors.call_args_list)

    def test_expand_nested_choose_collapse_refresh_and_undo(self):
        work = Path(tempfile.mkdtemp(dir=Path('.cache').resolve()))
        with patch('tkinter.messagebox.askyesno', return_value=False), patch('tkinter.messagebox.showerror') as errors, patch('tkinter.messagebox.showinfo') as info:
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
            tab.load('electronic-circuit')
            original = copy.deepcopy(vars(tab.recipe))
            count = len(app.tabs.tabs())
            index = next(i for i, e in enumerate(tab.recipe.ingredients) if e['name'] == 'copper-cable')
            path = (index,)
            self.assertTrue(tab.show_recipe(path, ('item', 'copper-cable'), 'copper-cable'))
            self.assertEqual(len(app.tabs.tabs()), count)
            self.assertEqual(tab.expanded_recipes[path]['name'], 'copper-cable')
            self.assertEqual(len(tab.canvas.find_withtag('recipe-link')), 1)
            # Edit a loaded dependency in place without changing its availability.
            _, dependency, prior_seconds = tab.chain_recipe(path)
            prior_enabled = app.catalog.recipes['copper-cable'].get('enabled', True)
            self.assertTrue(tab.save_chain_recipe(path, dependency, 4))
            self.assertEqual(app.project.data['recipes']['copper-cable']['seconds'], 4)
            self.assertEqual(app.catalog.recipes['copper-cable'].get('enabled', True), prior_enabled)
            self.assertTrue(app.undo())
            self.assertNotIn('copper-cable', app.project.data['recipes'])

            self.assertFalse(tab.dirty)
            self.assertEqual(vars(tab.recipe), original)
            child_path = path + (0,)
            self.assertTrue(tab.show_recipe(child_path, ('item', 'copper-plate'), 'copper-plate'))
            self.assertEqual(len(tab.expanded_recipes), 2)
            self.assertEqual(len(tab.canvas.find_withtag('recipe-link')), 2)
            self.assertEqual(tab.graph_width, 3120)
            self.assertTrue(tab.canvas.find_withtag('craft:' + '.'.join(map(str, child_path))))
            tab.collapse_recipes(path)
            self.assertFalse(tab.expanded_recipes)
            self.assertTrue(app.undo())
            self.assertEqual(len(tab.expanded_recipes), 2)
            self.assertEqual(len(tab.canvas.find_withtag('recipe-link')), 2)
            self.assertEqual(vars(tab.recipe), original)
            self.assertFalse(tab.show_recipe(child_path + (0,), ('item', 'unobtainable-test-item')))
            self.assertTrue(info.called)
            alternate = Recipe('alternate-cable', {'ingredients': [{'type': 'item', 'name': 'copper-plate', 'amount': 2}],
                'results': [{'type': 'item', 'name': 'copper-cable', 'amount': 4}, {'type': 'item', 'name': 'stone', 'amount': 1}]})
            app.project.save_recipe(alternate, 'alternate-cable', 2, True, custom=True)
            app.refresh_catalog()
            tab.show_recipe(path, ('item', 'copper-cable'))
            dialog = next(w for w in app.winfo_children() if isinstance(w, tk.Toplevel))
            listing = next(w for w in dialog.winfo_children() if isinstance(w, tk.Listbox))
            names = list(listing.get(0, 'end'))
            listing.selection_clear(0, 'end')
            listing.selection_set(names.index('alternate-cable'))
            next(w for w in dialog.winfo_children() if isinstance(w, ttk.Button)).invoke()
            self.assertEqual(tab.expanded_recipes[path]['name'], 'alternate-cable')
            self.assertNotIn(child_path, tab.expanded_recipes)
            products = [node['value']['name'] for node in tab.graph_nodes.values() if node.get('path') == path and node['side'] == 'results']
            self.assertEqual(products, ['copper-cable', 'stone'])
            # Editing the expanded source updates its display on the original graph.
            tabs_before = len(app.tabs.tabs())
            tab.edit('ingredients', 0, path)
            dialog = next(w for w in app.winfo_children() if isinstance(w, tk.Toplevel))
            quantity = next(w for w in dialog.winfo_children() if isinstance(w, ttk.Entry))
            quantity.delete(0, 'end')
            quantity.insert(0, '7')
            next(w for w in dialog.winfo_children() if isinstance(w, ttk.Button) and w.cget('text') == 'Save changes').invoke()
            self.assertEqual(len(app.tabs.tabs()), tabs_before)
            self.assertEqual(app.project.data['recipes']['alternate-cable']['ingredients'][0]['amount'], 7)
            # The craft box is editable directly and persists the branch time.
            entry = tab.edit_expanded_recipe(path)
            entry.delete(0, 'end')
            entry.insert(0, '3')
            entry.event_generate('<FocusOut>')
            app.update()
            self.assertEqual(app.project.data['recipes']['alternate-cable']['seconds'], 3)
            self.assertTrue(app.undo())
            self.assertEqual(app.project.data['recipes']['alternate-cable']['seconds'], 2)
            # Adding to a branch stays in the same chart and is undoable.
            self.assertTrue(tab.add_entry('ingredients', ('item', 'iron-plate'), 2, path=path))
            self.assertEqual(len(app.project.data['recipes']['alternate-cable']['ingredients']), 2)
            self.assertTrue(app.undo())
            self.assertEqual(len(app.project.data['recipes']['alternate-cable']['ingredients']), 1)
            node = next(n for n in tab.graph_nodes.values() if n['path'] == path and n['side'] == 'ingredients')
            self.assertEqual(node['value']['amount'], 7)
            self.assertEqual(vars(tab.recipe), original)
            self.assertFalse(tab.dirty)
            # Quantities in the primary recipe remain editable with expansions open.
            tab.recipe.ingredients[index]['amount'] = 11
            tab.mark()
            tab.draw()
            self.assertTrue(app.undo())
            self.assertEqual(vars(tab.recipe), original)
            self.assertIn(path, tab.expanded_recipes)
            # Loaded recipes cannot expand recursively into themselves.
            self.assertFalse(tab.show_recipe(path + (0,), ('item', 'copper-cable'), 'alternate-cable'))
            tab.load('iron-gear-wheel')
            self.assertFalse(tab.expanded_recipes)
            old_seconds = tab.seconds.get()
            entry = tab.edit_crafting_time()
            entry.delete(0, 'end')
            entry.insert(0, '1.25')
            entry.event_generate('<FocusOut>')
            self.assertEqual(float(tab.seconds.get()), 1.25)
            self.assertTrue(app.undo())
            self.assertEqual(tab.seconds.get(), old_seconds)

            self.assertFalse(errors.called, errors.call_args_list)
