"""Generate projected alpha shadow sheets without external image packages."""
import base64
import math
import struct
import zlib
from collections import deque
import queue
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox


def png_alpha(data):
    if data[:8] != b'\x89PNG\r\n\x1a\n':
        raise ValueError('Choose a valid PNG sprite sheet.')
    offset, compressed, palette_alpha = 8, bytearray(), b''
    while offset < len(data):
        length = struct.unpack('>I', data[offset:offset+4])[0]
        kind, chunk = data[offset+4:offset+8], data[offset+8:offset+8+length]
        if kind == b'IHDR':
            width, height, depth, color, _, _, interlace = struct.unpack('>IIBBBBB', chunk)
        elif kind == b'IDAT':
            compressed.extend(chunk)
        elif kind == b'tRNS':
            palette_alpha = chunk
        offset += length+12
    if depth != 8 or interlace:
        raise ValueError('Convert the sprite to an 8-bit non-interlaced PNG first.')
    channels = {0:1, 2:3, 3:1, 4:2, 6:4}.get(color)
    if channels is None:
        raise ValueError('Unsupported PNG color format.')
    decoded = zlib.decompress(compressed)
    stride, previous, result = width*channels, bytearray(width*channels), bytearray(width*height)
    if len(decoded) != (stride+1)*height:
        raise ValueError('Invalid PNG pixel data.')
    def paeth(a,b,c):
        p=a+b-c; distances=(abs(p-a),abs(p-b),abs(p-c))
        return (a,b,c)[distances.index(min(distances))]
    for y in range(height):
        filter_type = decoded[y*(stride+1)]
        row = bytearray(decoded[y*(stride+1)+1:(y+1)*(stride+1)])
        if filter_type not in range(5):
            raise ValueError('Invalid PNG filter.')
        if filter_type:
            for x in range(stride):
                a = row[x-channels] if x >= channels else 0
                b = previous[x]; c = previous[x-channels] if x >= channels else 0
                row[x] = (row[x] + (a if filter_type == 1 else b if filter_type == 2 else (a+b)//2 if filter_type == 3 else paeth(a,b,c))) & 255
        if color in (4,6):
            alpha = row[channels-1::channels]
        elif color == 3:
            alpha = bytes(palette_alpha[i] if i < len(palette_alpha) else 255 for i in row)
        elif color == 0 and len(palette_alpha) == 2:
            transparent = struct.unpack('>H',palette_alpha)[0]
            alpha = bytes(0 if value == transparent else 255 for value in row)
        elif color == 2 and len(palette_alpha) == 6:
            transparent = struct.unpack('>HHH',palette_alpha)
            alpha = bytes(0 if tuple(row[x:x+3]) == transparent else 255 for x in range(0,stride,3))
        else:
            alpha = b'\xff'*width
        result[y*width:(y+1)*width] = alpha
        previous = row
    return width, height, result


def alpha_png(width, height, alpha):
    def chunk(kind, data):
        return struct.pack('>I',len(data))+kind+data+struct.pack('>I',zlib.crc32(kind+data)&0xffffffff)
    # Grayscale+alpha: black luminance and the generated transparency.
    rows=bytearray((width*2+1)*height)
    for y in range(height):
        rows[y*(width*2+1)+2:(y+1)*(width*2+1):2] = alpha[y*width:(y+1)*width]
    return b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',width,height,8,4,0,0,0))+chunk(b'IDAT',zlib.compress(rows))+chunk(b'IEND',b'')


def blur_alpha(alpha, width, height, radius):
    if not radius:
        return alpha
    temporary, result = bytearray(len(alpha)), bytearray(len(alpha))
    size = 2*radius+1
    for y in range(height):
        total=sum(alpha[y*width:y*width+radius+1])
        for x in range(width):
            temporary[y*width+x] = total//size
            if x-radius >= 0:total -= alpha[y*width+x-radius]
            if x+radius+1 < width:total += alpha[y*width+x+radius+1]
    for x in range(width):
        total=sum(temporary[y*width+x] for y in range(min(radius+1,height)))
        for y in range(height):
            result[y*width+x] = total//size
            if y-radius >= 0:total -= temporary[(y-radius)*width+x]
            if y+radius+1 < height:total += temporary[(y+radius+1)*width+x]
    return result


def create_shadow_sheet(png, frame_width, frame_height, count, columns, slant=.6, flatten=.35, opacity=.45, softness=1):
    if not all(math.isfinite(v) for v in (slant,flatten,opacity)) or not -2 <= slant <= 2 or not .05 <= flatten <= 1 or not 0 < opacity <= 1 or not isinstance(softness,int) or not 0 <= softness <= 8:
        raise ValueError('Use shadow length −2 to 2, height 0.05 to 1, opacity 1–100%, and softness 0–8 pixels.')
    width,height,alpha = png_alpha(png)
    if min(frame_width,frame_height,count,columns) < 1 or min(count,columns)*frame_width > width or math.ceil(count/columns)*frame_height > height:
        raise ValueError('Frame settings do not fit the sprite sheet.')
    dx = abs(slant)*(frame_height-1)
    minimum_x = -dx if slant < 0 else 0
    cell_width = frame_width+math.ceil(dx)+softness*2
    cell_height = math.ceil((frame_height-1)*flatten)+1+softness*2
    output_width,output_height = min(count,columns)*cell_width, math.ceil(count/columns)*cell_height
    if max(output_width,output_height) > 8192:
        raise ValueError('The shadow sheet would exceed 8192 pixels. Reduce the shadow length or softness, or use smaller source frames.')
    output=bytearray(output_width*output_height)
    for frame in range(count):
        frame_alpha=bytearray(cell_width*cell_height)
        source_x,source_y=frame%columns*frame_width,frame//columns*frame_height
        for y in range(frame_height):
            target_y=math.floor(y*flatten)+softness
            shift=slant*(frame_height-1-y)-minimum_x+softness
            for x in range(frame_width):
                value=round(alpha[(source_y+y)*width+source_x+x]*opacity)
                if value:
                    index=target_y*cell_width+math.floor(x+shift)
                    frame_alpha[index]=max(frame_alpha[index],value)
        frame_alpha=blur_alpha(frame_alpha,cell_width,cell_height,softness)
        left,top=frame%columns*cell_width,frame//columns*cell_height
        for y in range(cell_height):
            output[(top+y)*output_width+left:(top+y)*output_width+left+cell_width]=frame_alpha[y*cell_width:(y+1)*cell_width]
    return {'data':base64.b64encode(alpha_png(output_width,output_height,output)).decode('ascii'),
            'width':output_width,'height':output_height,'frame_width':cell_width,'frame_height':cell_height,
            'shift_pixels':[minimum_x-softness+cell_width/2-frame_width/2,(frame_height-1)*(1-flatten)-softness+cell_height/2-frame_height/2],
            'parameters':dict(slant=slant,flatten=flatten,opacity=opacity,softness=softness)}


def create_horizontal_shadow_sheet(png, frame_width, frame_height, count, columns, length=.6):
    """Cast each alpha row straight right; the light is fixed on the left."""
    if not math.isfinite(length) or not 0 <= length <= 4:
        raise ValueError('Shadow length must be between 0 and 4 frame widths.')
    width,height,alpha=png_alpha(png)
    if min(frame_width,frame_height,count,columns) < 1 or min(count,columns)*frame_width > width or math.ceil(count/columns)*frame_height > height:
        raise ValueError('Frame settings do not fit the sprite sheet.')
    distance=round(length*frame_width)
    padding=1
    cell_width,cell_height=frame_width+distance+2*padding,frame_height+2*padding
    output_width,output_height=min(count,columns)*cell_width,math.ceil(count/columns)*cell_height
    if max(output_width,output_height)>8192:
        raise ValueError('The shadow sheet would exceed 8192 pixels. Reduce shadow length or use smaller source frames.')
    output=bytearray(output_width*output_height)
    for frame in range(count):
        frame_alpha=bytearray(cell_width*cell_height)
        sx,sy=frame%columns*frame_width,frame//columns*frame_height
        for y in range(frame_height):
            maximum=deque()
            for x in range(frame_width+distance):
                value=alpha[(sy+y)*width+sx+x] if x<frame_width else 0
                while maximum and maximum[-1][1]<=value:maximum.pop()
                maximum.append((x,value))
                while maximum[0][0]<x-distance:maximum.popleft()
                frame_alpha[(y+padding)*cell_width+x+padding]=round(maximum[0][1]*.45)
        frame_alpha=blur_alpha(frame_alpha,cell_width,cell_height,padding)
        left,top=frame%columns*cell_width,frame//columns*cell_height
        for y in range(cell_height):
            output[(top+y)*output_width+left:(top+y)*output_width+left+cell_width]=frame_alpha[y*cell_width:(y+1)*cell_width]
    return {'data':base64.b64encode(alpha_png(output_width,output_height,output)).decode('ascii'),
            'width':output_width,'height':output_height,'frame_width':cell_width,'frame_height':cell_height,
            'shift_pixels':[distance/2,0], 'parameters':{'length':length,'light_source':'left','direction':'right'}}


class ShadowEditor(tk.Toplevel):
    def __init__(self, owner, asset, settings, on_apply):
        super().__init__(owner.app)
        from editors import field
        from ui import help_label
        self.title('Create shadow sprites'); self.transient(owner.app); self.geometry('780x540')
        self.asset,self.settings,self.on_apply=asset,settings,on_apply
        self.sheet=tk.PhotoImage(master=self,data=asset['data'])
        self.png=self.sheet.tk.call(self.sheet,'data','-format','png')
        self.result,self.job,self.mailbox=None,None,queue.Queue()
        previous=owner.assets.get('shadow',{}).get('parameters',{})
        self.length,_,_=field(self,'Shadow length',previous.get('length',.6))
        help_label(self,'The light is fixed on the left. Shadows extend completely horizontally to the right, with no vertical shift. Length is measured in frame widths: 1 extends one frame width; use 0 to 4. Opacity and soft edges are automatic.',wraplength=700)
        self.canvas=tk.Canvas(self,width=700,height=280,bg='#c9ced4',highlightthickness=0)
        self.canvas.pack(fill='both',expand=True,padx=16,pady=8)
        self.status=tk.StringVar(value='Generate shadows for every animation frame, then preview and apply or export the PNG.')
        ttk.Label(self,textvariable=self.status,wraplength=720,padding=12).pack(fill='x')
        footer=ttk.Frame(self,padding=12);footer.pack(fill='x')
        self.generate_button=ttk.Button(footer,text='Generate preview',command=self.generate);self.generate_button.pack(side='left')
        self.apply_button=ttk.Button(footer,text='Apply shadows',command=self.apply,state='disabled');self.apply_button.pack(side='right')
        self.export_button=ttk.Button(footer,text='Export PNG…',command=self.export,state='disabled');self.export_button.pack(side='right',padx=8)
        ttk.Button(footer,text='Cancel',command=self.destroy).pack(side='right',padx=8)
        self.generate()

    def generate(self):
        if self.job is not None:return
        try:
            parameters=dict(length=float(self.length.get()))
        except ValueError:
            messagebox.showerror('Invalid shadow settings','Enter numeric shadow settings.',parent=self);return
        self.generate_button.configure(state='disabled');self.apply_button.configure(state='disabled');self.export_button.configure(state='disabled')
        self.status.set('Creating shadows for all frames…')
        def work():
            try:
                result=create_horizontal_shadow_sheet(self.png,self.settings['width'],self.settings['height'],self.settings['frame_count'],self.settings['line_length'],**parameters)
                from machine_model import sprite_layout_digest
                result['source_digest']=sprite_layout_digest(self.asset,self.settings)
                self.mailbox.put(result)
            except Exception as exc:self.mailbox.put(exc)
        threading.Thread(target=work,daemon=True).start()
        self.job=self.after(50,self.poll)

    def poll(self):
        self.job=None
        try:result=self.mailbox.get_nowait()
        except queue.Empty:
            self.job=self.after(50,self.poll);return
        self.generate_button.configure(state='normal')
        if isinstance(result,Exception):
            self.status.set('Could not create shadows.');messagebox.showerror('Cannot create shadows',str(result),parent=self);return
        self.result=result
        self.draw_preview()
        self.apply_button.configure(state='normal');self.export_button.configure(state='normal')
        self.status.set(f"Created {self.settings['frame_count']} shadow frames. Preview shows frame 1; the exported shadow animation stays synchronized with the building.")

    def draw_preview(self):
        from sprite_sheet_editor import SheetNormalizer
        from flow import scale_image
        width,height=self.settings['width'],self.settings['height']
        sw,sh=self.result['frame_width'],self.result['frame_height']
        dx,dy=self.result['shift_pixels']
        left,top=min(-width/2,dx-sw/2),min(-height/2,dy-sh/2)
        right,bottom=max(width/2,dx+sw/2),max(height/2,dy+sh/2)
        factor=min(650/(right-left),240/(bottom-top),4)
        x,y=350-(left+right)*factor/2,140-(top+bottom)*factor/2
        shadow_sheet=tk.PhotoImage(master=self,data=self.result['data'])
        sprite=tk.PhotoImage(master=self,width=width,height=height)
        shadow=tk.PhotoImage(master=self,width=sw,height=sh)
        SheetNormalizer.copy(sprite,self.sheet,(0,0,width,height),(0,0))
        SheetNormalizer.copy(shadow,shadow_sheet,(0,0,sw,sh),(0,0))
        self.preview_images=[scale_image(shadow,max(1,round(sw*factor))),scale_image(sprite,max(1,round(width*factor)))]
        self.canvas.delete('all')
        self.canvas.create_image(x+dx*factor,y+dy*factor,image=self.preview_images[0])
        self.canvas.create_image(x,y,image=self.preview_images[1])

    def apply(self):
        if self.result is not None:
            self.on_apply(self.result);self.destroy()

    def export(self):
        if self.result is None:return
        path=filedialog.asksaveasfilename(parent=self,title='Export shadow sprite sheet',initialfile='shadow-sprites.png',defaultextension='.png',filetypes=[('PNG image','*.png')])
        if path:
            try:
                from pathlib import Path
                Path(path).write_bytes(base64.b64decode(self.result['data']))
            except OSError as exc:messagebox.showerror('Cannot export shadows',str(exc),parent=self)

    def destroy(self):
        if self.job is not None:self.after_cancel(self.job)
        super().destroy()
