import copy,json,tempfile
from pathlib import Path
import tkinter as tk
from tkinter import ttk
import unittest
from unittest.mock import patch
from app import App
from core import Catalog
from bulk_items import create_items
from installation import find_installation

@unittest.skipUnless(Path('.cache/test-catalog.json').exists(),'Requires catalog')
class BulkUnused(unittest.TestCase):
    def test_mixed_batch_finished_validation_and_undo(self):
        work=Path(tempfile.mkdtemp(dir=Path('.cache').resolve()))
        with patch('tkinter.messagebox.askyesno',return_value=False), patch('tkinter.messagebox.showerror') as errors:
            app=App(); app.withdraw(); self.addCleanup(app.destroy)
            app.autosave_path=work/'project.json'
            app.catalog=Catalog(json.loads(Path('.cache/test-catalog.json').read_text(encoding='utf-8')))
            app.root_path=find_installation() or Path('unconfigured-factorio-installation')
            app.mods_path=work/'mods'; app.mods_path.mkdir()
            app.setup_frame.destroy(); app.workspace()
            chart=app.nametowidget(app.tabs.select())
            create_items(chart,'bulk unused a  bulk unused b')
            fluid=copy.deepcopy(app.project.data['items']['bulk_unused_b'])
            fluid.update(name='bulk_fluid',kind='fluid',default_temperature=25)
            app.project.data['items']['bulk_fluid']=fluid
            app.refresh_catalog(); app.pending_tab()
            pending=app.nametowidget(app.tabs.select())
            keys=[('item','bulk_unused_a'),('item','bulk_unused_b'),('fluid','bulk_fluid')]
            rows=[kind+':'+name for kind,name in keys]
            pending.unused.selection_set(*rows)
            self.assertEqual(len(pending.unused.selection()),3)
            before=copy.deepcopy(app.project.data)
            self.assertTrue(pending.apply_unused_edits(keys,{'stack_size':'50','description':'Shared description'}))
            self.assertEqual(app.project.data['items']['bulk_unused_a']['stack_size'],50)
            self.assertEqual(app.project.data['items']['bulk_fluid']['stack_size'],100)
            self.assertEqual(app.project.data['items']['bulk_fluid']['description'],'Shared description')
            self.assertTrue(app.undo()); self.assertEqual(app.project.data,before)
            self.assertFalse(pending.apply_unused_edits(keys,{'description':'No partial updates','stack_size':'0'}))
            self.assertEqual(app.project.data,before); errors.reset_mock()
            pending.unused.selection_set(*rows)
            dialog=pending.bulk_edit_unused()
            def descendants(widget):
                for child in widget.winfo_children():
                    yield child
                    yield from descendants(child)
            choice=next(w for w in descendants(dialog) if isinstance(w,ttk.Combobox))
            choice.set('Mark as finished product')
            next(w for w in descendants(dialog) if isinstance(w,ttk.Button) and w.cget('text')=='Apply to selected').invoke()
            for row in rows:self.assertFalse(pending.unused.exists(row))
            self.assertTrue(app.undo())
            for row in rows:self.assertTrue(pending.unused.exists(row))
            from core import Recipe
            recipe=Recipe('bulk-delete-producer',{'ingredients':[{'type':'item','name':'iron-plate','amount':1}],
                'results':[{'type':kind,'name':name,'amount':1} for kind,name in keys]})
            app.project.save_recipe(recipe,recipe.name,1,False,custom=True)
            app.persist(); app.refresh_catalog()
            chart.load(recipe.name)
            before=copy.deepcopy(app.project.data)
            count=len(app.undo_stack)
            # A failure after the first deletion restores disk, history and charts.
            with patch.object(app.project,'compile',side_effect=ValueError('Test failure')):
                self.assertFalse(pending.delete_unused_batch(keys))
            self.assertEqual(app.project.data,before)
            self.assertEqual(json.loads(app.autosave_path.read_text(encoding='utf-8')),before)
            self.assertEqual(chart.loaded_name,recipe.name)
            self.assertEqual(len(app.undo_stack),count)
            errors.reset_mock()
            pending.unused.selection_set(*rows)
            dialog=pending.bulk_edit_unused()
            with patch.object(app.project,'compile',wraps=app.project.compile) as compile_batch, patch.object(app,'persist',wraps=app.persist) as persist_batch, patch.object(app,'refresh_catalog',wraps=app.refresh_catalog) as refresh_batch:
                next(w for w in descendants(dialog) if isinstance(w,ttk.Button) and w.cget('text')=='Delete selected items and recipes').invoke()
                self.assertEqual(compile_batch.call_count,1)
                self.assertEqual(persist_batch.call_count,1)
                self.assertEqual(refresh_batch.call_count,1)
            for key in keys:self.assertNotIn(key,app.catalog.items)
            self.assertNotIn(recipe.name,app.catalog.recipes)
            self.assertIsNone(chart.loaded_name)
            self.assertEqual(len(app.undo_stack),count+1)
            self.assertTrue(app.undo())
            self.assertEqual(app.project.data,before)
            self.assertEqual(chart.loaded_name,recipe.name)
            self.assertFalse(errors.called,errors.call_args_list)
            # Dependency checks run before mutation, not partway through the batch.
            app.project.data['machines']['blocker']={'recipes':[recipe.name]}
            blocked=copy.deepcopy(app.project.data)
            self.assertFalse(pending.delete_unused_batch(keys))
            self.assertEqual(app.project.data,blocked)
            self.assertIn('Machine: blocker',str(errors.call_args))

