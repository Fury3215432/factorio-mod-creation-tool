"""Brush masks that freeze a sprite sheet outside its animated region."""
import base64
import math
import time
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

from flow import scale_image


def paint_mask(mask, width, height, x, y, radius, value=1):
    radius = max(1, int(radius))
    for row in range(max(0, math.ceil(y-radius)), min(height, math.floor(y+radius)+1)):
        extent = math.sqrt(max(0, radius*radius-(row-y)**2))
        left, right = max(0, math.ceil(x-extent)), min(width, math.floor(x+extent)+1)
        if right > left:
            mask[row*width+left:row*width+right] = bytes([value])*(right-left)


def mask_rectangles(mask, width, height):
    """Merge equal horizontal runs vertically for fast native image copies."""
    active, result = {}, []
    for y in range(height):
        runs, x = set(), 0
        row = mask[y*width:(y+1)*width]
        while x < width:
            start = row.find(b'\x01', x)
            if start < 0:
                break
            x = row.find(b'\x00', start)
            if x < 0:
                x = width
            runs.add((start, x))
        for run in list(active):
            if run not in runs:
                result.append((*run, active.pop(run), y))
        for run in runs:
            active.setdefault(run, y)
    result.extend((*run, start, height) for run, start in active.items())
    return [(left, top, right, bottom) for left, right, top, bottom in result]


class SheetNormalizer:
    def __init__(self, sheet, width, height, count, columns, mask):
        if min(width, height, count, columns) < 1 or len(mask) != width*height:
            raise ValueError('Invalid frame dimensions or mask.')
        if min(count, columns)*width > sheet.width() or math.ceil(count/columns)*height > sheet.height():
            raise ValueError('The frames do not fit inside the sprite sheet.')
        self.sheet, self.width, self.height, self.count, self.columns = sheet, width, height, count, columns
        self.rectangles = mask_rectangles(mask, width, height)
        self.result = tk.PhotoImage(master=sheet.tk, width=sheet.width(), height=sheet.height())
        self.copy(self.result, sheet, (0, 0, sheet.width(), sheet.height()), (0, 0))

    @staticmethod
    def copy(destination, source, rectangle, position):
        destination.tk.call(destination, 'copy', source, '-from', *rectangle, '-to', *position, '-compositingrule', 'set')

    def step(self, index):
        if not 0 <= index < self.count:
            raise ValueError('Invalid animation frame.')
        if index == 0:
            return
        x, y = index % self.columns*self.width, index//self.columns*self.height
        self.copy(self.result, self.sheet, (0, 0, self.width, self.height), (x, y))
        for left, top, right, bottom in self.rectangles:
            self.copy(self.result, self.sheet, (x+left, y+top, x+right, y+bottom), (x+left, y+top))


class SpriteSheetEditor(tk.Toplevel):
    def __init__(self, owner, asset, settings, on_apply):
        super().__init__(owner.app)
        self.title('Normalize sprite sheet — paint animation mask')
        self.transient(owner.app)
        self.geometry(f'{min(1120,self.winfo_screenwidth()-80)}x{min(800,self.winfo_screenheight()-100)}')
        self.columnconfigure(0,weight=1)
        self.rowconfigure(2,weight=1)
        self.owner, self.settings, self.on_apply = owner, settings, on_apply
        self.sheet = tk.PhotoImage(master=self, data=asset['data'])
        self.width, self.height = settings['width'], settings['height']
        self.mask = bytearray(self.width*self.height)
        self.history, self.last_point, self.output = [], None, None
        self.render_job = self.normalize_job = self.play_job = None
        self.frame_index = 0
        self.tool, self.radius = tk.StringVar(value='Brush'), tk.IntVar(value=12)
        self.show_mask, self.playing = tk.BooleanVar(value=True), tk.BooleanVar(value=True)
        self.status = tk.StringVar(value='Paint the parts that should animate. Everything else will use frame 1 unchanged.')
        self.first = self.crop(self.sheet, 0)
        self.display_scale = min(440/self.width, 430/self.height, 4)
        self.first_display = self.display(self.first)
        toolbar = ttk.Frame(self, padding=12); toolbar.grid(row=0,column=0,sticky='ew')
        for tool in ('Brush', 'Eraser'):
            ttk.Radiobutton(toolbar, text=tool, variable=self.tool, value=tool).pack(side='left', padx=4)
        ttk.Label(toolbar, text='Brush radius (frame pixels)').pack(side='left', padx=(16, 4))
        ttk.Spinbox(toolbar, from_=1, to=256, textvariable=self.radius, width=6).pack(side='left')
        ttk.Button(toolbar, text='Undo stroke', command=self.undo_mask).pack(side='left', padx=8)
        ttk.Button(toolbar, text='Clear mask', command=lambda: self.fill_mask(0)).pack(side='left', padx=4)
        ttk.Button(toolbar, text='Select all', command=lambda: self.fill_mask(1)).pack(side='left', padx=4)
        # Keep all root children in grid; only the preview row consumes spare height.
        tips=ttk.Label(self,text='Paint on the first frame like a layer mask: painted pixels retain each frame’s original animation; unpainted pixels are copied exactly from frame 1. Brush radius is measured in source-frame pixels. Eraser removes painted regions. The source PNG is preserved.',style='Help.TLabel',wraplength=1050,padding=(12,0))
        tips.grid(row=1,column=0,sticky='ew')
        panels = ttk.Frame(self, padding=12); panels.grid(row=2,column=0,sticky='nsew')
        self.canvases = []
        for title in ('Frame 1 · paint mask here', 'Normalized animation preview'):
            panel = ttk.LabelFrame(panels, text=title, padding=8); panel.pack(side='left', fill='both', expand=True, padx=6)
            canvas = tk.Canvas(panel, width=1, height=1, bg='#273240', highlightthickness=0)
            canvas.pack(fill='both', expand=True)
            canvas.bind('<Configure>', lambda event: self.redraw())
            self.canvases.append(canvas)
        self.canvases[0].bind('<Button-1>', self.begin_stroke)
        self.canvases[0].bind('<B1-Motion>', self.continue_stroke)
        self.canvases[0].bind('<ButtonRelease-1>', self.end_stroke)
        options = ttk.Frame(self, padding=12); options.grid(row=3,column=0,sticky='ew')
        ttk.Checkbutton(options, text='Show mask', variable=self.show_mask, command=self.redraw).pack(side='left')
        ttk.Checkbutton(options, text='Play preview', variable=self.playing, command=self.play_preview).pack(side='left', padx=16)
        status_label=ttk.Label(self, textvariable=self.status, wraplength=1050, padding=12)
        status_label.grid(row=4,column=0,sticky='ew')
        footer = self.footer = ttk.Frame(self, padding=12); footer.grid(row=5,column=0,sticky='ew')
        ttk.Button(footer, text='Preview result', command=self.normalize).pack(side='left')
        self.apply_button = ttk.Button(footer, text='Apply to machine', command=self.apply, state='disabled'); self.apply_button.pack(side='right')
        self.export_button = ttk.Button(footer, text='Export PNG…', command=self.export, state='disabled'); self.export_button.pack(side='right', padx=8)
        ttk.Button(footer, text='Cancel', command=self.destroy).pack(side='right', padx=8)
        def resized(event):
            if event.widget is self:
                for label in (tips,status_label):
                    label.configure(wraplength=max(200,event.width-36))
        self.bind('<Configure>',resized,add='+')
        self.bind('<Control-z>', lambda event: (self.undo_mask(), 'break')[1])
        self.bind('<Escape>', lambda event: self.destroy())
        self.redraw()

    def crop(self, sheet, index):
        image = tk.PhotoImage(master=self, width=self.width, height=self.height)
        x, y = index % self.settings['line_length']*self.width, index//self.settings['line_length']*self.height
        SheetNormalizer.copy(image, sheet, (x, y, x+self.width, y+self.height), (0, 0))
        return image

    def display(self, image):
        return scale_image(image, max(1, round(self.width*self.display_scale)))

    def redraw(self):
        if self.render_job is not None:
            self.after_cancel(self.render_job)
        self.render_job = None
        if not self.canvases:
            return
        scale=self.display_scale
        if all(c.winfo_width()>24 and c.winfo_height()>24 for c in self.canvases):
            scale=min(4,min((c.winfo_width()-24)/self.width for c in self.canvases),
                      min((c.winfo_height()-24)/self.height for c in self.canvases))
        if abs(scale-self.display_scale)>.001:
            self.display_scale=scale
            self.first_display=self.display(self.first)
            if self.output is not None:
                self.preview_image=self.display(self.crop(self.output,self.frame_index))
        for index, canvas in enumerate(self.canvases):
            canvas.delete('all')
            for y in range(0, canvas.winfo_height(), 16):
                for x in range(0, canvas.winfo_width(), 16):
                    canvas.create_rectangle(x, y, x+16, y+16, fill='#343a43' if (x//16+y//16)%2 else '#454d58', outline='')
            image = self.first_display if index == 0 or self.output is None else self.preview_image
            canvas.create_image(12, 12, image=image, anchor='nw', tags='sprite')
        if self.show_mask.get():
            scale = self.first_display.width()/self.width
            for left, top, right, bottom in mask_rectangles(self.mask, self.width, self.height):
                self.canvases[0].create_rectangle(12+left*scale, 12+top*scale, 12+right*scale, 12+bottom*scale,
                                                fill='#f37b50', stipple='gray50', outline='', tags='mask')

    def remember(self):
        self.history.append(bytes(self.mask))
        while len(self.history) > 20 or sum(map(len, self.history)) > 32*1024*1024:
            self.history.pop(0)

    def invalidate(self):
        for attr in ('normalize_job', 'play_job'):
            if getattr(self, attr) is not None:
                self.after_cancel(getattr(self, attr)); setattr(self, attr, None)
        self.output = None
        self.apply_button.configure(state='disabled'); self.export_button.configure(state='disabled')
        if self.render_job is None:
            self.render_job = self.after(16, self.redraw)

    def begin_stroke(self, event):
        self.remember(); self.last_point = None
        self.continue_stroke(event)

    def continue_stroke(self, event):
        scale = self.first_display.width()/self.width
        point = ((event.x-12)/scale, (event.y-12)/scale)
        try:
            radius = max(1, min(256, int(self.radius.get())))
        except (ValueError, tk.TclError):
            return
        previous = self.last_point or point
        steps = max(1, math.ceil(math.dist(previous, point)/max(1, radius/2)))
        for step in range(1, steps+1):
            x, y = [previous[i]+(point[i]-previous[i])*step/steps for i in range(2)]
            paint_mask(self.mask, self.width, self.height, x, y, radius, self.tool.get() == 'Brush')
        self.last_point = point
        self.invalidate()

    def end_stroke(self, event):
        self.last_point = None

    def fill_mask(self, value):
        self.remember(); self.mask[:] = bytes([value])*len(self.mask)
        self.invalidate()

    def undo_mask(self):
        if self.history:
            self.mask[:] = self.history.pop(); self.invalidate()

    def normalize(self):
        self.invalidate()
        job = SheetNormalizer(self.sheet, self.width, self.height, self.settings['frame_count'], self.settings['line_length'], self.mask)
        index = 0
        def step():
            nonlocal index
            self.normalize_job = None
            job.step(index); index += 1
            self.status.set(f'Normalizing frame {index}/{job.count}…')
            if index < job.count:
                self.normalize_job = self.after(1, step)
            else:
                self.output = job.result
                self.preview_time = 0
                self.preview_image = self.display(self.crop(self.output, 0))
                self.apply_button.configure(state='normal'); self.export_button.configure(state='normal')
                self.status.set('Ready. Only painted regions animate; everything outside the mask matches frame 1. Apply to the machine or export a new PNG.')
                self.redraw(); self.play_preview()
        self.normalize_job = self.after(1, step)

    def play_preview(self):
        if self.play_job is not None:
            self.after_cancel(self.play_job); self.play_job = None
        if self.output is None:
            return
        from machine_ui import preview_animation_frame
        started = time.monotonic()
        elapsed = getattr(self, 'preview_time', 0)
        def tick():
            self.play_job = None
            self.preview_time = elapsed + time.monotonic()-started if self.playing.get() else elapsed
            index = preview_animation_frame(self.preview_time, self.settings['frame_count'], self.settings['animation_speed'], self.settings['run_mode'])
            if index != self.frame_index or not self.playing.get():
                self.preview_image = self.display(self.crop(self.output, index))
                self.canvases[1].itemconfigure('sprite', image=self.preview_image)
                self.frame_index = index
            if self.playing.get():
                self.play_job = self.after(16, tick)
        tick()

    def apply(self):
        if self.output is None:
            return
        data = self.output.tk.call(self.output, 'data', '-format', 'png')
        self.on_apply({'data': base64.b64encode(data).decode('ascii'), 'width': self.output.width(), 'height': self.output.height()})
        self.destroy()

    def export(self):
        if self.output is None:
            return
        path = filedialog.asksaveasfilename(parent=self, title='Export normalized sprite sheet', initialfile='normalized-sprite-sheet.png', defaultextension='.png', filetypes=[('PNG image', '*.png')])
        if path:
            try:
                self.output.write(path, format='png')
            except (OSError, tk.TclError) as exc:
                messagebox.showerror('Cannot export sprite sheet', str(exc), parent=self)

    def destroy(self):
        for attr in ('render_job', 'normalize_job', 'play_job'):
            job = getattr(self, attr, None)
            if job is not None:
                self.after_cancel(job)
        super().destroy()
