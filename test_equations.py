from installation import find_installation
import copy
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from app import App
from equations import plan_equations, item_suggestions, equation_terms, equation_line_checks
from core import Catalog, load_game
from project import Project


@unittest.skipUnless(Path('.cache/test-catalog.json').exists(), 'Requires cached catalog')
class EquationsTests(unittest.TestCase):
    def fixture(self):
        raw = json.loads(Path('.cache/test-catalog.json').read_text(encoding='utf-8'))
        return SimpleNamespace(catalog=Catalog(raw), base_raw=raw, project=Project())

    def test_parser(self):
        app = self.fixture()
        plan = plan_equations(app, 'copper plate + iron plate = metal alloy')
        self.assertEqual(plan['items'], {'metal_alloy': 'metal alloy'})
        recipe = plan['recipes'][0]
        self.assertEqual(recipe['name'], 'metal_alloy_recipe')
        self.assertEqual([e['name'] for e in recipe['prototype']['ingredients']], ['copper-plate', 'iron-plate'])
        plan = plan_equations(app, '2 * iron plate + iron plate = 3 metal alloy\nmetal alloy + 0.5 water = wet alloy', category='chemistry')
        self.assertEqual(plan['recipes'][0]['prototype']['ingredients'][0]['amount'], 3)
        self.assertEqual(plan['recipes'][0]['prototype']['results'][0]['amount'], 3)
        self.assertEqual(plan['recipes'][1]['prototype']['ingredients'][1], {'type': 'fluid', 'name': 'water', 'amount': .5})
        for text in ('', 'iron plate', 'iron plate =', 'iron plate == metal', 'iron plate + = metal', '-2 iron plate = metal', '0 iron plate = metal', '0.5 iron plate = metal', 'iron  plate = metal', 'iron plate = metal\niron plate = metal'):
            with self.subTest(text=text), self.assertRaises(ValueError):
                plan_equations(app, text)
        app.catalog.recipes['metal_alloy_recipe'] = {}
        plan = plan_equations(app, 'iron plate = metal alloy\ncopper plate = metal alloy')
        self.assertEqual([r['name'] for r in plan['recipes']], ['metal_alloy_recipe_2', 'metal_alloy_recipe_3'])

    def test_per_recipe_options_and_suggestions(self):
        app = self.fixture()
        plan = plan_equations(app, 'iron ore = iron plate; time=3.5; category=smelting\niron plate = new gear', seconds='2')
        self.assertEqual([(r['seconds'], r['category']) for r in plan['recipes']], [(3.5, 'smelting'), (2, 'crafting')])
        self.assertEqual(plan_equations(app, 'iron ore = iron plate; seconds=4')['recipes'][0]['seconds'], 4)
        # Alternate time/category settings are distinct recipes, not duplicate equations.
        self.assertEqual(len(plan_equations(app, 'iron ore = iron plate; time=1\niron ore = iron plate; time=2')['recipes']), 2)
        for suffix in ('; time=0', '; time=nan', '; category=not-a-category', '; count=3', '; time=2; seconds=3', ';'):
            with self.subTest(suffix=suffix), self.assertRaisesRegex(ValueError, 'Line 1:'):
                plan_equations(app, 'iron ore = iron plate' + suffix)
        text = '2 * iron pate + fluid:watr = new invention; time=3; category=smelting'
        suggestions = item_suggestions(app.catalog, text)
        self.assertEqual(next(r for r in suggestions if r['term'] == 'iron pate')['name'], 'iron-plate')
        self.assertIn(('watr', 'fluid', 'water'), [(r['term'], r['kind'], r['name']) for r in suggestions])
        self.assertFalse(item_suggestions(app.catalog, 'iron plate + fluid:water = copper plate'))
        spans = list(equation_terms(text))
        self.assertEqual([text[start:end] for start, end, _, _ in spans], ['iron pate', 'watr', 'new invention'])

    def test_line_checks(self):
        checks = equation_line_checks(self.fixture(),
            'iron ore = iron plate; time=3; category=smelting\n\niron plate = new item; category=typo\n'
            'iron plate + = invalid\niron plate = other item; time=0\n'
            'iron ore = iron plate; time=3; category=smelting\ncopper plate = another item', '1', 'crafting')
        self.assertEqual(set(checks), {1, 3, 4, 5, 6, 7})
        self.assertIsNone(checks[1]); self.assertIsNone(checks[7])
        for number in (3, 4, 5, 6):
            self.assertIsNotNone(checks[number])

    def test_root_product_names_and_chains(self):
        app = self.fixture()
        text = ('2 item:copper-ore + iron plate = 3 crushed SCOPE + SCOPE dust =4 =smelting\n'
                'iron ore = crushed SCOPE\ncrushed copper ore = washed ROOT')
        plan = plan_equations(app, text)
        self.assertEqual(plan['items'], {'crushed_copper_ore': 'crushed copper ore', 'copper_ore_dust': 'copper ore dust',
                                        'crushed_iron_ore': 'crushed iron ore', 'washed_copper_ore': 'washed copper ore'})
        first = plan['recipes'][0]
        self.assertEqual(first['prototype']['ingredients'][0]['amount'], 2)
        self.assertEqual(first['prototype']['results'][0], {'type': 'item', 'name': 'crushed_copper_ore', 'amount': 3})
        self.assertEqual((first['seconds'], first['category']), (4, 'smelting'))
        self.assertTrue(all(error is None for error in equation_line_checks(app, text, '1', 'crafting').values()))
        from equations import equation_chains
        chains = equation_chains(plan)
        self.assertTrue(any(entry['name'] == 'crushed_copper_ore_recipe' for _, branches in chains for entry in branches.values()))
        # Reuse existing results and show their icons without rewriting the text.
        self.assertEqual(plan_equations(app, 'copper ore = ROOT')['items'], {})
        self.assertEqual(plan_equations(app, 'iron ore = ROOT')['recipes'][0]['prototype']['results'][0]['name'], 'iron-ore')
        spans = list(equation_terms('2 item:copper ore = crushed ROOT; time=3', expand_roots=True))
        self.assertEqual([row[2] for row in spans], ['copper ore', 'crushed copper ore'])
        self.assertFalse(item_suggestions(app.catalog, 'iron ore = ROOT'))
        for invalid in ('ROOT = crushed ROOT', 'iron ROOT = dust', '= crushed ROOT'):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                plan_equations(app, invalid)

    def test_equals_format_chain_scope_root_and_readings(self):
        app = self.fixture()
        app.catalog.raw.setdefault('recipe-category', {})['crushing_crusher'] = {}
        text = ('copper ore = crushed SCOPE =3 = crushing_crusher\n'
                'crushed copper ore = concentrated ROOT = 4 = crafting\n'
                'concentrated copper ore = washed SCOPE + ROOT dust =5')
        plan = plan_equations(app, text)
        self.assertEqual(plan['items'], {'crushed_copper_ore': 'crushed copper ore',
            'concentrated_copper_ore': 'concentrated copper ore', 'washed_concentrated_copper_ore': 'washed concentrated copper ore',
            'copper_ore_dust': 'copper ore dust'})
        self.assertEqual([(r['seconds'], r['category']) for r in plan['recipes']], [(3, 'crushing_crusher'), (4, 'crafting'), (5, 'crafting')])
        readings = {}
        self.assertTrue(all(e is None for e in equation_line_checks(app, text, '1', 'crafting', readings).values()))
        self.assertEqual(readings[2], 'crushed copper ore = concentrated copper ore = 4 = crafting')
        reverse = plan_equations(app, '\n'.join(reversed(text.splitlines())))
        self.assertEqual(set(reverse['items']), set(plan['items']))
        self.assertEqual(plan_equations(app, 'copper ore = crushed SCOPE = = crushing_crusher', seconds='2')['recipes'][0]['seconds'], 2)
        for invalid in ('copper ore = dust = 0', 'copper ore = dust = 1 = unknown', 'copper ore = dust = 1 = crafting = extra',
                        'iron ore = SCOPE + ROOT = nan', 'SCOPE = dust'):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                plan_equations(app, invalid)
        for invalid in ('a = b\nb = a\nb = processed ROOT', 'copper ore = shared\niron ore = shared\nshared = processed ROOT'):
            with self.subTest(invalid=invalid), self.assertRaisesRegex(ValueError, 'ROOT'):
                plan_equations(app, invalid)
        terms = list(equation_terms(text, expand_roots=True))
        self.assertIn('concentrated copper ore', [r[2] for r in terms])
        self.assertFalse(any(r[2] in ('3', '4', '5', 'crafting', 'crushing_crusher') for r in terms))

    def test_exit_saves_document_without_import_and_restores_it(self):
        work = Path(tempfile.mkdtemp(dir=Path('.cache').resolve()))
        with patch('tkinter.messagebox.askyesno', return_value=False), patch('tkinter.messagebox.showerror') as errors:
            app = App(); app.withdraw(); self.addCleanup(app.destroy)
            app.autosave_path = work / 'project.json'
            app.catalog = self.fixture().catalog
            app.root_path = find_installation() or Path('unconfigured-factorio-installation')
            app.mods_path = work / 'mods'; app.mods_path.mkdir()
            app.setup_frame.destroy(); app.workspace()
            tab = app.equations_tab()
            text = 'copper ore = crushed SCOPE =3 =crafting\nunfinished equation'
            tab.text.insert('1.0', text); tab.modified(None)
            self.assertTrue(tab.dirty)
            with patch('tkinter.messagebox.askyesnocancel', return_value=True), patch.object(app, 'destroy') as destroy:
                app.close()
                destroy.assert_called_once()
            saved = Project.open(app.autosave_path)
            self.assertEqual(saved.data['recipes'], {})
            self.assertEqual(saved.data['items'], {})
            self.assertEqual(saved.data['equations_draft']['input'][0], text)
            app.restore_project(app.autosave_path)
            restored = app.equations_tab()
            self.assertEqual(restored.current_input()[0], text)
            self.assertFalse(restored.dirty)
            restored.text.delete('2.0', 'end'); restored.modified(None)
            self.assertTrue(restored.save_changes())
            self.assertFalse(app.project.data['recipes'])
            self.assertTrue(restored.apply_changes())
            self.assertIn('crushed_copper_ore_recipe', app.project.data['recipes'])
            app.restore_project(app.autosave_path)
            reopened = app.equations_tab()
            before = copy.deepcopy(app.project.data)
            self.assertTrue(reopened.apply_changes())
            self.assertEqual(app.project.data, before)
            self.assertFalse(errors.called, errors.call_args_list)

    def test_use_suggestion_preserves_quantities_options_and_undo(self):
        work = Path(tempfile.mkdtemp(dir=Path('.cache').resolve()))
        with patch('tkinter.messagebox.askyesno', return_value=False), patch('tkinter.messagebox.showerror') as errors:
            app = App(); app.withdraw(); self.addCleanup(app.destroy)
            app.autosave_path = work / 'project.json'
            app.catalog = self.fixture().catalog
            app.root_path = find_installation() or Path('unconfigured-factorio-installation')
            app.mods_path = work / 'mods'; app.mods_path.mkdir()
            app.setup_frame.destroy(); app.workspace()
            tab = app.equations_tab()
            original = '2 iron pate + item:iron pate = new metal; time=3; category=smelting'
            tab.text.insert('1.0', original); tab.refresh()
            key = next(k for k, row in tab.suggestion_rows.items() if row['term'] == 'iron pate' and row['name'] == 'iron-plate' and row['force'] is None)
            tab.suggestions.selection_set(key); tab.use_suggestion()
            self.assertIn('2 item:iron-plate + item:iron pate', tab.text.get('1.0', 'end-1c'))
            tab.undo_text(None)
            self.assertEqual(tab.text.get('1.0', 'end-1c'), original)
            tab.refresh()
            # Apply both separate typed forms; replacements never touch metadata.
            for force in (None, 'item'):
                key = next(k for k, row in tab.suggestion_rows.items() if row['term'] == 'iron pate' and row['name'] == 'iron-plate' and row['force'] == force)
                tab.suggestions.selection_set(key); tab.use_suggestion()
            # Icons live above recognized names without adding hidden text/image
            # characters, so quantities, parser offsets and undo remain intact.
            app.deiconify()
            app.geometry('1200x900')
            app.update()
            tab.refresh_input_icons()
            self.assertEqual([label.item_key for label in tab.input_icons], [('item', 'iron-plate'), ('item', 'iron-plate')])
            self.assertFalse(tab.text.image_names())
            self.assertEqual([label.line_number for label in tab.line_markers], [1])
            self.assertEqual(tab.line_markers[0].reading, '3 iron plate = new metal = 3 = smelting')
            end_box = tab.text.bbox('1.end')
            self.assertGreater(int(tab.line_markers[0].place_info()['x']), end_box[0])
            self.assertEqual(tab.text.get('1.0', 'end-1c'), '2 item:iron-plate + item:iron-plate = new metal; time=3; category=smelting')
            tab.text.edit_undo()
            self.assertIn('+ item:iron pate', tab.text.get('1.0', 'end-1c'))
            tab.text.edit_redo()
            app.withdraw()
            self.assertTrue(tab.apply_changes())
            saved = app.project.data['recipes']['new_metal_recipe']
            self.assertEqual(saved['seconds'], 3)
            self.assertEqual(saved['category'], 'smelting')
            self.assertEqual(saved['ingredients'], [{'type': 'item', 'name': 'iron-plate', 'amount': 3}])
            self.assertNotIn('iron_pate', app.project.data['items'])
            tab.suggest_enabled.set(False); tab.refresh_suggestions()
            self.assertFalse(tab.suggestions.get_children())
            self.assertFalse(errors.called, errors.call_args_list)

    def test_chain_roots_branches_alternatives_and_cycles(self):
        from equations import equation_chains
        plan = plan_equations(self.fixture(), 'iron plate = part a\ncopper plate = part b\npart a + part b = component\ncomponent = final product\nstone = separate product')
        graphs = equation_chains(plan)
        self.assertEqual([name for name, _ in graphs], ['final_product_recipe', 'separate_product_recipe'])
        self.assertEqual(set(e['name'] for e in graphs[0][1].values()), {'component_recipe', 'part_a_recipe', 'part_b_recipe'})
        selected = equation_chains(plan, ['component_recipe'])
        self.assertEqual(len(selected), 1)
        self.assertEqual(len(selected[0][1]), 2)
        cyclic = plan_equations(self.fixture(), 'cycle a = cycle b\ncycle b = cycle a')
        graphs = equation_chains(cyclic)
        self.assertEqual(len(graphs), 1)
        self.assertEqual(len(graphs[0][1]), 1)
        alternative = plan_equations(self.fixture(), 'iron plate = shared part\ncopper plate = shared part\nshared part = finished test')
        graphs = equation_chains(alternative)
        covered = {name for name, _ in graphs} | {e['name'] for _, graph in graphs for e in graph.values()}
        self.assertEqual(covered, {r['name'] for r in alternative['recipes']})

    def test_show_diagram_saves_batch_and_expands_whole_chain(self):
        work = Path(tempfile.mkdtemp(dir=Path('.cache').resolve()))
        with patch('tkinter.messagebox.askyesno', return_value=False), patch('tkinter.messagebox.showerror') as errors:
            app = App()
            app.withdraw()
            self.addCleanup(app.destroy)
            app.autosave_path = work / 'project.json'
            app.catalog = self.fixture().catalog
            app.root_path = find_installation() or Path('unconfigured-factorio-installation')
            app.mods_path = work / 'mods'
            app.mods_path.mkdir()
            app.setup_frame.destroy()
            app.workspace()
            tab = app.equations_tab()
            tab.text.insert('1.0', 'iron plate = diagram part; time=4; category=smelting\ndiagram part = diagram component\ndiagram component = diagram final; time=7\nstone = separate diagram')
            tab.refresh()
            charts = tab.show_diagram()
            self.assertEqual(len(charts), 2)
            chart = charts[0]
            self.assertEqual(chart.loaded_name, 'diagram_final_recipe')
            self.assertEqual(chart.expanded_recipes[(0,)]['name'], 'diagram_component_recipe')
            self.assertEqual(chart.expanded_recipes[(0, 0)]['name'], 'diagram_part_recipe')
            self.assertEqual(len(chart.canvas.find_withtag('recipe-link')), 2)
            self.assertEqual(len(app.project.data['recipes']), 4)
            self.assertEqual(app.project.data['recipes']['diagram_part_recipe']['category'], 'smelting')
            self.assertEqual(app.project.data['recipes']['diagram_part_recipe']['seconds'], 4)
            self.assertEqual(float(chart.seconds.get()), 7)
            tab.show_diagram()
            self.assertEqual(len(app.project.data['recipes']), 4)
            self.assertFalse(errors.called, errors.call_args_list)

    def test_preview_apply_roundtrip_and_undo(self):
        work = Path(tempfile.mkdtemp(dir=Path('.cache').resolve()))
        with patch('tkinter.messagebox.askyesno', return_value=False), patch('tkinter.messagebox.showerror') as errors:
            app = App()
            app.withdraw()
            self.addCleanup(app.destroy)
            app.autosave_path = work / 'project.json'
            app.catalog = self.fixture().catalog
            app.root_path = (find_installation() or Path('unconfigured-factorio-installation'))
            app.mods_path = work / 'mods'
            app.mods_path.mkdir()
            app.setup_frame.destroy()
            app.workspace()
            tab = app.equations_tab()
            self.assertIs(app.equations_tab(), tab)
            tab.text.insert('1.0', 'copper plate + iron plate = metal alloy\n2 metal alloy = alloy block + alloy scrap')
            app.update()
            tab.refresh()
            self.assertTrue(tab.dirty)
            self.assertEqual(tab.preview.get_children(), ('metal_alloy_recipe', 'alloy_block_recipe'))
            self.assertFalse(app.project.data['items'])
            self.assertTrue(tab.apply_changes())
            self.assertEqual(set(app.project.data['items']), {'metal_alloy', 'alloy_block', 'alloy_scrap'})
            self.assertEqual(app.project.data['items']['metal_alloy']['title'], 'metal alloy')
            self.assertIn(('item', 'metal_alloy'), app.catalog.items)
            self.assertEqual(app.catalog.recipes['alloy_block_recipe']['main_product'], 'alloy_block')
            self.assertEqual(len(app.project.data['recipes']), 2)
            self.assertFalse(tab.dirty)
            self.assertEqual(str(tab.apply_button.cget('state')), 'disabled')
            self.assertTrue(tab.apply_changes())
            self.assertEqual(len(app.project.data['recipes']), 2)
            tab.preview.selection_set('metal_alloy_recipe')
            chart = tab.open_selected()
            self.assertEqual(chart.loaded_name, 'metal_alloy_recipe')
            self.assertEqual(chart.recipe.results[0]['name'], 'metal_alloy')
            # Closing this clean chart does not change the applied equation batch.
            chart.destroy()
            reopened = Project.open(app.autosave_path)
            self.assertEqual(reopened.data['recipes']['alloy_block_recipe']['ingredients'][0]['name'], 'metal_alloy')
            if os.environ.get('FACTORIO_TEST_INSTALL'):
                archive = work / 'equations-test_1.0.0.zip'
                app.project.export(archive, Catalog(app.base_raw), app.root_path, app.mods_path, mod_name='equations-test')
                loaded, _, _ = load_game(os.environ['FACTORIO_TEST_INSTALL'], [archive], work / 'engine')
                self.assertEqual(loaded.items[('item', 'metal_alloy')]['localised_name'], 'metal alloy')
                self.assertEqual(loaded.recipes['alloy_block_recipe']['main_product'], 'alloy_block')
            self.assertTrue(app.undo())
            self.assertNotIn(('item', 'metal_alloy'), app.catalog.items)
            self.assertNotIn('metal_alloy_recipe', app.catalog.recipes)
            self.assertTrue(tab.dirty)
            self.assertEqual(tab.preview.get_children(), ('metal_alloy_recipe', 'alloy_block_recipe'))
            self.assertEqual(Project.open(app.autosave_path).data['items'], {})
            # Errors on a later line leave the entire batch unapplied.
            before = copy.deepcopy(app.project.data)
            tab.text.insert('end', '\ninvalid equation')
            self.assertFalse(tab.apply_changes())
            self.assertEqual(app.project.data, before)
            self.assertIn('Line 3', errors.call_args.args[1])
