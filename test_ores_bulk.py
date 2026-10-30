from installation import find_installation
import copy
import json
import os
from pathlib import Path
import subprocess
import tempfile
import tkinter as tk
from tkinter import ttk
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from app import App
from bulk_science import apply_science
from core import Catalog, load_game, read_mod
from project import Project, default_icon_asset


@unittest.skipUnless(Path('.cache/test-catalog.json').exists(), 'Requires cached game catalog')
class OreAndBulkTests(unittest.TestCase):
    def test_ore_and_bulk_science(self):
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
            app.new_tab().edit_item()
            dialog = next(w for w in app.winfo_children() if isinstance(w, tk.Toplevel))
            def descendants(widget):
                for child in widget.winfo_children():
                    yield child
                    yield from descendants(child)
            fields = {}
            for row in descendants(dialog):
                children = row.winfo_children()
                if children and isinstance(children[0], ttk.Label):
                    for child in children[1:]:
                        if isinstance(child, (ttk.Entry, ttk.Combobox)):
                            fields[children[0].cget('text')] = child
            fields['Creation type'].set('ore')
            for label, value in [('Item ID', 'violet-ore'), ('Mining seconds', '0.25'), ('Mining yield', '2'), ('Ore density', '50'), ('Ore color', '#bb66ff')]:
                fields[label].delete(0, 'end')
                fields[label].insert(0, value)
            next(w for w in descendants(dialog) if isinstance(w, ttk.Button) and w.cget('text') == 'Create ore').invoke()
            self.assertFalse(errors.called, errors.call_args_list)
            self.assertIn(('item', 'violet-ore'), app.catalog.items)
            resource = app.catalog.raw['resource']['violet-ore']
            self.assertEqual(resource['minable']['results'][0]['amount'], 2)
            self.assertEqual(resource['category'], 'basic-solid')
            self.assertIn('violet-ore', app.catalog.raw['autoplace-control'])
            self.assertIn('violet-ore', Project.open(app.autosave_path).data['items'])
            browser = app.browse_creations()
            browser.kind_filter.set('ore')
            self.assertEqual(browser.list.get_children(), ('ore:violet-ore',))
            self.assertTrue(app.undo())
            self.assertNotIn('violet-ore', app.catalog.raw.get('resource', {}))
            # Restore the ore for real-game validation below.
            restored = {'name': 'violet-ore', 'title': 'Violet ore', 'kind': 'ore', 'stack_size': 100,
                        'subgroup': 'raw-resource', 'icon': default_icon_asset(),
                        'ore_template': 'iron-ore', 'ore_color': '#bb66ff', 'ore_density': 50, 'mining_time': .25, 'mining_amount': 2}
            app.project.data['items']['violet-ore'] = restored
            app.refresh_catalog()
            tree = app.tech_tab()
            tree.edit('automation-2')
            tree.clear_selection()
            names = {'automation-2', 'logistics-2'}
            for name in names:
                with patch.object(tree, 'node_name', return_value=name):
                    tree.node_click(SimpleNamespace(state=4))
            self.assertEqual(tree.multi_selected, names)
            original = {n: copy.deepcopy(app.catalog.raw['technology'][n]) for n in names}
            changed, skipped = apply_science(tree, names, {'chemical-science-pack'}, 'add', 3)
            self.assertEqual(set(changed), names)
            self.assertFalse(skipped)
            for name in names:
                proto = app.catalog.raw['technology'][name]
                self.assertEqual(proto['unit']['ingredients'][-1], ['chemical-science-pack', 3])
                self.assertEqual(proto['unit']['time'], original[name]['unit']['time'])
                self.assertEqual(proto['unit']['count'], original[name]['unit']['count'])
                self.assertEqual(proto.get('effects'), original[name].get('effects'))
            self.assertEqual(tree.multi_selected, names)
            changed, _ = apply_science(tree, names, {'chemical-science-pack'}, 'add', 9)
            self.assertFalse(changed)
            self.assertTrue(app.undo())
            for name in names:
                self.assertEqual(app.catalog.raw['technology'][name], original[name])
            changed, _ = apply_science(tree, names, {'chemical-science-pack'}, 'add', 3)
            changed, _ = apply_science(tree, names, {'chemical-science-pack'}, 'remove')
            self.assertEqual(set(changed), names)
            saved = copy.deepcopy(app.project.data)
            with self.assertRaisesRegex(ValueError, 'every science pack'):
                apply_science(tree, names, {'automation-science-pack', 'logistic-science-pack'}, 'remove')
            self.assertEqual(app.project.data, saved)
            # Trigger-based technologies are left unchanged.
            trigger = next(n for n, t in tree.technologies.items() if t.get('research_trigger'))
            changed, skipped = apply_science(tree, [trigger], {'chemical-science-pack'}, 'add')
            self.assertFalse(changed)
            self.assertEqual(skipped, [trigger])
            dialog = tree.bulk_science_dialog()
            self.assertIsNotNone(dialog)
            dialog.destroy()
            self.assertFalse(errors.called, errors.call_args_list)
            if os.environ.get('FACTORIO_TEST_INSTALL'):
                self.check_engine(app, work)

    def check_engine(self, app, work):
        archive = work / 'ore-bulk-test_1.0.0.zip'
        app.project.export(archive, Catalog(app.base_raw), app.root_path, app.mods_path, mod_name='ore-bulk-test')
        loaded, _, _ = load_game(app.root_path, [archive], work / 'dump')
        resource = loaded.raw['resource']['violet-ore']
        self.assertEqual(resource['minable']['mining_time'], .25)
        self.assertIn('autoplace', resource)
        self.assertIn('violet-ore', loaded.raw['planet']['nauvis']['map_gen_settings']['autoplace_controls'])
        self.assertEqual(loaded.raw['technology']['automation-2']['unit']['ingredients'], app.catalog.raw['technology']['automation-2']['unit']['ingredients'])
        mod = work / 'runtime-mod'
        mod.mkdir()
        for name, data in read_mod(archive)[1].items():
            path = mod / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        (mod / 'control.lua').write_text('''
script.on_init(function()
  local surface = game.surfaces[1]
  surface.request_to_generate_chunks({0,0}, 8)
  surface.force_generate_chunk_requests()
  assert(surface.count_entities_filtered{name="violet-ore"} > 0, "Ore did not generate naturally")
  for _, e in pairs(surface.find_entities_filtered{area={{-4,-4},{4,4}}}) do e.destroy() end
  local tiles = {}
  for x=-4,4 do for y=-4,4 do tiles[#tiles+1]={name="grass-1", position={x,y}} end end
  surface.set_tiles(tiles)
  assert(surface.create_entity{name="violet-ore",position={0.5,0.5},amount=10000})
  storage.drill = assert(surface.create_entity{name="electric-mining-drill",position={0.5,0.5},force="player"})
end)
script.on_event(defines.events.on_tick, function(event)
  storage.drill.energy = 1000000
  if event.tick == 240 then
    local count = 0
    for _, item in pairs(game.surfaces[1].find_entities_filtered{type="item-entity",area={{-5,-5},{5,5}}}) do
      if item.stack.valid_for_read and item.stack.name == "violet-ore" then count = count + item.stack.count end
    end
    assert(count > 0, "Drill did not mine the custom ore")
    helpers.write_file("ore-test.txt", "generated and mined", false)
  end
end)
''', encoding='utf-8')
        runtime = work / 'runtime'
        load_game(app.root_path, [mod], runtime)
        args = [str(app.root_path / 'bin/x64/factorio.exe'), '--config', str(runtime / 'config.ini'), '--mod-directory', str(runtime / 'mods')]
        save = runtime / 'test.zip'
        for command in (['--create', str(save)], ['--benchmark', str(save), '--benchmark-ticks', '245', '--benchmark-runs', '1']):
            result = subprocess.run(args + command, capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=180, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            self.assertEqual(result.returncode, 0, (result.stdout + result.stderr)[-5000:])
        self.assertEqual((runtime / 'script-output/ore-test.txt').read_text(), 'generated and mined')
