"""Bake approximate left-lit surface shading into custom machine sheets."""
import base64
import math
import queue
import re
import struct
import threading
import time
import zlib
import tkinter as tk
from tkinter import ttk, messagebox

from flow import scale_image
from sprite_shadows import png_alpha
from ui import help_label


def shade_sheet(rgb, alpha, width, height, settings, strength):
    """Use identical frame-local lighting, preserving every pixel's alpha."""
    if not math.isfinite(strength) or not 0 <= strength <= 1:
        raise ValueError('Shading strength must be between 0 and 100%.')
    fw, fh, count, columns = (settings[k] for k in ('width', 'height', 'frame_count', 'line_length'))
    if min(fw, fh, count, columns) <= 0 or columns*fw > width or math.ceil(count/columns)*fh > height:
        raise ValueError('Frame layout does not fit the sprite sheet.')
    if len(rgb) != width*height*3 or len(alpha) != width*height:
        raise ValueError('Invalid sprite pixel data.')
    pixels = bytearray(width*height*4)
    pixels[0::4], pixels[1::4], pixels[2::4], pixels[3::4] = rgb[0::3], rgb[1::3], rgb[2::3], alpha
    factors = [1-strength*x/max(1, fw-1) for x in range(fw)]
    for frame in range(count):
        left, top = frame % columns*fw, frame // columns*fh
        for y in range(top, top+fh):
            for x, factor in enumerate(factors):
                offset = (y*width+left+x)*4
                for channel in range(3):
                    pixels[offset+channel] = round(pixels[offset+channel]*factor)
    return rgba_png(width, height, pixels)


def rgba_png(width, height, pixels):
    def chunk(kind, data):
        return struct.pack('>I', len(data))+kind+data+struct.pack('>I', zlib.crc32(kind+data)&0xffffffff)
    rows = b''.join(b'\0'+pixels[y*width*4:(y+1)*width*4] for y in range(height))
    return b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR', struct.pack('>IIBBBBB', width, height, 8, 6, 0, 0, 0))+chunk(b'IDAT', zlib.compress(rows))+chunk(b'IEND', b'')


STYLE_DEFAULTS = dict(brightness=95, contrast=90, saturation=85, highlights=20, softness=15)


def detect_frame_layout(alpha, width, height, alpha_threshold=8):
    """Infer a regular grid only when transparent gutters separate cells."""
    def bands(values):
        runs, start = [], None
        for i, occupied in enumerate(values+[False]):
            if occupied and start is None:
                start = i
            elif not occupied and start is not None:
                runs.append((start, i)); start = None
        return runs
    def cell_size(runs, length):
        if len(runs) < 2:
            return length
        cell = length//len(runs)
        # Each band must fit its own equal-size cell, with consistent centers.
        centers = [(a+b)/2-i*cell for i, (a,b) in enumerate(runs)]
        if any(a < i*cell or b > (i+1)*cell for i,(a,b) in enumerate(runs)) or max(centers)-min(centers) > max(2, cell*.12):
            return length
        return cell
    if len(alpha) != width*height or min(width, height) < 1:
        raise ValueError('Invalid sprite pixel data.')
    columns = [False]*width; rows = [False]*height
    for y in range(height):
        for x in range(width):
            if alpha[y*width+x] >= alpha_threshold:
                columns[x] = rows[y] = True
    if not any(rows):
        raise ValueError('The sprite sheet is fully transparent.')
    xbands, ybands = bands(columns), bands(rows)
    fw, fh = cell_size(xbands,width), cell_size(ybands,height)
    def edges(runs, length):
        if len(runs) < 2:
            return [0,length]
        centers = [(a+b)/2 for a,b in runs]
        gaps = [b-a for a,b in zip(centers,centers[1:])]
        if max(gaps)-min(gaps) > max(3,sum(gaps)/len(gaps)*.15):
            return [0,length]
        return [0]+[(a[1]+b[0])//2 for a,b in zip(runs,runs[1:])]+[length]
    # Irregular outer margins cannot be expressed by equal frame dimensions.
    # Offer a repacked sheet rather than silently cutting across objects.
    xe = edges(xbands,width) if fw == width else list(range(0,width//fw*fw+1,fw))
    ye = edges(ybands,height) if fh == height else list(range(0,height//fh*fh+1,fh))
    if (fw == width and len(xe)>2) or (fh == height and len(ye)>2):
        regions=[(xe[x],ye[y],xe[x+1],ye[y+1]) for y in range(len(ye)-1) for x in range(len(xe)-1)]
        return dict(width=max(b-a for a,_,b,_ in regions),height=max(d-c for _,c,_,d in regions),frame_count=len(regions),line_length=len(xe)-1,regions=regions)
    per_row = width//fw
    last = max((y//fh)*per_row+x//fw for y in range((height//fh)*fh) for x in range(per_row*fw) if alpha[y*width+x] >= alpha_threshold)
    return dict(width=fw, height=fh, frame_count=last+1, line_length=per_row)


def repack_detected_sheet(rgb, alpha, width, height, layout):
    fw,fh,cols=layout['width'],layout['height'],layout['line_length']
    outw,outh=fw*cols,fh*math.ceil(layout['frame_count']/cols)
    pixels=bytearray(outw*outh*4)
    for frame,(left,top,right,bottom) in enumerate(layout['regions']):
        ox,oy=frame%cols*fw,frame//cols*fh
        for y in range(bottom-top):
            for x in range(right-left):
                source=(top+y)*width+left+x
                target=((oy+y)*outw+ox+x)*4
                pixels[target:target+4]=rgb[source*3:source*3+3]+bytes([alpha[source]])
    return dict(data=base64.b64encode(rgba_png(outw,outh,pixels)).decode('ascii'),width=outw,height=outh)


def alignment_shifts(rgb, alpha, width, settings, bounds, anchor='Outer housing'):
    """Match fixed housing instead of animated materials inside/below it."""
    fw,fh,count,cols=(settings[k] for k in ('width','height','frame_count','line_length'))
    l,t,r,b=bounds[0]
    step=max(1,math.ceil(math.sqrt((r-l+1)*(b-t+1)/350)))
    spanx,spany=r-l+1,b-t+1
    if anchor == 'Upper housing':
        top,bottom=t,t+max(1,spany//3)
    elif anchor == 'Lower body':
        top,bottom=t+spany//3,b+1
    else:
        top,bottom=t+spany//12,t+max(1,spany*3//4)
    samples=[(x,y,tuple(rgb[(y*width+x)*3:(y*width+x)*3+3]))
             for y in range(top,bottom,step) for x in range(l,r+1,step)
             if alpha[y*width+x]>=32 and (anchor!='Outer housing' or x<l+spanx*.28 or x>r-spanx*.28)]
    shifts=[(0,0)]
    for frame in range(1,count):
        ll,tt,rr,bb=bounds[frame]
        initial=(round((l+r-ll-rr)/2),t-tt)
        ox,oy=frame%cols*fw,frame//cols*fh
        def score(shift):
            dx,dy=shift
            error=0
            for x,y,color in samples:
                sx,sy=x-dx,y-dy
                if not (0<=sx<fw and 0<=sy<fh):
                    error+=255;continue
                index=(oy+sy)*width+ox+sx
                if alpha[index]<32:
                    error+=255;continue
                error+=min(180,sum(abs(rgb[index*3+c]-color[c]) for c in range(3))/3)
            return error/max(1,len(samples)) + .00001*(dx*dx+dy*dy)
        if not samples:
            shifts.append(initial);continue
        coarse=[(initial[0]+x,initial[1]+y) for y in range(-12,13,3) for x in range(-12,13,3)]
        best=min(coarse,key=score)
        shifts.append(min([(best[0]+x,best[1]+y) for y in range(-2,3) for x in range(-2,3)],key=score))
    return shifts


def center_sheet(rgb, alpha, width, height, settings, alpha_threshold=8, stabilize=False, anchor='Outer housing'):
    """Optionally align the body first, then center the combined bounds."""
    fw, fh, count, columns = (settings[k] for k in ('width','height','frame_count','line_length'))
    if min(fw,fh,count,columns) < 1 or min(count,columns)*fw > width or math.ceil(count/columns)*fh > height:
        raise ValueError('Frame layout does not fit the sprite sheet.')
    if len(rgb) != width*height*3 or len(alpha) != width*height:
        raise ValueError('Invalid sprite pixel data.')
    bounds=[]
    for frame in range(count):
        ox, oy = frame%columns*fw, frame//columns*fh
        left,top,right,bottom=fw,fh,-1,-1
        for y in range(fh):
            for x in range(fw):
                if alpha[(oy+y)*width+ox+x] >= alpha_threshold:
                    left=min(left,x); right=max(right,x); top=min(top,y); bottom=max(bottom,y)
        if right<left:
            raise ValueError(f'Frame {frame+1} is empty. Check frame dimensions and count.')
        bounds.append((left,top,right,bottom))
    shifts=alignment_shifts(rgb,alpha,width,settings,bounds,anchor) if stabilize else [(0,0)]*count
    left=min(box[0]+shift[0] for box,shift in zip(bounds,shifts))
    top=min(box[1]+shift[1] for box,shift in zip(bounds,shifts))
    right=max(box[2]+shift[0] for box,shift in zip(bounds,shifts))
    bottom=max(box[3]+shift[1] for box,shift in zip(bounds,shifts))
    if right-left+1>fw or bottom-top+1>fh:
        raise ValueError('Aligned frames need more transparent space. Check frame detection or enlarge the frame canvas before stabilizing.')
    dx, dy = (fw-(right-left+1))//2-left, (fh-(bottom-top+1))//2-top
    pixels = bytearray(width*height*4)
    pixels[0::4],pixels[1::4],pixels[2::4],pixels[3::4] = rgb[0::3],rgb[1::3],rgb[2::3],alpha
    for frame in range(count):
        ox, oy = frame%columns*fw, frame//columns*fh
        shiftx,shifty=dx+shifts[frame][0],dy+shifts[frame][1]
        for y in range(fh):
            start=((oy+y)*width+ox)*4
            pixels[start:start+fw*4] = b'\0'*(fw*4)
        for y in range(max(0,-shifty),min(fh,fh-shifty)):
            for x in range(max(0,-shiftx),min(fw,fw-shiftx)):
                source=(oy+y)*width+ox+x
                target=((oy+y+shifty)*width+ox+x+shiftx)*4
                pixels[target:target+4]=rgb[source*3:source*3+3]+bytes([alpha[source]])
    return rgba_png(width,height,pixels)


def match_style_sheet(rgb, alpha, width, height, settings, **options):
    """Conservative color/detail preset, frame-local and alpha preserving."""
    params = dict(STYLE_DEFAULTS, **options)
    for key, value in params.items():
        limit = 200 if key in ('brightness', 'contrast', 'saturation') else 100
        if not math.isfinite(value) or not 0 <= value <= limit:
            raise ValueError(f'{key.title()} must be between 0 and {limit}%.')
    # Reuse layout and pixel validation; neutral shading also initializes RGBA.
    fw, fh, count, columns = (settings[k] for k in ('width', 'height', 'frame_count', 'line_length'))
    if min(fw, fh, count, columns) <= 0 or columns*fw > width or math.ceil(count/columns)*fh > height:
        raise ValueError('Frame layout does not fit the sprite sheet.')
    if len(rgb) != width*height*3 or len(alpha) != width*height:
        raise ValueError('Invalid sprite pixel data.')
    pixels = bytearray(width*height*4)
    pixels[0::4], pixels[1::4], pixels[2::4], pixels[3::4] = rgb[0::3], rgb[1::3], rgb[2::3], alpha
    brightness, contrast, saturation, highlights, softness = (params[k]/100 for k in STYLE_DEFAULTS)
    for frame in range(count):
        left, top = frame % columns*fw, frame // columns*fh
        for y in range(top, top+fh):
            for x in range(left, left+fw):
                index = y*width+x
                color = list(rgb[index*3:index*3+3])
                if softness and alpha[index]:
                    neighbors = [(xx, yy) for xx, yy in ((x,y),(x-1,y),(x+1,y),(x,y-1),(x,y+1))
                                 if left <= xx < left+fw and top <= yy < top+fh]
                    weights = [(yy*width+xx, alpha[yy*width+xx]) for xx, yy in neighbors]
                    total = sum(weight for _, weight in weights)
                    color = [color[c]*(1-softness)+softness*sum(rgb[i*3+c]*weight for i, weight in weights)/total for c in range(3)]
                luminance = .2126*color[0]+.7152*color[1]+.0722*color[2]
                for channel in range(3):
                    value = luminance+(color[channel]-luminance)*saturation
                    value = ((value-127.5)*contrast+127.5)*brightness
                    value -= max(0, value-170)*highlights
                    pixels[index*4+channel] = round(max(0, min(255, value)))
    return rgba_png(width, height, pixels)


class SurfaceShadingEditor(tk.Toplevel):
    def __init__(self, owner, asset, settings, on_apply, style=False, center=False):
        super().__init__(owner.app)
        self.style = style
        self.center = center
        self.title('Auto-center object' if center else 'Match game style' if style else 'Shade machine surface')
        self.transient(owner.app)
        self.geometry('920x760' if style else '920x560' if center else '720x560')
        self.settings, self.on_apply, self.asset = settings, on_apply, asset
        self.source = tk.PhotoImage(master=self, data=asset['data'])
        ppm = self.source.data(format='ppm')
        header = re.match(rb'P6\s+(\d+)\s+(\d+)\s+255\s', ppm)
        if not header:
            self.destroy()
            raise ValueError('Cannot read sprite colors.')
        self.rgb = ppm[header.end():]
        self.width, self.height, self.alpha = png_alpha(self.source.data(format='png'))
        self.strength = tk.DoubleVar(self, value=35)
        self.stabilize = tk.BooleanVar(self,value=True)
        self.anchor = tk.StringVar(self,value='Outer housing')
        self.status = tk.StringVar(self, value='')
        self.output = None
        self.events = queue.Queue()
        self.job = None
        self.play_job = None
        self.busy = False
        if center:
            ttk.Label(self, text='Auto-center · original / centered preview').pack(padx=12,pady=12)
            ttk.Checkbutton(self,text='Stabilize sliding frames against frame 1',variable=self.stabilize).pack(pady=4)
            row=ttk.Frame(self);row.pack(pady=4)
            ttk.Label(row,text='Alignment reference').pack(side='left',padx=6)
            ttk.Combobox(row,textvariable=self.anchor,values=('Outer housing','Upper housing','Lower body'),state='readonly',width=22).pack(side='left')
            help_label(self, 'Outer housing aligns the side structure, ignoring the central conveyor and falling stones below it. Use Upper housing or Lower body if another area is stationary. This reference affects alignment only: all moving materials remain in the output. Disable stabilization for intentional whole-object motion. Apply centering, then save the machine; Ctrl+Z undoes it.', wraplength=860)
        elif style:
            ttk.Label(self, text='Match game style · original / adjusted preview').pack(padx=12, pady=12)
            help_label(self, 'A starting preset for softer detail, muted color and reduced highlights. Adjust to suit your asset; this does not reconstruct perspective or 3D lighting. Each preview starts from the original sheet. Applying preserves transparency and layout; Ctrl+Z undoes it.', wraplength=860)
            self.style_vars = {}
            explanations = dict(brightness='Overall lightness. 100 keeps the original level.', contrast='Difference between light and dark. Below 100 reduces harsh contrast.', saturation='Color intensity. Below 100 mutes vivid colors.', highlights='Reduces bright highlights without darkening the whole sprite equally.', softness='Blends neighboring pixels to soften excessive detail, within each frame only.')
            controls = ttk.Frame(self, padding=12); controls.pack(fill='x')
            for key, default in STYLE_DEFAULTS.items():
                row = ttk.Frame(controls); row.pack(fill='x', pady=2)
                ttk.Label(row, text=key.title()+' (%)', width=24).pack(side='left')
                variable = self.style_vars[key] = tk.DoubleVar(self, value=default)
                ttk.Spinbox(row, from_=0, to=200 if key in ('brightness','contrast','saturation') else 100, textvariable=variable, width=8).pack(side='left')
                help_label(controls, explanations[key], wraplength=850)
        else:
            ttk.Label(self, text='Light from the left · darker on the right').pack(padx=12, pady=12)
            help_label(self, 'Bakes approximate surface shading into every frame using the same left-to-right gradient. Transparency, frame layout and collision stay unchanged. This is a flat-image lighting effect, not 3D shading. Applying repeatedly adds more shading; use Ctrl+Z to undo.', wraplength=670)
            row = ttk.Frame(self, padding=12); row.pack(fill='x')
            ttk.Label(row, text='Shading strength (%)').pack(side='left')
            ttk.Spinbox(row, from_=0, to=100, textvariable=self.strength, width=8).pack(side='left', padx=8)
            help_label(self, 'Maximum darkening at the right edge of each frame. 0 preserves the original; 100 makes the right edge black.', wraplength=670)
        self.canvas = tk.Canvas(self, background='#526173', highlightthickness=0)
        self.canvas.pack(fill='both', expand=True, padx=12, pady=8)
        ttk.Label(self, textvariable=self.status).pack(padx=12)
        buttons = ttk.Frame(self, padding=12); buttons.pack(fill='x')
        self.generate_button = ttk.Button(buttons, text='Generate preview', command=self.generate)
        self.generate_button.pack(side='left')
        self.apply_button = ttk.Button(buttons, text='Apply centering' if center else 'Apply style' if style else 'Apply surface shading', command=self.apply, state='disabled')
        self.apply_button.pack(side='right')
        self.protocol('WM_DELETE_WINDOW', self.close)
        self.generate()

    def generate(self):
        if self.busy:
            return
        try:
            options = {key: float(var.get()) for key, var in self.style_vars.items()} if self.style else {}
            strength = float(self.strength.get())/100
            if not math.isfinite(strength) or not 0 <= strength <= 1:
                raise ValueError('Choose a strength from 0 to 100%.')
        except (ValueError, tk.TclError) as exc:
            messagebox.showerror('Invalid shading strength', str(exc), parent=self)
            return
        self.busy = True
        if self.play_job is not None:
            self.after_cancel(self.play_job)
            self.play_job=None
        stabilize = self.stabilize.get()
        anchor = self.anchor.get()
        self.output = None
        self.apply_button.configure(state='disabled')
        self.generate_button.configure(state='disabled')
        self.status.set('Processing all frames…')
        def work():
            try:
                self.events.put(center_sheet(self.rgb,self.alpha,self.width,self.height,self.settings,stabilize=stabilize,anchor=anchor) if self.center else match_style_sheet(self.rgb, self.alpha, self.width, self.height, self.settings, **options) if self.style else shade_sheet(self.rgb, self.alpha, self.width, self.height, self.settings, strength))
            except Exception as exc:
                self.events.put(exc)
        threading.Thread(target=work, daemon=True).start()
        self.job = self.after(30, self.poll)

    def poll(self):
        self.job = None
        try:
            result = self.events.get_nowait()
        except queue.Empty:
            self.job = self.after(30, self.poll)
            return
        self.busy = False
        self.generate_button.configure(state='normal')
        if isinstance(result, Exception):
            self.status.set(str(result))
            return
        self.output = result
        image = tk.PhotoImage(master=self, data=base64.b64encode(result))
        frame = tk.PhotoImage(master=self, width=self.settings['width'], height=self.settings['height'])
        frame.tk.call(frame, 'copy', image, '-from', 0, 0, frame.width(), frame.height())
        self.preview_image = scale_image(frame, max(1, round(frame.width()*min(400/frame.width(), 260/frame.height()))))
        self.canvas.delete('all')
        if self.style or self.center:
            original = tk.PhotoImage(master=self, width=frame.width(), height=frame.height())
            original.tk.call(original, 'copy', self.source, '-from', 0, 0, frame.width(), frame.height())
            self.original_preview = scale_image(original, self.preview_image.width())
            self.canvas.create_image(220, 140, image=self.original_preview)
            self.canvas.create_image(670, 140, image=self.preview_image)
        else:
            self.canvas.create_image(340, 140, image=self.preview_image)
        self.status.set('First frame preview. All frames will be processed. Regenerate after changing settings.')
        if self.center and self.settings['frame_count']>1:
            self.animate_comparison(image)
            self.status.set('Animated comparison: original left, stabilized result right. Apply centering, then save machine.')
        self.apply_button.configure(state='normal')

    def animate_comparison(self, result):
        from machine_ui import preview_animation_frame
        started=time.monotonic()
        cache={}
        fw,fh,count,cols=(self.settings[k] for k in ('width','height','frame_count','line_length'))
        def tick():
            self.play_job=None
            index=preview_animation_frame(time.monotonic()-started,count,self.settings.get('animation_speed',1),self.settings.get('run_mode','forward'))
            if index not in cache:
                images=[]
                for source in (self.source,result):
                    frame=tk.PhotoImage(master=self,width=fw,height=fh)
                    x,y=index%cols*fw,index//cols*fh
                    frame.tk.call(frame,'copy',source,'-from',x,y,x+fw,y+fh)
                    images.append(scale_image(frame,max(1,round(fw*min(400/fw,260/fh)))))
                if len(cache)>=32:cache.pop(next(iter(cache)))
                cache[index]=images
            self.original_preview,self.preview_image=cache[index]
            self.canvas.delete('all')
            self.canvas.create_image(220,140,image=self.original_preview)
            self.canvas.create_image(670,140,image=self.preview_image)
            self.play_job=self.after(33,tick)
        tick()

    def apply(self):
        if self.output is None or self.busy:
            return
        asset = dict(self.asset, data=base64.b64encode(self.output).decode('ascii'), width=self.width, height=self.height)
        self.on_apply(asset)
        self.close()

    def close(self):
        if self.job is not None:
            self.after_cancel(self.job)
        if self.play_job is not None:
            self.after_cancel(self.play_job)
        self.destroy()
