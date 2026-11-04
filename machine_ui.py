"""Machine creation tab with a left-hand configuration panel."""
import copy
import json
import math
import time
import tkinter as tk
from tkinter import filedialog, messagebox, ttk, colorchooser

from core import Catalog
from editors import field, select_names
from flow import prototype_image, scale_image
from machine_model import sprite_asset, validate_machine, importable_recipes, MACHINE_TYPES, ENERGY_SWITCH_TYPES, machine_kind, source_config, machine_source, zero_config, ZERO_SOURCE, editable_buildings, controlled_fields
from machine_geometry import dimensions, tint_preview
from project import identifier, png_asset, positive
from ui import HELP, help_label, scroll_form
from controls import sequence, BUTTONS

HELP.update({
    'Machine ID': 'Unique internal name for the building and its placeable item.',
    'Building template': 'Provides working animations, collision/selection boxes, pipe connections and sounds.',
    'Maximum health': 'Damage the building can take before it is destroyed.',
    'Crafting speed': 'Speed multiplier: 1 processes recipes at their base crafting time.',
    'Energy source': 'Choose electric for a power network, or burner to consume solid fuel. Energy controls take precedence over energy_source in the advanced JSON.',
    'Fuel categories': 'Comma-separated fuel categories accepted in burner mode. chemical accepts coal and wood; nuclear accepts nuclear fuel cells.',
    'Fuel inventory slots': 'Number of slots for fuel items in burner mode. Must be at least 1.',
    'Burnt fuel slots': 'Slots for spent fuel, such as used nuclear cells. Set 0 if the selected fuel has no burnt result.',
    'Power usage': 'Power consumed while working, such as 150kW or 1MW.',
    'Module slots': 'Number of module inventory slots, from 0 to 64. Effects follow the template.',
    'Icon PNG (optional)': 'Square item/inventory icon. Leave blank to use the template’s icon.',
    'Building PNG (optional)': 'PNG image or animation sprite sheet. Leave blank to keep the template’s animation.',
    'Placed width (tiles)': 'Actual width occupied on the map. Collision, selection, graphics and pipe positions resize with it.',
    'Placed height (tiles)': 'Actual height occupied on the map. Graphics keep their aspect ratio within this footprint.',
    'Sprite offset X (tiles)': 'Moves graphics horizontally relative to the collision box: positive is right, negative is left. Zero keeps the original position.',
    'Sprite offset Y (tiles)': 'Moves graphics vertically relative to the collision box: positive is down, negative is up. Supports decimals; 1 tile equals 32 game pixels. Collision, selection and connections stay fixed.',
    'Machine color': 'Hex tint applied to the building graphics, for example #88bbff. White keeps the original colors.',
    'Mining speed': 'Multiplier controlling how quickly this drill extracts resources.',
    'Mining radius': 'Distance from the drill center in which it searches for resources.',
    'Resource categories': 'Comma-separated resource categories this drill can mine, such as basic-solid.',
    'Resource drain (%)': 'Percentage of normal resource depletion. Zero preserves resources; 100 is normal.',
    'Allowed recipes': 'Only these recipes can be selected in this machine. Choose multiple entries in the searchable picker.',
})


def preview_animation_frame(elapsed, frame_count, speed, mode='forward'):
    """Sample the animation's phase on Factorio's normal 60-tick clock."""
    ticks = math.floor(max(0, elapsed) * 60 + 1e-9)
    advance = math.floor(ticks * speed + 1e-9)
    if mode == 'backward':
        return frame_count - 1 - advance % frame_count
    if mode == 'forward-then-backward' and frame_count > 1:
        position = advance % (2 * frame_count - 2)
        return position if position < frame_count else 2 * frame_count - 2 - position
    return advance % frame_count


class MachineTab(ttk.Frame):
    def __init__(self, app):
        super().__init__(app.tabs)
        self.app = app
        self.dirty = False
        self.saved_name = None
        self.assets = {}
        self.tinted_previews = {}
        self.animation_job = None
        self.preview_frame_index = 0
        self.play_animation = tk.BooleanVar(value=True)
        self.animation_status = tk.StringVar(value='Static preview')
        self.asset_paths = {}
        self.vars = {}
        self.ready = False
        self.last_state = None
        self.entity_type = 'assembling-machine'
        self.operation = 'create'
        self.item_name = None
        self.mode_text = tk.StringVar(value='CREATE A MACHINE — Select how to begin.')
        ttk.Label(self, textvariable=self.mode_text, foreground='#e9aa52', padding=12).pack(anchor='w')
        split = tk.PanedWindow(self, orient='horizontal', sashwidth=6, bg='#151b23', borderwidth=0)
        split.pack(fill='both', expand=True)
        left = ttk.Frame(split, width=480)
        split.add(left, width=480, minsize=370, stretch='never')
        footer = ttk.Frame(left, padding=10)
        footer.pack(side='bottom', fill='x')
        ttk.Button(footer, text='Save machine', command=self.save_changes).pack(side='right')
        notebook = ttk.Notebook(left)
        notebook.pack(fill='both', expand=True)
        details = ttk.Frame(notebook)
        advanced = ttk.Frame(notebook)
        notebook.add(details, text='Machine stats')
        notebook.add(advanced, text='All other stats (JSON)')
        body = scroll_form(details)
        body.compact_fields = True
        self.body = body
        self.field_rows = {}
        def add(label, key, default, parent=body):
            var, row, entry = field(parent, label, default)
            self.vars[key] = var
            self.field_rows[key] = (row, body.winfo_children()[-1], row.pack_info())
            return row, entry
        _, self.name_entry = add('Machine ID', 'name', '')
        add('Display name', 'title', '')
        add('Description', 'description', '')
        row, entry = add('Machine source', 'template', '')
        entry.destroy()
        self.source_display = tk.StringVar()
        ttk.Label(row, textvariable=self.source_display).pack(anchor='w')
        self.vars['template'].trace_add('write', lambda *_: self.source_display.set('From zero' if self.vars['template'].get() == ZERO_SOURCE else self.vars['template'].get()))
        add('Stack size', 'stack_size', 50)
        add('Maximum health', 'health', 400)
        self.speed_row, _ = add('Crafting speed', 'speed', 1)
        self.speed_help = body.winfo_children()[-1]
        row, entry = add('Energy source', 'energy_type', 'electric')
        entry.destroy()
        self.energy_choice = ttk.Combobox(row, textvariable=self.vars['energy_type'], values=['electric', 'burner'], state='readonly')
        self.energy_choice.pack(fill='x')
        add('Fuel categories', 'fuel_categories', 'chemical')
        add('Fuel inventory slots', 'fuel_inventory_size', 1)
        add('Burnt fuel slots', 'burnt_inventory_size', 1)
        add('Power usage', 'power', '150kW')
        add('Module slots', 'module_slots', 0)
        for label, key in [('Icon PNG (optional)', 'icon_path'), ('Building PNG (optional)', 'sprite_path')]:
            row, _ = add(label, key, '')
            ttk.Button(row, text='Browse…', command=lambda k=key: self.browse(k)).pack(side='right', padx=4)
        add('Frame width (pixels)', 'frame_width', 0)
        help_label(body, 'Width of one animation frame. Zero uses the full image width for a static image.', wraplength=335)
        add('Frame height (pixels)', 'frame_height', 0)
        help_label(body, 'Height of one frame. Zero uses the full image height. Frames are read left to right, then down.', wraplength=335)
        add('Animation frames', 'frame_count', 1)
        help_label(body, 'Total frames in the PNG sprite sheet. Use 1 for a static building.', wraplength=335)
        add('Frames per row', 'line_length', 1)
        help_label(body, 'Number of frame columns before playback continues on the next row.', wraplength=335)
        self.normalize_button = ttk.Button(body, text='Normalize sprite sheet…', command=self.normalize_sprite_sheet)
        self.normalize_button.pack(anchor='w', padx=16, pady=6)
        self.shading_button = ttk.Button(body, text='Shade machine surface…', command=lambda: self.normalize_sprite_sheet(shading=True))
        self.shading_button.pack(anchor='w', padx=16, pady=4)
        self.style_button = ttk.Button(body, text='Match game style…', command=lambda: self.normalize_sprite_sheet(style=True))
        self.style_button.pack(anchor='w', padx=16, pady=4)
        self.center_button = ttk.Button(body, text='Auto-center object…', command=lambda: self.normalize_sprite_sheet(center=True))
        self.center_button.pack(anchor='w', padx=16, pady=4)
        self.detect_frames_button = ttk.Button(body, text='Auto-detect frame size…', command=self.detect_sprite_frames)
        self.detect_frames_button.pack(anchor='w', padx=16, pady=4)
        self.shadow_button = ttk.Button(body, text='Create shadows…', command=self.create_shadows)
        self.shadow_button.pack(anchor='w', padx=16, pady=4)
        self.remove_shadow_button = ttk.Button(body, text='Remove generated shadows', command=self.remove_shadows)
        self.remove_shadow_button.pack(anchor='w', padx=16, pady=4)
        help_label(body, 'Generate shadow sprites from a fixed light on the left. Shadows cast horizontally to the right; choose only their length, then preview and apply.', wraplength=335)
        help_label(body, 'Paint a mask on frame 1: only painted regions animate; everything else is held fixed from frame 1. Preview and apply the normalized sheet without modifying the source file.', wraplength=335)
        add('Animation speed', 'animation_speed', 1)
        help_label(body, 'Playback multiplier: 1 is the normal Factorio rate, 0.5 is half speed.', wraplength=335)
        row, entry = add('Playback mode', 'run_mode', 'forward')
        entry.destroy()
        ttk.Combobox(row, textvariable=self.vars['run_mode'], values=['forward', 'backward', 'forward-then-backward'], state='readonly').pack(fill='x')
        help_label(body, 'Play frames forward, backward, or back and forth while the machine works.', wraplength=335)
        add('Placed width (tiles)', 'width', 3)
        add('Placed height (tiles)', 'height', 3)
        add('Visual scale', 'visual_scale', 1)
        help_label(body, 'Appearance only: 1 keeps the normal size, 2 doubles it, and 0.5 halves it. Collision, selection, footprint, and connection positions stay unchanged. Maximum 16.', wraplength=335)
        add('Sprite offset X (tiles)', 'sprite_offset_x', 0)
        add('Sprite offset Y (tiles)', 'sprite_offset_y', 0)
        row, _ = add('Machine color', 'color', '#ffffff')
        ttk.Button(row, text='Choose…', command=self.choose_color).pack(side='right', padx=4)
        self.resources_panel = ttk.Frame(body)
        self.resources_panel.compact_fields = True
        row, _ = add('Resource categories', 'resource_categories', 'basic-solid', parent=self.resources_panel)
        ttk.Button(row, text='Choose…', command=self.choose_resources).pack(side='right', padx=4)
        add('Mining radius', 'mining_radius', 2.49, parent=self.resources_panel)
        add('Resource drain (%)', 'resource_drain', 100, parent=self.resources_panel)
        self.recipes_panel = ttk.Frame(body)
        self.recipes_panel.pack(fill='x')
        self.vars['recipes'] = tk.StringVar(value='')
        self.vars['categories'] = tk.StringVar(value='')
        ttk.Button(self.recipes_panel, text='Choose recipe categories…', command=self.choose_categories).pack(anchor='w', padx=16)
        ttk.Label(self.recipes_panel, textvariable=self.vars['categories'], wraplength=335).pack(anchor='w', padx=16)
        help_label(self.recipes_panel, 'Selected categories allow all recipes in them, including custom categories created in the recipe editor. Leave empty to use only individually selected recipes.', wraplength=335)
        ttk.Label(self.recipes_panel, text='Allowed recipes', padding=(16, 12, 16, 4)).pack(anchor='w')
        row = ttk.Frame(self.recipes_panel)
        row.pack(fill='x', padx=16)
        ttk.Button(row, text='Choose…', command=self.choose_recipes).pack(side='left')
        ttk.Button(row, text='Import recipes', command=self.import_recipes_dialog).pack(side='left', padx=6)
        ttk.Button(self.recipes_panel, text='Remove all recipes', command=self.remove_all_recipes).pack(anchor='w', padx=16, pady=4)
        help_label(self.recipes_panel, 'Choose recipes individually or import the recipes supported by existing machines. Remove a recipe with its × in the list on the right.', wraplength=335)
        help_label(advanced, 'All remaining prototype stats are loaded here, including energy-source details, resistances, animations and sounds. Use valid JSON. Identity, size, speed and other basic fields are controlled by Machine stats.', wraplength=400)
        self.advanced_text = tk.Text(advanced, width=35, height=12, wrap='word', undo=True)
        advanced_scroll = ttk.Scrollbar(advanced, orient='vertical', command=self.advanced_text.yview)
        self.advanced_text.configure(yscrollcommand=advanced_scroll.set)
        advanced_scroll.pack(side='right', fill='y')
        self.advanced_text.pack(fill='both', expand=True)
        self.advanced_text.insert('1.0', '{}')
        self.advanced_text.edit_modified(False)
        def advanced_changed(*_):
            if self.advanced_text.edit_modified():
                self.mark('advanced-text')
                self.advanced_text.edit_modified(False)
        self.advanced_text.bind('<<Modified>>', advanced_changed)
        app.bind_text_undo(self.advanced_text)
        for var in self.vars.values():
            var.trace_add('write', self.mark)
        self.vars['template'].trace_add('write', lambda *_: self.preview())
        self.right = ttk.Frame(split, padding=16)
        split.add(self.right, minsize=280, stretch='always')
        ttk.Label(self.right, text='Building preview', font=('Segoe UI', 16, 'bold')).pack(anchor='w')
        self.preview_canvas = tk.Canvas(self.right, bg='#202936', height=210, highlightthickness=0)
        self.preview_canvas.pack(fill='x', pady=12)
        ttk.Checkbutton(self.right, text='Play animation preview', variable=self.play_animation, command=self.preview).pack(anchor='w')
        ttk.Label(self.right, textvariable=self.animation_status).pack(anchor='w')
        self.info = tk.StringVar()
        ttk.Label(self.right, textvariable=self.info, wraplength=550, justify='left').pack(anchor='w')
        self.list_heading = ttk.Label(self.right, text='Allowed recipes', font=('Segoe UI', 12, 'bold'), padding=(0, 18, 0, 6))
        self.list_heading.pack(anchor='w')
        self.recipe_list = ttk.Frame(self.right)
        self.recipe_list.pack(fill='both', expand=True)
        self.recipe_rows = scroll_form(self.recipe_list)
        self.rendered_recipes = None
        help_label(self.right, 'Saved machines remain in this project. Select one below to edit it later; all machines are included in Export mod file.', wraplength=550, padx=0)
        self.saved_choice = ttk.Combobox(self.right, state='readonly')
        self.saved_choice.pack(fill='x', pady=5)
        self.saved_choice.bind('<<ComboboxSelected>>', lambda e: self.load(self.saved_choice.get()))
        self.status = tk.StringVar(value='Fill in the left panel, choose recipes, then save the machine.')
        ttk.Label(self.right, textvariable=self.status, wraplength=550).pack(anchor='w', pady=6)
        self.refresh()
        self.dirty = False
        self.form_children = [(child, child.pack_info()) for child in self.winfo_children()]
        for child, _ in self.form_children:
            child.pack_forget()
        self.placeholder = ttk.Frame(self, padding=32)
        self.placeholder.pack(fill='both', expand=True)
        ttk.Label(self.placeholder, text='Create a machine from zero, edit a machine, or create a variant.', font=('Segoe UI', 14), wraplength=700).pack(anchor='w', pady=12)
        ttk.Button(self.placeholder, text='Choose how to begin…', command=self.open_start_dialog).pack(anchor='w')

    def mark(self, *_):
        if not self.ready:
            return
        if self.last_state and not self.app.undoing:
            key = _[0] if _ else None
            self.app.record_undo('Edit machine stats', self, self.last_state, coalesce=(id(self), key) if key else None)
        self.dirty = True
        if self in self.app.tabs.winfo_children():
            try:
                self.app.tabs.tab(self, text=(self.saved_name or 'Create machine') + ' *')
            except tk.TclError:
                pass
        if hasattr(self, 'recipe_list'):
            self.preview()
        self.last_state = self.snapshot()

    def snapshot(self):
        return {'values': {k: v.get() for k, v in self.vars.items()}, 'advanced': self.advanced_text.get('1.0', 'end-1c'),
                'saved_name': self.saved_name, 'entity_type': self.entity_type, 'operation': self.operation,
                'item_name': self.item_name, 'assets': copy.deepcopy(self.assets), 'asset_paths': dict(self.asset_paths),
                'dirty': self.dirty, 'mode': self.mode_text.get(), 'readonly': str(self.name_entry.cget('state'))}

    def restore(self, state):
        self.ready = False
        for key in ('saved_name', 'entity_type', 'operation', 'item_name', 'assets', 'asset_paths'):
            setattr(self, key, copy.deepcopy(state[key]))
        for key, value in state['values'].items():
            self.vars[key].set(value)
        self.advanced_text.delete('1.0', 'end')
        self.advanced_text.insert('1.0', state['advanced'])
        self.advanced_text.edit_modified(False)
        self.name_entry.configure(state=state['readonly'])
        self.mode_text.set(state['mode'])
        self.recipes_panel.pack_forget()
        self.resources_panel.pack_forget()
        if self.entity_type in MACHINE_TYPES:
            (self.resources_panel if self.entity_type == 'mining-drill' else self.recipes_panel).pack(fill='x')
        self.list_heading.configure(text='Resource categories' if self.entity_type == 'mining-drill' else 'Allowed recipes')
        self.speed_row.winfo_children()[0].configure(text='Mining speed' if self.entity_type == 'mining-drill' else 'Crafting speed')
        self.speed_help.configure(text=HELP['Mining speed'] if self.entity_type == 'mining-drill' else HELP['Crafting speed'])
        self.energy_choice.configure(values=list(dict.fromkeys(['electric', 'burner', self.vars['energy_type'].get()])))
        self.dirty = state['dirty']
        self.configure_building_fields()
        self.ready = True
        self.app.tabs.tab(self, text=(self.saved_name or 'Create machine') + (' *' if self.dirty else ''))
        self.preview()
        self.last_state = self.snapshot()

    def browse(self, key):
        path = filedialog.askopenfilename(title='Choose machine PNG', filetypes=[('PNG image', '*.png')])
        if path:
            self.vars[key].set(path)

    def choose_categories(self):
        select_names(self.app, 'Choose recipe categories',
                     [c for c in self.app.catalog.raw.get('recipe-category', {}) if not c.startswith('recipe-studio-')],
                     lambda names: self.vars['categories'].set(', '.join(dict.fromkeys(self.selected_categories() + list(names)))))

    def selected_categories(self):
        return [name.strip() for name in self.vars['categories'].get().split(',') if name.strip()]

    def remove_all_recipes(self):
        if not self.ready or (not self.selected_recipes() and not self.selected_categories()):
            return
        before = self.snapshot()
        self.ready = False
        self.vars['recipes'].set('')
        self.vars['categories'].set('')
        self.ready = True
        self.app.record_undo('Remove all machine recipes', self, before)
        self.dirty = True
        self.preview()
        self.last_state = self.snapshot()
        self.status.set('All recipes and recipe categories removed. Save machine to apply; Ctrl+Z restores them.')

    def choose_recipes(self):
        select_names(self.app, 'Choose recipes this building can craft', self.app.catalog.recipes, self.add_recipes)

    def add_recipes(self, names):
        self.vars['recipes'].set(', '.join(dict.fromkeys(self.selected_recipes() + list(names))))

    def remove_recipe(self, name):
        self.vars['recipes'].set(', '.join(r for r in self.selected_recipes() if r != name))

    def import_recipes_dialog(self):
        dialog = tk.Toplevel(self.app)
        dialog.title('Import recipes from machines')
        dialog.geometry('660x520')
        ttk.Label(dialog, text='Select one or more machines', padding=12, font=('Segoe UI', 13, 'bold')).pack(anchor='w')
        query = tk.StringVar()
        ttk.Entry(dialog, textvariable=query).pack(fill='x', padx=12)
        help_label(dialog, 'Filter existing machine names. Select multiple rows using Ctrl or Shift; Done imports the union of their craftable recipes.', wraplength=620, padx=12)
        choices = sorted((kind, name) for kind in ('assembling-machine', 'furnace', 'rocket-silo') for name in self.app.catalog.raw.get(kind, {}) if name != self.saved_name)
        listing = tk.Listbox(dialog, selectmode='extended', exportselection=False)
        listing.pack(fill='both', expand=True, padx=12, pady=8)
        matches = []
        selected = set()
        def remember():
            selected.difference_update(matches)
            selected.update(matches[i] for i in listing.curselection())
        def refresh(*_):
            remember()
            matches[:] = [key for key in choices if query.get().lower() in key[1].lower()]
            listing.delete(0, 'end')
            for index, (kind, name) in enumerate(matches):
                listing.insert('end', name + '  ·  ' + kind)
                if (kind, name) in selected:
                    listing.selection_set(index)
        query.trace_add('write', refresh)
        refresh()
        def done():
            remember()
            if not selected:
                messagebox.showinfo('Select machines', 'Select at least one machine.', parent=dialog)
                return
            imported = importable_recipes(self.app.catalog, selected)
            self.add_recipes(imported)
            self.status.set(f'Imported {len(imported)} recipes from {len(selected)} machines. Save machine to keep these changes.')
            dialog.destroy()
        ttk.Button(dialog, text='Done', command=done).pack(anchor='e', padx=12, pady=12)

    def selected_recipes(self):
        return [v.strip() for v in self.vars['recipes'].get().split(',') if v.strip()]

    def detect_sprite_frames(self):
        try:
            from sprite_shading import detect_frame_layout, repack_detected_sheet
            import re
            from sprite_shadows import png_alpha
            path = self.vars['sprite_path'].get().strip()
            asset = self.assets.get('sprite') if path == self.asset_paths.get('sprite') else sprite_asset(path) if path else None
            if not asset:
                raise ValueError('Choose a Building PNG / sprite sheet first.')
            image = tk.PhotoImage(master=self, data=asset['data'])
            width,height,alpha = png_alpha(image.data(format='png'))
            layout = detect_frame_layout(alpha,width,height)
            detail = ('No reliable transparent grid was found. This proposal treats the image as one frame. Enter dimensions manually if it is an animation sheet.' if layout['frame_count'] == 1 else 'Detected using transparent gaps. Check the proposal; internal gaps can be mistaken for frame boundaries.')
            if 'regions' in layout:
                detail += '\nUneven margins detected: applying will embed a repacked sheet with uniform cells. The original file is preserved. Regenerate any cast shadows afterward.'
            if not messagebox.askyesno('Detected frame layout', f"Frame size: {layout['width']} × {layout['height']} pixels\nFrames: {layout['frame_count']}\nFrames per row: {layout['line_length']}\n\n{detail}\n\nApply these settings?", parent=self):
                return
            before = self.snapshot()
            repacked = None
            if 'regions' in layout:
                ppm = image.data(format='ppm')
                header = re.match(rb'P6\s+\d+\s+\d+\s+255\s',ppm)
                if not header:
                    raise ValueError('Cannot read sprite colors.')
                repacked = repack_detected_sheet(ppm[header.end():],alpha,width,height,layout)
            self.ready = False
            if repacked:
                self.assets['sprite'] = repacked
                self.assets.pop('shadow',None)
                self.asset_paths['sprite'] = 'Detected sprite sheet (embedded)'
                self.vars['sprite_path'].set(self.asset_paths['sprite'])
            for key, source in (('frame_width','width'),('frame_height','height'),('frame_count','frame_count'),('line_length','line_length')):
                self.vars[key].set(str(layout[source]))
            self.ready = True
            self.app.record_undo('Auto-detect frame size',self,before)
            self.dirty = True
            self.app.tabs.tab(self,text=(self.saved_name or 'Create machine')+' *')
            self.preview(); self.last_state = self.snapshot()
        except (ValueError,OSError,tk.TclError) as exc:
            messagebox.showerror('Cannot detect frame size',str(exc),parent=self)

    def normalize_sprite_sheet(self, shading=False, style=False, center=False):
        try:
            from machine_model import animation_settings
            from sprite_sheet_editor import SpriteSheetEditor
            from sprite_shading import SurfaceShadingEditor
            path = self.vars['sprite_path'].get().strip()
            asset = self.assets.get('sprite') if path == self.asset_paths.get('sprite') else sprite_asset(path) if path else None
            if not asset:
                raise ValueError('Choose a Building PNG / sprite sheet first, then enter its frame dimensions and frame count.')
            config = {'sprite': asset}
            for key in ('frame_width', 'frame_height', 'frame_count', 'line_length'):
                config[key] = int(self.vars[key].get())
            config.update(animation_speed=float(self.vars['animation_speed'].get()), run_mode=self.vars['run_mode'].get())
            settings = animation_settings(config)
            def apply(normalized):
                before = self.snapshot()
                self.ready = False
                self.assets['sprite'] = normalized
                self.assets.pop('shadow', None)
                self.asset_paths['sprite'] = 'Centered sprite sheet (embedded)' if center else 'Style-matched sprite sheet (embedded)' if style else 'Shaded sprite sheet (embedded)' if shading else 'Normalized sprite sheet (embedded)'
                self.vars['sprite_path'].set(self.asset_paths['sprite'])
                self.ready = True
                self.dirty = True
                self.app.record_undo('Auto-center object' if center else 'Match game style' if style else 'Shade machine surface' if shading else 'Normalize sprite sheet', self, before)
                self.app.tabs.tab(self, text=(self.saved_name or 'Create machine') + ' *')
                self.preview()
                self.last_state = self.snapshot()
            if style or center:
                return SurfaceShadingEditor(self, asset, settings, apply, style=style, center=center)
            return (SurfaceShadingEditor if shading else SpriteSheetEditor)(self, asset, settings, apply)
        except (ValueError, OSError, tk.TclError) as exc:
            messagebox.showerror('Cannot center object' if center else 'Cannot match game style' if style else 'Cannot shade sprite sheet' if shading else 'Cannot normalize sprite sheet', str(exc), parent=self)
            return None

    def create_shadows(self):
        try:
            from machine_model import animation_settings
            from sprite_shadows import ShadowEditor
            path = self.vars['sprite_path'].get().strip()
            asset = self.assets.get('sprite') if path == self.asset_paths.get('sprite') else sprite_asset(path) if path else None
            if not asset:
                raise ValueError('Choose a Building PNG or animation sheet first, and set its frame dimensions and count.')
            config = {'sprite':asset, 'animation_speed':float(self.vars['animation_speed'].get()), 'run_mode':self.vars['run_mode'].get()}
            for key in ('frame_width','frame_height','frame_count','line_length'):
                config[key] = int(self.vars[key].get())
            settings = animation_settings(config)
            def apply(shadow):
                before = self.snapshot()
                self.assets['shadow'] = shadow
                self.app.record_undo('Create shadow sprites', self, before)
                self.dirty = True
                self.app.tabs.tab(self, text=(self.saved_name or 'Create machine') + ' *')
                self.preview(); self.last_state = self.snapshot()
            return ShadowEditor(self,asset,settings,apply)
        except (ValueError,OSError,tk.TclError) as exc:
            messagebox.showerror('Cannot create shadows',str(exc),parent=self)
            return None

    def remove_shadows(self):
        if self.assets.get('shadow'):
            before = self.snapshot()
            self.assets.pop('shadow',None)
            self.app.record_undo('Remove shadow sprites',self,before)
            self.dirty = True
            self.app.tabs.tab(self,text=(self.saved_name or 'Create machine')+' *')
            self.preview(); self.last_state = self.snapshot()

    def sprite_preview_position(self):
        try:
            width, height = float(self.vars['width'].get()), float(self.vars['height'].get())
            x, y = float(self.vars['sprite_offset_x'].get()), float(self.vars['sprite_offset_y'].get())
            if not all(math.isfinite(v) for v in (width, height, x, y)) or width <= 0 or height <= 0:
                return 115, 86
            tile = min(140 / width, 130 / height)
            return 115 + x * tile, 86 + y * tile
        except ValueError:
            return 115, 86

    def preview(self):
        if not hasattr(self, 'preview_canvas'):
            return
        source = self.app.base_raw.get(self.entity_type, {}).get(self.vars['template'].get(), {})
        image = prototype_image(self.app, source, 120, self.assets.get('icon'))
        if self.assets.get('sprite'):
            raw_image = tk.PhotoImage(master=self, data=self.assets['sprite']['data'])
            try:
                width = int(self.vars['frame_width'].get()) or raw_image.width()
                height = int(self.vars['frame_height'].get()) or raw_image.height()
                if 0 < width <= raw_image.width() and 0 < height <= raw_image.height():
                    frame = tk.PhotoImage(master=self, width=width, height=height)
                    frame.tk.call(frame, 'copy', raw_image, '-from', 0, 0, width, height)
                    raw_image = frame
            except (ValueError, tk.TclError):
                pass
            factor = min(170 / raw_image.width(), 130 / raw_image.height())
            image = scale_image(raw_image, max(1, int(raw_image.width() * factor)))
        color = self.vars['color'].get()
        if image and len(color) == 7 and color.startswith('#'):
            try:
                key = (self.entity_type, self.vars['template'].get(), color, self.assets.get('icon', {}).get('data'), self.assets.get('sprite', {}).get('data'))
                if key not in self.tinted_previews:
                    self.tinted_previews[key] = tint_preview(image, color)
                    if len(self.tinted_previews) > 8:
                        self.tinted_previews.pop(next(iter(self.tinted_previews)))
                image = self.tinted_previews[key]
            except (ValueError, tk.TclError):
                pass
        if image:
            try:
                visual_scale = float(self.vars['visual_scale'].get())
                if 0 < visual_scale <= 16 and visual_scale != 1:
                    image = scale_image(image, max(1, min(1024, round(image.width() * visual_scale))))
            except (ValueError, tk.TclError):
                pass
        self.preview_image = image
        c = self.preview_canvas
        c.delete('all')
        try:
            width, height = float(self.vars['width'].get()), float(self.vars['height'].get())
            if 0 < width <= 64 and 0 < height <= 64:
                tile = min(140 / width, 130 / height)
                left, top = 115 - width * tile / 2, 85 - height * tile / 2
                for x in range(int(width) + 1):
                    c.create_line(left + x * tile, top, left + x * tile, top + height * tile, fill='#526173')
                for y in range(int(height) + 1):
                    c.create_line(left, top + y * tile, left + width * tile, top + y * tile, fill='#526173')
        except ValueError:
            pass
        if image:
            c.create_image(*self.sprite_preview_position(), image=image, tags='machine-preview-image')
        c.create_text(115, 160, text=self.vars['title'].get() or self.vars['name'].get() or 'New machine', fill='#e6edf3', width=210, font=('Segoe UI', 12, 'bold'))
        boxes = source.get('fluid_boxes', [])
        if not isinstance(boxes, list):
            boxes = [v for v in boxes.values() if isinstance(v, dict)]
        boxes = list(boxes)
        for key, direction in [('input_fluid_box', 'input'), ('output_fluid_box', 'output')]:
            if source.get(key):
                boxes.append(dict(source[key], production_type=direction))
        geometry = source.get('selection_box', [[-1.5, -1.5], [1.5, 1.5]])
        self.info.set(f"Source: {'From zero' if self.vars['template'].get() == ZERO_SOURCE else self.vars['template'].get()} ({self.entity_type})\nPlaced footprint: {self.vars['width'].get()} × {self.vars['height'].get()} tiles\nVisual scale: {self.vars['visual_scale'].get()}× (appearance only)\nColor: {self.vars['color'].get()}\nFluid ports: {sum(b.get('production_type') in ('input', 'input-output') for b in boxes)} input, {sum(b.get('production_type') in ('output', 'input-output') for b in boxes)} output\nGraphics: {'custom PNG' if self.vars['sprite_path'].get() else 'add a building PNG' if self.vars['template'].get() == ZERO_SOURCE else 'source animation'}\nSize changes affect collision, selection, graphics and connection positions.")
        names = tuple(self.selected_recipes()) if self.entity_type != 'mining-drill' else tuple(v.strip() for v in self.vars['resource_categories'].get().split(',') if v.strip())
        if names != self.rendered_recipes:
            for child in self.recipe_rows.winfo_children():
                child.destroy()
            for name in names:
                row = ttk.Frame(self.recipe_rows)
                row.pack(fill='x', padx=6, pady=2)
                ttk.Button(row, text='×', width=2, style='Small.TButton', command=lambda n=name: self.remove_resource(n) if self.entity_type == 'mining-drill' else self.remove_recipe(n)).pack(side='right', padx=6)
                label = ttk.Label(row, text=name, wraplength=360)
                label.pack(side='left', fill='x', expand=True)
                if self.entity_type != 'mining-drill':
                    def recipe_menu(event, name=name):
                        from creations_ui import rename_recipe
                        if hasattr(self, 'context_menu'):
                            self.context_menu.destroy()
                        self.context_menu = tk.Menu(self, tearoff=False)
                        self.context_menu.add_command(label='Rename recipe', command=lambda: rename_recipe(self, name))
                        self.context_menu.tk_popup(event.x_root, event.y_root)
                    label.bind('<Button-%d>' % BUTTONS[self.app.controls['context_button']], recipe_menu)
                row.bind('<Configure>', lambda e, text=label: text.configure(wraplength=max(100, e.width - 45)))
            self.rendered_recipes = names
        self.start_animation_preview()

    def start_animation_preview(self):
        if self.animation_job is not None:
            self.after_cancel(self.animation_job)
            self.animation_job = None
        self.animation_status.set('Static preview')
        asset = self.assets.get('sprite')
        path = self.vars['sprite_path'].get().strip()
        try:
            if path and path != self.asset_paths.get('sprite'):
                asset = sprite_asset(path)
            if not asset:
                return
            from machine_model import animation_settings
            config = {'sprite': asset}
            for key in ('frame_width', 'frame_height', 'frame_count', 'line_length'):
                config[key] = int(self.vars[key].get())
            config['animation_speed'] = float(self.vars['animation_speed'].get())
            config['run_mode'] = self.vars['run_mode'].get()
            settings = animation_settings(config)
            sheet = tk.PhotoImage(master=self, data=asset['data'])
            from machine_model import matching_shadow
            try:
                shadow = matching_shadow(dict(config,shadow=self.assets.get('shadow')))
            except ValueError:
                shadow = None
            shadow_sheet = tk.PhotoImage(master=self,data=shadow['data']) if shadow else None
            count, columns = settings['frame_count'], settings['line_length']
            width, height = settings['width'], settings['height']
            scale = float(self.vars['visual_scale'].get())
            if not 0 < scale <= 16:
                return
            color = self.vars['color'].get()
            delay = max(16, min(250, round(1000 / (60 * settings['animation_speed']))))
        except (ValueError, OSError, tk.TclError):
            self.animation_status.set('Set valid sprite-sheet dimensions to preview animation.')
            return
        cache, shadow_cache = {}, {}
        signature = (asset['data'], width, height, count, columns, settings['animation_speed'], settings['run_mode'])
        if signature != getattr(self, 'preview_animation_signature', None):
            self.preview_elapsed = 0
        self.preview_animation_signature = signature
        last_time = time.monotonic()
        was_active = True
        def tick():
            nonlocal last_time, was_active
            self.animation_job = None
            now = time.monotonic()
            if str(self.app.tabs.select()) != str(self):
                last_time = now
                was_active = False
                self.animation_job = self.after(250, tick)
                return
            if was_active and self.play_animation.get():
                self.preview_elapsed += now - last_time
            last_time = now
            was_active = True
            frame_index = preview_animation_frame(self.preview_elapsed, count, settings['animation_speed'], settings['run_mode'])
            self.preview_frame_index = frame_index
            if frame_index not in cache:
                frame = tk.PhotoImage(master=self, width=width, height=height)
                x, y = frame_index % columns * width, frame_index // columns * height
                frame.tk.call(frame, 'copy', sheet, '-from', x, y, x + width, y + height)
                factor = min(170 / width, 130 / height) * scale
                image = scale_image(frame, max(1, min(1024, round(width * factor))))
                if color != '#ffffff':
                    image = tint_preview(image, color)
                if len(cache) >= 32:
                    cache.pop(next(iter(cache)))
                cache[frame_index] = image
            self.preview_image = cache[frame_index]
            if not self.preview_canvas.find_withtag('machine-preview-image'):
                self.preview_canvas.create_image(*self.sprite_preview_position(), image=self.preview_image, tags='machine-preview-image')
            else:
                self.preview_canvas.itemconfigure('machine-preview-image', image=self.preview_image)
                self.preview_canvas.coords('machine-preview-image', *self.sprite_preview_position())
            if shadow:
                factor = min(170/width,130/height)*scale
                if frame_index not in shadow_cache:
                    from sprite_sheet_editor import SheetNormalizer
                    sw,sh = shadow['frame_width'],shadow['frame_height']
                    shadow_frame = tk.PhotoImage(master=self,width=sw,height=sh)
                    sx,sy = frame_index%columns*sw,frame_index//columns*sh
                    SheetNormalizer.copy(shadow_frame,shadow_sheet,(sx,sy,sx+sw,sy+sh),(0,0))
                    if len(shadow_cache) >= 32:shadow_cache.pop(next(iter(shadow_cache)))
                    shadow_cache[frame_index] = scale_image(shadow_frame,max(1,min(2048,round(sw*factor))))
                self.preview_shadow_image = shadow_cache[frame_index]
                px,py = self.sprite_preview_position()
                position = (px+shadow['shift_pixels'][0]*factor,py+shadow['shift_pixels'][1]*factor)
                if not self.preview_canvas.find_withtag('machine-preview-shadow'):
                    self.preview_canvas.create_image(*position,image=self.preview_shadow_image,tags='machine-preview-shadow')
                else:
                    self.preview_canvas.itemconfigure('machine-preview-shadow',image=self.preview_shadow_image)
                    self.preview_canvas.coords('machine-preview-shadow',*position)
                self.preview_canvas.tag_lower('machine-preview-shadow','machine-preview-image')
            else:
                self.preview_canvas.delete('machine-preview-shadow')
            self.animation_status.set(f'Frame {frame_index + 1}/{count}' + (' — paused' if not self.play_animation.get() else ''))
            if count > 1 and self.play_animation.get():
                self.animation_job = self.after(delay, tick)
        tick()

    def destroy(self):
        if self.animation_job is not None:
            self.after_cancel(self.animation_job)
            self.animation_job = None
        super().destroy()

    def save_changes(self, quiet=False):
        if not self.ready:
            return True
        before = copy.deepcopy(self.app.project.data)
        state_before = self.snapshot()
        try:
            name = identifier(self.vars['name'].get().strip())
            if self.saved_name and name != self.saved_name:
                raise ValueError('Saved machine IDs cannot be renamed. Create a new machine instead.')
            if name in self.app.project.data['machines'] and name != self.saved_name:
                raise ValueError('That machine is already saved. Select it in the saved machines list to edit it.')
            machine = {'title': self.vars['title'].get().strip() or name.replace('-', ' ').title(), 'description': self.vars['description'].get(),
                       'template': self.vars['template'].get(), 'stack_size': positive(self.vars['stack_size'].get(), 'Stack size', True),
                       'health': positive(self.vars['health'].get(), 'Health', True), 'speed': positive(self.vars['speed'].get(), 'Crafting speed'),
                       'power': self.vars['power'].get().strip(), 'energy_type': self.vars['energy_type'].get(),
                       'fuel_categories': [c.strip() for c in self.vars['fuel_categories'].get().split(',') if c.strip()],
                       'fuel_inventory_size': int(self.vars['fuel_inventory_size'].get()), 'burnt_inventory_size': int(self.vars['burnt_inventory_size'].get()),
                       'module_slots': int(self.vars['module_slots'].get()), 'width': positive(self.vars['width'].get(), 'Placed width', True),
                       'height': positive(self.vars['height'].get(), 'Placed height', True), 'visual_scale': positive(self.vars['visual_scale'].get(), 'Visual scale'), 'color': self.vars['color'].get(),
                       'sprite_offset_x': float(self.vars['sprite_offset_x'].get()), 'sprite_offset_y': float(self.vars['sprite_offset_y'].get()),
                       'entity_type': self.entity_type, 'operation': self.operation, 'item_name': self.item_name,
                       'resource_categories': [v.strip() for v in self.vars['resource_categories'].get().split(',') if v.strip()],
                       'mining_radius': positive(self.vars['mining_radius'].get(), 'Mining radius'), 'resource_drain': int(self.vars['resource_drain'].get()),
                       'advanced': json.loads(self.advanced_text.get('1.0', 'end')),
                       'item_type': self.app.catalog.items.get(('item', self.item_name), {}).get('type', 'item'),
                       'recipes': self.selected_recipes() if self.entity_type in ('assembling-machine', 'furnace', 'rocket-silo') else [],
                       'categories': self.selected_categories() if self.entity_type in ('assembling-machine', 'furnace', 'rocket-silo') else []}
            for key in ('frame_width', 'frame_height', 'frame_count', 'line_length'):
                machine[key] = int(self.vars[key].get())
            if machine['frame_width'] < 0 or machine['frame_height'] < 0:
                raise ValueError('Frame dimensions must be zero or positive.')
            machine['animation_speed'] = positive(self.vars['animation_speed'].get(), 'Animation speed')
            machine['run_mode'] = self.vars['run_mode'].get()
            for key, loader in [('icon', png_asset), ('sprite', sprite_asset)]:
                path = self.vars[key + '_path'].get().strip()
                asset = self.assets.get(key) if path == self.asset_paths.get(key, '') else (loader(path) if path else None)
                if asset:
                    tk.PhotoImage(master=self, data=asset['data'])
                machine[key] = asset
                machine[key + '_path'] = path
            conversion = (before['machine_drafts'].get(name) or before['machines'].get(name) or {})
            machine['shadow'] = copy.deepcopy(self.assets.get('shadow'))
            if not all(math.isfinite(machine[key]) for key in ('sprite_offset_x', 'sprite_offset_y')):
                raise ValueError('Sprite offsets must be finite numbers in tiles.')
            if conversion.get('converted_item'):
                machine['converted_item'] = conversion['converted_item']
                machine['converted_original'] = copy.deepcopy(conversion['converted_original'])
                if not machine.get('sprite'):
                    self.app.project.data['machine_drafts'][name] = machine
                    self.app.persist()
                    self.app.record_undo('Save machine draft', self, state_before, before)
                    self.dirty = False
                    self.app.refresh_catalog()
                    self.status.set('Machine draft saved. Add its Building PNG in Suggested actions → Machines to complete the conversion.')
                    self.last_state = self.snapshot()
                    return True
            validate_machine(name, machine, Catalog(self.app.base_raw), self.app.project)
            import time
            machine['created_at'] = before['machines'].get(name, {}).get('created_at', time.time_ns())
            self.app.project.data['machines'][name] = machine
            if machine.get('converted_item'):
                self.app.project.data['machine_drafts'].pop(name, None)
                self.app.project.data['items'].pop(name, None)
            self.app.project.compile(Catalog(self.app.base_raw))
            self.app.persist()
            self.app.record_undo('Save machine', self, state_before, before)
            self.saved_name = name
            self.name_entry.configure(state='readonly')
            self.assets = {k: machine[k] for k in ('icon', 'sprite', 'shadow') if machine.get(k)}
            self.asset_paths = {k: machine[k + '_path'] for k in ('icon', 'sprite')}
            self.dirty = False
            self.app.tabs.tab(self, text=name)
            self.app.refresh_catalog()
            self.status.set('Machine saved. Export includes its building, placeable item and configured crafting/mining settings.')
            self.last_state = self.snapshot()
            return True
        except (ValueError, OSError, KeyError, TypeError, tk.TclError) as exc:
            self.app.project.data = before
            messagebox.showerror('Cannot save machine', str(exc), parent=self)
            return False

    def load(self, name):
        if self.dirty:
            answer = messagebox.askyesnocancel('Unsaved machine', 'Save changes before switching machines?', parent=self)
            if answer is None or (answer and not self.save_changes()):
                return
        if name is None:
            self.open_start_dialog()
            return
        machine = copy.deepcopy(self.app.project.data['machines'].get(name) or self.app.project.data['machine_drafts'][name])
        self.saved_name = name
        self.populate(machine, name, 'edit')

    def open_start_dialog(self):
        if hasattr(self, 'start_dialog') and self.start_dialog.winfo_exists():
            self.start_dialog.lift()
            return
        dialog = tk.Toplevel(self.app)
        self.start_dialog = dialog
        dialog.title('Create machine — choose how to begin')
        dialog.geometry('680x480')
        dialog.transient(self.app)
        ttk.Label(dialog, text='How would you like to begin?', padding=20, font=('Segoe UI', 16, 'bold')).pack(anchor='w')
        help_label(dialog, 'Create from zero starts a new crafting machine with basic defaults and your own building PNG or animation. Edit machine updates an existing machine. Create variant copies one into a new machine.', wraplength=620)
        def select(mode):
            if mode == 'create':
                self.saved_name = None
                self.populate(zero_config(), '', 'create')
                dialog.destroy()
                return
            for child in dialog.winfo_children():
                child.destroy()
            title = {'create': 'Choose template', 'edit': 'Edit machine', 'variant': 'Create variant'}[mode]
            ttk.Label(dialog, text=title, padding=16, font=('Segoe UI', 14, 'bold')).pack(anchor='w')
            query = tk.StringVar()
            ttk.Entry(dialog, textvariable=query).pack(fill='x', padx=16)
            help_label(dialog, 'Search loaded or saved machines by name. All loaded placeable buildings are included: boilers, steam engines, turbines, power buildings, belts, storage, and crafting machines.', wraplength=620)
            listing = tk.Listbox(dialog, exportselection=False)
            listing.pack(fill='both', expand=True, padx=16, pady=8)
            choices = editable_buildings(self.app.catalog)
            matches = []
            def refresh(*_):
                matches[:] = [key for key in choices if query.get().lower() in key[1].lower() or query.get().lower() in key[0]]
                listing.delete(0, 'end')
                for kind, name in matches:
                    listing.insert('end', name + '  ·  ' + kind)
            def done(*_):
                if not listing.curselection():
                    return
                kind, name = matches[listing.curselection()[0]]
                self.configure_source(kind, name, mode)
                dialog.destroy()
            query.trace_add('write', refresh)
            refresh()
            listing.bind('<Double-Button-%d>' % BUTTONS[self.app.controls['picker_button']], done)
            listing.bind(sequence(self.app.controls['picker_accept']), done)
            ttk.Button(dialog, text='Load selected machine', command=done).pack(anchor='e', padx=16, pady=12)
        for title, mode in [('Create from zero', 'create'), ('Edit machine', 'edit'), ('Create variant', 'variant')]:
            ttk.Button(dialog, text=title, command=lambda m=mode: select(m)).pack(fill='x', padx=20, pady=8)

    def configure_source(self, kind, name, mode='create'):
        if name in self.app.project.data['machines']:
            machine = copy.deepcopy(self.app.project.data['machines'][name])
        else:
            machine = source_config(kind, name, self.app.catalog)
            machine['operation'] = 'edit' if mode == 'edit' else 'create'
        if mode != 'edit':
            machine['operation'] = 'create'
            self.saved_name = None
            proposed = '' if mode == 'create' else name + '-variant'
            index = 2
            used = set(self.app.project.data['machines']) | {n for group in self.app.catalog.raw.values() for n in group}
            while proposed and proposed in used:
                proposed = name + '-variant-' + str(index)
                index += 1
        else:
            proposed = name
            self.saved_name = name if name in self.app.project.data['machines'] else None
        self.populate(machine, proposed, mode)

    def populate(self, machine, name, mode):
        self.ready = False
        self.entity_type = machine_kind(machine)
        self.operation = machine.get('operation', 'create')
        self.item_name = machine.get('item_name', name) if self.operation == 'edit' else None
        self.name_entry.configure(state='normal')
        source = machine_source(self.app.base_raw, machine)
        defaults = {'visual_scale': 1, 'frame_width': 0, 'frame_height': 0, 'frame_count': 1, 'line_length': 1, 'animation_speed': 1, 'run_mode': 'forward', 'width': round(dimensions(source)[0]), 'height': round(dimensions(source)[1]), 'color': '#ffffff',
                    'resource_categories': source.get('resource_categories', ['basic-solid']), 'mining_radius': source.get('resource_searching_radius', 2.49), 'resource_drain': source.get('resource_drain_rate_percent', 100)}
        defaults.update(sprite_offset_x=0, sprite_offset_y=0)
        energy=source.get('energy_source',{})
        defaults.update(fuel_categories=energy.get('fuel_categories',['chemical']),fuel_inventory_size=energy.get('fuel_inventory_size',1),burnt_inventory_size=energy.get('burnt_inventory_size',1))
        for key, var in self.vars.items():
            value = name if key == 'name' else machine.get(key, defaults.get(key, ''))
            if key in ('recipes', 'categories', 'fuel_categories'):
                value = ', '.join(machine.get(key, defaults.get(key, [])))
            if key == 'resource_categories':
                value = ', '.join(value)
            var.set(value)
        from machine_model import CONTROLLED
        advanced = machine.get('advanced', {k: v for k, v in source.items() if k not in controlled_fields(self.entity_type)})
        self.advanced_text.delete('1.0', 'end')
        self.advanced_text.insert('1.0', json.dumps(advanced, indent=2, ensure_ascii=False))
        self.advanced_text.edit_modified(False)
        self.assets = {k: machine[k] for k in ('icon', 'sprite', 'shadow') if machine.get(k)}
        self.asset_paths = {k: machine.get(k + '_path', '') for k in ('icon', 'sprite')}
        self.energy_choice.configure(values=list(dict.fromkeys(['electric', 'burner', machine['energy_type']])))
        self.name_entry.configure(state='readonly' if mode == 'edit' else 'normal')
        self.recipes_panel.pack_forget()
        self.resources_panel.pack_forget()
        if self.entity_type == 'mining-drill':
            self.resources_panel.pack(fill='x')
            self.list_heading.configure(text='Resource categories')
        elif self.entity_type in MACHINE_TYPES:
            self.recipes_panel.pack(fill='x')
            self.list_heading.configure(text='Allowed recipes')
        else:
            self.list_heading.configure(text='Building-specific stats are in All other stats (JSON)')
        self.configure_building_fields()
        self.speed_row.winfo_children()[0].configure(text='Mining speed' if self.entity_type == 'mining-drill' else 'Crafting speed')
        self.speed_help.configure(text=HELP['Mining speed'] if self.entity_type == 'mining-drill' else HELP['Crafting speed'])
        if self.placeholder.winfo_exists():
            self.placeholder.pack_forget()
        for child, options in self.form_children:
            child.pack(**options)
        self.ready = True
        self.dirty = False
        self.mode_text.set({'create': 'CREATE FROM ZERO — Set the stats, add a building PNG or animation, and choose recipes.', 'variant': 'CREATE VARIANT — Save a new machine with its own identity.', 'edit': 'EDIT MACHINE — Save changes to the selected machine.'}[mode])
        self.status.set('Mining drill loaded. Adjust its mining stats, footprint and color, then save.' if self.entity_type == 'mining-drill' else 'Source stats loaded. Adjust them and save the machine.')
        self.app.tabs.tab(self, text=name or 'Create machine')
        self.rendered_recipes = None
        self.preview()
        self.last_state = self.snapshot()

    def configure_building_fields(self):
        generic = self.entity_type not in MACHINE_TYPES
        self.normalize_button.configure(state='disabled' if generic else 'normal')
        self.shading_button.configure(state='disabled' if generic else 'normal')
        self.style_button.configure(state='disabled' if generic else 'normal')
        self.center_button.configure(state='disabled' if generic else 'normal')
        self.detect_frames_button.configure(state='disabled' if generic else 'normal')
        self.shadow_button.configure(state='disabled' if generic else 'normal')
        self.remove_shadow_button.configure(state='disabled' if generic else 'normal')
        for key in ('speed', 'power', 'energy_type', 'fuel_categories', 'fuel_inventory_size', 'burnt_inventory_size', 'module_slots', 'sprite_path', 'frame_width', 'frame_height', 'frame_count', 'line_length', 'animation_speed', 'run_mode'):
            row, help_text, options = self.field_rows[key]
            row.pack_forget()
            help_text.pack_forget()
            if not generic or (key in ('energy_type','fuel_categories','fuel_inventory_size','burnt_inventory_size') and self.entity_type in ENERGY_SWITCH_TYPES):
                row.pack(**options)
                help_text.pack(fill='x', padx=16)

    def choose_color(self):
        color = colorchooser.askcolor(color=self.vars['color'].get(), title='Machine color', parent=self.app)[1]
        if color:
            self.vars['color'].set(color)

    def choose_resources(self):
        def selected(names):
            old = [s.strip() for s in self.vars['resource_categories'].get().split(',') if s.strip()]
            self.vars['resource_categories'].set(', '.join(dict.fromkeys(old + names)))
        select_names(self.app, 'Choose mineable resource categories', self.app.catalog.raw.get('resource-category', {}), selected)

    def remove_resource(self, name):
        self.vars['resource_categories'].set(', '.join(v.strip() for v in self.vars['resource_categories'].get().split(',') if v.strip() and v.strip() != name))

    def refresh(self):
        self.saved_choice.configure(values=sorted(set(self.app.project.data['machines']) | set(self.app.project.data['machine_drafts'])))
        if self.saved_name and self.saved_name not in self.app.project.data['machines'] and self.saved_name not in self.app.project.data['machine_drafts']:
            self.saved_name = None
            self.ready = False
            self.dirty = False
            for child, _ in self.form_children:
                child.pack_forget()
            self.placeholder.pack(fill='both', expand=True)
            self.app.tabs.tab(self, text='Create machine')
        if self.saved_name:
            self.saved_choice.set(self.saved_name)
            if not self.dirty and self.saved_name in self.app.project.data['machines']:
                self.dirty = False
                self.app.tabs.tab(self, text=self.saved_name)
        self.preview()

    def close(self):
        if self.dirty:
            answer = messagebox.askyesnocancel('Close machine', 'Save machine changes before closing?', parent=self)
            if answer is None or (answer and not self.save_changes()):
                return
        if hasattr(self, 'start_dialog') and self.start_dialog.winfo_exists():
            self.start_dialog.destroy()
        self.destroy()
