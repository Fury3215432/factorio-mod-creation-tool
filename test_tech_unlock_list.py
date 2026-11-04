import json,tempfile
from pathlib import Path
from tkinter import ttk
import unittest
from unittest.mock import patch
from app import App
from core import Catalog
from installation import find_installation

@unittest.skipUnless(Path('.cache/test-catalog.json').exists(),'Requires catalog')
class TechnologyUnlockList(unittest.TestCase):
    def test_icons_multi_remove_undo_save_and_reopen(self):
        work=Path(tempfile.mkdtemp(dir=Path('.cache').resolve()))
        with patch('tkinter.messagebox.askyesno',return_value=False),patch('tkinter.messagebox.showerror') as errors:
            app=App();app.withdraw();self.addCleanup(app.destroy)
            app.autosave_path=work/'project.json'
            app.catalog=Catalog(json.loads(Path('.cache/test-catalog.json').read_text(encoding='utf-8')))
            app.root_path=find_installation() or Path('unconfigured-factorio-installation')
            app.mods_path=work/'mods';app.mods_path.mkdir()
            app.setup_frame.destroy();app.workspace()
            tree=app.tech_tab();tree.edit('automation-2')
            tree.editor_vars['unlocks'].set('iron-gear-wheel, copper-cable')
            self.assertEqual(tree.unlock_list.get_children(),('iron-gear-wheel','copper-cable'))
            self.assertEqual(len(tree.unlock_list.images),2)
            self.assertEqual(tree.unlock_list.set('copper-cable','products'),'copper-cable')
            tree.unlock_list.selection_set('iron-gear-wheel','copper-cable')
            def descendants(widget):
                for child in widget.winfo_children():
                    yield child
                    yield from descendants(child)
            count=len(app.undo_stack)
            next(w for w in descendants(tree) if isinstance(w,ttk.Button) and w.cget('text')=='Delete selected unlocks').invoke()
            self.assertFalse(tree.unlock_list.get_children())
            self.assertEqual(len(app.undo_stack),count+1)
            self.assertTrue(app.undo())
            self.assertEqual(tree.unlock_list.get_children(),('iron-gear-wheel','copper-cable'))
            self.assertTrue(tree.save_changes())
            self.assertEqual(tree.unlock_list.get_children(),('iron-gear-wheel','copper-cable'))
            tree.edit('logistics');tree.edit('automation-2')
            self.assertEqual(tree.unlock_list.get_children(),('iron-gear-wheel','copper-cable'))
            self.assertFalse(errors.called,errors.call_args_list)
            # A legacy item ID is visible for cleanup, but cannot be saved as an unlock.
            from bulk_items import create_items
            create_items(tree,'unlock item only')
            tree.editor_vars['unlocks'].set('iron-gear-wheel, unlock_item_only')
            self.assertIn('Invalid: not a recipe ID',tree.unlock_list.set('unlock_item_only','products'))
            before=json.loads(json.dumps(app.project.data))
            self.assertFalse(tree.save_changes())
            self.assertEqual(app.project.data,before)
            errors.reset_mock()
            tree.unlock_list.selection_set('unlock_item_only')
            next(w for w in descendants(tree) if isinstance(w,ttk.Button) and w.cget('text')=='Delete selected unlocks').invoke()
            self.assertEqual(tree.editor_vars['unlocks'].get(),'iron-gear-wheel')
            self.assertIn(('item','unlock_item_only'),app.catalog.items)
            self.assertTrue(tree.save_changes())
            self.assertIn(('item','unlock_item_only'),app.catalog.items)
            self.assertFalse(errors.called,errors.call_args_list)

