import base64
import tkinter as tk
import time
import unittest
from types import SimpleNamespace
from sprite_shading import shade_sheet, match_style_sheet, SurfaceShadingEditor
from sprite_shadows import png_alpha


class SurfaceShading(unittest.TestCase):
    def test_style_identity_alpha_frame_isolation_and_validation(self):
        root = tk.Tk(); root.withdraw(); self.addCleanup(root.destroy)
        settings = dict(width=2, height=1, frame_count=2, line_length=2)
        rgb = bytes([255,0,0]*2+[0,0,255]*2+[0,255,0])
        alpha = bytes([255,128,255,255,0])
        neutral = dict(brightness=100, contrast=100, saturation=100, highlights=0, softness=0)
        data = match_style_sheet(rgb, alpha, 5, 1, settings, **neutral)
        image = tk.PhotoImage(master=root, data=base64.b64encode(data))
        self.assertEqual(image.get(0,0), (255,0,0))
        self.assertEqual(bytes(png_alpha(data)[2]), alpha)
        data = match_style_sheet(rgb, alpha, 5, 1, settings, **dict(neutral, softness=100))
        image = tk.PhotoImage(master=root, data=base64.b64encode(data))
        self.assertEqual(image.get(1,0), (255,0,0))
        self.assertEqual(image.get(2,0), (0,0,255))
        self.assertEqual(image.get(4,0), (0,255,0))
        with self.assertRaises(ValueError):
            match_style_sheet(rgb, alpha, 5, 1, settings, brightness=float('nan'))

    def test_style_dialog_preview_apply(self):
        root = tk.Tk(); root.withdraw(); self.addCleanup(root.destroy)
        image = tk.PhotoImage(master=root, width=2, height=2)
        image.put('white', to=(0,0,2,2))
        applied = []
        editor = SurfaceShadingEditor(SimpleNamespace(app=root), dict(data=base64.b64encode(image.data(format='png')).decode()), dict(width=2,height=2,frame_count=1,line_length=1), applied.append, style=True)
        deadline = time.monotonic()+5
        while editor.output is None and time.monotonic() < deadline:
            root.update(); time.sleep(.01)
        self.assertIsNotNone(editor.output)
        self.assertTrue(hasattr(editor, 'original_preview'))
        editor.apply()
        self.assertEqual(len(applied), 1)

    def test_frame_local_shading_and_alpha(self):
        root = tk.Tk(); root.withdraw(); self.addCleanup(root.destroy)
        settings = dict(width=3, height=2, frame_count=2, line_length=2)
        alpha = bytes([0, 64, 128, 255, 128, 64, 255]*2)
        rgb = bytes([200, 100, 50])*14
        data = shade_sheet(rgb, alpha, 7, 2, settings, .5)
        self.assertEqual(bytes(png_alpha(data)[2]), alpha)
        image = tk.PhotoImage(master=root, data=base64.b64encode(data))
        self.assertEqual(image.get(0, 0), (200, 100, 50))
        self.assertEqual(image.get(2, 0), (100, 50, 25))
        self.assertEqual(image.get(5, 0), image.get(2, 0))
        self.assertEqual(image.get(6, 0), (200, 100, 50))
        for strength in (-1, 2, float('nan')):
            with self.assertRaises(ValueError):
                shade_sheet(rgb, alpha, 7, 2, settings, strength)

    def test_dialog_generates_and_applies_embedded_sheet(self):
        root = tk.Tk(); root.withdraw(); self.addCleanup(root.destroy)
        sheet = tk.PhotoImage(master=root, width=6, height=2)
        sheet.put('#c86432', to=(0, 0, 6, 2))
        sheet.transparency_set(0, 0, True)
        asset = dict(data=base64.b64encode(sheet.data(format='png')).decode(), width=6, height=2)
        settings = dict(width=3, height=2, frame_count=2, line_length=2)
        applied = []
        editor = SurfaceShadingEditor(SimpleNamespace(app=root), asset, settings, applied.append)
        deadline = time.monotonic()+5
        while editor.output is None and time.monotonic() < deadline:
            root.update(); time.sleep(.01)
        self.assertIsNotNone(editor.output)
        editor.apply()
        self.assertEqual(len(applied), 1)
        result = tk.PhotoImage(master=root, data=applied[0]['data'])
        self.assertTrue(result.transparency_get(0, 0))
        self.assertLess(result.get(2, 0)[0], result.get(1, 0)[0])
        self.assertEqual(result.get(2, 0), result.get(5, 0))
