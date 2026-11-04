import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from app import App
from core import Catalog, load_game
from machine_model import source_config, prototypes, sprite_asset, validate_machine
from project import Project
from installation import find_installation


@unittest.skipUnless(Path('.cache/test-catalog.json').exists(), 'Requires cached catalog')
class SpriteOffset(unittest.TestCase):
    def test_layers_geometry_preview_persistence_and_engine(self):
        raw = json.loads(Path('.cache/test-catalog.json').read_text(encoding='utf-8'))
        catalog = Catalog(raw)
        config = source_config('assembling-machine', 'assembling-machine-2', catalog)
        config.update(operation='edit', visual_scale=1.4)
        baseline, _ = prototypes('assembling-machine-2', config, raw)
        config.update(sprite_offset_x=.75, sprite_offset_y=-.5)
        validate_machine('assembling-machine-2', config, catalog, Project())
        shifted, _ = prototypes('assembling-machine-2', config, raw)
        for key in ('collision_box', 'selection_box', 'tile_width', 'tile_height', 'fluid_boxes', 'minable'):
            self.assertEqual(shifted.get(key), baseline.get(key))
        for before, after in zip(baseline['graphics_set']['animation']['layers'], shifted['graphics_set']['animation']['layers']):
            self.assertEqual(after['shift'], [before['shift'][0]+.75, before['shift'][1]-.5])
        custom = copy.deepcopy(config)
        custom['sprite'] = sprite_asset(Path('assets/default-item-icon.png'))
        custom_entity, _ = prototypes('assembling-machine-2', custom, raw)
        self.assertEqual(custom_entity['graphics_set']['animation']['shift'], [.75, -.5])
        invalid = dict(config, sprite_offset_x=float('nan'))
        with self.assertRaises(ValueError):
            validate_machine('assembling-machine-2', invalid, catalog, Project())
        work = Path(tempfile.mkdtemp(dir=Path('.cache').resolve()))
        with patch('tkinter.messagebox.askyesno', return_value=False), patch('tkinter.messagebox.showerror') as errors:
            app=App(); app.withdraw(); self.addCleanup(app.destroy)
            app.autosave_path=work/'project.json'; app.catalog=catalog
            app.root_path=find_installation() or Path('unconfigured-factorio-installation')
            app.mods_path=work/'mods'; app.mods_path.mkdir()
            app.setup_frame.destroy(); app.workspace()
            app.new_machine_tab(source=('assembling-machine', 'assembling-machine-2'), mode='edit')
            tab=app.nametowidget(app.tabs.select())
            tab.vars['visual_scale'].set('1.4')
            tab.vars['sprite_offset_x'].set('.75'); tab.vars['sprite_offset_y'].set('-.5')
            self.assertGreater(tab.sprite_preview_position()[0],115)
            self.assertLess(tab.sprite_preview_position()[1],86)
            self.assertTrue(tab.save_changes(),errors.call_args_list)
            tab.load('assembling-machine-2')
            self.assertEqual(float(tab.vars['sprite_offset_x'].get()), .75)
            if find_installation():
                archive=work/'recipe-studio-project_1.0.0.zip'
                app.project.export(archive,Catalog(app.base_raw),app.root_path,app.mods_path)
                loaded,_,_=load_game(app.root_path,[archive],work/'engine')
                entity=loaded.raw['assembling-machine']['assembling-machine-2']
                self.assertEqual(entity['collision_box'],shifted['collision_box'])
                self.assertEqual(entity['graphics_set']['animation']['layers'][0]['shift'],shifted['graphics_set']['animation']['layers'][0]['shift'])
            self.assertFalse(errors.called,errors.call_args_list)

