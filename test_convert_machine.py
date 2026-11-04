import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from app import App
from core import Catalog, Recipe, load_game
from creations_ui import convert_to_machine
from bulk_items import create_items
from installation import find_installation


@unittest.skipUnless(Path('.cache/test-catalog.json').exists(), 'Requires cached catalog')
class ConvertMachine(unittest.TestCase):
    def test_draft_suggested_actions_complete_export_and_undo(self):
        work=Path(tempfile.mkdtemp(dir=Path('.cache').resolve()))
        with patch('tkinter.messagebox.askyesno',return_value=False), patch('tkinter.messagebox.showerror') as errors:
            app=App(); app.withdraw(); self.addCleanup(app.destroy)
            app.autosave_path=work/'project.json'
            app.catalog=Catalog(json.loads(Path('.cache/test-catalog.json').read_text(encoding='utf-8')))
            app.root_path=find_installation() or Path('unconfigured-factorio-installation')
            app.mods_path=work/'mods'; app.mods_path.mkdir()
            app.setup_frame.destroy(); app.workspace()
            chart=app.nametowidget(app.tabs.select())
            create_items(chart,'conversion test')
            name='conversion_test'; key=('item',name)
            recipe=Recipe(name+'_recipe',{'ingredients':[{'type':'item','name':'iron-plate','amount':1}], 'results':[{'type':'item','name':name,'amount':1}]})
            app.project.save_recipe(recipe,recipe.name,1,False,custom=True)
            app.persist(); app.refresh_catalog()
            self.assertTrue(convert_to_machine(chart,key))
            machine=app.nametowidget(app.tabs.select())
            self.assertIn(name,app.project.data['machine_drafts'])
            self.assertNotIn('place_result',app.catalog.items[key])
            machine.vars['speed'].set('2')
            self.assertTrue(machine.save_changes())
            self.assertEqual(app.project.data['machine_drafts'][name]['speed'],2)
            app.pending_tab(); pending=app.nametowidget(app.tabs.select())
            self.assertEqual(pending.groups.tab(pending.machines_page,'text'),'Machines (1)')
            self.assertIn(name,json.loads(app.autosave_path.read_text(encoding='utf-8'))['machine_drafts'])
            machine.vars['sprite_path'].set(str(Path('assets/default-item-icon.png').resolve()))
            self.assertTrue(machine.save_changes(),errors.call_args_list)
            self.assertNotIn(name,app.project.data['machine_drafts'])
            self.assertNotIn(name,app.project.data['items'])
            self.assertEqual(app.catalog.items[key]['place_result'],name)
            self.assertEqual(app.project.data['recipes'][recipe.name]['results'][0]['name'],name)
            self.assertEqual(app.catalog.raw['assembling-machine'][name]['crafting_speed'],2)
            if find_installation():
                archive=work/'recipe-studio-project_1.0.0.zip'
                app.project.export(archive,Catalog(app.base_raw),app.root_path,app.mods_path)
                loaded,_,_=load_game(app.root_path,[archive],work/'engine')
                self.assertEqual(loaded.items[key]['place_result'],name)
                self.assertEqual(loaded.raw['assembling-machine'][name]['crafting_speed'],2)
            self.assertTrue(app.undo())
            self.assertIn(name,app.project.data['machine_drafts'])
            self.assertNotIn('place_result',app.catalog.items[key])
            self.assertFalse(errors.called,errors.call_args_list)

