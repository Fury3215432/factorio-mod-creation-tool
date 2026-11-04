import json,tempfile
from pathlib import Path
import unittest
from unittest.mock import patch
from app import App
from machine_ui import preview_animation_frame
from core import Catalog
from installation import find_installation
from test_project import make_icon


class AnimationClock(unittest.TestCase):
    def test_phase_tracks_game_ticks_instead_of_callback_count(self):
        self.assertEqual(preview_animation_frame(.5,64,4),56)
        self.assertEqual(preview_animation_frame(10,64,4),32)
        self.assertEqual(preview_animation_frame(.2,64,.1),1)
        self.assertEqual(preview_animation_frame(0,4,1,'backward'),3)
        self.assertEqual(preview_animation_frame(1/60,4,1,'backward'),2)
        self.assertEqual([preview_animation_frame(t/60,4,1,'forward-then-backward') for t in range(7)], [0,1,2,3,2,1,0])
        self.assertEqual(preview_animation_frame(999,1,20),0)

@unittest.skipUnless(Path('.cache/test-catalog.json').exists(),'Requires catalog')
class AnimationPreview(unittest.TestCase):
    def test_play_pause_backwards_and_cleanup(self):
        work=Path(tempfile.mkdtemp(dir=Path('.cache').resolve()))
        with patch('tkinter.messagebox.askyesno',return_value=False):
            app=App(); app.withdraw(); self.addCleanup(app.destroy)
            app.autosave_path=work/'project.json'
            app.catalog=Catalog(json.loads(Path('.cache/test-catalog.json').read_text(encoding='utf-8')))
            app.root_path=find_installation() or Path('unconfigured-factorio-installation')
            app.mods_path=work/'mods'; app.mods_path.mkdir()
            app.setup_frame.destroy(); app.workspace()
            app.new_machine_tab(); app.update_idletasks()
            tab=app.nametowidget(app.tabs.select())
            from machine_model import zero_config
            tab.populate(zero_config(),'','create')
            tab.vars['sprite_path'].set(str(make_icon(work/'sheet.png')))
            tab.vars['frame_width'].set('16'); tab.vars['frame_height'].set('16')
            tab.vars['frame_count'].set('4'); tab.vars['line_length'].set('2')
            tab.vars['animation_speed'].set('0.1')
            tab.preview()
            self.assertIsNotNone(tab.animation_job)
            app.after(200, app.quit); app.mainloop()
            self.assertEqual(tab.preview_frame_index,1)
            tab.play_animation.set(False); tab.preview()
            self.assertIsNone(tab.animation_job)
            self.assertIn('paused',tab.animation_status.get())
            tab.vars['run_mode'].set('backward'); tab.preview()
            self.assertEqual(tab.preview_frame_index,3)
            tab.play_animation.set(True); tab.preview()
            # A delayed paint skips ahead to the correct phase at high speed,
            # instead of advancing just one frame or slowing the animation.
            tab.vars['frame_width'].set('1'); tab.vars['frame_height'].set('1')
            tab.vars['frame_count'].set('64'); tab.vars['line_length'].set('32')
            tab.vars['animation_speed'].set('4'); tab.vars['run_mode'].set('forward')
            now=[0.0]; callbacks=[]
            def schedule(delay, callback):
                callbacks.append(callback)
                return 'preview-test-timer'
            tab.preview_animation_signature=None
            with patch('machine_ui.time.monotonic',side_effect=lambda:now[0]), patch.object(tab,'after',side_effect=schedule):
                tab.start_animation_preview()
                self.assertEqual(tab.preview_frame_index,0)
                now[0]=.5; callbacks[-1]()
                self.assertEqual(tab.preview_frame_index,56)
                tab.play_animation.set(False); tab.start_animation_preview()
                self.assertEqual(tab.preview_frame_index,56)
                self.assertIsNone(tab.animation_job)
                tab.play_animation.set(True); tab.start_animation_preview()
                self.assertEqual(tab.preview_frame_index,56)
            # Return to normal scheduling to verify destruction cancels it.
            tab.preview()
            job=tab.animation_job
            self.assertIsNotNone(job)
            tab.destroy()
            self.assertIsNone(tab.animation_job)
            self.assertNotIn(job,app.tk.call('after','info'))
