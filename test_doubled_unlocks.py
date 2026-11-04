import copy,json,tempfile
from pathlib import Path
import unittest
from unittest.mock import patch
from core import Catalog
from project import Project
from app import App
from installation import find_installation

class DoubledUnlocks(unittest.TestCase):
    def test_transitive_prerequisites_without_item_false_positives(self):
        def technology(recipes=(), prerequisites=()):
            return {'effects':[{'type':'unlock-recipe','recipe':name} for name in recipes],'prerequisites':list(prerequisites)}
        recipe={'results':[{'type':'item','name':'same-item','amount':1}]}
        raw={'recipe':{'original':recipe,'alternative':recipe},'technology':{
            'first':technology(['original']), 'middle':technology([],['first']),
            'last':technology(['original','alternative'],['middle','first']),
            'unrelated':technology(['original'])}}
        project=Project()
        shared=project.recipes_with_multiple_technology_unlocks(Catalog(raw))
        self.assertEqual(shared,[{'type':'recipe','name':'original','recipes':['original'],'technologies':['first','last','unrelated']}])
        baseline=copy.deepcopy(raw)
        self.assertEqual(project.multi_technology_suggestions(Catalog(raw),baseline),[])
        raw['technology']['added']=technology(['original'])
        changes=project.multi_technology_suggestions(Catalog(raw),baseline)
        self.assertEqual(len(changes),1)
        self.assertIn('added',changes[0]['technologies'])
        project.data['hidden_multi_tech']['recipe:original']=True
        self.assertEqual(project.multi_technology_suggestions(Catalog(raw),baseline),[])
        self.assertEqual(len(project.multi_technology_suggestions(Catalog(raw),baseline,True)),1)

        self.assertEqual(project.doubled_technology_unlocks(Catalog(raw)),[
            {'technology':'last','recipe':'original','prerequisites':['first']}])
        raw['technology']['first']['prerequisites']=['last']
        rows=project.doubled_technology_unlocks(Catalog(raw))
        self.assertTrue(all(row['technology'] not in row['prerequisites'] for row in rows))

    @unittest.skipUnless(Path('.cache/test-catalog.json').exists(),'Requires catalog')
    def test_suggested_actions_lists_and_opens_technology(self):
        work=Path(tempfile.mkdtemp(dir=Path('.cache').resolve()))
        with patch('tkinter.messagebox.askyesno',return_value=False):
            app=App();app.withdraw();self.addCleanup(app.destroy)
            app.autosave_path=work/'project.json'
            app.catalog=Catalog(json.loads(Path('.cache/test-catalog.json').read_text(encoding='utf-8')))
            app.root_path=find_installation() or Path('unconfigured-factorio-installation')
            app.mods_path=work/'mods';app.mods_path.mkdir()
            app.setup_frame.destroy();app.workspace()
            proto=copy.deepcopy(app.base_raw['technology']['automation-2'])
            proto.update(name='doubled-test-technology',prerequisites=['automation-2'])
            app.project.data['technologies'][proto['name']]={'prototype':proto}
            app.refresh_catalog();app.pending_tab()
            pending=app.nametowidget(app.tabs.select())
            rows=[key for key,row in pending.doubled_rows.items() if row['technology']==proto['name']]
            self.assertTrue(rows)
            self.assertEqual(app.pending_button.winfo_manager(),'pack')
            pending.doubled.selection_set(rows[0])
            tree=pending.open_doubled_technology()
            self.assertEqual(tree.selected,proto['name'])
            recipe=pending.doubled_rows[rows[0]]['recipe']
            original_effects=copy.deepcopy(app.catalog.raw['technology'][proto['name']]['effects'])
            earlier_effects=copy.deepcopy(app.catalog.raw['technology']['automation-2']['effects'])
            count=len(app.undo_stack)
            from types import SimpleNamespace
            with patch.object(pending.doubled,'identify_row',return_value=rows[0]):
                self.assertTrue(pending.remove_doubled_technology_unlock(SimpleNamespace(y=5)))
            self.assertEqual(len(app.undo_stack),count+1)
            self.assertFalse(any(row['technology']==proto['name'] and row['recipe']==recipe for row in pending.doubled_rows.values()))
            self.assertEqual(app.catalog.raw['technology']['automation-2']['effects'],earlier_effects)
            self.assertNotIn(recipe,tree.editor_vars['unlocks'].get().split(', '))
            self.assertEqual(app.catalog.raw['technology'][proto['name']]['effects'],[effect for effect in original_effects if effect.get('recipe')!=recipe])
            self.assertTrue(app.undo())
            self.assertEqual(app.catalog.raw['technology'][proto['name']]['effects'],original_effects)
            self.assertIn(recipe,tree.editor_vars['unlocks'].get().split(', '))
            self.assertTrue(any(proto['name'] in row['technologies'] and 'automation-2' in row['technologies'] for row in pending.multi_tech_rows.values()))
            entry=next(row for row in pending.multi_tech_rows.values() if proto['name'] in row['technologies'])
            token=entry['type']+':'+entry['name']
            self.assertTrue(pending.hide_multi_technology(entry))
            self.assertFalse(any(row['name']==entry['name'] and row['type']==entry['type'] for row in pending.multi_tech_rows.values()))
            from project import Project
            self.assertTrue(Project.open(app.autosave_path).data['hidden_multi_tech'][token])
            self.assertTrue(app.undo())
            self.assertNotIn(token,app.project.data['hidden_multi_tech'])
            self.assertTrue(pending.hide_multi_technology(entry))
            pending.show_hidden_multi.set(True);pending.refresh()
            self.assertTrue(any(row['name']==entry['name'] for row in pending.multi_tech_rows.values()))
            self.assertTrue(pending.hide_multi_technology(entry,False))
            pending.show_hidden_multi.set(False);pending.refresh()
            self.assertTrue(any(row['name']==entry['name'] for row in pending.multi_tech_rows.values()))

            from contextlib import ExitStack
            with ExitStack() as stack:
                for method in ('items_missing_icons','missing_machine_recipes','items_missing_recipes','items_unused','recipes_missing_unlocks','doubled_technology_unlocks'):
                    stack.enter_context(patch.object(app.project,method,return_value=[]))
                app.update_pending_button()
                self.assertEqual(app.pending_button.cget('text'),'Suggested actions')
                self.assertEqual(app.pending_button.winfo_manager(),'pack')
                with patch.object(app.project,'items_missing_icons',return_value=['one-real-issue']):
                    app.update_pending_button()
                    self.assertEqual(app.pending_button.cget('text'),'Suggested actions (1)')

