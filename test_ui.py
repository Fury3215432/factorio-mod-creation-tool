from installation import find_installation
"""UI workflow smoke test; no real game windows or file picker interaction."""
import json
from pathlib import Path
import tempfile
import tkinter as tk
from tkinter import ttk
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app import App, Picker, RecipeTab
from core import Catalog, read_mod
from editors import TechTab, technology_dialog
from test_project import make_icon
from controls import settings_dialog


@unittest.skipUnless(Path('.cache/test-catalog.json').exists(), 'Requires a cached real game catalog')
class UIWorkflow(unittest.TestCase):
    def test_project_item_and_technology(self):
        cache = Path('.cache').resolve()
        work = Path(tempfile.mkdtemp(dir=cache))
        def error(*args, **kwargs):
            raise AssertionError(str(args))
        with patch('tkinter.messagebox.askyesno', return_value=False), patch('tkinter.messagebox.showerror', side_effect=error), patch('tkinter.messagebox.showinfo'):
            app = App()
            app.withdraw()
            self.addCleanup(app.destroy)
            app.autosave_path = work / 'autosave.json'
            app.catalog = Catalog(json.loads(Path('.cache/test-catalog.json').read_text(encoding='utf-8')))
            app.root_path = (find_installation() or Path('unconfigured-factorio-installation'))
            app.mods_path = work / 'mods'
            app.mods_path.mkdir()
            app.setup_frame.destroy()
            app.workspace()
            recipe_tab = app.nametowidget(app.tabs.select())
            recipe_tab.load('iron-gear-wheel')
            recipe_tab.recipe.ingredients[0]['amount'] = 8
            recipe_tab.mark()
            self.assertTrue(recipe_tab.save_changes())
            recipe_tab.category.set('smelting')
            self.assertIn('furnace', recipe_tab.machines_text.get())
            self.assertTrue(recipe_tab.save_changes())
            self.assertEqual(app.project.data['recipes']['iron-gear-wheel']['category'], 'smelting')
            app.new_item_tab()
            item_tab = app.nametowidget(app.tabs.select())
            self.assertTrue(item_tab.is_custom)
            self.assertFalse(item_tab.recipe.results)
            self.assertFalse(item_tab.enabled.get())
            item_tab.edit_item()
            dialog = next(w for w in app.winfo_children() if isinstance(w, tk.Toplevel))
            self.assertEqual(dialog.cget('background'), '#171c24')
            def fill(parent, label, value):
                def descendants(widget):
                    for child in widget.winfo_children():
                        yield child
                        yield from descendants(child)
                for row in descendants(parent):
                    children = row.winfo_children()
                    if children and isinstance(children[0], ttk.Label) and children[0].cget('text') == label:
                        entry = next(w for w in children if isinstance(w, ttk.Entry))
                        entry.delete(0, 'end')
                        entry.insert(0, value)
                        return
                raise AssertionError('Missing field ' + label)
            fill(dialog, 'Item ID', 'ui-component')
            fill(dialog, 'Display name', 'UI Component')
            fill(dialog, 'PNG file', str(make_icon(work / 'component.png')))
            footer = next(w for w in dialog.winfo_children() if any(isinstance(c, ttk.Button) for c in w.winfo_children()))
            next(w for w in footer.winfo_children() if isinstance(w, ttk.Button)).invoke()
            self.assertIn('ui-component', app.project.data['items'])
            self.assertFalse(item_tab.recipe.results)
            item_tab.name.set('ui-component')
            item_tab.add_entry('results', ('item', 'ui-component'))
            item_tab.add_entry('ingredients', ('item', 'iron-plate'), 2)
            self.assertTrue(item_tab.save_changes())
            self.assertIsNotNone(app.icon(('item', 'ui-component')))
            picker = Picker(app, lambda k: None, initial='ui-component')
            self.assertIn(('item', 'ui-component'), picker.matches)
            picker.destroy()
            app.tech_tab()
            tree = app.nametowidget(app.tabs.select())
            self.assertIsInstance(tree, TechTab)
            self.assertIn('automation', tree.positions)
            tree.set_zoom(0.8)
            technology_dialog(tree)
            self.assertFalse(any(isinstance(w, tk.Toplevel) for w in app.winfo_children()))
            dialog = tree.editor_frame
            notebook = next(w for w in dialog.winfo_children() if isinstance(w, ttk.Notebook))
            main = notebook.winfo_children()[0]
            fill(main, 'Technology ID', 'ui-research')
            fill(main, 'Prerequisites', 'automation')
            fill(main, 'Recipe unlocks', 'ui-component')
            fill(main, 'Research count', '25')
            self.assertTrue(app.undo())
            self.assertEqual(tree.editor_vars['count'].get(), '10')
            dialog = tree.editor_frame
            footer = next(w for w in dialog.winfo_children() if any(isinstance(child, ttk.Button) and child.cget('text') == 'Create technology' for child in w.winfo_children()))
            next(w for w in footer.winfo_children() if isinstance(w, ttk.Button) and w.cget('text') == 'Create technology').invoke()
            self.assertIn('ui-research', tree.positions)
            self.assertFalse(app.project.data['recipes']['ui-component']['enabled'])
            self.assertFalse(item_tab.enabled.get())
            # Ctrl+wheel changes the world scale in both kinds of flowchart.
            for flow in (recipe_tab, tree):
                before = flow.zoom
                flow.wheel(SimpleNamespace(state=4, delta=120, x=200, y=100))
                self.assertGreater(flow.zoom, before)
                flow.wheel(SimpleNamespace(state=4, delta=-120, x=200, y=100))
                self.assertAlmostEqual(flow.zoom, before)
                flow.wheel(SimpleNamespace(state=0, delta=-120, x=200, y=100))
                self.assertAlmostEqual(flow.zoom, before)
                flow.canvas.xview_moveto(0.2)
                flow.canvas.yview_moveto(0.2)
                world = (flow.canvas.canvasx(60) / flow.zoom, flow.canvas.canvasy(60) / flow.zoom)
                flow.wheel(SimpleNamespace(state=4, delta=120, x=60, y=60))
                self.assertAlmostEqual(flow.canvas.canvasx(60) / flow.zoom, world[0], delta=3)
                self.assertAlmostEqual(flow.canvas.canvasy(60) / flow.zoom, world[1], delta=3)
            # Switching cards must protect unsaved panel edits.
            fill(tree.editor_frame, 'Research count', '41')
            self.assertTrue(tree.dirty)
            with patch('tkinter.messagebox.askyesnocancel', return_value=None):
                tree.edit('automation')
            self.assertEqual(tree.selected, 'ui-research')
            with patch('tkinter.messagebox.askyesnocancel', return_value=True):
                tree.edit('automation')
            self.assertEqual(app.project.data['technologies']['ui-research']['prototype']['unit']['count'], 41)
            self.assertEqual(tree.selected, 'automation')
            self.assertFalse(tree.dirty)
            # Application and mouse mappings are editable and persisted.
            app.controls_path = work / 'settings.json'
            settings_dialog(app)
            settings = next(w for w in app.winfo_children() if isinstance(w, tk.Toplevel))
            next(w for w in settings.winfo_children() if isinstance(w, ttk.Button)).invoke()
            fill(settings, 'Save current tab', 'Ctrl+Shift+S')
            def descendants(widget):
                for child in widget.winfo_children():
                    yield child
                    yield from descendants(child)
            next(w for w in descendants(settings) if isinstance(w, ttk.Button) and w.cget('text') == 'Save controls').invoke()
            self.assertEqual(app.controls['keys']['save'], 'Ctrl+Shift+S')
            self.assertEqual(json.loads(app.controls_path.read_text())['keys']['save'], 'Ctrl+Shift+S')
            self.assertTrue(recipe_tab.canvas.bind('<B1-Motion>'))
            with patch.object(recipe_tab.canvas, 'find_withtag', return_value=(1,)):
                recipe_tab.panning = False
                recipe_tab.pan_start(SimpleNamespace(x=100, y=100))
                self.assertFalse(recipe_tab.panning)
            with patch.object(recipe_tab.canvas, 'find_withtag', return_value=()):
                recipe_tab.pan_start(SimpleNamespace(x=100, y=100))
                self.assertTrue(recipe_tab.panning)
                recipe_tab.pan_end(SimpleNamespace(x=100, y=100))
            style = ttk.Style(app)
            normal = app.tk.splitlist(style.lookup('TNotebook.Tab', 'padding'))
            selected = app.tk.splitlist(style.lookup('TNotebook.Tab', 'padding', ('selected',)))
            self.assertGreater(int(selected[1]), int(normal[1]))
            app.new_machine_tab()
            machine_tab = app.nametowidget(app.tabs.select())
            self.assertFalse(machine_tab.ready)
            chooser = next(w for w in app.winfo_children() if isinstance(w, tk.Toplevel))
            next(w for w in chooser.winfo_children() if isinstance(w, ttk.Button) and w.cget('text') == 'Choose template').invoke()
            listing = next(w for w in chooser.winfo_children() if isinstance(w, tk.Listbox))
            index = next(i for i, text in enumerate(listing.get(0, 'end')) if text.startswith('assembling-machine-3 '))
            listing.selection_set(index)
            next(w for w in chooser.winfo_children() if isinstance(w, ttk.Button) and w.cget('text') == 'Load selected machine').invoke()
            self.assertTrue(machine_tab.ready)
            machine_tab.vars['recipes'].set('')
            fill(machine_tab, 'Machine ID', 'ui-workshop')
            fill(machine_tab, 'Display name', 'UI Workshop')
            machine_tab.add_recipes(['iron-gear-wheel', 'ui-component'])
            self.assertTrue(machine_tab.save_changes())
            self.assertIn('ui-workshop', app.project.data['machines'])
            self.assertEqual(app.catalog.items[('item', 'ui-workshop')]['place_result'], 'ui-workshop')
            self.assertEqual(app.catalog.recipes['iron-gear-wheel']['category'], 'recipe-studio-only-iron-gear-wheel')
            self.assertFalse(machine_tab.dirty)
            self.assertNotIn('ui-workshop', app.catalog.recipes)
            self.assertIn('ui-workshop', app.project.missing_machine_recipes(Catalog(app.base_raw)))
            warnings = [w for w in app.warning_area.winfo_children()]
            self.assertEqual(len(warnings), 1)
            next(w for w in warnings[0].winfo_children() if isinstance(w, ttk.Button) and w.cget('text') == 'Fix').invoke()
            construction_tab = app.nametowidget(app.tabs.select())
            self.assertTrue(construction_tab.is_custom)
            self.assertEqual(construction_tab.result_machine, 'ui-workshop')
            self.assertEqual(construction_tab.recipe.results[0]['name'], 'ui-workshop')
            construction_tab.recipe.ingredients = [{'type': 'item', 'name': 'iron-plate', 'amount': 5}]
            self.assertTrue(construction_tab.save_changes())
            self.assertEqual(app.project.missing_machine_recipes(Catalog(app.base_raw)), [])
            self.assertFalse(app.warning_area.winfo_children())
            # Each row has a remove control; selecting recipes does not need a text box.
            machine_tab.add_recipes(['iron-stick'])
            row = next(row for row in machine_tab.recipe_rows.winfo_children() if any(isinstance(w, ttk.Label) and w.cget('text') == 'iron-stick' for w in row.winfo_children()))
            next(w for w in row.winfo_children() if isinstance(w, ttk.Button)).invoke()
            self.assertNotIn('iron-stick', machine_tab.selected_recipes())
            machine_tab.import_recipes_dialog()
            importer = next(w for w in app.winfo_children() if isinstance(w, tk.Toplevel))
            listing = next(w for w in importer.winfo_children() if isinstance(w, tk.Listbox))
            index = next(i for i, text in enumerate(listing.get(0, 'end')) if text.startswith('stone-furnace '))
            listing.selection_set(index)
            next(w for w in importer.winfo_children() if isinstance(w, ttk.Button) and w.cget('text') == 'Done').invoke()
            self.assertIn('iron-plate', machine_tab.selected_recipes())
            self.assertTrue(machine_tab.save_changes())
            # Export from the main toolbar while a technology tab is selected.
            archive = work / 'recipe-studio-project_1.0.0.zip'
            with patch('tkinter.filedialog.asksaveasfilename', return_value=str(archive)):
                app.export_project()
                dialog = next(w for w in app.winfo_children() if isinstance(w, tk.Toplevel))
                next(w for w in dialog.winfo_children() if isinstance(w, ttk.Button)).invoke()
            self.assertTrue(archive.exists())
            _, files = read_mod(archive)
            self.assertIn('graphics/items/ui-component.png', files)
            code = '\n'.join(v.decode('utf-8') for k, v in files.items() if k.endswith('.lua'))
            self.assertIn('ui-research', code)
            self.assertIn('ui-workshop', code)
            self.assertIn('recipe.energy_required', code)
            # Closed recipe tabs leave edits saved; projects restore their data.
            recipe_tab.close()
            self.assertIn('iron-gear-wheel', app.project.data['recipes'])
            app.restore_project(work / 'autosave.json')
            self.assertIn(('item', 'ui-component'), app.catalog.items)
            app.nametowidget(app.tabs.select()).load('ui-component')
            self.assertTrue(app.nametowidget(app.tabs.select()).is_custom)
            app.new_machine_tab('ui-workshop')
            restored_machine = app.nametowidget(app.tabs.select())
            self.assertEqual(restored_machine.saved_name, 'ui-workshop')
            self.assertIn('ui-component', restored_machine.selected_recipes())
            self.assertFalse(restored_machine.dirty)
            # Edit a loaded drill in place, then create a separate variant from it.
            app.new_machine_tab(source=('mining-drill', 'electric-mining-drill'), mode='edit')
            edit_tab = app.nametowidget(app.tabs.select())
            self.assertEqual(edit_tab.vars['name'].get(), 'electric-mining-drill')
            self.assertEqual(float(edit_tab.vars['speed'].get()), app.base_raw['mining-drill']['electric-mining-drill']['mining_speed'])
            self.assertEqual(edit_tab.entity_type, 'mining-drill')
            edit_tab.vars['health'].set('555')
            edit_tab.vars['width'].set('5')
            edit_tab.vars['height'].set('5')
            self.assertTrue(app.undo())
            self.assertEqual(edit_tab.vars['height'].get(), '3')
            edit_tab.vars['height'].set('5')
            self.assertTrue(edit_tab.save_changes())
            self.assertEqual(app.project.data['machines']['electric-mining-drill']['operation'], 'edit')
            app.new_machine_tab(source=('mining-drill', 'electric-mining-drill'), mode='variant')
            variant_tab = app.nametowidget(app.tabs.select())
            self.assertEqual(variant_tab.vars['health'].get(), '555')
            variant_tab.vars['name'].set('ui-drill-variant')
            variant_tab.vars['color'].set('#88bbff')
            self.assertTrue(variant_tab.save_changes())
            self.assertEqual(app.project.data['machines']['ui-drill-variant']['operation'], 'create')
            self.assertEqual(app.catalog.raw['mining-drill']['electric-mining-drill']['max_health'], 555)
            self.assertEqual(app.catalog.raw['mining-drill']['ui-drill-variant']['tile_width'], 5)
            app.update()


if __name__ == '__main__':
    unittest.main()
