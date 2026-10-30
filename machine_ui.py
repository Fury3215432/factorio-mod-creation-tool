"""Machine creation tab with a left-hand configuration panel."""
import copy
import json
import tkinter as tk
from tkinter import filedialog, messagebox, ttk, colorchooser

from core import Catalog
from editors import field, select_names
from flow import prototype_image, scale_image
from machine_model import sprite_asset, validate_machine, importable_recipes, MACHINE_TYPES, machine_kind, source_config
from machine_geometry import dimensions, tint_preview
from project import identifier, png_asset, positive
from ui import HELP, help_label, scroll_form
from controls import sequence, BUTTONS

HELP.update({
    'Machine ID': 'Unique internal name for the building and its placeable item.',
    'Building template': 'Provides working animations, collision/selection boxes, pipe connections and sounds.',
    'Maximum health': 'Damage the building can take before it is destroyed.',
    'Crafting speed': 'Speed multiplier: 1 processes recipes at their base crafting time.',
    'Energy source': 'Electric machines need a power network. Burner machines consume chemical fuel.',
    'Power usage': 'Power consumed while working, such as 150kW or 1MW.',
    'Module slots': 'Number of module inventory slots, from 0 to 64. Effects follow the template.',
    'Icon PNG (optional)': 'Square item/inventory icon. Leave blank to use the template’s icon.',
    'Building PNG (optional)': 'Optional single-frame building image. Leave blank to keep the template’s animation.',
    'Placed width (tiles)': 'Actual width occupied on the map. Collision, selection, graphics and pipe positions resize with it.',
    'Placed height (tiles)': 'Actual height occupied on the map. Graphics keep their aspect ratio within this footprint.',
    'Machine color': 'Hex tint applied to the building graphics, for example #88bbff. White keeps the original colors.',
    'Mining speed': 'Multiplier controlling how quickly this drill extracts resources.',
    'Mining radius': 'Distance from the drill center in which it searches for resources.',
    'Resource categories': 'Comma-separated resource categories this drill can mine, such as basic-solid.',
    'Resource drain (%)': 'Percentage of normal resource depletion. Zero preserves resources; 100 is normal.',
    'Allowed recipes': 'Only these recipes can be selected in this machine. Choose multiple entries in the searchable picker.',
})


class MachineTab(ttk.Frame):
    def __init__(self, app):
        super().__init__(app.tabs)
        self.app = app
        self.dirty = False
        self.saved_name = None
        self.assets = {}
        self.tinted_previews = {}
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
        def add(label, key, default, parent=body):
            var, row, entry = field(parent, label, default)
            self.vars[key] = var
            return row, entry
        _, self.name_entry = add('Machine ID', 'name', '')
        add('Display name', 'title', '')
        add('Description', 'description', '')
        row, entry = add('Building template', 'template', '')
        entry.configure(state='readonly')
        add('Stack size', 'stack_size', 50)
        add('Maximum health', 'health', 400)
        self.speed_row, _ = add('Crafting speed', 'speed', 1)
        self.speed_help = body.winfo_children()[-1]
        row, entry = add('Energy source', 'energy_type', 'electric')
        entry.destroy()
        self.energy_choice = ttk.Combobox(row, textvariable=self.vars['energy_type'], values=['electric', 'burner'], state='readonly')
        self.energy_choice.pack(fill='x')
        add('Power usage', 'power', '150kW')
        add('Module slots', 'module_slots', 0)
        for label, key in [('Icon PNG (optional)', 'icon_path'), ('Building PNG (optional)', 'sprite_path')]:
            row, _ = add(label, key, '')
            ttk.Button(row, text='Browse…', command=lambda k=key: self.browse(k)).pack(side='right', padx=4)
        add('Placed width (tiles)', 'width', 3)
        add('Placed height (tiles)', 'height', 3)
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
        ttk.Label(self.recipes_panel, text='Allowed recipes', padding=(16, 12, 16, 4)).pack(anchor='w')
        row = ttk.Frame(self.recipes_panel)
        row.pack(fill='x', padx=16)
        ttk.Button(row, text='Choose…', command=self.choose_recipes).pack(side='left')
        ttk.Button(row, text='Import recipes', command=self.import_recipes_dialog).pack(side='left', padx=6)
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
        ttk.Label(self.placeholder, text='Choose a template, edit a machine, or create a variant to load its stats.', font=('Segoe UI', 14), wraplength=700).pack(anchor='w', pady=12)
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
        (self.resources_panel if self.entity_type == 'mining-drill' else self.recipes_panel).pack(fill='x')
        self.list_heading.configure(text='Resource categories' if self.entity_type == 'mining-drill' else 'Allowed recipes')
        self.speed_row.winfo_children()[0].configure(text='Mining speed' if self.entity_type == 'mining-drill' else 'Crafting speed')
        self.speed_help.configure(text=HELP['Mining speed'] if self.entity_type == 'mining-drill' else HELP['Crafting speed'])
        self.energy_choice.configure(values=list(dict.fromkeys(['electric', 'burner', self.vars['energy_type'].get()])))
        self.dirty = state['dirty']
        self.ready = True
        self.app.tabs.tab(self, text=(self.saved_name or 'Create machine') + (' *' if self.dirty else ''))
        self.preview()
        self.last_state = self.snapshot()

    def browse(self, key):
        path = filedialog.askopenfilename(title='Choose machine PNG', filetypes=[('PNG image', '*.png')])
        if path:
            self.vars[key].set(path)

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

    def preview(self):
        if not hasattr(self, 'preview_canvas'):
            return
        source = self.app.base_raw.get(self.entity_type, {}).get(self.vars['template'].get(), {})
        image = prototype_image(self.app, source, 120, self.assets.get('icon'))
        if self.assets.get('sprite'):
            raw_image = tk.PhotoImage(master=self, data=self.assets['sprite']['data'])
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
            c.create_image(115, 86, image=image)
        c.create_text(115, 160, text=self.vars['title'].get() or self.vars['name'].get() or 'New machine', fill='#e6edf3', width=210, font=('Segoe UI', 12, 'bold'))
        boxes = source.get('fluid_boxes', [])
        if not isinstance(boxes, list):
            boxes = [v for v in boxes.values() if isinstance(v, dict)]
        boxes = list(boxes)
        for key, direction in [('input_fluid_box', 'input'), ('output_fluid_box', 'output')]:
            if source.get(key):
                boxes.append(dict(source[key], production_type=direction))
        geometry = source.get('selection_box', [[-1.5, -1.5], [1.5, 1.5]])
        self.info.set(f"Source: {self.vars['template'].get()} ({self.entity_type})\nPlaced footprint: {self.vars['width'].get()} × {self.vars['height'].get()} tiles\nColor: {self.vars['color'].get()}\nFluid ports: {sum(b.get('production_type') in ('input', 'input-output') for b in boxes)} input, {sum(b.get('production_type') in ('output', 'input-output') for b in boxes)} output\nGraphics: {'custom PNG' if self.vars['sprite_path'].get() else 'source animation'}\nSize changes affect collision, selection, graphics and connection positions.")
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
                row.bind('<Configure>', lambda e, text=label: text.configure(wraplength=max(100, e.width - 45)))
            self.rendered_recipes = names

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
                       'module_slots': int(self.vars['module_slots'].get()), 'width': positive(self.vars['width'].get(), 'Placed width', True),
                       'height': positive(self.vars['height'].get(), 'Placed height', True), 'color': self.vars['color'].get(),
                       'entity_type': self.entity_type, 'operation': self.operation, 'item_name': self.item_name,
                       'resource_categories': [v.strip() for v in self.vars['resource_categories'].get().split(',') if v.strip()],
                       'mining_radius': positive(self.vars['mining_radius'].get(), 'Mining radius'), 'resource_drain': int(self.vars['resource_drain'].get()),
                       'advanced': json.loads(self.advanced_text.get('1.0', 'end')),
                       'recipes': self.selected_recipes() if self.entity_type != 'mining-drill' else []}
            for key, loader in [('icon', png_asset), ('sprite', sprite_asset)]:
                path = self.vars[key + '_path'].get().strip()
                asset = self.assets.get(key) if path and path == self.asset_paths.get(key) else (loader(path) if path else None)
                if asset:
                    tk.PhotoImage(master=self, data=asset['data'])
                machine[key] = asset
                machine[key + '_path'] = path
            validate_machine(name, machine, Catalog(self.app.base_raw), self.app.project)
            import time
            machine['created_at'] = before['machines'].get(name, {}).get('created_at', time.time_ns())
            self.app.project.data['machines'][name] = machine
            self.app.project.compile(Catalog(self.app.base_raw))
            self.app.persist()
            self.app.record_undo('Save machine', self, state_before, before)
            self.saved_name = name
            self.name_entry.configure(state='readonly')
            self.assets = {k: machine[k] for k in ('icon', 'sprite') if machine[k]}
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
        machine = copy.deepcopy(self.app.project.data['machines'][name])
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
        help_label(dialog, 'Choose template creates a new building from a template. Edit machine updates an existing machine. Create variant copies one into a new machine.', wraplength=620)
        def select(mode):
            for child in dialog.winfo_children():
                child.destroy()
            title = {'create': 'Choose template', 'edit': 'Edit machine', 'variant': 'Create variant'}[mode]
            ttk.Label(dialog, text=title, padding=16, font=('Segoe UI', 14, 'bold')).pack(anchor='w')
            query = tk.StringVar()
            ttk.Entry(dialog, textvariable=query).pack(fill='x', padx=16)
            help_label(dialog, 'Search loaded or saved machines by name. Mining drills, furnaces, assemblers and rocket silos are included.', wraplength=620)
            listing = tk.Listbox(dialog, exportselection=False)
            listing.pack(fill='both', expand=True, padx=16, pady=8)
            choices = sorted((kind, name) for kind in MACHINE_TYPES for name in self.app.catalog.raw.get(kind, {}))
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
        for title, mode in [('Choose template', 'create'), ('Edit machine', 'edit'), ('Create variant', 'variant')]:
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
        source = self.app.base_raw[self.entity_type][machine['template']]
        defaults = {'width': round(dimensions(source)[0]), 'height': round(dimensions(source)[1]), 'color': '#ffffff',
                    'resource_categories': source.get('resource_categories', ['basic-solid']), 'mining_radius': source.get('resource_searching_radius', 2.49), 'resource_drain': source.get('resource_drain_rate_percent', 100)}
        for key, var in self.vars.items():
            value = name if key == 'name' else machine.get(key, defaults.get(key, ''))
            if key == 'recipes':
                value = ', '.join(machine.get('recipes', []))
            if key == 'resource_categories':
                value = ', '.join(value)
            var.set(value)
        from machine_model import CONTROLLED
        advanced = machine.get('advanced', {k: v for k, v in source.items() if k not in CONTROLLED})
        self.advanced_text.delete('1.0', 'end')
        self.advanced_text.insert('1.0', json.dumps(advanced, indent=2, ensure_ascii=False))
        self.advanced_text.edit_modified(False)
        self.assets = {k: machine[k] for k in ('icon', 'sprite') if machine.get(k)}
        self.asset_paths = {k: machine.get(k + '_path', '') for k in ('icon', 'sprite')}
        self.energy_choice.configure(values=list(dict.fromkeys(['electric', 'burner', machine['energy_type']])))
        self.name_entry.configure(state='readonly' if mode == 'edit' else 'normal')
        self.recipes_panel.pack_forget()
        self.resources_panel.pack_forget()
        if self.entity_type == 'mining-drill':
            self.resources_panel.pack(fill='x')
            self.list_heading.configure(text='Resource categories')
        else:
            self.recipes_panel.pack(fill='x')
            self.list_heading.configure(text='Allowed recipes')
        self.speed_row.winfo_children()[0].configure(text='Mining speed' if self.entity_type == 'mining-drill' else 'Crafting speed')
        self.speed_help.configure(text=HELP['Mining speed'] if self.entity_type == 'mining-drill' else HELP['Crafting speed'])
        if self.placeholder.winfo_exists():
            self.placeholder.pack_forget()
        for child, options in self.form_children:
            child.pack(**options)
        self.ready = True
        self.dirty = False
        self.mode_text.set({'create': 'CHOOSE TEMPLATE — Create a new machine from the selected template.', 'variant': 'CREATE VARIANT — Save a new machine with its own identity.', 'edit': 'EDIT MACHINE — Save changes to the selected machine.'}[mode])
        self.status.set('Mining drill loaded. Adjust its mining stats, footprint and color, then save.' if self.entity_type == 'mining-drill' else 'Source stats loaded. Adjust them and save the machine.')
        self.app.tabs.tab(self, text=name or 'Create machine')
        self.rendered_recipes = None
        self.preview()
        self.last_state = self.snapshot()

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
        self.saved_choice.configure(values=sorted(self.app.project.data['machines']))
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
