import json
from pathlib import Path
import tempfile
import tkinter as tk
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from sprite_sheet_editor import SheetNormalizer, paint_mask, mask_rectangles


class MaskNormalization(unittest.TestCase):
    def test_brush_eraser_and_mask_rectangle_coverage(self):
        mask = bytearray(100)
        paint_mask(mask, 10, 10, 5, 5, 2)
        self.assertEqual(mask[55], 1)
        self.assertEqual(mask[0], 0)
        coverage = bytearray(100)
        for left, top, right, bottom in mask_rectangles(mask, 10, 10):
            for y in range(top, bottom):
                coverage[y*10+left:y*10+right] = b'\x01'*(right-left)
        self.assertEqual(coverage, mask)
        paint_mask(mask, 10, 10, 5, 5, 1, 0)
        self.assertEqual(mask[55], 0)
        self.assertEqual(mask[57], 1)

    def test_exact_masked_pixels_alpha_and_unused_sheet_pixels(self):
        root = tk.Tk(); root.withdraw(); self.addCleanup(root.destroy)
        sheet = tk.PhotoImage(master=root, width=9, height=4)
        sheet.put('#ff0000', to=(0,0,4,4)); sheet.put('#0000ff', to=(4,0,8,4)); sheet.put('#00ff00', to=(8,0,9,4))
        sheet.transparency_set(1,1,True); sheet.transparency_set(6,2,True)
        mask = bytearray(16); mask[0]=1; mask[10]=1
        normalizer = SheetNormalizer(sheet,4,4,2,2,mask)
        normalizer.step(0); normalizer.step(1)
        result = normalizer.result
        self.assertEqual(result.get(4,0),(0,0,255))
        self.assertEqual(result.get(5,0),(255,0,0))
        self.assertTrue(result.transparency_get(5,1))
        self.assertTrue(result.transparency_get(6,2))
        self.assertEqual(result.get(8,2),(0,255,0))
        self.assertTrue(result.transparency_get(1,1))
        with self.assertRaises(ValueError):
            SheetNormalizer(sheet,4,4,3,2,mask)

    @unittest.skipUnless(Path('.cache/test-catalog.json').exists(), 'Requires cached catalog')
    def test_editor_preview_apply_machine_undo_and_source_preserved(self):
        from app import App
        from core import Catalog
        from installation import find_installation
        from machine_model import zero_config
        work = Path(tempfile.mkdtemp(dir=Path('.cache').resolve()))
        with patch('tkinter.messagebox.askyesno', return_value=False), patch('tkinter.messagebox.showerror') as errors:
            app=App(); app.withdraw(); self.addCleanup(app.destroy)
            app.autosave_path=work/'project.json'
            app.catalog=Catalog(json.loads(Path('.cache/test-catalog.json').read_text(encoding='utf-8')))
            app.root_path=find_installation() or Path('unconfigured-factorio-installation')
            app.mods_path=work/'mods'; app.mods_path.mkdir()
            app.setup_frame.destroy(); app.workspace()
            app.new_machine_tab(); machine=app.nametowidget(app.tabs.select())
            machine.populate(zero_config(),'normalized-test','create')
            sheet=tk.PhotoImage(master=app,width=8,height=4)
            sheet.put('#ff0000',to=(0,0,4,4));sheet.put('#0000ff',to=(4,0,8,4))
            source=work/'sheet.png';sheet.write(source,format='png');original=source.read_bytes()
            machine.vars['sprite_path'].set(str(source))
            machine.vars['frame_width'].set('4'); machine.vars['frame_height'].set('4')
            machine.vars['frame_count'].set('2'); machine.vars['line_length'].set('2')
            editor=machine.normalize_sprite_sheet()
            self.assertIsNotNone(editor,errors.call_args_list)
            editor.radius.set(1)
            editor.begin_stroke(SimpleNamespace(x=12+2*4,y=12+2*4))
            editor.end_stroke(None)
            self.assertTrue(any(editor.mask))
            editor.undo_mask();self.assertFalse(any(editor.mask))
            editor.mask[0]=1
            editor.normalize()
            for _ in range(100):
                app.update()
                if editor.output is not None:break
                app.after(2)
            self.assertIsNotNone(editor.output)
            self.assertEqual(editor.output.get(4,0),(0,0,255))
            self.assertEqual(editor.output.get(5,0),(255,0,0))
            exported=work/'normalized-copy.png'
            with patch('sprite_sheet_editor.filedialog.asksaveasfilename',return_value=str(exported)):
                editor.export()
            exported_image=tk.PhotoImage(master=app,file=str(exported))
            self.assertEqual(exported_image.get(4,0),(0,0,255))
            self.assertEqual(exported_image.get(5,0),(255,0,0))
            editor.apply()
            self.assertEqual(machine.vars['sprite_path'].get(),'Normalized sprite sheet (embedded)')
            self.assertTrue(machine.save_changes(),errors.call_args_list)
            self.assertEqual(source.read_bytes(),original)
            self.assertEqual(app.project.data['machines']['normalized-test']['sprite']['width'],8)
            self.assertTrue(app.undo())
            self.assertTrue(app.undo())
            self.assertEqual(machine.vars['sprite_path'].get(),str(source))
            self.assertFalse(errors.called,errors.call_args_list)

