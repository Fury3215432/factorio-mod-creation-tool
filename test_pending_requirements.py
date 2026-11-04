from installation import find_installation
import json
import os
from pathlib import Path
import tempfile
import tkinter as tk
from tkinter import ttk
import unittest
from unittest.mock import patch

from app import App
from core import Catalog, load_game, read_mod
from project import Project, default_icon_asset
from test_project import make_icon


@unittest.skipUnless(Path('.cache/test-catalog.json').exists(), 'Requires cached real game data')
class PendingRequirements(unittest.TestCase):
    def test_create_result_with_fuel(self):
        from project import fuel_energy
        for bad in ('-1MJ', '0J', 'nan', '5MW', 'coal'):
            with self.assertRaises(ValueError):
                fuel_energy(bad)
        work = Path(tempfile.mkdtemp(dir=Path('.cache').resolve()))
        with patch('tkinter.messagebox.askyesno', return_value=False), patch('tkinter.messagebox.showerror') as errors:
            app = App()
            app.withdraw()
            self.addCleanup(app.destroy)
            app.autosave_path = work / 'project.json'
            app.root_path = find_installation() or Path('unconfigured-factorio-installation')
            app.mods_path = work / 'mods'
            app.mods_path.mkdir()
            app.catalog = Catalog(json.loads(Path('.cache/test-catalog.json').read_text(encoding='utf-8')))
            app.setup_frame.destroy()
            app.workspace()
            tab = app.nametowidget(app.tabs.select())
            tab.edit_item(as_result=True)
            dialog = next(w for w in app.winfo_children() if isinstance(w, tk.Toplevel))
            def descendants(widget):
                for child in widget.winfo_children():
                    yield child
                    yield from descendants(child)
            for row in descendants(dialog):
                children = row.winfo_children()
                if children and isinstance(children[0], ttk.Label):
                    value = {'Item ID': 'test-fuel-result', 'Fuel value': '8 MJ'}.get(children[0].cget('text'))
                    if value:
                        entry = next(w for w in children if isinstance(w, ttk.Entry))
                        entry.delete(0, 'end')
                        entry.insert(0, value)
            count = len(app.undo_stack)
            next(w for w in descendants(dialog) if isinstance(w, ttk.Button) and w.cget('text') == 'Create item').invoke()
            self.assertFalse(errors.called, errors.call_args_list)
            self.assertEqual(len(app.undo_stack), count + 1)
            self.assertEqual(tab.recipe.results[0]['name'], 'test-fuel-result')
            self.assertEqual(tab.name.get(), 'test-fuel-result_recipe')
            self.assertEqual(app.catalog.items[('item', 'test-fuel-result')]['fuel_value'], '8MJ')
            self.assertEqual(app.catalog.items[('item', 'test-fuel-result')]['fuel_category'], 'chemical')
            code = app.project.compile(Catalog(app.base_raw))[0]
            self.assertIn('8MJ', str(code))
            restored = Project.open(app.autosave_path)
            self.assertEqual(restored.item_prototype('test-fuel-result')['fuel_value'], '8MJ')
            self.assertTrue(app.undo())
            self.assertNotIn('test-fuel-result', app.project.data['items'])
            self.assertFalse(tab.recipe.results)
            # Loaded fuels retain their properties and can be made non-fuel explicitly.
            coal = app.project.editable_item(('item', 'coal'), app.catalog)
            app.project.data['items']['coal'] = coal
            self.assertEqual(app.project.item_prototype('coal')['fuel_value'], app.catalog.items[('item', 'coal')]['fuel_value'])
            coal['fuel_value'] = ''
            self.assertNotIn('fuel_value', app.project.item_prototype('coal'))
            self.assertNotIn('fuel_category', app.project.item_prototype('coal'))

    def test_fallback_pending_export_replace_and_undo(self):
        work = Path(tempfile.mkdtemp(dir=Path('.cache').resolve()))
        with patch('tkinter.messagebox.askyesno', return_value=False), patch('tkinter.messagebox.showerror') as errors:
            app = App()
            app.withdraw()
            self.addCleanup(app.destroy)
            app.autosave_path = work / 'project.json'
            app.root_path = (find_installation() or Path('unconfigured-factorio-installation'))
            app.mods_path = work / 'mods'
            app.mods_path.mkdir()
            app.catalog = Catalog(json.loads(Path('.cache/test-catalog.json').read_text(encoding='utf-8')))
            app.setup_frame.destroy()
            app.workspace()
            # Informational multi-tech entries keep the button accessible without a badge.
            self.assertEqual(app.pending_button.cget('text'), 'Suggested actions')
            recipe_tab = app.nametowidget(app.tabs.select())
            recipe_tab.edit_item()
            dialog = next(w for w in app.winfo_children() if isinstance(w, tk.Toplevel))
            def descendants(widget):
                for child in widget.winfo_children():
                    yield child
                    yield from descendants(child)
            for row in descendants(dialog):
                children = row.winfo_children()
                if children and isinstance(children[0], ttk.Label) and children[0].cget('text') == 'Item ID':
                    entry = next(w for w in children if isinstance(w, ttk.Entry))
                    entry.insert(0, 'pending-item')
                    break
            next(w for w in descendants(dialog) if isinstance(w, ttk.Button) and w.cget('text') == 'Create item').invoke()
            self.assertFalse(errors.called, errors.call_args_list)
            item = app.project.data['items']['pending-item']
            self.assertEqual(item['icon'], default_icon_asset())
            self.assertTrue(item['icon_is_default'])
            self.assertEqual(app.pending_button.winfo_manager(), 'pack')
            toolbar = app.create_machine_button.master.pack_slaves()
            self.assertEqual(toolbar.index(app.pending_button), toolbar.index(app.create_machine_button) + 1)
            self.assertIsNotNone(app.icon(('item', 'pending-item')))
            self.assertEqual(Project.open(app.autosave_path).items_missing_icons(), ['pending-item'])
            app.pending_button.invoke()
            pending = app.nametowidget(app.tabs.select())
            self.assertEqual(pending.items.get_children(), ('pending-item',))
            self.assertEqual(pending.recipes.get_children(), ('item:pending-item',))
            text = work / 'items.txt'
            self.assertTrue(pending.export_text(text))
            self.assertEqual(text.read_text(encoding='utf-8'), 'pending-item\n')
            # Default-icon items remain valid mod assets, not just UI placeholders.
            archive = work / 'recipe-studio-project_1.0.0.zip'
            app.project.export(archive, Catalog(app.base_raw), app.root_path, app.mods_path)
            self.assertIn('graphics/items/pending-item.png', read_mod(archive)[1])
            if os.environ.get('FACTORIO_TEST_INSTALL'):
                loaded, _, _ = load_game(os.environ['FACTORIO_TEST_INSTALL'], [archive], work / 'engine')
                self.assertEqual(loaded.items[('item', 'pending-item')]['icon_size'], 64)
            png = make_icon(work / 'real-icon.png')
            pending.items.selection_set('pending-item')
            with patch('pending_ui.filedialog.askopenfilename', return_value=str(png)):
                pending.choose_selected()
            self.assertEqual(app.project.items_missing_icons(), [])
            self.assertTrue(app.pending_button.winfo_manager())
            self.assertFalse(pending.items.get_children())
            self.assertFalse(app.project.data['items']['pending-item']['icon_is_default'])
            self.assertTrue(app.undo())
            self.assertEqual(app.project.items_missing_icons(), ['pending-item'])
            self.assertTrue(app.pending_button.winfo_manager())
            self.assertEqual(pending.items.get_children(), ('pending-item',))
            self.assertFalse(errors.called, errors.call_args_list)
            # Exercise the actual Windows shell-drop handler, including Unicode paths.
            import ctypes
            import struct
            from ctypes import wintypes
            if hasattr(pending.items, '_file_drop_handler'):
                unicode_png = work / 'icon with spaces é.png'
                unicode_png.write_bytes(png.read_bytes())
                data = struct.pack('<IiiII', 20, 4, 6, 0, 1) + (str(unicode_png) + '\0\0').encode('utf-16-le')
                kernel = ctypes.WinDLL('kernel32')
                kernel.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
                kernel.GlobalAlloc.restype = wintypes.HGLOBAL
                kernel.GlobalLock.argtypes = [wintypes.HGLOBAL]
                kernel.GlobalLock.restype = ctypes.c_void_p
                kernel.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
                handle = kernel.GlobalAlloc(0x42, len(data))
                self.assertTrue(handle)
                address = kernel.GlobalLock(handle)
                ctypes.memmove(address, data, len(data))
                kernel.GlobalUnlock(handle)
                user = ctypes.WinDLL('user32')
                user.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
                user.PostMessageW.restype = ctypes.c_ssize_t
                pending.groups.select(pending.icons_page)
                with patch.object(pending.items, 'identify_row', return_value='pending-item'):
                    user.PostMessageW(pending.items.winfo_id(), 0x233, handle, 0)
                    app.after(120, app.quit)
                    app.mainloop()
                self.assertFalse(app.project.items_missing_icons())
                self.assertEqual(app.project.data['items']['pending-item']['icon_path'], str(unicode_png))
                self.assertTrue(app.undo())
                self.assertEqual(app.project.items_missing_icons(), ['pending-item'])
                with patch.object(pending.items, 'identify_row', return_value='pending-item'):
                    self.assertFalse(pending.drop_icon(['bad.jpg'], 0, 0))
                    self.assertFalse(pending.drop_icon([str(png), str(png)], 0, 0))
                errors.reset_mock()
            # A missing crafting recipe has a working Fix action and clears on save.
            pending.recipes.selection_set('item:pending-item')
            recipe = pending.fix_recipe()
            self.assertEqual(recipe.recipe.results[0]['name'], 'pending-item')
            self.assertEqual(recipe.name.get(), 'pending-item_recipe')
            self.assertTrue(recipe.save_changes())
            self.assertFalse(pending.recipes.get_children())
            self.assertTrue(app.project.items_missing_icons())
            self.assertTrue(app.pending_button.winfo_manager())
            self.assertTrue(app.undo())
            self.assertEqual(pending.recipes.get_children(), ('item:pending-item',))
            app.update()

    def test_loaded_recipe_can_be_saved_as_copy(self):
        work = Path(tempfile.mkdtemp(dir=Path('.cache').resolve()))
        with patch('tkinter.messagebox.askyesno', return_value=False), patch('tkinter.messagebox.showerror') as errors:
            app = App()
            app.withdraw()
            self.addCleanup(app.destroy)
            app.autosave_path = work / 'project.json'
            app.root_path = (find_installation() or Path('unconfigured-factorio-installation'))
            app.mods_path = work / 'mods'
            app.mods_path.mkdir()
            app.catalog = Catalog(json.loads(Path('.cache/test-catalog.json').read_text(encoding='utf-8')))
            app.setup_frame.destroy()
            app.workspace()
            tab = app.nametowidget(app.tabs.select())
            self.assertFalse(tab.copy_button.winfo_manager())
            tab.load('iron-gear-wheel')
            self.assertEqual(tab.copy_button.winfo_manager(), 'pack')
            self.assertEqual(tab.commit_text.get(), 'Apply edit')
            tab.recipe.ingredients[0]['amount'] = 8
            tab.mark()
            self.assertTrue(tab.save_as_new('eight-plate-gears'))
            self.assertNotIn('iron-gear-wheel', app.project.data['recipes'])
            self.assertEqual(tab.loaded_name, 'eight-plate-gears')
            self.assertFalse(tab.dirty)
            self.assertTrue(app.save_all())
            self.assertNotIn('iron-gear-wheel', app.project.data['recipes'])
            self.assertEqual(app.catalog.recipes['iron-gear-wheel']['ingredients'][0]['amount'], 2)
            self.assertEqual(app.catalog.recipes['eight-plate-gears']['ingredients'][0]['amount'], 8)
            if os.environ.get('FACTORIO_TEST_INSTALL'):
                archive = work / 'recipe-studio-project_1.0.0.zip'
                app.project.export(archive, Catalog(app.base_raw), app.root_path, app.mods_path)
                loaded, _, _ = load_game(os.environ['FACTORIO_TEST_INSTALL'], [archive], work / 'engine')
                self.assertEqual(loaded.recipes['iron-gear-wheel']['ingredients'][0]['amount'], 2)
                self.assertEqual(loaded.recipes['eight-plate-gears']['ingredients'][0]['amount'], 8)
            self.assertTrue(app.undo())
            self.assertEqual(tab.loaded_name, 'iron-gear-wheel')
            self.assertNotIn('eight-plate-gears', app.project.data['recipes'])
            self.assertEqual(tab.recipe.ingredients[0]['amount'], 8)
            self.assertFalse(errors.called, errors.call_args_list)


if __name__ == '__main__':
    unittest.main()
