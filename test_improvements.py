import json
from pathlib import Path
import tempfile
import unittest

from controls import sequence
from core import Catalog, Recipe, read_mod
from project import Project


class ExportChanges(unittest.TestCase):
    def test_exact_mod_log_and_category(self):
        cache = Path('.cache').resolve()
        cache.mkdir(exist_ok=True)
        work = Path(tempfile.mkdtemp(dir=cache))
        original = work / 'original'
        original.mkdir()
        (original / 'info.json').write_text(json.dumps({'name': 'example', 'version': '1.0.0', 'factorio_version': '2.0', 'dependencies': ['base']}))
        original_script = 'local keep = true\nreturn keep\n'
        (original / 'data-final-fixes.lua').write_text(original_script)
        (original / 'unchanged.bin').write_bytes(b'unchanged asset')
        mods = work / 'mods'
        mods.mkdir()
        raw = {'item': {'plate': {'stack_size': 100}}, 'recipe-category': {'crafting': {}, 'smelting': {}},
               'recipe': {'plate': {'type': 'recipe', 'name': 'plate', 'ingredients': [{'type': 'item', 'name': 'plate', 'amount': 1}], 'results': [{'type': 'item', 'name': 'plate', 'amount': 2}]}}}
        catalog = Catalog(raw)
        project = Project()
        recipe = Recipe('plate', catalog.recipes['plate'])
        recipe.ingredients[0]['amount'] = 3
        project.save_recipe(recipe, 'plate', 4, True, category='smelting')
        archive = work / 'example_1.0.0.zip'
        project.export(archive, catalog, work, mods, target=original)
        _, files = read_mod(archive)
        report = json.loads(files['recipe-studio-changes.json'])
        changes = {c['path']: c for c in report['prototype_changes'][0]['changes']}
        self.assertEqual(changes['/category']['before'], 'crafting')
        self.assertEqual(changes['/category']['after'], 'smelting')
        self.assertEqual(changes['/ingredients']['before'][0]['amount'], 1)
        self.assertEqual(changes['/ingredients']['after'][0]['amount'], 3)
        self.assertEqual(changes['/energy_required']['after'], 4)
        file_changes = {c['path']: c for c in report['file_changes']}
        self.assertIn('-local keep = true', file_changes['data-final-fixes.lua']['diff'])
        self.assertNotIn('unchanged.bin', file_changes)
        self.assertEqual(files['unchanged.bin'], b'unchanged asset')
        self.assertEqual(json.loads(archive.with_name('example_1.0.0.changes.json').read_text()), report)
        lua = '\n'.join(v.decode('utf-8') for k, v in files.items() if k.endswith('.lua'))
        self.assertIn('recipe.category = "smelting"', lua)
        self.assertEqual(project.merged_raw(raw)['recipe']['plate']['category'], 'smelting')

    def test_shortcut_sequences(self):
        self.assertEqual(sequence('Ctrl+Shift+S'), '<Control-Shift-s>')
        self.assertEqual(sequence('F2'), '<F2>')
        with self.assertRaises(ValueError):
            sequence('Wrong+S')


if __name__ == '__main__':
    unittest.main()
