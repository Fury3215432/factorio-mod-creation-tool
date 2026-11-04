import json
from pathlib import Path
import tempfile
import unittest
import wave
from core import Catalog, load_game, read_mod
from project import Project, default_icon_asset
from machine_model import sprite_asset
from ore_model import resource, sound_asset
from installation import find_installation
from test_project import make_icon

@unittest.skipUnless(Path('.cache/test-catalog.json').exists(), 'Requires cached catalog')
class CustomOre(unittest.TestCase):
    def test_custom_graphics_sounds_persist_and_load(self):
        work = Path(tempfile.mkdtemp(dir=Path('.cache').resolve()))
        catalog = Catalog(json.loads(Path('.cache/test-catalog.json').read_text(encoding='utf-8')))
        png = make_icon(work / 'ore.png')
        sound = work / 'ore.wav'
        with wave.open(str(sound), 'wb') as output:
            output.setnchannels(1)
            output.setsampwidth(2)
            output.setframerate(44100)
            output.writeframes(b'\0\0' * 4410)
        item = {'name': 'custom-ore-test', 'title': 'Custom ore', 'kind': 'ore', 'stack_size': 100,
                'subgroup': 'raw-resource', 'icon': default_icon_asset(), 'ore_graphics': sprite_asset(png),
                'ore_frame_width': 16, 'ore_frame_height': 16, 'ore_stage_counts': [100, 0],
                'ore_variations': 2, 'ore_graphics_scale': 1.5, 'ore_sound_volume': .5,
                'ore_mining_sound': sound_asset(sound), 'ore_mined_sound': sound_asset(sound),
                'ore_walking_sound': sound_asset(sound), 'ore_autoplace': True}
        project = Project()
        project.data['items'][item['name']] = item
        prototype = resource(item['name'], item, catalog.raw, project.item_prototype(item['name']))
        self.assertEqual(prototype['stage_counts'], [100, 0])
        self.assertEqual(prototype['stages']['sheet']['variation_count'], 2)
        self.assertEqual(prototype['stages']['sheet']['scale'], 3)
        with self.assertRaisesRegex(ValueError, 'fit'):
            resource(item['name'], dict(item, ore_variations=3), catalog.raw, project.item_prototype(item['name']))
        path = work / 'project.json'
        project.save(path)
        png.unlink()
        sound.unlink()
        project = Project.open(path)
        root = find_installation()
        if root:
            mods = work / 'mods'
            mods.mkdir()
            archive = work / 'recipe-studio-project_1.0.0.zip'
            project.export(archive, catalog, root, mods)
            files = read_mod(archive)[1]
            self.assertIn('graphics/ores/custom-ore-test.png', files)
            self.assertIn('sound/ores/custom-ore-test-mining.wav', files)
            loaded, _, _ = load_game(root, [archive], work / 'engine')
            ore = loaded.raw['resource']['custom-ore-test']
            self.assertEqual(ore['stage_counts'], [100, 0])
            self.assertEqual(ore['mining_sound']['volume'], .5)
            self.assertEqual(ore['walking_sound']['volume'], .5)
