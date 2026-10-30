import copy
import json
import os
from pathlib import Path
import tempfile
import unittest
import struct
import zlib

from core import Catalog, Recipe, load_game, read_mod
from project import Project, png_asset


def make_icon(path):
    def chunk(kind, data):
        return struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind + data) & 0xffffffff)
    data = b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', 32, 32, 8, 6, 0, 0, 0))
    data += chunk(b'IDAT', zlib.compress((b'\0' + bytes([80, 140, 200, 255]) * 32) * 32)) + chunk(b'IEND', b'')
    Path(path).write_bytes(data)
    return path


class ProjectTests(unittest.TestCase):
    def directory(self):
        cache = Path('.cache').resolve()
        cache.mkdir(exist_ok=True)
        return Path(tempfile.mkdtemp(dir=cache))

    def fixture(self):
        return Catalog({'item': {'plate': {'stack_size': 100}},
                        'tool': {'science': {'stack_size': 100}},
                        'item-subgroup': {'intermediate-product': {}},
                        'recipe': {'plate': {'type': 'recipe', 'name': 'plate', 'ingredients': [], 'results': [{'name': 'plate', 'amount': 1}]}},
                        'technology': {'start': {'name': 'start', 'unit': {'count': 1, 'time': 1, 'ingredients': [['science', 1]]}}}})

    def test_save_many_restore_compile(self):
        catalog = self.fixture()
        project = Project()
        recipe = Recipe('plate', catalog.recipes['plate'])
        project.save_recipe(recipe, 'plate', 5, True)
        project.save_recipe(recipe, 'alternate-plate', 7, True)
        path = self.directory() / 'project.json'
        project.save(path)
        restored = Project.open(path)
        code, _ = restored.compile(catalog)
        self.assertEqual(len(restored.data['recipes']), 2)
        self.assertIn('recipe.energy_required = 5.0', code)
        self.assertIn('recipe.energy_required = 7.0', code)
        self.assertEqual(restored.merged_raw(catalog.raw)['recipe']['alternate-plate']['energy_required'], 7)
        recipe.results[0]['amount'] = 99
        self.assertEqual(restored.recipe('plate').results[0]['amount'], 1)

    def test_technology_cycle_and_unknown_science(self):
        catalog = self.fixture()
        project = Project()
        prototype = {'type': 'technology', 'name': 'next', 'prerequisites': ['start'], 'unit': {'count': 10, 'time': 30, 'ingredients': [['science', 1]]}, 'effects': []}
        project.validate_technology(prototype, catalog)
        project.data['technologies']['next'] = {'prototype': prototype}
        start = copy.deepcopy(catalog.raw['technology']['start'])
        start['prerequisites'] = ['next']
        with self.assertRaisesRegex(ValueError, 'cycle'):
            project.validate_technology(start, catalog, 'start')
        prototype = copy.deepcopy(prototype)
        prototype['unit']['ingredients'] = [['missing', 1]]
        with self.assertRaisesRegex(ValueError, 'Unknown science'):
            project.validate_technology(prototype, catalog)

    def test_edited_recipe_keeps_loaded_technology_unlock(self):
        catalog = self.fixture()
        catalog.raw['technology']['start']['effects'] = [{'type': 'unlock-recipe', 'recipe': 'plate'}]
        project = Project()
        project.save_recipe(Recipe('plate', catalog.recipes['plate']), 'plate', 3, True)
        code, _ = project.compile(catalog)
        self.assertIn('recipe.enabled = false', code)
        merged = project.merged_raw(catalog.raw)
        self.assertFalse(merged['recipe']['plate']['enabled'])
        self.assertEqual(merged['technology']['start'], catalog.raw['technology']['start'])
        self.assertEqual(project.recipe_unlocks('plate', catalog.raw), ['start'])
        override = copy.deepcopy(catalog.raw['technology']['start'])
        override['effects'] = []
        project.data['technologies']['start'] = {'prototype': override}
        self.assertEqual(project.recipe_unlocks('plate', catalog.raw), [])
        self.assertTrue(project.merged_raw(catalog.raw)['recipe']['plate']['enabled'])

    @unittest.skipUnless(os.environ.get('FACTORIO_TEST_INSTALL'), 'Set FACTORIO_TEST_INSTALL for engine tests')
    def test_complete_project_engine_round_trip(self):
        install = Path(os.environ['FACTORIO_TEST_INSTALL'])
        workspace = self.directory()
        catalog, _, mods = load_game(install, [], workspace)
        project = Project()
        advanced = Recipe('advanced-circuit', catalog.recipes['advanced-circuit'])
        advanced.ingredients[0]['amount'] = 9
        project.save_recipe(advanced, 'advanced-circuit', 3, True)
        for name, amount in [('iron-gear-wheel', 7), ('burner-inserter', 9)]:
            recipe = Recipe(name, catalog.recipes[name])
            recipe.ingredients[0]['amount'] = amount
            project.save_recipe(recipe, name, 2, True, category='smelting' if name == 'iron-gear-wheel' else 'crafting')
        icon = png_asset(make_icon(workspace / 'icon.png'))
        project.data['items']['studio-component'] = {'name': 'studio-component', 'title': 'Studio Component', 'description': 'A new ingredient.',
                                                   'stack_size': 200, 'subgroup': 'intermediate-product', 'icon': icon}
        custom = Recipe('studio-component', {'ingredients': [{'type': 'item', 'name': 'iron-plate', 'amount': 3}], 'results': [{'type': 'item', 'name': 'studio-component', 'amount': 2}]})
        project.save_recipe(custom, 'studio-component', 0.5, True, custom=True)
        separation = Recipe('studio-separation', {'ingredients': [{'type': 'item', 'name': 'stone', 'amount': 8}],
            'results': [{'type': 'item', 'name': 'copper-ore', 'amount': 1}, {'type': 'item', 'name': 'stone', 'amount': 7}]})
        project.save_recipe(separation, 'studio-separation', 1, True, custom=True)
        dependent = Recipe('iron-stick', catalog.recipes['iron-stick'])
        dependent.ingredients = [{'type': 'item', 'name': 'studio-component', 'amount': 1}]
        project.save_recipe(dependent, 'iron-stick', 1, True)
        edited = copy.deepcopy(catalog.raw['technology']['automation'])
        edited['unit']['count'] = 42
        project.data['technologies']['automation'] = {'prototype': edited}
        new = {'type': 'technology', 'name': 'studio-research', 'localised_name': 'Studio Research',
               'icon': '__base__/graphics/technology/automation-1.png', 'icon_size': 256,
               'prerequisites': ['automation'], 'unit': {'count': 20, 'time': 15, 'ingredients': [['automation-science-pack', 1]]},
               'effects': [{'type': 'unlock-recipe', 'recipe': 'studio-component'}]}
        project.data['technologies']['studio-research'] = {'prototype': new, 'icon': icon}
        path = workspace / 'my-project.json'
        project.save(path)
        restored = Project.open(path)
        archive = workspace / 'recipe-studio-project_1.0.0.zip'
        restored.export(archive, catalog, install, mods)
        updated, _, _ = load_game(install, [archive], self.directory())
        self.assertEqual(updated.recipes['iron-gear-wheel']['ingredients'][0]['amount'], 7)
        self.assertFalse(updated.recipes['advanced-circuit']['enabled'])
        self.assertEqual(updated.recipes['advanced-circuit']['ingredients'][0]['amount'], 9)
        self.assertEqual(project.recipe_unlocks('advanced-circuit', updated.raw), project.recipe_unlocks('advanced-circuit', catalog.raw))
        self.assertTrue(project.recipe_unlocks('advanced-circuit', updated.raw))
        self.assertEqual(updated.recipes['iron-gear-wheel']['category'], 'smelting')
        self.assertEqual(updated.recipes['burner-inserter']['ingredients'][0]['amount'], 9)
        self.assertEqual(updated.items[('item', 'studio-component')]['stack_size'], 200)
        self.assertEqual(updated.recipes['iron-stick']['ingredients'][0]['name'], 'studio-component')
        self.assertEqual(updated.recipes['studio-separation']['main_product'], 'copper-ore')
        self.assertEqual(updated.raw['technology']['automation']['unit']['count'], 42)
        self.assertEqual(updated.raw['technology']['studio-research']['prerequisites'], ['automation'])
        self.assertFalse(updated.recipes['studio-component']['enabled'])
        self.assertIn('graphics/items/studio-component.png', read_mod(archive)[1])
        # Updating an existing mod keeps earlier edits and all embedded assets.
        second = Project()
        recipe = Recipe('burner-inserter', updated.recipes['burner-inserter'])
        recipe.ingredients[0]['amount'] = 11
        second.save_recipe(recipe, 'burner-inserter', 3, True)
        second.export(archive, updated, install, mods, target=archive)
        final, _, _ = load_game(install, [archive], self.directory())
        self.assertEqual(final.recipes['burner-inserter']['ingredients'][0]['amount'], 11)
        self.assertIn(('item', 'studio-component'), final.items)
        self.assertIn('studio-research', final.raw['technology'])


if __name__ == '__main__':
    unittest.main()
