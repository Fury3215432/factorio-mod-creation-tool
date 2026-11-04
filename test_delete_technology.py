import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from app import App
from core import Catalog, load_game
from project import Project
from delete_items import delete_technology
from installation import find_installation


@unittest.skipUnless(Path('.cache/test-catalog.json').exists(), 'Requires cached catalog')
class DeleteTechnology(unittest.TestCase):
    def test_deleted_technology_tip_dependencies_and_engine_export(self):
        raw = json.loads(Path('.cache/test-catalog.json').read_text(encoding='utf-8'))
        raw['tips-and-tricks-item']['test-dependent-tip'] = {
            'type': 'tips-and-tricks-item', 'name': 'test-dependent-tip', 'dependencies': ['long-handed-inserters', 'inserters']}
        project = Project()
        project.data['deleted']['technology'] = {'automation': True, 'circuit-network': True, 'oil-processing': True}
        merged = project.merged_raw(raw)
        self.assertNotIn('long-handed-inserters', merged['tips-and-tricks-item'])
        self.assertNotIn('circuit-network', merged['tips-and-tricks-item'])
        self.assertNotIn('eco-unfriendly', merged['research-achievement'])
        self.assertNotIn('technology_to_unlock', merged['shortcut']['give-red-wire'])
        self.assertEqual(merged['tips-and-tricks-item']['test-dependent-tip']['dependencies'], ['inserters'])
        self.assertTrue(all(not set(p.get('prerequisites', [])) & set(project.data['deleted']['technology']) for p in merged['technology'].values()))
        changes = project.changes(Catalog(raw))
        self.assertTrue(any(row['type'] == 'tips-and-tricks-item' and row['name'] == 'long-handed-inserters' and row['operation'] == 'deleted' for row in changes))
        installation = find_installation()
        if installation:
            work = Path(tempfile.mkdtemp(dir=Path('.cache').resolve()))
            base = Catalog(json.loads(Path('.cache/test-catalog.json').read_text(encoding='utf-8')))
            archive = work/'recipe-studio-project_1.0.0.zip'
            (work/'mods').mkdir()
            project.export(archive, base, installation, work/'mods')
            loaded, _, _ = load_game(installation, [archive], work/'engine')
            self.assertNotIn('automation', loaded.raw['technology'])
            self.assertNotIn('long-handed-inserters', loaded.raw['tips-and-tricks-item'])
            self.assertNotIn('circuit-network', loaded.raw['tips-and-tricks-item'])
            self.assertNotIn('eco-unfriendly', loaded.raw['research-achievement'])
            self.assertNotIn('technology_to_unlock', loaded.raw['shortcut']['give-red-wire'])

    def test_created_loaded_blockers_failure_and_undo(self):
        work = Path(tempfile.mkdtemp(dir=Path('.cache').resolve()))
        with patch('tkinter.messagebox.askyesno', return_value=False), patch('tkinter.messagebox.showerror') as errors:
            app = App(); app.withdraw(); self.addCleanup(app.destroy)
            app.autosave_path = work / 'project.json'
            app.catalog = Catalog(json.loads(Path('.cache/test-catalog.json').read_text(encoding='utf-8')))
            app.root_path = find_installation() or Path('unconfigured-factorio-installation')
            app.mods_path = work / 'mods'; app.mods_path.mkdir()
            app.setup_frame.destroy(); app.workspace()
            prototype = copy.deepcopy(app.catalog.raw['technology']['automation'])
            prototype.update(name='delete-test-tech', prerequisites=[])
            app.project.data['technologies']['delete-test-tech'] = {'prototype': prototype}
            child = copy.deepcopy(prototype); child.update(name='delete-test-child', prerequisites=['delete-test-tech'])
            app.project.data['technologies']['delete-test-child'] = {'prototype': child}
            app.persist(); app.refresh_catalog()
            tree = app.tech_tab(); tree.edit('delete-test-tech')
            before = copy.deepcopy(app.project.data)
            self.assertFalse(delete_technology(tree, 'delete-test-tech', confirm=False))
            self.assertEqual(app.project.data, before)
            self.assertIn('delete-test-child', str(errors.call_args)); errors.reset_mock()
            self.assertTrue(delete_technology(tree, 'delete-test-child', confirm=False))
            tree.editor_vars['time'].set('123')
            before = copy.deepcopy(app.project.data)
            with patch.object(app.project, 'compile', side_effect=ValueError('Test failure')):
                self.assertFalse(delete_technology(tree, 'delete-test-tech', confirm=False))
            self.assertEqual(app.project.data, before); errors.reset_mock()
            self.assertTrue(delete_technology(tree, 'delete-test-tech', confirm=False))
            self.assertNotIn('delete-test-tech', app.catalog.raw['technology'])
            self.assertIsNone(tree.selected)
            self.assertTrue(app.undo())
            self.assertEqual(app.project.data, before)
            self.assertEqual(tree.selected, 'delete-test-tech')
            self.assertEqual(tree.editor_vars['time'].get(), '123')
            # Loaded technology deletion also removes the original prototype,
            # rather than only reverting a saved edit.
            parents = {p for proto in app.catalog.raw['technology'].values() for p in proto.get('prerequisites', [])}
            leaf = next(n for n in app.base_raw['technology'] if n not in parents)
            browser = app.browse_creations()
            self.assertTrue(delete_technology(browser, leaf, confirm=False))
            self.assertNotIn(leaf, app.catalog.raw['technology'])
            code, _ = app.project.compile(Catalog(app.base_raw))
            self.assertIn(leaf, code)
            self.assertTrue(app.undo()); self.assertIn(leaf, app.catalog.raw['technology'])
            self.assertFalse(errors.called, errors.call_args_list)

