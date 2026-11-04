import copy,json,tempfile
from pathlib import Path
from tkinter import ttk
import unittest
from unittest.mock import patch
from core import Catalog, load_game
from app import App
from installation import find_installation
from recipe_unlocks import create_shared_prerequisite

@unittest.skipUnless(Path('.cache/test-catalog.json').exists(),'Requires catalog')
class SharedPrerequisite(unittest.TestCase):
    def test_multi_select_form_cycles_undo_and_export(self):
        work=Path(tempfile.mkdtemp(dir=Path('.cache').resolve()))
        with patch('tkinter.messagebox.askyesno',return_value=False),patch('tkinter.messagebox.showerror') as errors:
            app=App();app.withdraw();self.addCleanup(app.destroy)
            app.autosave_path=work/'project.json'
            app.catalog=Catalog(json.loads(Path('.cache/test-catalog.json').read_text(encoding='utf-8')))
            app.root_path=find_installation() or Path('unconfigured-factorio-installation')
            app.mods_path=work/'mods';app.mods_path.mkdir()
            app.setup_frame.destroy();app.workspace()
            recipes=['iron-gear-wheel','copper-cable']
            for name in ('shared-parent-a','shared-parent-b'):
                proto=copy.deepcopy(app.base_raw['technology']['automation-2'])
                proto.update(name=name,prerequisites=['automation'],effects=[{'type':'unlock-recipe','recipe':recipe} for recipe in recipes])
                app.project.data['technologies'][name]={'prototype':proto}
            app.refresh_catalog();app.pending_tab()
            pending=app.nametowidget(app.tabs.select())
            rows=[key for key,row in pending.multi_tech_rows.items() if row['name'] in recipes]
            self.assertEqual(len(rows),2)
            pending.multi_tech.selection_set(*rows)
            before=copy.deepcopy(app.project.data)
            import tkinter as tk
            def walk(widget):
                for child in widget.winfo_children():
                    yield child
                    yield from walk(child)
            assignment=pending.assign_multi_technology()
            listing=next(w for w in walk(assignment) if isinstance(w,tk.Listbox))
            index=list(listing.get(0,'end')).index('automation')
            listing.selection_clear(0,'end');listing.selection_set(index)
            undo_count=len(app.undo_stack)
            next(w for w in walk(assignment) if isinstance(w,ttk.Button) and w.cget('text')=='Add to selected technology').invoke()
            self.assertEqual(len(app.undo_stack),undo_count+1)
            for recipe in recipes:
                self.assertTrue({'automation','shared-parent-a','shared-parent-b'} <= set(app.project.recipe_unlocks(recipe,app.base_raw)))
            self.assertTrue(app.undo())
            self.assertEqual(app.project.data,before)
            pending.multi_tech.selection_set(*rows)

            bad=copy.deepcopy(app.catalog.raw['technology']['shared-parent-a'])
            bad.update(name='cycle-test',prerequisites=['shared-parent-a'])
            with self.assertRaisesRegex(ValueError,'cycle'):
                create_shared_prerequisite(pending,recipes,bad)
            self.assertEqual(app.project.data,before)
            dialog=pending.create_multi_prerequisite()
            def descendants(widget):
                for child in widget.winfo_children():
                    yield child
                    yield from descendants(child)
            for widget in descendants(dialog):
                children=widget.winfo_children()
                if children and isinstance(children[0],ttk.Label) and children[0].cget('text')=='Technology ID':
                    entry=next(w for w in children if isinstance(w,ttk.Entry));entry.delete(0,'end');entry.insert(0,'shared-prerequisite-test')
            count=len(app.undo_stack)
            next(w for w in descendants(dialog) if isinstance(w,ttk.Button) and w.cget('text')=='Create technology').invoke()
            self.assertFalse(errors.called,errors.call_args_list)
            self.assertEqual(len(app.undo_stack),count+1)
            for recipe in recipes:
                self.assertEqual(app.project.recipe_unlocks(recipe,app.base_raw),['shared-prerequisite-test'])
                self.assertFalse(app.catalog.recipes[recipe]['enabled'])
            for parent in ('shared-parent-a','shared-parent-b'):
                self.assertIn('shared-prerequisite-test',app.catalog.raw['technology'][parent]['prerequisites'])
                self.assertIn('automation',app.catalog.raw['technology'][parent]['prerequisites'])
                self.assertFalse(app.catalog.raw['technology'][parent]['effects'])
            if find_installation():
                archive=work/'recipe-studio-project_1.0.0.zip'
                app.project.export(archive,Catalog(app.base_raw),app.root_path,app.mods_path)
                loaded,_,_=load_game(app.root_path,[archive],work/'engine')
                self.assertIn('shared-prerequisite-test',loaded.raw['technology']['shared-parent-a']['prerequisites'])
                self.assertEqual({effect['recipe'] for effect in loaded.raw['technology']['shared-prerequisite-test']['effects']},set(recipes))
            self.assertTrue(app.undo())
            self.assertEqual(app.project.data,before)
            self.assertEqual(len([row for row in pending.multi_tech_rows.values() if row['name'] in recipes]),2)
