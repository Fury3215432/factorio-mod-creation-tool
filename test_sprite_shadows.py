import base64
import copy
import json
from pathlib import Path
import tempfile
import time
import tkinter as tk
import unittest
from unittest.mock import patch

from sprite_shadows import alpha_png, png_alpha, create_shadow_sheet, create_horizontal_shadow_sheet


class ShadowPixels(unittest.TestCase):
    def test_horizontal_right_cast_changes_only_length(self):
        alpha=bytearray(8*6)
        alpha[2*8+1]=255
        png=alpha_png(8,6,alpha)
        short=create_horizontal_shadow_sheet(png,4,6,2,2,length=.5)
        long=create_horizontal_shadow_sheet(png,4,6,2,2,length=1)
        self.assertEqual(short['shift_pixels'],[1,0])
        self.assertEqual(long['shift_pixels'],[2,0])
        self.assertEqual(short['frame_height'],long['frame_height'])
        self.assertEqual(long['frame_width']-short['frame_width'],2)
        width,height,pixels=png_alpha(base64.b64decode(long['data']))
        occupied=[(x,y) for y in range(height) for x in range(long['frame_width']) if pixels[y*width+x]]
        self.assertEqual({y for x,y in occupied},{2,3,4})
        self.assertGreater(max(x for x,y in occupied),4)
        self.assertFalse(any(pixels[y*width+x] for y in range(height) for x in range(long['frame_width'],width)))
        for length in (-1,float('inf'),5):
            with self.assertRaises(ValueError):create_horizontal_shadow_sheet(png,4,6,2,2,length=length)

    def test_alpha_opacity_frame_isolation_and_geometry(self):
        alpha=bytearray(32);alpha[0]=255;alpha[3*8+7]=128
        png=alpha_png(8,4,alpha)
        self.assertEqual(png_alpha(png),(8,4,alpha))
        result=create_shadow_sheet(png,4,4,2,2,slant=0,flatten=1,opacity=.5,softness=0)
        width,height,shadow=png_alpha(base64.b64decode(result['data']))
        self.assertEqual((width,height),(8,4))
        self.assertEqual(shadow[0],128);self.assertEqual(shadow[31],64)
        self.assertEqual(sum(value != 0 for value in shadow),2)
        self.assertEqual(result['shift_pixels'],[0,0])
        projected=create_shadow_sheet(png,4,4,2,2,slant=-.5,flatten=.5,softness=1)
        self.assertGreater(projected['frame_width'],4)
        self.assertEqual(projected['width'],projected['frame_width']*2)
        for parameters in ({'opacity':0},{'slant':float('nan')},{'flatten':2},{'softness':-1}):
            with self.subTest(parameters=parameters),self.assertRaises(ValueError):
                create_shadow_sheet(png,4,4,2,2,**parameters)

    @unittest.skipUnless(Path('.cache/test-catalog.json').exists(),'Requires cached catalog')
    def test_editor_apply_layers_save_export_engine_and_undo(self):
        from app import App
        from core import Catalog,load_game
        from installation import find_installation
        from machine_model import zero_config,matching_shadow
        from test_project import make_icon
        work=Path(tempfile.mkdtemp(dir=Path('.cache').resolve()))
        with patch('tkinter.messagebox.askyesno',return_value=False),patch('tkinter.messagebox.showerror') as errors:
            app=App();app.withdraw();self.addCleanup(app.destroy)
            app.autosave_path=work/'project.json'
            app.catalog=Catalog(json.loads(Path('.cache/test-catalog.json').read_text(encoding='utf-8')))
            app.root_path=find_installation() or Path('unconfigured-factorio-installation')
            app.mods_path=work/'mods';app.mods_path.mkdir()
            app.setup_frame.destroy();app.workspace()
            app.new_machine_tab();machine=app.nametowidget(app.tabs.select())
            machine.populate(zero_config(),'shadow-test','create')
            original=make_icon(work/'sheet.png'); original_bytes=original.read_bytes()
            machine.vars['sprite_path'].set(str(original))
            machine.vars['frame_width'].set('16');machine.vars['frame_height'].set('16')
            machine.vars['frame_count'].set('4');machine.vars['line_length'].set('2')
            editor=machine.create_shadows();self.assertIsNotNone(editor,errors.call_args_list)
            self.assertTrue(hasattr(editor,'length'))
            self.assertFalse(any(hasattr(editor,key) for key in ('slant','flatten','opacity','softness')))
            deadline=time.monotonic()+8
            while editor.result is None and time.monotonic()<deadline:
                app.update();app.after(5)
            self.assertIsNotNone(editor.result,errors.call_args_list)
            self.assertEqual(editor.result['shift_pixels'][1],0)
            editor.apply()
            self.assertIn('shadow',machine.assets)
            self.assertTrue(machine.preview_canvas.find_withtag('machine-preview-shadow'))
            self.assertTrue(machine.save_changes(),errors.call_args_list)
            saved=app.project.data['machines']['shadow-test']
            layers=app.catalog.raw['assembling-machine']['shadow-test']['graphics_set']['animation']['layers']
            self.assertTrue(layers[1]['draw_as_shadow'])
            self.assertEqual(layers[0]['frame_count'],layers[1]['frame_count'])
            self.assertEqual(layers[0]['animation_speed'],layers[1]['animation_speed'])
            code,assets=app.project.compile(Catalog(app.base_raw))
            self.assertIn('graphics/machines/shadow-test-shadow.png',assets)
            self.assertEqual(original.read_bytes(),original_bytes)
            invalid=copy.deepcopy(saved);invalid['frame_count']=3
            with self.assertRaisesRegex(ValueError,'Recreate or remove'):
                matching_shadow(invalid)
            if find_installation():
                archive=work/'recipe-studio-project_1.0.0.zip'
                app.project.export(archive,Catalog(app.base_raw),app.root_path,app.mods_path)
                loaded,_,_=load_game(app.root_path,[archive],work/'engine')
                exported=loaded.raw['assembling-machine']['shadow-test']['graphics_set']['animation']['layers']
                self.assertTrue(exported[1]['draw_as_shadow'])
            self.assertTrue(app.undo());self.assertTrue(app.undo())
            self.assertNotIn('shadow',machine.assets)
            self.assertFalse(errors.called,errors.call_args_list)

