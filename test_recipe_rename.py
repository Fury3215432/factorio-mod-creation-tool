import copy,json,tempfile
from pathlib import Path
import tkinter as tk
from unittest import TestCase,skipUnless
from unittest.mock import patch
from app import App
from core import Catalog, load_game
from project import Project
from machine_model import source_config
from installation import find_installation
from creations_ui import rename_recipe

@skipUnless(Path('.cache/test-catalog.json').exists(), 'Requires catalog')
class RenameRecipes(TestCase):
    def test_reuse_deleted_id_replace_existing_and_rename_back(self):
        from delete_items import delete_recipe
        work=Path(tempfile.mkdtemp(dir=Path('.cache').resolve()))
        with patch('tkinter.messagebox.askyesno',return_value=False) as confirm, patch('tkinter.messagebox.showerror') as errors:
            app=App(); app.withdraw(); self.addCleanup(app.destroy)
            app.autosave_path=work/'project.json'
            app.catalog=Catalog(json.loads(Path('.cache/test-catalog.json').read_text(encoding='utf-8')))
            app.root_path=find_installation() or Path('unconfigured-factorio-installation')
            app.mods_path=work/'mods'; app.mods_path.mkdir()
            app.setup_frame.destroy(); app.workspace()
            chart=app.nametowidget(app.tabs.select())
            chart.add_entry('ingredients',('item','copper-plate'))
            chart.add_entry('results',('item','iron-gear-wheel'))
            chart.name.set('reused-id-test'); self.assertTrue(chart.save_changes())
            self.assertTrue(delete_recipe(chart,'iron-gear-wheel'))
            before=copy.deepcopy(app.project.data)
            self.assertTrue(rename_recipe(chart,'reused-id-test','iron-gear-wheel'))
            self.assertNotIn('iron-gear-wheel',app.project.data['deleted']['recipe'])
            self.assertFalse(app.project.data['recipes']['iron-gear-wheel']['custom'])
            self.assertFalse(chart.is_custom)
            chart.recipe.ingredients[0]['amount']=4; chart.mark()
            self.assertTrue(chart.save_changes())
            self.assertTrue(app.undo())
            self.assertTrue(app.undo())
            self.assertTrue(app.undo()); self.assertEqual(app.project.data,before)
            # Renaming a loaded recipe away and back reuses the tombstone and
            # removes the stale rename mapping for the restored ID.
            source=app.new_tab(); source.load('copper-cable')
            self.assertTrue(rename_recipe(source,'copper-cable','temporary-cable'))
            self.assertTrue(rename_recipe(source,'temporary-cable','copper-cable'))
            self.assertIn('copper-cable',app.catalog.recipes)
            self.assertNotIn('copper-cable',app.project.data['recipe_renames'])
            previous=copy.deepcopy(app.project.data)
            self.assertFalse(rename_recipe(source,'copper-cable','iron-plate'))
            self.assertEqual(app.project.data,previous)
            confirm.return_value=True
            self.assertTrue(rename_recipe(source,'copper-cable','iron-plate'))
            self.assertNotIn('copper-cable',app.catalog.recipes)
            self.assertEqual(app.project.data['recipes']['iron-plate']['ingredients'][0]['name'],'copper-plate')
            self.assertTrue(app.undo()); self.assertEqual(app.project.data,previous)
            self.assertFalse(errors.called,errors.call_args_list)

    def test_rename_updates_chains_unlocks_machines_and_undo(self):
        work=Path(tempfile.mkdtemp(dir=Path('.cache').resolve()))
        with patch('tkinter.messagebox.askyesno',return_value=False), patch('tkinter.messagebox.showerror') as errors:
            app=App(); app.withdraw(); self.addCleanup(app.destroy)
            app.autosave_path=work/'project.json'
            app.catalog=Catalog(json.loads(Path('.cache/test-catalog.json').read_text(encoding='utf-8')))
            app.root_path=find_installation() or Path('unconfigured-factorio-installation')
            app.mods_path=work/'mods'; app.mods_path.mkdir()
            app.setup_frame.destroy(); app.workspace()
            chart=app.nametowidget(app.tabs.select()); chart.load('electric-engine-unit')
            index=next(i for i,e in enumerate(chart.recipe.ingredients) if e['name']=='engine-unit')
            chart.show_recipe((index,),('item','engine-unit'),'engine-unit')
            direct=app.new_tab(); direct.load('engine-unit')
            direct.recipe.ingredients[0]['amount']=8; direct.mark()
            machine=source_config('assembling-machine','assembling-machine-3',app.catalog)
            machine['recipes']=['engine-unit']; app.project.data['machines']['rename-test-machine']=machine
            app.refresh_catalog()
            original_unlocks=app.project.recipe_unlocks('engine-unit',app.base_raw)
            tabs=len(app.tabs.tabs())
            self.assertTrue(rename_recipe(chart,'engine-unit','renamed-engine'), errors.call_args_list)
            self.assertEqual(len(app.tabs.tabs()),tabs)
            self.assertNotIn('engine-unit',app.catalog.recipes)
            self.assertIn('renamed-engine',app.catalog.recipes)
            self.assertEqual(chart.expanded_recipes[(index,)]['name'],'renamed-engine')
            self.assertEqual(direct.loaded_name,'renamed-engine')
            self.assertEqual(direct.recipe.ingredients[0]['amount'],8)
            self.assertTrue(direct.dirty)
            self.assertEqual(app.project.recipe_unlocks('renamed-engine',app.base_raw),original_unlocks)
            self.assertEqual(app.project.data['machines']['rename-test-machine']['recipes'],['renamed-engine'])
            before=copy.deepcopy(app.project.data)
            self.assertFalse(rename_recipe(chart,'renamed-engine','iron-plate'))
            self.assertEqual(app.project.data,before); errors.reset_mock()
            self.assertTrue(app.undo())
            self.assertIn('engine-unit',app.catalog.recipes)
            self.assertEqual(direct.loaded_name,'engine-unit')
            self.assertEqual(chart.expanded_recipes[(index,)]['name'],'engine-unit')
            self.assertTrue(rename_recipe(chart,'engine-unit','renamed-engine'), errors.call_args_list)
            # Repeated renames flatten old references and survive export.
            self.assertTrue(rename_recipe(chart,'renamed-engine','renamed-engine-final'))
            if find_installation():
                archive=work/'recipe-studio-project_1.0.0.zip'
                app.project.export(archive,Catalog(app.base_raw),app.root_path,app.mods_path)
                loaded,_,_=load_game(app.root_path,[archive],work/'engine')
                self.assertNotIn('engine-unit',loaded.recipes)
                self.assertNotIn('renamed-engine',loaded.recipes)
                self.assertIn('renamed-engine-final',loaded.recipes)
                for technology in original_unlocks:
                    self.assertTrue(any(e.get('recipe')=='renamed-engine-final' for e in loaded.raw['technology'][technology]['effects']))
            self.assertFalse(errors.called,errors.call_args_list)
