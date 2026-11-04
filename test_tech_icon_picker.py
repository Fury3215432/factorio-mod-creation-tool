import json,tempfile
from pathlib import Path
import tkinter as tk
from tkinter import ttk
import unittest
from unittest.mock import patch
from app import App
from core import Catalog,load_game,read_mod
from project import Project
from installation import find_installation

@unittest.skipUnless(Path('.cache/test-catalog.json').exists(),'Requires catalog')
class TechnologyIconPicker(unittest.TestCase):
    def test_select_recipe_and_item_icons_undo_persist_export(self):
        work=Path(tempfile.mkdtemp(dir=Path('.cache').resolve()))
        with patch('tkinter.messagebox.askyesno',return_value=False),patch('tkinter.messagebox.showerror') as errors:
            app=App();app.withdraw();self.addCleanup(app.destroy)
            app.autosave_path=work/'project.json'
            app.catalog=Catalog(json.loads(Path('.cache/test-catalog.json').read_text(encoding='utf-8')))
            app.root_path=find_installation() or Path('unconfigured-factorio-installation')
            app.mods_path=work/'mods';app.mods_path.mkdir()
            app.setup_frame.destroy();app.workspace()
            tree=app.tech_tab();tree.edit('automation-2')
            tree.editor_vars['unlocks'].set('iron-gear-wheel')
            def descendants(widget):
                for child in widget.winfo_children():
                    yield child
                    yield from descendants(child)
            def select_icon(kind):
                next(w for w in descendants(tree) if isinstance(w,ttk.Button) and w.cget('text')=='Choose icon from unlocks…').invoke()
                dialog=next(w for w in app.winfo_children() if isinstance(w,tk.Toplevel) and w.title()=='Choose technology icon from unlocks')
                listing=next(w for w in descendants(dialog) if isinstance(w,ttk.Treeview))
                row=next(row for row in listing.get_children() if listing.set(row,'kind')==kind and listing.item(row,'text')=='iron-gear-wheel')
                listing.selection_set(row)
                next(w for w in descendants(dialog) if isinstance(w,ttk.Button) and w.cget('text')=='Use selected icon').invoke()
            old=tree.editor_vars['png'].get()
            select_icon('recipe')
            self.assertEqual(tree.editor_vars['png'].get(),'@unlock:recipe:iron-gear-wheel')
            self.assertTrue(app.undo())
            self.assertEqual(tree.editor_vars['png'].get(),old)
            select_icon('item')
            self.assertEqual(tree.editor_vars['png'].get(),'@unlock:item:iron-gear-wheel')
            self.assertTrue(tree.save_changes())
            saved=Project.open(app.autosave_path).data['technologies']['automation-2']
            self.assertEqual(saved['icon']['size'],64)
            self.assertEqual(saved['icon_path'],'@unlock:item:iron-gear-wheel')
            tree.edit('logistics');tree.edit('automation-2')
            self.assertTrue(tree.save_changes())
            if find_installation():
                archive=work/'recipe-studio-project_1.0.0.zip'
                app.project.export(archive,Catalog(app.base_raw),app.root_path,app.mods_path)
                self.assertIn('graphics/technologies/automation-2.png',read_mod(archive)[1])
                loaded,_,_=load_game(app.root_path,[archive],work/'engine')
                self.assertEqual(loaded.raw['technology']['automation-2']['icon_size'],64)
            self.assertFalse(errors.called,errors.call_args_list)
