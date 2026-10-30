from installation import find_installation
"""Rendering regressions: work stays bounded by the viewport, not tree size."""
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import tkinter as tk

from app import App
from core import Catalog


@unittest.skipUnless(Path('.cache/test-catalog.json').exists(), 'Requires cached real game data')
class TechnologyRendering(unittest.TestCase):
    def test_large_tree_is_virtualized_and_reuses_handlers(self):
        raw = json.loads(Path('.cache/test-catalog.json').read_text(encoding='utf-8'))
        icon = raw['technology']['automation']['icon']
        raw['technology'] = {f'perf-{i:04d}': {'type': 'technology', 'name': f'perf-{i:04d}', 'icon': icon, 'icon_size': 256,
                                              'prerequisites': [f'perf-{i-1:04d}'] if i else [],
                                              'unit': {'count': 10, 'time': 10, 'ingredients': [['automation-science-pack', 1]]}} for i in range(3000)}
        with patch('tkinter.messagebox.askyesno', return_value=False):
            app = App()
            app.withdraw()
            self.addCleanup(app.destroy)
            app.catalog = Catalog(raw)
            app.root_path = (find_installation() or Path('unconfigured-factorio-installation'))
            app.mods_path = Path('.cache/preview-mods')
            app.mods_path.mkdir(exist_ok=True)
            app.setup_frame.destroy()
            app.workspace()
            app.tech_tab()
            tree = app.nametowidget(app.tabs.select())
            self.assertFalse(hasattr(tree, 'gallery'))
            self.assertEqual(len(tree.positions), 3000)
            self.assertLess(len(tree.rendered_nodes), 20)
            self.assertLess(len(tree.canvas.find_all()), 200)
            # Opening the tree paints placeholders without decoding 3000 PNGs.
            self.assertFalse(getattr(app, 'prototype_sources', {}))
            self.assertGreater(len(tree.icon_tasks), 0)
            tree.after_cancel(tree.image_job)
            tree.image_job = None
            tree.load_next_icon()
            self.assertGreater(len(app.prototype_sources), 0)
            # Repainting does not register a new Python callback per card.
            handlers_before = len(tree.canvas._tclCommands or [])
            ids_before = tree.canvas.find_all()
            tree.draw()
            self.assertEqual(tree.canvas.find_all(), ids_before)
            for index in range(40):
                tree.selected = f'perf-{index % 4:04d}'
                tree.draw()
            self.assertEqual(len(tree.canvas._tclCommands or []), handlers_before)
            # Panning/focusing loads distant cards and drops off-screen ones.
            tree.focus_node('perf-2999')
            self.assertIn('perf-2999', tree.rendered_nodes)
            self.assertNotIn('perf-0000', tree.rendered_nodes)
            self.assertLess(len(tree.rendered_nodes), 20)
            world = (tree.canvas.canvasx(60) / tree.zoom, tree.canvas.canvasy(60) / tree.zoom)
            tree.wheel(SimpleNamespace(state=4, delta=120, x=60, y=60))
            self.assertAlmostEqual(tree.canvas.canvasx(60) / tree.zoom, world[0], delta=3)
            self.assertAlmostEqual(tree.canvas.canvasy(60) / tree.zoom, world[1], delta=3)
            self.assertLess(len(tree.rendered_nodes), 20)
            tree.close()
            app.update()


if __name__ == '__main__':
    unittest.main()
