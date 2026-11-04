import copy
import json
from pathlib import Path
import tempfile
import unittest
from core import Catalog, Recipe, load_game
from installation import find_installation
from project import Project


class FurnaceOutputs(unittest.TestCase):
    def test_slots_match_solid_outputs_and_preserve_other_furnaces(self):
        raw = {'recipe': {}, 'furnace': {
            'small': {'crafting_categories': ['smelting'], 'result_inventory_size': 1},
            'large': {'crafting_categories': ['smelting'], 'result_inventory_size': 4},
            'other': {'crafting_categories': ['other'], 'result_inventory_size': 1},
            'fixed': {'crafting_categories': ['smelting'], 'fixed_recipe': 'other', 'result_inventory_size': 1}}}
        project = Project()
        recipe = Recipe('test', {'category': 'smelting', 'ingredients': [], 'results': [
            {'type': 'item', 'name': 'a', 'amount': 2}, {'type': 'item', 'name': 'b', 'amount': 1},
            {'type': 'fluid', 'name': 'water', 'amount': 10}]})
        project.save_recipe(recipe, 'test', 1, True, custom=True)
        merged = project.merged_raw(raw)
        self.assertEqual([merged['furnace'][name]['result_inventory_size'] for name in ('small', 'large', 'other', 'fixed')], [2, 4, 1, 1])
        self.assertEqual(raw['furnace']['small']['result_inventory_size'], 1)

    @unittest.skipUnless(Path('.cache/test-catalog.json').exists() and find_installation(), 'Requires Factorio and catalog')
    def test_export_loads_with_two_output_slots(self):
        root = find_installation()
        work = Path(tempfile.mkdtemp(dir=Path('.cache').resolve()))
        catalog = Catalog(json.loads(Path('.cache/test-catalog.json').read_text(encoding='utf-8')))
        project = Project()
        recipe = Recipe('two-output-smelting-test', {'category': 'smelting',
            'ingredients': [{'type': 'item', 'name': 'iron-ore', 'amount': 1}],
            'results': [{'type': 'item', 'name': 'iron-plate', 'amount': 1}, {'type': 'item', 'name': 'stone', 'amount': 1}]})
        project.save_recipe(recipe, recipe.name, .5, True, custom=True)
        mods = work / 'mods'
        mods.mkdir()
        archive = work / 'recipe-studio-project_1.0.0.zip'
        project.export(archive, catalog, root, mods)
        loaded, _, _ = load_game(root, [archive], work / 'engine')
        self.assertEqual(len(loaded.recipes[recipe.name]['results']), 2)
        for name in ('stone-furnace', 'steel-furnace', 'electric-furnace'):
            self.assertGreaterEqual(loaded.raw['furnace'][name]['result_inventory_size'], 2)
