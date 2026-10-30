import json
import os
from pathlib import Path
import tempfile
import unittest

from core import Catalog, Recipe, entries, load_game, lua, export_mod, read_mod


class RecipeTests(unittest.TestCase):
    def test_legacy_and_special_products(self):
        proto = {'normal': {'ingredients': [['iron-plate', 2]], 'results': [{'name': 'iron-gear-wheel', 'amount_min': 1, 'amount_max': 3, 'probability': 0.5}]}}
        recipe = Recipe('gears', proto)
        self.assertEqual(recipe.ingredients[0]['amount'], 2)
        exported = recipe.export('new-gears', 1, True)
        self.assertIn('["probability"] = 0.5', exported)
        self.assertIn('source.normal or {}', exported)
        recipe.ingredients[0]['amount'] = 10
        self.assertEqual(proto['normal']['ingredients'][0][1], 2)

    def test_validation(self):
        recipe = Recipe('test', {'ingredients': [], 'result': 'iron-plate'})
        for name, seconds in [('bad.name', 1), ('ok', 'nan'), ('ok', 0)]:
            with self.assertRaises(ValueError):
                recipe.export(name, seconds, True)
        recipe.results[0]['amount'] = 1.5
        with self.assertRaises(ValueError):
            recipe.export('ok', 1, True)

    def test_fluid_and_catalog(self):
        raw = {'fluid': {'water': {'name': 'water'}}, 'item': {'iron-plate': {'stack_size': 100}}, 'recipe': {'wet': {'results': [{'type': 'fluid', 'name': 'water', 'amount': 1.5}]}}}
        catalog = Catalog(raw)
        self.assertIn(('fluid', 'water'), catalog.items)
        self.assertEqual(catalog.by_product[('fluid', 'water')], ['wet'])
        self.assertIn('1.5', Recipe('wet', raw['recipe']['wet']).export('wet-new', 1, True))
        self.assertEqual(lua('a\nb"c'), '"a\\010b\\"c"')

    @unittest.skipUnless(os.environ.get('FACTORIO_TEST_INSTALL'), 'Set FACTORIO_TEST_INSTALL for real engine round-trip')
    def test_real_engine_mod_round_trip(self):
        install = os.environ['FACTORIO_TEST_INSTALL']
        cache = Path('.cache').resolve()
        cache.mkdir(exist_ok=True)
        first = Path(tempfile.mkdtemp(dir=cache))
        catalog, _, _ = load_game(install, [], first)
        recipe = Recipe('iron-gear-wheel', catalog.recipes['iron-gear-wheel'])
        recipe.ingredients[0]['amount'] = 7
        recipe.results[0]['amount'] = 3
        mod = Path(tempfile.mkdtemp(dir=cache))
        version = json.loads((Path(install) / 'data/base/info.json').read_text())['version']
        (mod / 'info.json').write_text(json.dumps({'name': 'recipe-studio-test', 'version': '1.0.0', 'title': 'Recipe Studio Test', 'author': 'Recipe Studio', 'factorio_version': '.'.join(version.split('.')[:2]), 'dependencies': ['base']}))
        (mod / 'recipes').mkdir()
        (mod / 'recipes' / 'studio-gears.lua').write_text(recipe.export('studio-gears', 2, True), encoding='utf-8')
        (mod / 'data.lua').write_text('require("recipes.studio-gears")')
        second = Path(tempfile.mkdtemp(dir=cache))
        updated, _, _ = load_game(install, [mod], second)
        result = updated.recipes['studio-gears']
        self.assertEqual(result['ingredients'][0]['amount'], 7)
        self.assertEqual(result['results'][0]['amount'], 3)
        self.assertEqual(result['energy_required'], 2)
        # A standalone archive loads its own recipe with no manual require line.
        empty_mods = first / 'mods'
        standalone = cache / 'recipe-studio-gears_1.0.0.zip'
        export_mod(standalone, recipe, 'iron-gear-wheel', 3, True, install, empty_mods, mod_name='recipe-studio-gears')
        standalone_catalog, _, _ = load_game(install, [standalone], Path(tempfile.mkdtemp(dir=cache)))
        self.assertEqual(standalone_catalog.recipes['iron-gear-wheel']['ingredients'][0]['amount'], 7)
        self.assertEqual(standalone_catalog.recipes['iron-gear-wheel']['energy_required'], 3)
        # Keep the selected mod's original final-fixes, even if it returns.
        (mod / 'data-final-fixes.lua').write_text('data.raw.recipe["iron-plate"].energy_required = 12\nreturn true\n')
        (mod / 'asset.txt').write_text('preserve this file')
        edited = Recipe('burner-inserter', catalog.recipes['burner-inserter'])
        edited.ingredients[0]['amount'] = 9
        patched = cache / 'recipe-studio-test_1.0.0.zip'
        export_mod(patched, edited, 'burner-inserter', 4, True, install, empty_mods, target=mod)
        patched_catalog, _, _ = load_game(install, [patched], Path(tempfile.mkdtemp(dir=cache)))
        self.assertEqual(patched_catalog.recipes['burner-inserter']['ingredients'][0]['amount'], 9)
        self.assertEqual(patched_catalog.recipes['iron-plate']['energy_required'], 12)
        self.assertIn('studio-gears', patched_catalog.recipes)
        info, files = read_mod(patched)
        self.assertEqual(files['asset.txt'], b'preserve this file')
        # Re-export an already patched ZIP and keep its previous edits.
        export_mod(patched, recipe, 'iron-gear-wheel', 5, True, install, empty_mods, target=patched)
        final, _, _ = load_game(install, [patched], Path(tempfile.mkdtemp(dir=cache)))
        self.assertEqual(final.recipes['burner-inserter']['ingredients'][0]['amount'], 9)
        self.assertEqual(final.recipes['iron-gear-wheel']['energy_required'], 5)

    def test_mod_dependency_and_filename(self):
        cache = Path('.cache').resolve()
        cache.mkdir(exist_ok=True)
        root = Path(tempfile.mkdtemp(dir=cache))
        (root / 'data/base').mkdir(parents=True)
        (root / 'data/base/info.json').write_text('{"version":"2.0.77"}')
        mods = root / 'mods'
        mod = mods / 'example_1.0.0'
        mod.mkdir(parents=True)
        (mod / 'info.json').write_text(json.dumps({'name': 'example', 'version': '1.0.0'}))
        recipe = Recipe('test', {'ingredients': [], 'result': 'iron-plate'})
        destination = root / 'recipe-studio-test_1.0.0.zip'
        info = export_mod(destination, recipe, 'test', 1, True, root, mods)
        self.assertIn('example >= 1.0.0', info['dependencies'])
        self.assertIn('data-final-fixes.lua', read_mod(destination)[1])
        with self.assertRaises(ValueError):
            export_mod(root / 'wrong.zip', recipe, 'test', 1, True, root, mods)


if __name__ == '__main__':
    unittest.main()
