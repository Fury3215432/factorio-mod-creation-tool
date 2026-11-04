import copy
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch
import zipfile

from app import App
from core import Catalog, Recipe, prepare_mod_test, launch_mod_test
from installation import find_installation
from project import Project


@unittest.skipUnless(Path('.cache/test-catalog.json').exists() and find_installation(), 'Requires Factorio and cached catalog')
class TestModLaunch(unittest.TestCase):
    def fixture(self):
        work=Path(tempfile.mkdtemp(dir=Path('.cache').resolve()))
        source=work/'source-mods'; source.mkdir()
        with zipfile.ZipFile(source/'test-dependency_1.0.0.zip', 'w') as archive:
            archive.writestr('test-dependency_1.0.0/info.json',json.dumps({'name':'test-dependency', 'version':'1.0.0',
                'title':'Test dependency', 'author':'Test', 'factorio_version':'2.0', 'dependencies':['base']}))
            archive.writestr('test-dependency_1.0.0/data.lua','-- no prototype changes\n')
        (source/'mod-list.json').write_text('{"mods":[]}',encoding='utf-8')
        catalog=Catalog(json.loads(Path('.cache/test-catalog.json').read_text(encoding='utf-8')))
        project=Project()
        project.save_recipe(Recipe('iron-gear-wheel',catalog.recipes['iron-gear-wheel']),'iron-gear-wheel',3,True)
        return work,source,catalog,project

    def test_isolated_export_launch_arguments_and_real_factorio_load(self):
        work,source,catalog,project=self.fixture()
        original={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in source.iterdir()}
        before=copy.deepcopy(project.data)
        workspace=work/'playtest'
        command=prepare_mod_test(project,catalog,find_installation(),source,workspace)
        self.assertNotIn('--dump-data',command)
        self.assertEqual(Path(command[command.index('--mod-directory')+1]),workspace/'mods')
        enabled=json.loads((workspace/'mods/mod-list.json').read_text(encoding='utf-8'))
        self.assertEqual({m['name'] for m in enabled['mods']},{'base','test-dependency','recipe-studio-playtest'})
        with zipfile.ZipFile(workspace/'mods/recipe-studio-playtest_1.0.0.zip') as archive:
            info=json.loads(archive.read('recipe-studio-playtest_1.0.0/info.json'))
            self.assertTrue(any('test-dependency' in dep for dep in info['dependencies']))
        self.assertEqual(original,{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in source.iterdir()})
        self.assertEqual(project.data,before)
        with patch('core.subprocess.Popen') as launch:
            process=launch_mod_test(project,catalog,find_installation(),source,work/'second-test')
            self.assertIs(process,launch.return_value)
            self.assertNotIn('--dump-data',launch.call_args.args[0])
        # Verify the exact prepared profile loads in Factorio, without opening
        # a game window during automated tests.
        (workspace/'script-output').mkdir(exist_ok=True)
        result=subprocess.run(command+['--dump-data'],capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=300)
        self.assertEqual(result.returncode,0,(result.stdout+result.stderr)[-2500:])
        dump=json.loads((workspace/'script-output/data-raw-dump.json').read_text(encoding='utf-8'))
        self.assertEqual(dump['recipe']['iron-gear-wheel']['energy_required'],3)

    def test_button_saves_edits_but_not_equation_import_and_reports_launch_failure(self):
        work,source,catalog,project=self.fixture()
        with patch('tkinter.messagebox.askyesno',return_value=False),patch('tkinter.messagebox.showerror') as errors:
            app=App();app.withdraw();self.addCleanup(app.destroy)
            app.autosave_path=work/'project.json';app.catalog=catalog;app.root_path=find_installation();app.mods_path=source
            app.setup_frame.destroy();app.workspace();app.project=project;app.refresh_catalog()
            equations=app.equations_tab();equations.text.insert('1.0','unfinished equation');equations.modified(None)
            process=MagicMock();process.poll.return_value=None
            def thread(**options):
                return SimpleNamespace(start=options['target'])
            with patch('app.threading.Thread',side_effect=thread),patch('core.launch_mod_test',return_value=process) as launch:
                self.assertTrue(app.test_mod())
                self.assertEqual(str(app.test_button.cget('state')),'disabled')
                self.assertEqual(app.project.data['equations_draft']['input'][0],'unfinished equation')
                self.assertEqual(set(app.project.data['recipes']),{'iron-gear-wheel'})
                app.after_cancel(app.poll_job);app.poll()
                self.assertIs(app.test_process,process)
                self.assertEqual(str(app.test_button.cget('state')),'normal')
                with patch('tkinter.messagebox.showinfo'):
                    self.assertFalse(app.test_mod())
                self.assertEqual(launch.call_count,1)
                process.poll.return_value=0
                launch.side_effect=OSError('Launch failed')
                self.assertTrue(app.test_mod())
                app.after_cancel(app.poll_job);app.poll()
                self.assertEqual(str(app.test_button.cget('state')),'normal')
                errors.assert_called_once()
                self.assertIn('Launch failed',str(errors.call_args))

