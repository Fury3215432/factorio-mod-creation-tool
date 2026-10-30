import copy
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

from core import Catalog, Recipe, load_game, read_mod
from machine_model import recipe_category, sprite_asset, validate_machine, importable_recipes, source_config, prototypes
from project import Project, png_asset
from test_project import make_icon


def machine(recipes=None):
    return {'title': 'Test Workshop', 'description': 'A custom crafting building.', 'template': 'assembling-machine-3',
            'health': 600, 'stack_size': 50, 'speed': 2, 'power': '150kW', 'energy_type': 'electric', 'module_slots': 2,
            'recipes': recipes or ['iron-gear-wheel'], 'icon': None, 'sprite': None, 'sprite_scale': 1}


class MachineTests(unittest.TestCase):
    def directory(self):
        cache = Path('.cache').resolve()
        cache.mkdir(exist_ok=True)
        return Path(tempfile.mkdtemp(dir=cache))

    @unittest.skipUnless(Path('.cache/test-catalog.json').exists(), 'Requires cached game catalog')
    def test_machine_validation_and_persistence(self):
        catalog = Catalog(json.loads(Path('.cache/test-catalog.json').read_text(encoding='utf-8')))
        project = Project()
        value = machine()
        validate_machine('my-workshop', value, catalog, project)
        value['recipes'] = ['missing-recipe']
        with self.assertRaisesRegex(ValueError, 'Unknown allowed recipe'):
            validate_machine('my-workshop', value, catalog, project)
        value = machine(['advanced-oil-processing'])
        with self.assertRaisesRegex(ValueError, 'fluid ports'):
            validate_machine('my-workshop', value, catalog, project)
        value = machine()
        project.data['machines']['my-workshop'] = value
        path = self.directory() / 'project.json'
        project.save(path)
        restored = Project.open(path)
        merged = restored.merged_raw(catalog.raw)
        self.assertNotIn('my-workshop', merged['recipe'])
        self.assertEqual(restored.missing_machine_recipes(catalog), ['my-workshop'])
        self.assertEqual(merged['item']['my-workshop']['place_result'], 'my-workshop')
        self.assertEqual(merged['assembling-machine']['my-workshop']['minable']['result'], 'my-workshop')
        self.assertEqual(merged['recipe']['iron-gear-wheel']['category'], recipe_category('iron-gear-wheel'))
        self.assertIn(recipe_category('iron-gear-wheel'), merged['assembling-machine']['assembling-machine-3']['crafting_categories'])
        self.assertNotIn(recipe_category('iron-stick'), merged['assembling-machine']['my-workshop']['crafting_categories'])
        old = Project({'format': 1, 'items': {}, 'recipes': {}, 'technologies': {}})
        self.assertEqual(old.data['machines'], {})
        old_machine = machine()
        old_machine.update(ingredients=[{'type': 'item', 'name': 'iron-plate', 'amount': 5}], build_time=3, enabled=True)
        migrated = Project({'format': 1, 'items': {}, 'recipes': {}, 'technologies': {}, 'machines': {'old-workshop': old_machine}})
        self.assertIn('old-workshop', migrated.data['recipes'])
        self.assertNotIn('ingredients', migrated.data['machines']['old-workshop'])
        self.assertEqual(migrated.missing_machine_recipes(catalog), [])
        imported = importable_recipes(catalog, [('furnace', 'stone-furnace'), ('assembling-machine', 'assembling-machine-1')])
        self.assertIn('iron-plate', imported)
        self.assertIn('iron-gear-wheel', imported)
        self.assertNotIn('sulfur', imported)
        self.assertEqual(importable_recipes(Catalog(merged), [('assembling-machine', 'my-workshop')]), ['iron-gear-wheel'])

    @unittest.skipUnless(os.environ.get('FACTORIO_TEST_INSTALL'), 'Set FACTORIO_TEST_INSTALL for engine tests')
    def test_machine_engine_and_runtime(self):
        root = Path(os.environ['FACTORIO_TEST_INSTALL'])
        first = self.directory()
        catalog, _, mods = load_game(root, [], first)
        project = Project()
        project.data['machines']['test-workshop'] = machine()
        second = machine(['iron-gear-wheel', 'iron-stick'])
        second.update(energy_type='burner', module_slots=0)
        icon_path = make_icon(first / 'machine.png')
        second['icon'], second['sprite'] = png_asset(icon_path), sprite_asset(icon_path)
        project.data['machines']['second-workshop'] = second
        chemistry = machine(['sulfur'])
        chemistry['template'] = 'chemical-plant'
        project.data['machines']['chemistry-workshop'] = chemistry
        project.data['machines']['recipe-less-workshop'] = machine()
        drill = source_config('mining-drill', 'electric-mining-drill', catalog)
        drill.update(width=5, height=5, speed=2, color='#88bbff', mining_radius=4.49)
        project.data['machines']['large-blue-drill'] = drill
        edit = source_config('assembling-machine', 'assembling-machine-1', catalog)
        edit.update(operation='edit', health=777, speed=3, width=5, height=5, color='#ffaa88', recipes=['iron-gear-wheel'])
        project.data['machines']['assembling-machine-1'] = edit
        unchanged_variant = source_config('assembling-machine', 'assembling-machine-1', catalog)
        unchanged_variant['recipes'] = ['iron-stick']
        project.data['machines']['original-size-variant'] = unchanged_variant
        furnace = source_config('furnace', 'steel-furnace', catalog)
        furnace.update(width=4, height=4, recipes=['iron-plate'])
        project.data['machines']['large-furnace'] = furnace
        # Explicit construction recipes live in the ordinary recipe workflow.
        for name in project.data['machines']:
            if name == 'recipe-less-workshop' or name == 'assembling-machine-1':
                continue
            recipe = Recipe(name, {'ingredients': [{'type': 'item', 'name': 'iron-plate', 'amount': 5}], 'results': [{'type': 'item', 'name': name, 'amount': 1}]})
            project.save_recipe(recipe, name, 2, True, custom=True)
        archive = first / 'recipe-studio-project_1.0.0.zip'
        project.export(archive, catalog, root, mods)
        second_workspace = self.directory()
        updated, _, _ = load_game(root, [archive], second_workspace)
        entity = updated.raw['assembling-machine']['test-workshop']
        self.assertEqual(entity['max_health'], 600)
        self.assertEqual(entity['crafting_speed'], 2)
        self.assertEqual(entity['crafting_categories'], [recipe_category('iron-gear-wheel')])
        self.assertEqual(updated.items[('item', 'test-workshop')]['place_result'], 'test-workshop')
        self.assertTrue(updated.recipes['test-workshop']['enabled'])
        self.assertNotIn('recipe-less-workshop', updated.recipes)
        self.assertIn(('item', 'recipe-less-workshop'), updated.items)
        self.assertEqual(project.missing_machine_recipes(catalog), ['recipe-less-workshop'])
        self.assertIn(recipe_category('iron-gear-wheel'), updated.raw['assembling-machine']['assembling-machine-3']['crafting_categories'])
        self.assertEqual(updated.recipes['iron-stick']['category'], recipe_category('iron-stick'))
        self.assertNotIn(recipe_category('iron-stick'), entity['crafting_categories'])
        self.assertEqual(updated.raw['assembling-machine']['second-workshop']['energy_source']['type'], 'burner')
        drill_entity = updated.raw['mining-drill']['large-blue-drill']
        self.assertEqual(drill_entity['mining_speed'], 2)
        self.assertEqual(drill_entity['selection_box'], [[-2.5, -2.5], [2.5, 2.5]])
        self.assertEqual(drill_entity['tile_width'], 5)
        self.assertEqual(updated.raw['assembling-machine']['assembling-machine-1']['max_health'], 777)
        self.assertEqual(updated.raw['assembling-machine']['assembling-machine-1']['crafting_speed'], 3)
        self.assertEqual(updated.raw['assembling-machine']['original-size-variant']['tile_width'], 3)
        self.assertEqual(updated.raw['assembling-machine']['original-size-variant']['crafting_speed'], catalog.raw['assembling-machine']['assembling-machine-1']['crafting_speed'])
        self.assertEqual(updated.raw['furnace']['large-furnace']['tile_width'], 4)
        self.assertIn('assembling-machine-1', updated.recipes)
        self.assertTrue(any(c['type'] == 'assembling-machine' and c['name'] == 'assembling-machine-1' and c['operation'] == 'modified' for c in project.changes(catalog)))
        # Exercise placement, recipe selection, actual crafting and mining in-game.
        _, files = read_mod(archive)
        mod = first / 'runtime-mod'
        mod.mkdir()
        for name, data in files.items():
            destination = mod / name
            destination.parent.mkdir(exist_ok=True, parents=True)
            destination.write_bytes(data)
        (mod / 'control.lua').write_text('''
script.on_init(function()
  local surface = game.surfaces[1]
  surface.request_to_generate_chunks({0,0}, 1)
  surface.force_generate_chunk_requests()
  local tiles = {}
  for x=-20,20 do for y=-20,20 do table.insert(tiles, {name="grass-1",position={x,y}}) end end
  surface.set_tiles(tiles)
  for _, e in pairs(surface.find_entities_filtered{area={{-20,-20},{20,20}}}) do if e.valid then e.destroy() end end
  local entity = assert(surface.create_entity{name="test-workshop",position={0,0},force="player"})
  assert(entity.name == "test-workshop")
  entity.set_recipe("iron-gear-wheel")
  assert(entity.get_recipe().name == "iron-gear-wheel")
  assert(entity.insert{name="iron-plate",count=20} > 0)
  storage.machine = entity
  assert(surface.create_entity{name="iron-ore",position={10.5,10.5},amount=1000})
  storage.drill = assert(surface.create_entity{name="large-blue-drill",position={10.5,10.5},force="player"})
  assert(storage.drill.bounding_box.right_bottom.x - storage.drill.bounding_box.left_top.x > 4)
end)
script.on_event(defines.events.on_tick, function(event)
  local entity = storage.machine
  if not entity or not entity.valid then return end
  entity.energy = 1000000
  storage.drill.energy = 1000000
  if event.tick == 120 then
    assert(entity.get_output_inventory().get_item_count("iron-gear-wheel") > 0, "Machine did not craft")
    local ore = 0
    for _, item in pairs(storage.drill.surface.find_entities_filtered{type="item-entity", area={{6,5},{15,15}}}) do
      if item.stack.valid_for_read and item.stack.name == "iron-ore" then ore = ore + item.stack.count end
    end
    assert(ore > 0, "Resized mining drill did not mine")
    local previous = entity.get_recipe().name
    local accepted = pcall(function() entity.set_recipe("iron-stick") end)
    assert(not accepted or not entity.get_recipe() or entity.get_recipe().name ~= "iron-stick", "Accepted an unselected recipe")
    local inventory = game.create_inventory(10)
    assert(entity.mine{inventory=inventory, force=true})
    assert(inventory.get_item_count("test-workshop") == 1, "Mining did not return placeable item")
    helpers.write_file("machine-runtime-test.txt", "placed, crafted selected recipe, rejected unselected recipe, mined item", false)
  end
end)
''', encoding='utf-8')
        runtime = self.directory()
        load_game(root, [mod], runtime)
        exe = root / 'bin/x64/factorio.exe'
        args = [str(exe), '--config', str(runtime / 'config.ini'), '--mod-directory', str(runtime / 'mods')]
        save = runtime / 'runtime.zip'
        for command in (['--create', str(save)], ['--benchmark', str(save), '--benchmark-ticks', '125', '--benchmark-runs', '1']):
            result = subprocess.run(args + command, capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=180, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            self.assertEqual(result.returncode, 0, (result.stdout + result.stderr)[-5000:])
        self.assertIn('rejected unselected recipe', (runtime / 'script-output/machine-runtime-test.txt').read_text())


if __name__ == '__main__':
    unittest.main()
