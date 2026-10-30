"""Shared canvas navigation and prototype images."""
import base64
import json
import math
import re
import tkinter as tk
import zipfile
from fractions import Fraction
from controls import BUTTONS, MODIFIERS


def select_event(owner):
    controls = getattr(owner.app, 'controls', {})
    return '<Button-%d>' % BUTTONS.get(controls.get('select_button', 'Left'), 1)


def bind_navigation(owner, redraw):
    canvas = owner.canvas
    controls = getattr(owner.app, 'controls', {})
    def wheel(event):
        if not event.delta:
            return 'break'
        if event.state & MODIFIERS.get(controls.get('zoom_modifier', 'Ctrl'), 4):
            steps = (1 if event.delta > 0 else -1) if abs(event.delta) < 120 else event.delta / 120
            zoom_at(owner, 1.15 ** steps, redraw, event.x, event.y)
        else:
            steps = max(1, round(abs(event.delta) / 120))
            canvas.yview_scroll(-steps if event.delta > 0 else steps, 'units')
        return 'break'
    canvas.bind('<MouseWheel>', wheel)
    for button in (1, 2, 3):
        canvas.unbind('<ButtonPress-%d>' % button)
        canvas.unbind('<ButtonRelease-%d>' % button)
        canvas.unbind('<B%d-Motion>' % button)
    owner.panning = False
    def pan_start(event):
        if canvas.find_withtag('current'):
            return
        owner.panning = True
        canvas.scan_mark(event.x, event.y)
        canvas.configure(cursor='fleur')
        return 'break'
    def pan_move(event):
        if owner.panning:
            canvas.scan_dragto(event.x, event.y, gain=1)
            return 'break'
    def pan_end(event):
        owner.panning = False
        canvas.configure(cursor='')
    context_button = BUTTONS.get(controls.get('context_button', 'Right'), 3)
    for button in {BUTTONS.get(controls.get('pan_button', 'Left'), 1), BUTTONS.get(controls.get('alternate_pan', 'Middle'), 2)}:
        canvas.bind('<ButtonPress-%d>' % button, pan_start)
        canvas.bind('<B%d-Motion>' % button, pan_move)
        canvas.bind('<ButtonRelease-%d>' % button, pan_end)
    if hasattr(owner, 'context'):
        canvas.bind('<ButtonPress-%d>' % context_button, owner.context)
    owner.pan_start, owner.pan_move, owner.pan_end = pan_start, pan_move, pan_end
    owner.wheel = wheel


def zoom_at(owner, factor, redraw, x=None, y=None):
    """Keep the point beneath the pointer fixed as the world scale changes."""
    c = owner.canvas
    old = owner.zoom
    new = min(2.5, max(0.25, old * factor))
    if math.isclose(old, new):
        return
    x = c.winfo_width() / 2 if x is None else x
    y = c.winfo_height() / 2 if y is None else y
    world_x, world_y = c.canvasx(x) / old, c.canvasy(y) / old
    owner.zoom = new
    prepare = getattr(owner, 'prepare_zoom', None)
    if prepare:
        prepare()
    else:
        redraw()
    region = [float(v) for v in c.cget('scrollregion').split()]
    if len(region) == 4:
        left, top, right, bottom = region
        c.xview_moveto((world_x * new - x - left) / max(1, right - left))
        c.yview_moveto((world_y * new - y - top) / max(1, bottom - top))
    if prepare:
        redraw()


def scale_image(image, size):
    size = max(1, int(size))
    shrink = max(1, image.width() // size)
    reduced = image.subsample(shrink) if shrink > 1 else image
    ratio = Fraction(size, reduced.width()).limit_denominator(8)
    return reduced.zoom(ratio.numerator).subsample(ratio.denominator)


def prototype_image(app, prototype, size, asset=None, cached_only=False):
    """Read game/mod PNGs and crop the first icon (including mipmapped sheets)."""
    if not hasattr(app, 'prototype_images'):
        app.prototype_images = {}
        app.prototype_sources = {}
    source = prototype.get('icon') or next(iter(prototype.get('icons', [])), {}).get('icon', '')
    icon_size = prototype.get('icon_size', 64)
    if not prototype.get('icon') and prototype.get('icons'):
        icon_size = prototype['icons'][0].get('icon_size', icon_size)
    token = ('asset', asset['data']) if asset else (source, icon_size)
    key = (token, int(size))
    if key in app.prototype_images:
        return app.prototype_images[key]
    if cached_only:
        return None
    try:
        if token not in app.prototype_sources:
            data = None
            if asset:
                data = base64.b64decode(asset['data'])
                icon_size = asset['size']
            else:
                match = re.match(r'^__([^/]+)__/(.+)$', source)
                if not match:
                    return None
                mod, relative = match.groups()
                builtin = app.root_path / 'data' / mod / relative
                if builtin.is_file():
                    data = builtin.read_bytes()
                else:
                    for path in app.mods_path.iterdir():
                        if path.is_dir() and (path / 'info.json').exists():
                            info = json.loads((path / 'info.json').read_text(encoding='utf-8-sig'))
                            if info['name'] == mod:
                                data = (path / relative).read_bytes()
                                break
                        elif path.suffix.lower() == '.zip':
                            with zipfile.ZipFile(path) as archive:
                                infos = [n for n in archive.namelist() if n.count('/') == 1 and n.endswith('/info.json')]
                                if infos and json.loads(archive.read(infos[0]).decode('utf-8-sig'))['name'] == mod:
                                    data = archive.read(infos[0].split('/')[0] + '/' + relative)
                                    break
            if not data:
                return None
            original = tk.PhotoImage(master=app, data=base64.b64encode(data))
            crop = tk.PhotoImage(master=app, width=min(icon_size, original.width()), height=min(icon_size, original.height()))
            crop.tk.call(str(crop), 'copy', str(original), '-from', 0, 0, crop.width(), crop.height())
            app.prototype_sources[token] = crop
        result = scale_image(app.prototype_sources[token], size)
        app.prototype_images[key] = result
        if len(app.prototype_images) > 1536:
            app.prototype_images.pop(next(iter(app.prototype_images)))
        return result
    except (OSError, ValueError, KeyError, zipfile.BadZipFile, tk.TclError):
        return None
