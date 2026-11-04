import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from core import Catalog, load_game
from installation import find_installation
from machine_model import source_config, validate_machine, prototypes
from project import Project


@unittest.skipUnless(Path('.cache/test-catalog.json').exists(), 'Requires cached catalog')
class MachineEnergy(unittest.TestCase):
    def catalog(self):
        return Catalog(json.loads(Path('.cache/test-catalog.json').read_text(encoding='utf-8')))

    def test_conversion_validation_and_engine(self):
        catalog=self.catalog();project=Project()
        for kind,name,target in [('assembling-machine','assembling-machine-1','burner'),('lab','lab','burner'),('radar','radar','burner'),('inserter','inserter','burner'),('pump','pump','burner'),('boiler','boiler','electric')]:
            machine=source_config(kind,name,catalog)
            machine.update(operation='edit',energy_type=target,fuel_categories=['chemical'],fuel_inventory_size=2,burnt_inventory_size=0)
            validate_machine(name,machine,catalog,project)
            entity,_=prototypes(name,machine,catalog.raw)
            self.assertEqual(entity['energy_source']['type'],target)
            if target=='burner':
                self.assertEqual(entity['energy_source']['fuel_inventory_size'],2)
                self.assertNotIn('usage_priority',entity['energy_source'])
            else:self.assertNotIn('fuel_inventory_size',entity['energy_source'])
            self.assertEqual(entity.get('energy_usage'),catalog.raw[kind][name].get('energy_usage'))
            invalid=copy.deepcopy(machine);invalid.update(energy_type='burner',fuel_categories=['nonexistent-fuel'])
            with self.assertRaisesRegex(ValueError,'fuel categories'):validate_machine(name,invalid,catalog,project)
            project.data['machines'][name]=machine
        root=find_installation()
        if root:
            work=Path(tempfile.mkdtemp(dir=Path('.cache').resolve()));mods=work/'mods';mods.mkdir()
            archive=work/'recipe-studio-project_1.0.0.zip'
            project.export(archive,catalog,root,mods)
            loaded,_,_=load_game(root,[archive],work/'engine')
            self.assertEqual(loaded.raw['lab']['lab']['energy_source']['type'],'burner')
            self.assertEqual(loaded.raw['boiler']['boiler']['energy_source']['type'],'electric')

    def test_generic_editor_save_reload_and_undo(self):
        from app import App
        work=Path(tempfile.mkdtemp(dir=Path('.cache').resolve()))
        with patch('tkinter.messagebox.askyesno',return_value=False),patch('tkinter.messagebox.showerror') as errors:
            app=App();app.withdraw();self.addCleanup(app.destroy)
            app.autosave_path=work/'project.json';app.catalog=self.catalog()
            app.root_path=find_installation() or Path('unconfigured-factorio-installation')
            app.mods_path=work/'mods';app.mods_path.mkdir();app.setup_frame.destroy();app.workspace()
            app.new_machine_tab(source=('lab','lab'),mode='edit');tab=app.nametowidget(app.tabs.select())
            self.assertTrue(tab.field_rows['energy_type'][0].winfo_manager())
            tab.vars['energy_type'].set('burner');tab.vars['fuel_inventory_size'].set('3')
            self.assertTrue(tab.save_changes(),errors.call_args_list)
            self.assertEqual(app.catalog.raw['lab']['lab']['energy_source']['fuel_inventory_size'],3)
            tab.load('lab');self.assertEqual(tab.vars['energy_type'].get(),'burner')
            self.assertEqual(tab.vars['fuel_inventory_size'].get(),'3')
            self.assertTrue(app.undo())
            self.assertEqual(app.catalog.raw['lab']['lab']['energy_source']['type'],'electric')
            self.assertFalse(errors.called,errors.call_args_list)
