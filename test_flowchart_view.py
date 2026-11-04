import json
from pathlib import Path
import tempfile
import tkinter as tk
from tkinter import ttk
import unittest
from unittest.mock import patch

from app import App
from core import Catalog
from creations_ui import open_all_recipes_containing
from installation import find_installation


@unittest.skipUnless(Path('.cache/test-catalog.json').exists(), 'Requires cached catalog')
class FlowchartView(unittest.TestCase):
    def test_edits_and_catalog_refresh_preserve_panned_zoomed_view(self):
        work = Path(tempfile.mkdtemp(dir=Path('.cache').resolve()))
        with patch('tkinter.messagebox.askyesno', return_value=False), patch('tkinter.messagebox.showerror') as errors:
            app = App(); self.addCleanup(app.destroy)
            app.geometry('1100x800')
            app.autosave_path = work / 'project.json'
            app.catalog = Catalog(json.loads(Path('.cache/test-catalog.json').read_text(encoding='utf-8')))
            app.root_path = find_installation() or Path('unconfigured-factorio-installation')
            app.mods_path = work / 'mods'; app.mods_path.mkdir()
            app.setup_frame.destroy(); app.workspace()
            tab = app.nametowidget(app.tabs.select())
            for key in [key for key in app.catalog.items if key[0] == 'item'][:20]:
                tab.add_entry('ingredients', key)
            tab.add_entry('results', ('item', 'iron-plate'))
            tab.zoom = 2; tab.draw(); app.update()
            def pan(chart):
                chart.canvas.xview_moveto(.35); chart.canvas.yview_moveto(.65)
                app.update_idletasks()
                return chart.canvas.canvasx(0), chart.canvas.canvasy(0)
            def assert_view(chart, expected):
                app.update_idletasks()
                self.assertAlmostEqual(chart.canvas.canvasx(0), expected[0], delta=2)
                self.assertAlmostEqual(chart.canvas.canvasy(0), expected[1], delta=2)
            position = pan(tab)
            self.assertGreater(position[1], 1000)
            tab.edit('ingredients', 15)
            dialog = next(w for w in app.winfo_children() if isinstance(w, tk.Toplevel))
            entry = next(w for w in dialog.winfo_children() if isinstance(w, ttk.Entry))
            entry.delete(0, 'end'); entry.insert(0, '7')
            next(w for w in dialog.winfo_children() if isinstance(w, ttk.Button) and w.cget('text') == 'Save changes').invoke()
            assert_view(tab, position)
            tab.draw(); assert_view(tab, position)
            app.refresh_catalog(); assert_view(tab, position)
            from flow import zoom_at
            world = (tab.canvas.canvasx(60)/tab.zoom, tab.canvas.canvasy(60)/tab.zoom)
            zoom_at(tab, .9, tab.draw, 60, 60)
            self.assertAlmostEqual(tab.canvas.canvasx(60)/tab.zoom, world[0], delta=2)
            self.assertAlmostEqual(tab.canvas.canvasy(60)/tab.zoom, world[1], delta=2)
            multi = open_all_recipes_containing(app, ('item', 'copper-plate'))
            multi.zoom = 1.5; multi.draw(); app.update()
            position = pan(multi)
            path = next(iter(multi.direct_roots))
            _, recipe, _ = multi.chain_recipe(path)
            self.assertTrue(multi.save_chain_recipe(path, recipe, 3))
            assert_view(multi, position)
            self.assertEqual(multi.zoom, 1.5)
            self.assertFalse(errors.called, errors.call_args_list)

