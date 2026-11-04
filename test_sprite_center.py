import base64
import json
from pathlib import Path
import tempfile
import time
import tkinter as tk
import unittest
from unittest.mock import patch

from sprite_shading import center_sheet, detect_frame_layout, repack_detected_sheet, alignment_shifts
from sprite_shadows import png_alpha


class SpriteCentering(unittest.TestCase):
    def test_falling_stones_do_not_move_the_housing_anchor(self):
        width,height=192,64
        rgb=bytearray(width*height*3);alpha=bytearray(width*height);bounds=[]
        for frame,(dx,dy) in enumerate(((0,0),(3,2),(-2,-1))):
            for y in range(8,29):
                for x in range(10,45):
                    i=(y+dy)*width+frame*64+x+dx
                    rgb[i*3:i*3+3]=bytes((30+x*3,20+y*5,90));alpha[i]=255
            for y in range(30+frame*8,33+frame*8):
                for x in range(25,29):
                    i=(y+dy)*width+frame*64+x+dx
                    rgb[i*3:i*3+3]=bytes((130,130,130));alpha[i]=255
            bounds.append((10+dx,8+dy,44+dx,32+frame*8+dy))
        settings=dict(width=64,height=64,frame_count=3,line_length=3)
        self.assertEqual(alignment_shifts(rgb,alpha,width,settings,bounds),[(0,0),(-3,-2),(2,1)])

    def test_stabilization_corrects_translation_and_keeps_flame_animation(self):
        root=tk.Tk();root.withdraw();self.addCleanup(root.destroy)
        width,height=96,32
        rgb=bytearray(width*height*3);alpha=bytearray(width*height)
        bounds=[]
        offsets=((0,0),(3,-2),(-2,2))
        for frame,(dx,dy) in enumerate(offsets):
            for y in range(14,26):
                for x in range(6,21):
                    i=(y+dy)*width+frame*32+x+dx
                    rgb[i*3:i*3+3]=bytes((40+x*6,30+y*4,90))
                    alpha[i]=255
            for y in range(4+frame,13):
                i=(y+dy)*width+frame*32+12+dx
                rgb[i*3:i*3+3]=bytes((255,120,0));alpha[i]=255
            bounds.append((6+dx,4+frame+dy,20+dx,25+dy))
        settings=dict(width=32,height=32,frame_count=3,line_length=3)
        self.assertEqual(alignment_shifts(rgb,alpha,width,settings,bounds),[(0,0),(-3,2),(2,-2)])
        result=center_sheet(rgb,alpha,width,height,settings,stabilize=True)
        image=tk.PhotoImage(master=root,data=base64.b64encode(result))
        _,_,out=png_alpha(result)
        anchors=[];flames=[]
        for frame in range(3):
            anchors.append([(x,y) for y in range(32) for x in range(32) if image.get(frame*32+x,y)==(76,86,90) and out[y*width+frame*32+x]])
            flames.append(sum(1 for y in range(32) for x in range(32) if image.get(frame*32+x,y)==(255,120,0) and out[y*width+frame*32+x]))
        self.assertTrue(anchors[0])
        self.assertEqual(anchors[0],anchors[1]);self.assertEqual(anchors[1],anchors[2])
        self.assertEqual(flames,[9,8,7])

    def test_faint_noise_does_not_block_detection_or_centering(self):
        alpha=bytearray([1]*64)
        for ox in (0,4):
            for oy in (0,4):
                alpha[(oy+1)*8+ox+1]=255
        layout=detect_frame_layout(alpha,8,8)
        self.assertEqual(layout,dict(width=4,height=4,frame_count=4,line_length=2))
        alpha=bytearray([1]*36);alpha[0]=255
        result=center_sheet(bytes([200,100,50])*36,alpha,6,6,dict(width=6,height=6,frame_count=1,line_length=1))
        _,_,out=png_alpha(result)
        self.assertEqual(out[2*6+2],255)
        self.assertNotEqual(out[0],255)

    def test_uneven_margins_repack_without_losing_visible_pixels(self):
        alpha=bytearray(19*8)
        for left in (2,11):
            for y in range(2,6):
                for x in range(left,left+8):alpha[y*19+x]=255
        layout=detect_frame_layout(alpha,19,8)
        self.assertIn('regions',layout)
        self.assertEqual(layout['frame_count'],2)
        asset=repack_detected_sheet(bytes([200,100,50])*19*8,alpha,19,8,layout)
        _,_,out=png_alpha(base64.b64decode(asset['data']))
        self.assertEqual(sum(out),sum(alpha))

    def test_shared_shift_preserves_animation_alpha_and_unused_area(self):
        root=tk.Tk(); root.withdraw(); self.addCleanup(root.destroy)
        width,height=13,4
        alpha=bytearray(width*height)
        alpha[0]=128; alpha[7]=255; alpha[12]=64
        rgb=bytes([200,100,50])*width*height
        result=center_sheet(rgb,alpha,width,height,dict(width=6,height=4,frame_count=2,line_length=2))
        _,_,out=png_alpha(result)
        self.assertEqual(out[width+2],128)
        self.assertEqual(out[width+9],255)
        self.assertEqual(out[0],0)
        self.assertEqual(out[12],64)
        self.assertEqual(sum(out),sum(alpha))
        image=tk.PhotoImage(master=root,data=base64.b64encode(result))
        self.assertEqual(image.get(2,1),(200,100,50))
        with self.assertRaises(ValueError):
            center_sheet(rgb,bytes(width*height),width,height,dict(width=6,height=4,frame_count=2,line_length=2))

    def test_detect_grid_partial_final_row_and_single_frame(self):
        alpha=bytearray(64)
        for ox,oy in ((0,0),(4,0),(0,4)):
            for y in (1,2):
                for x in (1,2):alpha[(oy+y)*8+ox+x]=255
        self.assertEqual(detect_frame_layout(alpha,8,8),dict(width=4,height=4,frame_count=3,line_length=2))
        self.assertEqual(detect_frame_layout(bytes([255])*64,8,8),dict(width=8,height=8,frame_count=1,line_length=1))
        with self.assertRaises(ValueError):detect_frame_layout(bytes(64),8,8)

    @unittest.skipUnless(Path('.cache/test-catalog.json').exists(),'Requires cached catalog')
    def test_machine_detection_center_save_undo_source_unchanged(self):
        from app import App
        from core import Catalog
        from installation import find_installation
        from machine_model import zero_config
        work=Path(tempfile.mkdtemp(dir=Path('.cache').resolve()))
        with patch('tkinter.messagebox.askyesno',return_value=False), patch('tkinter.messagebox.showerror') as errors:
            app=App();app.withdraw();self.addCleanup(app.destroy)
            app.autosave_path=work/'project.json'
            app.catalog=Catalog(json.loads(Path('.cache/test-catalog.json').read_text(encoding='utf-8')))
            app.root_path=find_installation() or Path('unconfigured-factorio-installation')
            app.mods_path=work/'mods';app.mods_path.mkdir()
            app.setup_frame.destroy();app.workspace()
            app.new_machine_tab();machine=app.nametowidget(app.tabs.select())
            machine.populate(zero_config(),'center-test','create')
            sheet=tk.PhotoImage(master=app,width=12,height=6)
            sheet.put('#c86432',to=(1,1,3,3));sheet.put('#c86432',to=(7,1,9,3))
            source=work/'sheet.png';sheet.write(source,format='png');original=source.read_bytes()
            machine.vars['sprite_path'].set(str(source))
            with patch('tkinter.messagebox.askyesno',return_value=True):machine.detect_sprite_frames()
            self.assertEqual(machine.vars['frame_width'].get(),'6')
            self.assertEqual(machine.vars['frame_count'].get(),'2')
            editor=machine.normalize_sprite_sheet(center=True)
            self.assertIsNotNone(editor,errors.call_args_list)
            deadline=time.monotonic()+5
            while editor.output is None and time.monotonic()<deadline:
                app.update();time.sleep(.01)
            self.assertIsNotNone(editor.output)
            editor.apply()
            self.assertEqual(machine.vars['sprite_path'].get(),'Centered sprite sheet (embedded)')
            self.assertTrue(machine.save_changes(),errors.call_args_list)
            self.assertEqual(source.read_bytes(),original)
            self.assertTrue(app.undo());self.assertTrue(app.undo())
            self.assertEqual(machine.vars['sprite_path'].get(),str(source))
            self.assertFalse(errors.called,errors.call_args_list)
