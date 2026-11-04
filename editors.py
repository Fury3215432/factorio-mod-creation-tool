"""Item forms, project export, and the technology flowchart."""
import copy
import json
from time import time_ns
import math
import weakref
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk, colorchooser
import zipfile

from core import Catalog, loaded_mods, mod_archive_name
from project import identifier, png_asset, positive, default_icon_asset, is_finished_product, fuel_energy
from ui import HELP, help_label, scroll_form, entry_undo
from controls import sequence, BUTTONS

BG, CARD, TEXT, ACCENT = '#171c24', '#273240', '#e6edf3', '#e9aa52'


def field(parent, label, value='', width=50):
    row = ttk.Frame(parent)
    row.pack(fill='x', padx=16, pady=4)
    compact = getattr(parent, 'compact_fields', False)
    ttk.Label(row, text=label, width=21 if not compact else 0).pack(side='top' if compact else 'left', anchor='w')
    var = tk.StringVar(value=str(value))
    entry = ttk.Entry(row, textvariable=var, width=18 if compact else width)
    entry.pack(side='left', fill='x', expand=True)
    if isinstance(parent.winfo_toplevel(), tk.Toplevel):
        entry_undo(entry, var)
    help_label(parent, HELP.get(label, 'This value controls ' + label.lower() + ' in the exported mod.'), wraplength=335 if compact else 610)
    return var, row, entry


def item_dialog(tab, item=None, as_ingredient=False, as_result=False):
    app = tab.app
    item = copy.deepcopy(item or {})
    dialog = tk.Toplevel(app)
    dialog.title('Create item' if not item else 'Edit item')
    dialog.transient(app)
    dialog.geometry('740x710')
    footer = ttk.Frame(dialog, padding=12)
    footer.pack(side='bottom', fill='x')
    body = scroll_form(dialog)
    ttk.Label(body, text='Create or edit an item, fluid, science pack or ore.', padding=16, font=('Segoe UI', 13, 'bold')).pack(anchor='w')
    kind, row, entry = field(body, 'Creation type', item.get('kind', 'item'))
    entry.destroy()
    ttk.Combobox(row, textvariable=kind, values=['item', 'fluid', 'science pack', 'ore'], state='disabled' if item.get('operation') == 'edit' else 'readonly').pack(side='left', fill='x', expand=True)
    name, _, name_entry = field(body, 'Item ID', item.get('name', ''))
    if item.get('operation') == 'edit':
        name_entry.configure(state='readonly')
        help_label(body, 'Loaded items keep their ID and type so existing recipes and entities continue to work. Other properties can be edited.', wraplength=610)
    title, _, _ = field(body, 'Display name', item.get('title', ''))
    description, _, _ = field(body, 'Description', item.get('description', ''))
    finished = tk.BooleanVar(value=is_finished_product(item))
    ttk.Checkbutton(body, text='Mark as finished product', variable=finished).pack(anchor='w', padx=16, pady=4)
    help_label(body, 'Finished products are excluded from the unused-ingredient list in Suggested actions. Missing icons and crafting recipes are still tracked.', wraplength=610)
    stack, stack_row, _ = field(body, 'Stack size', item.get('stack_size', 100))
    stack_help = body.winfo_children()[-1]
    temperature, temp_row, _ = field(body, 'Default temperature', item.get('default_temperature', 25))
    temp_help = body.winfo_children()[-1]
    fuel, _, _ = field(body, 'Fuel value', item.get('fuel_value', ''))
    help_label(body, 'Energy released per item (or fluid unit), such as 4MJ or 500kJ. Leave blank to make it non-fuel.', wraplength=610)
    fuel_category, fuel_row, fuel_entry = field(body, 'Fuel category', item.get('fuel_category', (item.get('fuel_categories') or ['chemical'])[0]))
    fuel_entry.destroy()
    ttk.Combobox(fuel_row, textvariable=fuel_category, values=sorted(app.catalog.raw.get('fuel-category', {})), state='readonly').pack(side='left', fill='x', expand=True)
    help_label(body, 'Determines which burners accept this solid fuel. Chemical is used by ordinary burners; fluids do not use a fuel category.', wraplength=610)
    quantity, quantity_row, _ = field(body, 'Recipe result amount', item.get('default_amount', 1))
    subgroup, row, entry = field(body, 'Inventory subgroup', item.get('subgroup', 'intermediate-product'))
    entry.destroy()
    ttk.Combobox(row, textvariable=subgroup, values=sorted(app.catalog.raw.get('item-subgroup', {})), state='readonly').pack(side='left', fill='x', expand=True)
    path, row, entry = field(body, 'PNG file', item.get('icon_path', ''))
    ttk.Button(row, text='Browse…', command=lambda: choose_png(path)).pack(side='right', padx=4)
    ore_frame = ttk.Frame(body)
    ore_graphics, ore_graphics_row, _ = field(ore_frame, 'Ore graphics PNG', item.get('ore_graphics_path', ''))
    def choose_ore_graphics():
        chosen = filedialog.askopenfilename(parent=dialog, title='Choose ore ground PNG or sprite sheet', filetypes=[('PNG graphics', '*.png')])
        if chosen:
            ore_graphics.set(chosen)
    ttk.Button(ore_graphics_row, text='Browse…', command=choose_ore_graphics).pack(side='right')
    help_label(ore_frame, 'Ground graphics for the mineable ore. Use a transparent PNG or sheet. If blank, the item icon is used as the ground graphic; no ore template is needed.', wraplength=610)
    ore_frame_width, _, _ = field(ore_frame, 'Ore frame width', item.get('ore_frame_width', 0))
    ore_frame_height, _, _ = field(ore_frame, 'Ore frame height', item.get('ore_frame_height', 0))
    help_label(ore_frame, 'Pixel dimensions of each ground sprite. Zero calculates dimensions from the sheet and stage/variation counts.', wraplength=610)
    ore_stages, _, _ = field(ore_frame, 'Ore stage amounts', ', '.join(map(str, item.get('ore_stage_counts', [0]))))
    help_label(ore_frame, 'Descending resource amounts for depletion graphics, ending at 0. Example: 1000, 100, 0 needs 3 sprite columns. A single 0 uses a static sprite.', wraplength=610)
    ore_variations, _, _ = field(ore_frame, 'Ore variations', item.get('ore_variations', 1))
    help_label(ore_frame, 'Number of random visual variations arranged down the PNG rows. Depletion stages go across columns.', wraplength=610)
    ore_scale, _, _ = field(ore_frame, 'Ore graphics scale', item.get('ore_graphics_scale', 1))
    help_label(ore_frame, 'Visual size multiplier: 1 fits a frame to one tile width. This does not change mining yield or collision.', wraplength=610)
    ore_sounds = {}
    for sound, label in [('mining', 'Mining sound'), ('mined', 'Mined sound'), ('walking', 'Walking sound')]:
        variable, sound_row, _ = field(ore_frame, label, item.get('ore_' + sound + '_sound_path', ''))
        ore_sounds[sound] = variable
        def choose_sound(variable=variable):
            chosen = filedialog.askopenfilename(parent=dialog, title='Choose ore sound', filetypes=[('Audio', '*.ogg *.wav')])
            if chosen:
                variable.set(chosen)
        ttk.Button(sound_row, text='Browse…', command=choose_sound).pack(side='right')
        help_label(ore_frame, 'Optional OGG/WAV for this ore. Mining plays during manual mining; mined plays on completion; walking plays when walking over it. Files are embedded in the project and export.', wraplength=610)
    ore_volume, _, _ = field(ore_frame, 'Ore sound volume', item.get('ore_sound_volume', .7))
    help_label(ore_frame, 'Volume for custom ore sounds, from 0 (silent) to 1 (full volume).', wraplength=610)
    mining_time, _, _ = field(ore_frame, 'Mining seconds', item.get('mining_time', 1))
    mining_amount, _, _ = field(ore_frame, 'Mining yield', item.get('mining_amount', 1))
    ore_color, color_row, _ = field(ore_frame, 'Ore color', item.get('ore_color', '#ffffff'))
    def pick_ore_color():
        selected = colorchooser.askcolor(color=ore_color.get(), parent=dialog, title='Ore color')[1]
        if selected:
            ore_color.set(selected)
    ttk.Button(color_row, text='Choose…', command=pick_ore_color).pack(side='right')
    ore_density, _, _ = field(ore_frame, 'Ore density', item.get('ore_density', 10))
    ore_autoplace = tk.BooleanVar(value=item.get('ore_autoplace', True))
    ore_starting = tk.BooleanVar(value=item.get('ore_starting_area', True))
    ttk.Checkbutton(ore_frame, text='Generate ore patches on Nauvis', variable=ore_autoplace).pack(anchor='w', padx=16, pady=4)
    help_label(ore_frame, 'Adds map-generation controls and ore patches in new maps or newly generated terrain; existing explored terrain is unchanged.', wraplength=610)
    ttk.Checkbutton(ore_frame, text='Include a starting-area patch', variable=ore_starting).pack(anchor='w', padx=16, pady=4)
    help_label(ore_frame, 'Allows patches near spawn when automatic map generation is enabled.', wraplength=610)
    ttk.Label(body, text=('PNG is optional. Leave it blank to keep the loaded item’s original icon.\n' if item.get('operation') == 'edit' else 'PNG is optional. Without one, the checkerboard icon is used and the item appears in Suggested actions.\n') + 'The item is saved immediately and can be selected as an ingredient or result in any flowchart.', wraplength=620, padding=16).pack(anchor='w')
    def update_type(*_):
        if kind.get() == 'science pack' and item.get('kind') != 'science pack':
            finished.set(True)
        if kind.get() == 'science pack' and subgroup.get() == 'intermediate-product' and 'science-pack' in app.catalog.raw.get('item-subgroup', {}):
            subgroup.set('science-pack')
        if kind.get() == 'ore' and subgroup.get() == 'intermediate-product' and 'raw-resource' in app.catalog.raw.get('item-subgroup', {}):
            subgroup.set('raw-resource')
        ore_frame.pack_forget()
        if kind.get() == 'ore':
            ore_frame.pack(fill='x', before=quantity_row)
        for widget in (stack_row, stack_help):
            widget.pack_forget()
        for widget in (temp_row, temp_help):
            widget.pack_forget()
        rows = (temp_row, temp_help) if kind.get() == 'fluid' else (stack_row, stack_help)
        anchor = quantity_row
        for widget in rows:
            widget.pack(fill='x', before=anchor, padx=16, pady=4)
        create_button.configure(text=('Create ' if not item else 'Save ') + kind.get())
    def save():
        before = copy.deepcopy(app.project.data)
        try:
            item_id = identifier(name.get().strip())
            if not item and (('item', item_id) in app.catalog.items or ('fluid', item_id) in app.catalog.items):
                raise ValueError('That item ID already exists in the game. Choose a new ID.')
            if not item and item_id in app.project.data['items']:
                raise ValueError('This project already contains that item. Load its recipe to edit it.')
            icon_path = path.get().strip()
            icon = item.get('icon')
            if icon_path:
                if not icon or icon_path != item.get('icon_path'):
                    icon = png_asset(icon_path)
            elif (not icon or item.get('icon_path')) and item.get('operation') != 'edit':
                icon = copy.deepcopy(default_icon_asset())
            if icon:
                tk.PhotoImage(data=icon['data'], master=dialog)
            draft = {'name': item_id, 'title': title.get().strip() or item_id.replace('-', ' ').title(),
                     'description': description.get(), 'kind': kind.get(), 'finished_product': finished.get(),
                     'stack_size': positive(stack.get(), 'Stack size', True) if kind.get() != 'fluid' else 100,
                     'subgroup': subgroup.get(), 'icon': icon, 'icon_path': icon_path,
                     'icon_is_default': bool(icon and icon['data'] == default_icon_asset()['data'])}
            draft['fuel_value'] = fuel_energy(fuel.get())
            if draft['fuel_value'] and kind.get() != 'fluid':
                if fuel_category.get() not in app.catalog.raw.get('fuel-category', {}):
                    raise ValueError('Choose a loaded fuel category.')
                draft['fuel_category'] = fuel_category.get()
                if item.get('fuel_categories') or 'fuel_categories' in app.catalog.raw.get('item', {}).get('coal', {}):
                    draft['fuel_categories'] = [fuel_category.get()]
            if item.get('operation') == 'edit':
                if item_id != item['name'] or kind.get() != item.get('kind', 'item'):
                    raise ValueError('Loaded items must keep their original ID and type.')
                draft.update(operation='edit', original=copy.deepcopy(item['original']))
            if draft['subgroup'] not in app.catalog.raw.get('item-subgroup', {}):
                raise ValueError('Choose a loaded inventory subgroup.')
            if kind.get() == 'fluid':
                draft['default_temperature'] = float(temperature.get())
                if not math.isfinite(draft['default_temperature']):
                    raise ValueError('Default temperature must be a finite number.')
                for key in ('base_color', 'flow_color'):
                    if key in item:
                        draft[key] = item[key]
            if kind.get() == 'ore':
                draft.update(ore_template=None, mining_time=positive(mining_time.get(), 'Mining seconds'),
                             mining_amount=positive(mining_amount.get(), 'Mining yield', True), ore_color=ore_color.get(),
                             ore_density=positive(ore_density.get(), 'Ore density'), ore_autoplace=ore_autoplace.get(),
                             ore_starting_area=ore_starting.get())
                from machine_model import sprite_asset
                from ore_model import sound_asset
                graphics_path = ore_graphics.get().strip()
                draft['ore_graphics'] = (item.get('ore_graphics') if graphics_path == item.get('ore_graphics_path') else sprite_asset(graphics_path)) if graphics_path else None
                draft['ore_graphics_path'] = graphics_path
                draft['ore_frame_width'] = int(ore_frame_width.get())
                draft['ore_frame_height'] = int(ore_frame_height.get())
                if min(draft['ore_frame_width'], draft['ore_frame_height']) < 0:
                    raise ValueError('Ore frame dimensions cannot be negative.')
                draft['ore_stage_counts'] = [int(value.strip()) for value in ore_stages.get().split(',')]
                draft['ore_variations'] = positive(ore_variations.get(), 'Ore variations', True)
                draft['ore_graphics_scale'] = positive(ore_scale.get(), 'Ore graphics scale')
                draft['ore_sound_volume'] = float(ore_volume.get())
                for sound, variable in ore_sounds.items():
                    sound_path = variable.get().strip()
                    key = 'ore_' + sound + '_sound'
                    draft[key] = (item.get(key) if sound_path == item.get(key + '_path') else sound_asset(sound_path)) if sound_path else None
                    draft[key + '_path'] = sound_path

            draft['created_at'] = item.get('created_at', time_ns())
            amount = positive(quantity.get(), 'Result amount', kind.get() != 'fluid')
            draft['default_amount'] = amount
            if item and item['name'] not in app.project.data['items']:
                app.project.data['items'][item['name']] = copy.deepcopy(item)
            remap = app.project.update_creation(item['name'], draft, app.catalog) if item else None
            if not item:
                app.project.data['items'][item_id] = draft
            app.project.compile(Catalog(app.base_raw))
            # Validate every open draft before committing a type conversion.
            related = []
            if remap and remap[0] != remap[1]:
                for widget in app.tabs.winfo_children():
                    if hasattr(widget, 'loaded_name') and hasattr(widget, 'recipe'):
                        state = widget.snapshot()
                        changed = False
                        for entry in state['recipe'].ingredients + state['recipe'].results:
                            if (entry['type'], entry['name']) == remap[0]:
                                entry.update(type=remap[1][0], name=remap[1][1])
                                if remap[1][0] == 'item':
                                    for key in ('temperature', 'minimum_temperature', 'maximum_temperature', 'fluidbox_index'):
                                        entry.pop(key, None)
                                changed = True
                        if changed:
                            if state.get('auto_name') and not state['loaded_name'] and not state['saved_key'] and state['recipe'].results:
                                state['name'] = state['recipe'].results[0]['name'] + '_recipe'
                            for entry in state['recipe'].ingredients + state['recipe'].results:
                                if entry['type'] == 'item':
                                    for key in ('amount', 'amount_min', 'amount_max'):
                                        if key in entry:
                                            positive(entry[key], 'Item quantity', True)
                            if state['item_draft'] and state['item_draft']['name'] == item['name']:
                                state['item_draft'] = copy.deepcopy(draft)
                            related.append((widget, widget.snapshot(), state))
            app.persist()
            app.record_undo('Create item' if not item else 'Edit item', tab, tab.snapshot(), before)
            app.undo_stack[-1]['related'] = [(weakref.ref(widget), prior) for widget, prior, _ in related]
            for widget, _, state in related:
                widget.restore(state)
            app.refresh_catalog()
            if as_ingredient or as_result:
                tracking = tab.tracking
                tab.tracking = False
                tab.add_entry('results' if as_result else 'ingredients', ('fluid' if draft['kind'] == 'fluid' else 'item', item_id), amount)
                if as_result and tab.auto_name and not tab.loaded_name and not tab.saved_key:
                    tab.name.set(tab.recipe.results[0]['name'] + '_recipe')
                tab.tracking = tracking
                tab.dirty = True
                tab.update_mode()
                tab.last_state = tab.snapshot()
            dialog.destroy()
        except (ValueError, OSError, tk.TclError) as exc:
            app.project.data = before
            messagebox.showerror('Cannot create item', str(exc), parent=dialog)
    create_button = ttk.Button(footer, text='Create item' if not item else 'Save item', command=save)
    create_button.pack(side='left')
    kind.trace_add('write', update_type)
    update_type()
    dialog.bind(sequence(app.controls['dialog_dismiss']), lambda e: dialog.destroy())


def choose_png(variable):
    path = filedialog.askopenfilename(title='Choose square PNG icon', filetypes=[('PNG image', '*.png')])
    if path:
        variable.set(path)


def export_project_dialog(app):
    try:
        app.project.compile(Catalog(app.base_raw))
        mods = loaded_mods(app.mods_path)
    except (ValueError, OSError, KeyError, zipfile.BadZipFile) as exc:
        messagebox.showerror('Cannot export project', str(exc))
        return
    dialog = tk.Toplevel(app)
    dialog.title('Export all saved changes')
    dialog.transient(app)
    dialog.geometry('720x520')
    d = app.project.data
    deleted = sum(len(names) for names in d.get('deleted', {}).values())
    ttk.Label(dialog, text=f"Export {len(d['recipes'])} recipes, {len(d['items'])} items, {len(d['technologies'])} technologies and {len(d['machines'])} machines." + (f' Remove {deleted} loaded prototypes.' if deleted else ''), padding=16, wraplength=680).pack(anchor='w')
    options = ['Create a new mod'] + ['Update ' + i.get('title', i['name']) + ' (' + i['name'] + ')' for _, i in mods]
    choice = ttk.Combobox(dialog, values=options, state='readonly')
    choice.pack(fill='x', padx=16)
    choice.current(1 if len(mods) == 1 else 0)
    name, _, entry = field(dialog, 'New mod ID', 'recipe-studio-project')
    note = tk.StringVar()
    def refresh(*_):
        updating = choice.current() > 0
        entry.configure(state='disabled' if updating else 'normal')
        note.set('Exports a copy of the selected mod with all project edits applied after its original scripts. Replace the old installed copy.' if updating else 'Creates an installable mod with all saved project changes, icons and an automatic loader. Loaded mods become dependencies.')
    choice.bind('<<ComboboxSelected>>', refresh)
    refresh()
    ttk.Label(dialog, textvariable=note, wraplength=610, padding=16).pack(anchor='w')
    ttk.Label(dialog, text='Install required dependency mods alongside this ZIP.\nYour original loaded mod files stay unchanged.', padding=16).pack(anchor='w')
    def save():
        try:
            index = choice.current() - 1
            target = mods[index][0] if index >= 0 else None
            info = mods[index][1] if target else {'name': name.get().strip(), 'version': '1.0.0'}
            filename = mod_archive_name(info)
            path = filedialog.asksaveasfilename(parent=dialog, title='Save complete Factorio mod', initialfile=filename, defaultextension='.zip', filetypes=[('Factorio mod ZIP', '*.zip')])
            if not path:
                return
            result = app.project.export(path, Catalog(app.base_raw), app.root_path, app.mods_path, target, name.get().strip())
            dialog.destroy()
            log_note = '\n\nChange log: ' + str(Path(path).with_name(Path(path).stem + '.changes.json')) + '\nAlso included inside the ZIP as recipe-studio-changes.json.' if mods or target else ''
            messagebox.showinfo('Mod ready', 'Saved: ' + path + '\n\nCopy this ZIP into your Factorio mods folder, enable it, and restart Factorio. Replace older copies of the same mod, including unpacked duplicates.\n\nDependencies: ' + ', '.join(result.get('dependencies', [])) + log_note)
        except (ValueError, OSError, KeyError, zipfile.BadZipFile) as exc:
            messagebox.showerror('Cannot export mod', str(exc), parent=dialog)
    ttk.Button(dialog, text='Export mod file…', command=save).pack(anchor='e', padx=16, pady=12)


def select_names(app, title, values, callback):
    dialog = tk.Toplevel(app)
    dialog.title(title)
    dialog.geometry('520x440')
    query = tk.StringVar()
    ttk.Entry(dialog, textvariable=query).pack(fill='x', padx=12, pady=12)
    help_label(dialog, 'Filters the available IDs. Select one or more matches to add them.', wraplength=470, padx=12)
    listing = tk.Listbox(dialog, bg=BG, fg=TEXT, selectmode='extended')
    listing.pack(fill='both', expand=True, padx=12)
    matches = []
    def refresh(*_):
        matches[:] = [v for v in sorted(values) if query.get().lower() in v.lower()]
        listing.delete(0, 'end')
        for value in matches:
            listing.insert('end', value)
    def apply():
        callback([matches[i] for i in listing.curselection()])
        dialog.destroy()
    query.trace_add('write', refresh)
    refresh()
    ttk.Button(dialog, text='Add selected', command=apply).pack(pady=12)
    listing.bind('<Double-Button-%d>' % BUTTONS[app.controls['picker_button']], lambda e: apply())
    dialog.bind(sequence(app.controls['picker_accept']), lambda e: apply())
    dialog.bind(sequence(app.controls['dialog_dismiss']), lambda e: dialog.destroy())


from technology import TechTab


def unlock_icon_picker(owner, recipes, callback):
    app = owner.app
    from core import entries
    from flow import prototype_image
    candidates = {}
    for name in recipes:
        recipe = app.catalog.recipes.get(name)
        if recipe is None:
            continue
        candidates[('recipe', name)] = recipe
        for product in entries(recipe, 'results'):
            key = product['type'], product['name']
            candidates[key] = app.catalog.items.get(key, {})
    dialog = tk.Toplevel(app)
    dialog.title('Choose technology icon from unlocks')
    dialog.transient(app)
    dialog.geometry('680x500')
    help_label(dialog, 'Choose an icon from an unlocked recipe or one of its resulting items/fluids. The selected PNG is embedded in the project and exported mod.', wraplength=640)
    holder = ttk.Frame(dialog, padding=12)
    holder.pack(fill='both', expand=True)
    listing = ttk.Treeview(holder, columns=('kind',), show='tree headings', selectmode='browse', height=9)
    ttk.Style(dialog).configure('UnlockIcons.Treeview', rowheight=42)
    listing.configure(style='UnlockIcons.Treeview')
    listing.heading('#0', text='Icon / ID')
    listing.heading('kind', text='Source')
    listing.column('#0', width=420)
    listing.column('kind', width=120)
    scrollbar = ttk.Scrollbar(holder, orient='vertical', command=listing.yview)
    listing.configure(yscrollcommand=scrollbar.set)
    scrollbar.pack(side='right', fill='y')
    listing.pack(fill='both', expand=True)
    images, choices = [], {}
    def picture(key, size):
        kind, name = key
        if kind != 'recipe':
            return app.icon(key, size=size)
        recipe = candidates[key]
        image = prototype_image(app, recipe, size)
        if not image:
            products = entries(recipe, 'results')
            if products:
                image = app.icon((products[0]['type'], products[0]['name']), size=size)
        return image
    for key in candidates:
        image = picture(key, 36)
        if not image:
            continue
        row_id = str(len(choices))
        choices[row_id] = key
        images.append(image)
        listing.insert('', 'end', iid=row_id, text=key[1], values=(key[0],), image=image)
    listing.images = images
    if choices:
        listing.selection_set(next(iter(choices)))
    else:
        ttk.Label(dialog, text='Add recipe unlocks with available icons first.', padding=12).pack(anchor='w')
    def choose(*_):
        selected = listing.selection()
        if not selected:
            return
        key = choices[selected[0]]
        image = picture(key, 64)
        if image is None:
            return
        import base64
        data = image.tk.call(str(image), 'data', '-format', 'png')
        if isinstance(data, str):
            data = data.encode('latin1')
        asset = {'data': base64.b64encode(data).decode('ascii'), 'size': image.width()}
        callback(asset, '@unlock:' + key[0] + ':' + key[1])
        dialog.destroy()
    ttk.Button(dialog, text='Use selected icon', command=choose).pack(anchor='e', padx=12, pady=12)
    listing.bind('<Double-Button-1>', choose)
    listing.bind(sequence(app.controls['picker_accept']), choose)
    return dialog


def technology_dialog(tab, name=None, force=False):
    if not force and not tab.confirm_switch():
        return
    app = tab.app
    tab.editor_tracking = False
    existing = copy.deepcopy(app.catalog.raw.get('technology', {}).get(name, {}))
    saved = app.project.data['technologies'].get(name, {})
    tab.editor_icon_choices = {saved.get('icon_path'): copy.deepcopy(saved['icon'])} if saved.get('icon') and saved.get('icon_path', '').startswith('@unlock:') else {}
    prototype = existing or {'type': 'technology', 'name': '', 'icon': '__base__/graphics/technology/automation-1.png', 'icon_size': 256,
                             'prerequisites': [], 'effects': [], 'unit': {'count': 10, 'time': 30, 'ingredients': [['automation-science-pack', 1]]}}
    for child in tab.editor_host.winfo_children():
        child.destroy()
    tab.selected = name
    tab.dirty = False
    if name and name not in tab.positions:
        tab.query.set('')
        tab.refresh()
    dialog = ttk.Frame(tab.editor_host)
    dialog.pack(fill='both', expand=True)
    tab.editor_frame = dialog
    header = ttk.Frame(dialog, padding=10)
    header.pack(fill='x')
    ttk.Label(header, text='New technology' if name is None else name.replace('-', ' ').title(), foreground=ACCENT, font=('Segoe UI', 12, 'bold'), wraplength=370).pack(anchor='w')
    preview = tk.Canvas(header, height=120, bg='#2d2e29', highlightthickness=0)
    preview.pack(fill='x', pady=(6, 0))
    image = tab.tech_image(name, 76) if name else None
    if image:
        tab.preview_image = image
        preview.create_image(44, 43, image=image)
    preview.create_text(48, 86, text=(name or 'New technology').replace('-', ' ').title(), anchor='n', fill=TEXT, width=94, font=('Segoe UI', 8))
    unit_preview = prototype.get('unit', {})
    summary = 'Trigger-based research' if prototype.get('research_trigger') else str(unit_preview.get('count', unit_preview.get('count_formula', 10))) + ' research units\n' + str(unit_preview.get('time', 30)) + ' seconds per unit'
    preview.create_text(96, 14, text=summary, anchor='nw', fill=TEXT, width=260, font=('Segoe UI', 10))
    tab.preview_science_images = []
    for index, ingredient in enumerate(unit_preview.get('ingredients', [])[:9]):
        pack = ingredient['name'] if isinstance(ingredient, dict) else ingredient[0]
        science_icon = app.icon(('item', pack), size=18)
        if science_icon:
            tab.preview_science_images.append(science_icon)
            preview.create_image(108 + index * 24, 67, image=science_icon)
    footer = ttk.Frame(dialog, padding=8)
    footer.pack(side='bottom', fill='x')
    notebook = ttk.Notebook(dialog)
    notebook.pack(fill='both', expand=True, padx=8, pady=(0, 8))
    details = ttk.Frame(notebook)
    advanced = ttk.Frame(notebook)
    notebook.add(details, text='Research & unlocks')
    notebook.add(advanced, text='Advanced JSON')
    scroll = tk.Canvas(details, bg=BG, highlightthickness=0, width=380)
    scrollbar = ttk.Scrollbar(details, orient='vertical', command=scroll.yview)
    scroll.configure(yscrollcommand=scrollbar.set)
    scrollbar.pack(side='right', fill='y')
    scroll.pack(side='left', fill='both', expand=True)
    main = ttk.Frame(scroll)
    main.compact_fields = True
    window = scroll.create_window(0, 0, window=main, anchor='nw')
    main.bind('<Configure>', lambda e: scroll.configure(scrollregion=scroll.bbox('all')))
    scroll.bind('<Configure>', lambda e: scroll.itemconfigure(window, width=e.width))
    # A panel-local bind tag scrolls fields without hijacking the tree's zoom.
    panel_tag = 'TechPanelScroll_' + str(dialog).replace('.', '_')
    scroll.bind_class(panel_tag, '<MouseWheel>', lambda e: (scroll.yview_scroll(-1 if e.delta > 0 else 1, 'units'), 'break')[-1])
    tech_id, _, entry = field(main, 'Technology ID', name or '')
    if name:
        entry.configure(state='disabled')
    title, _, _ = field(main, 'Display name', prototype.get('localised_name', '') if isinstance(prototype.get('localised_name', ''), str) else '')
    description, _, _ = field(main, 'Description', prototype.get('localised_description', '') if isinstance(prototype.get('localised_description', ''), str) else '')
    prerequisites, row, _ = field(main, 'Prerequisites', ', '.join(prototype.get('prerequisites', [])))
    def append_names(variable, values):
        old = split_names(variable.get())
        variable.set(', '.join(dict.fromkeys(old + values)))
    ttk.Button(row, text='Choose…', command=lambda: select_names(app, 'Select prerequisite technologies', [n for n in app.catalog.raw.get('technology', {}) if n != name], lambda names: append_names(prerequisites, names))).pack(side='right', padx=4)
    unit = prototype.get('unit', {})
    count, _, _ = field(main, 'Research count', unit.get('count', 10))
    formula, _, _ = field(main, 'Count formula (optional)', unit.get('count_formula', ''))
    time, _, _ = field(main, 'Seconds per research unit', unit.get('time', 30))
    packs = []
    for ingredient in unit.get('ingredients', [['automation-science-pack', 1]]):
        pack, amount = (ingredient['name'], ingredient['amount']) if isinstance(ingredient, dict) else ingredient
        packs.append(str(pack) + ':' + str(amount))
    science, row, _ = field(main, 'Science packs', ', '.join(packs))
    def add_packs(names):
        current = {s.split(':')[0].strip() for s in split_names(science.get())}
        append_names(science, [n + ':1' for n in names if n not in current])
    ttk.Button(row, text='Choose…', command=lambda: select_names(app, 'Select science packs', app.catalog.raw.get('tool', {}), add_packs)).pack(side='right', padx=4)
    ttk.Label(main, text='Science format: automation-science-pack:1,\nlogistic-science-pack:1', padding=(16, 0, 16, 6)).pack(anchor='w')
    unlocks = tk.StringVar(value=', '.join(e['recipe'] for e in prototype.get('effects', []) if e.get('type') == 'unlock-recipe'))
    row = ttk.Frame(main)
    row.pack(fill='x', padx=16, pady=4)
    ttk.Label(row, text='Recipe unlocks').pack(side='left')
    def add_recipe_unlocks(names):
        invalid = [recipe for recipe in names if recipe not in app.catalog.recipes]
        if invalid:
            messagebox.showerror('Recipe IDs required', 'Technologies unlock recipes, not item IDs. Invalid entries: ' + ', '.join(invalid), parent=tab)
            return
        append_names(unlocks, names)
    ttk.Button(row, text='Add recipes…', command=lambda: select_names(app, 'Select recipe IDs to unlock', app.catalog.recipes, add_recipe_unlocks)).pack(side='right', padx=4)
    unlock_holder = ttk.Frame(main)
    unlock_holder.pack(fill='both', padx=16, pady=4)
    ttk.Style(tab).configure('RecipeUnlocks.Treeview', rowheight=32)
    unlock_list = ttk.Treeview(unlock_holder, columns=('products',), show='tree headings', height=6, selectmode='extended', style='RecipeUnlocks.Treeview')
    tab.unlock_list = unlock_list
    unlock_list.heading('#0', text='Recipe')
    unlock_list.column('#0', width=190, minwidth=100)
    unlock_list.heading('products', text='Products')
    unlock_list.column('products', width=145, minwidth=80)
    unlock_scroll = ttk.Scrollbar(unlock_holder, orient='vertical', command=unlock_list.yview)
    unlock_list.configure(yscrollcommand=unlock_scroll.set)
    unlock_scroll.pack(side='right', fill='y')
    unlock_list.pack(fill='both', expand=True)
    def refresh_unlock_list(*_):
        from core import entries
        from flow import prototype_image
        selected = unlock_list.selection()
        unlock_list.delete(*unlock_list.get_children())
        unlock_list.images = []
        for recipe_name in dict.fromkeys(split_names(unlocks.get())):
            recipe = app.catalog.recipes.get(recipe_name, {})
            products = entries(recipe, 'results')
            image = prototype_image(app, recipe, 24)
            if not image and products:
                image = app.icon((products[0]['type'], products[0]['name']), size=24)
            options = {}
            if image:
                unlock_list.images.append(image)
                options['image'] = image
            unlock_list.insert('', 'end', iid=recipe_name, text=recipe_name,
                               values=(', '.join(product['name'] for product in products) if recipe_name in app.catalog.recipes else 'Invalid: not a recipe ID — delete this unlock',), **options)
        retained = [recipe for recipe in selected if unlock_list.exists(recipe)]
        if retained:
            unlock_list.selection_set(*retained)
    def remove_unlocks(*_):
        selected = set(unlock_list.selection())
        if selected:
            before_state = tab.snapshot()
            tab.editor_tracking = False
            unlocks.set(', '.join(recipe for recipe in split_names(unlocks.get()) if recipe not in selected))
            tab.editor_tracking = True
            tab.dirty = True
            app.record_undo('Remove technology recipe unlocks', tab, before_state)
            tab.last_editor_state = tab.snapshot()
        return 'break'
    ttk.Button(main, text='Delete selected unlocks', command=remove_unlocks).pack(anchor='w', padx=16, pady=4)
    unlock_list.bind('<Delete>', remove_unlocks)
    help_label(main, 'Recipes unlocked by this technology, shown with their icons and products. Add recipes accepts recipe IDs only; Ctrl/Shift-select rows and Delete selected unlocks removes them from this technology. Save technology to apply.', wraplength=335)
    def unlock_context(event):
        recipe = unlock_list.identify_row(event.y)
        if not recipe:
            return
        if recipe not in unlock_list.selection():
            unlock_list.selection_set(recipe)
        if hasattr(unlock_list, 'context_menu'):
            unlock_list.context_menu.destroy()
        unlock_list.context_menu = tk.Menu(unlock_list, tearoff=False)
        from creations_ui import rename_recipe
        if recipe in app.catalog.recipes:
            unlock_list.context_menu.add_command(label='Rename recipe', command=lambda: rename_recipe(tab, recipe))
        unlock_list.context_menu.add_command(label='Delete selected unlocks', command=remove_unlocks)
        unlock_list.context_menu.tk_popup(event.x_root, event.y_root)
    unlock_list.bind('<Button-%d>' % BUTTONS[app.controls['context_button']], unlock_context)
    unlock_trace = unlocks.trace_add('write', refresh_unlock_list)
    def cleanup_unlock_list(event):
        if event.widget is unlock_list:
            unlocks.trace_remove('write', unlock_trace)
    unlock_list.bind('<Destroy>', cleanup_unlock_list, add='+')
    refresh_unlock_list()
    def add_necessary_ingredients():
        from recipe_unlocks import necessary_ingredient_recipes, choose_ingredient_recipe, IngredientChoiceCancelled
        try:
            roots = split_names(unlocks.get())
            if not roots:
                messagebox.showinfo('No recipe unlocks', 'Add at least one recipe unlock first.', parent=tab)
                return
            names = necessary_ingredient_recipes(app, roots, name, split_names(prerequisites.get()),
                                                 chooser=lambda key, choices: choose_ingredient_recipe(tab, key, choices))
            if names != roots:
                before_state = tab.snapshot()
                tab.editor_tracking = False
                unlocks.set(', '.join(names))
                tab.editor_tracking = True
                tab.dirty = True
                app.record_undo('Add necessary ingredients', tab, before_state)
                tab.last_editor_state = tab.snapshot()
        except IngredientChoiceCancelled:
            return
        except (ValueError, KeyError) as exc:
            messagebox.showerror('Cannot add necessary ingredients', str(exc), parent=tab)
    ttk.Button(main, text='Add necessary ingredients', command=add_necessary_ingredients).pack(anchor='w', padx=16, pady=4)
    help_label(main, 'Adds direct ingredient recipes, then deeper ingredients only when every recipe using them is unlocked here. Recipes available from the start or through prerequisite technologies are excluded. Save technology to apply; Ctrl+Z restores the edit.', wraplength=335)

    png, row, _ = field(main, 'Custom icon PNG (optional)', saved.get('icon_path', ''))
    ttk.Button(row, text='Browse…', command=lambda: choose_png(png)).pack(side='right', padx=4)
    def choose_unlock_icon():
        def selected(asset, marker):
            tab.editor_icon_choices[marker] = asset
            png.set(marker)
        return unlock_icon_picker(tab, split_names(unlocks.get()), selected)
    ttk.Button(main, text='Choose icon from unlocks…', command=choose_unlock_icon).pack(anchor='w', padx=16, pady=4)
    help_label(main, 'Use the PNG of an unlocked recipe or its resulting item/fluid as this technology’s icon.', wraplength=335)

    trigger = tk.BooleanVar(value=bool(prototype.get('research_trigger')))
    ttk.Checkbutton(main, text='Use research trigger (Advanced JSON)', variable=trigger).pack(anchor='w', padx=16, pady=8)
    ttk.Label(main, text='Leave PNG blank to keep the existing icon.\nOther effects and properties stay in Advanced JSON.\nAn unlock makes its recipe unavailable at the start.', padding=16, wraplength=335).pack(anchor='w')
    controlled = {'name', 'type', 'prerequisites', 'unit', 'effects', 'localised_name', 'localised_description'}
    rest = {k: v for k, v in prototype.items() if k not in controlled}
    rest['effects'] = [e for e in prototype.get('effects', []) if e.get('type') != 'unlock-recipe']
    # Keep non-form properties and the unabridged prototype accessible.
    ttk.Label(advanced, text='Research triggers, upgrade levels and other effects.', wraplength=330, padding=8).pack(anchor='w')
    text = tk.Text(advanced, bg=BG, fg=TEXT, insertbackground=TEXT, wrap='word', undo=True, width=30, height=8)
    advanced_scroll = ttk.Scrollbar(advanced, orient='vertical', command=text.yview)
    text.configure(yscrollcommand=advanced_scroll.set)
    advanced_scroll.pack(side='right', fill='y')
    text.pack(fill='both', expand=True, padx=8, pady=8)
    text.insert('1.0', json.dumps(rest, indent=2, ensure_ascii=False))
    help_label(advanced, 'Additional Factorio technology properties. Use valid JSON; these values are preserved in the exported prototype.', wraplength=330, padx=8)
    def save():
        before = copy.deepcopy(app.project.data)
        state_before = tab.snapshot()
        try:
            new_name = identifier(tech_id.get().strip())
            if not name and new_name in app.catalog.raw.get('technology', {}):
                raise ValueError('That technology already exists. Click its card to edit it.')
            extra = json.loads(text.get('1.0', 'end'))
            if not isinstance(extra, dict):
                raise ValueError('Advanced properties must be a JSON object.')
            proto = {k: v for k, v in extra.items() if k not in controlled}
            proto.update(type='technology', name=new_name, prerequisites=split_names(prerequisites.get()))
            if title.get().strip():
                proto['localised_name'] = title.get().strip()
            elif 'localised_name' in prototype:
                proto['localised_name'] = prototype['localised_name']
            else:
                proto['localised_name'] = new_name.replace('-', ' ').title()
            if description.get():
                proto['localised_description'] = description.get()
            elif 'localised_description' in prototype:
                proto['localised_description'] = prototype['localised_description']
            effects = extra.get('effects', [])
            if not isinstance(effects, list) or any(not isinstance(e, dict) or not e.get('type') for e in effects):
                raise ValueError('Effects must be an array of Factorio effect objects.')
            effects = [e for e in effects if e['type'] != 'unlock-recipe']
            effects += [{'type': 'unlock-recipe', 'recipe': n} for n in split_names(unlocks.get())]
            proto['effects'] = effects
            if trigger.get():
                if not proto.get('research_trigger'):
                    raise ValueError('Set research_trigger in the advanced properties, or turn off trigger research.')
            else:
                proto.pop('research_trigger', None)
                ingredients = []
                for pack in split_names(science.get()):
                    parts = pack.split(':')
                    ingredients.append([parts[0].strip(), positive(parts[1].strip() if len(parts) > 1 else 1, 'Science amount', True)])
                research = copy.deepcopy(unit)
                research.update(time=positive(time.get(), 'Research time'), ingredients=ingredients)
                research.pop('count', None)
                research.pop('count_formula', None)
                if formula.get().strip():
                    research['count_formula'] = formula.get().strip()
                else:
                    research['count'] = positive(count.get(), 'Research count', True)
                proto['unit'] = research
            asset = saved.get('icon')
            if png.get().startswith('@unlock:'):
                asset = tab.editor_icon_choices.get(png.get())
                if not asset:
                    raise ValueError('Choose the unlock icon again.')
            elif png.get().strip() and (not asset or png.get() != saved.get('icon_path')):
                asset = png_asset(png.get())
            if not png.get().strip():
                asset = None
            if asset:
                tk.PhotoImage(data=asset['data'], master=dialog)
            app.project.validate_technology(proto, app.catalog, previous=name)
            if not asset and not proto.get('icon') and not proto.get('icons'):
                raise ValueError('A technology needs an icon or a custom PNG.')
            app.project.data['technologies'][new_name] = {'prototype': proto, 'icon': asset, 'icon_path': png.get(),
                'created_at': app.project.data['technologies'].get(new_name, {}).get('created_at', time_ns())}
            # Technology unlocks should not also be available from the start.
            for effect in effects:
                if effect['type'] != 'unlock-recipe':
                    continue
                recipe_name = effect['recipe']
                if recipe_name in app.project.data['recipes']:
                    app.project.data['recipes'][recipe_name]['enabled'] = False
                else:
                    from core import Recipe
                    recipe = Recipe(recipe_name, app.catalog.recipes[recipe_name])
                    app.project.save_recipe(recipe, recipe_name, recipe.original.get('normal', recipe.original).get('energy_required', 0.5), False)
            app.project.compile(Catalog(app.base_raw))
            app.persist()
            app.record_undo('Save technology', tab, state_before, before)
            app.refresh_catalog()
            for widget in app.tabs.winfo_children():
                if hasattr(widget, 'saved_key') and widget.saved_key in app.project.data['recipes']:
                    if widget.saved_key in {e['recipe'] for e in effects if e['type'] == 'unlock-recipe'}:
                        was_dirty = widget.dirty
                        was_tracking = widget.tracking
                        widget.tracking = False
                        widget.enabled.set(False)
                        widget.tracking = was_tracking
                        widget.dirty = was_dirty
                        app.tabs.tab(widget, text=widget.saved_key + (' *' if was_dirty else ''))
                        widget.last_state = widget.snapshot()
            tab.dirty = False
            technology_dialog(tab, new_name, force=True)
            return True
        except (ValueError, OSError, KeyError, TypeError, tk.TclError) as exc:
            app.project.data = before
            messagebox.showerror('Cannot save technology', str(exc), parent=dialog)
            return False
    tab.editor_save = save
    ttk.Button(footer, text='Save technology' if name else 'Create technology', command=save).pack(side='right')
    if name:
        from delete_items import delete_technology
        ttk.Button(footer, text='Delete technology', command=lambda: delete_technology(tab, name)).pack(side='right', padx=6)
    ttk.Button(footer, text='Discard', command=lambda: technology_dialog(tab, name, force=True)).pack(side='left')
    def mark(*_):
        if not tab.editor_tracking:
            return
        if not app.undoing and getattr(tab, 'last_editor_state', None):
            key = _[0] if _ else None
            app.record_undo('Edit technology', tab, tab.last_editor_state, coalesce=(id(tab), key) if key else None)
        tab.dirty = True
        tab.last_editor_state = tab.snapshot()
    tab.editor_vars = dict(tech_id=tech_id, title=title, description=description, prerequisites=prerequisites,
                           count=count, formula=formula, time=time, science=science, unlocks=unlocks, png=png, trigger=trigger)
    tab.editor_text = text
    for variable in (tech_id, title, description, prerequisites, count, formula, time, science, unlocks, png, trigger):
        variable.trace_add('write', mark)
    text.edit_modified(False)
    def text_changed(event):
        if text.edit_modified():
            mark('advanced-text')
            text.edit_modified(False)
    text.bind('<<Modified>>', text_changed)
    app.bind_text_undo(text)
    tab.editor_tracking = True
    tab.last_editor_state = tab.snapshot()
    def bind_panel(widget):
        widget.bindtags((panel_tag,) + widget.bindtags())
        for child in widget.winfo_children():
            bind_panel(child)
    bind_panel(main)
    tab.draw()
    if not force:
        tab.focus_node(name)


def split_names(value):
    return [n.strip() for n in value.split(',') if n.strip()]


def category_dialog(tab):
    app = tab.app
    dialog = tk.Toplevel(app)
    dialog.title('Create recipe category')
    dialog.transient(app)
    dialog.geometry('650x540')
    name, _, entry = field(dialog, 'Category ID')
    help_label(dialog, 'Unique internal ID used by recipes and compatible crafting machines. Use letters, numbers, underscores or hyphens.', wraplength=610)
    ttk.Label(dialog, text='Compatible producers (optional)', padding=12).pack(anchor='w')
    help_label(dialog, 'Ctrl-click or Shift-click to select producers that should accept this category. Other machine restrictions, such as fluid ports, still apply. You can also create a machine for its recipes later.', wraplength=610)
    holder = ttk.Frame(dialog, padding=12)
    holder.pack(fill='both', expand=True)
    listing = tk.Listbox(holder, selectmode='extended', exportselection=False, bg= CARD, fg=TEXT, selectbackground='#45566c')
    scrollbar = ttk.Scrollbar(holder, command=listing.yview)
    listing.configure(yscrollcommand=scrollbar.set)
    scrollbar.pack(side='right', fill='y')
    listing.pack(fill='both', expand=True)
    producers = [(kind, n) for kind in ('assembling-machine', 'furnace', 'rocket-silo', 'character') for n in sorted(app.base_raw.get(kind, {}))]
    for kind, producer in producers:
        listing.insert('end', producer + ' (' + kind + ')')
    def create():
        before = copy.deepcopy(app.project.data)
        state = tab.snapshot()
        try:
            category = identifier(name.get().strip())
            if category in app.catalog.raw.get('recipe-category', {}):
                raise ValueError('That recipe category already exists.')
            app.project.data['categories'][category] = {'producers': [list(producers[i]) for i in listing.curselection()]}
            app.project.compile(Catalog(app.base_raw))
            app.persist()
        except (ValueError, OSError, KeyError) as exc:
            app.project.data = before
            messagebox.showerror('Cannot create category', str(exc), parent=dialog)
            return
        app.record_undo('Create recipe category', tab, state, before)
        app.refresh_catalog()
        tab.tracking = False
        tab.category.set(category)
        tab.tracking = True
        tab.dirty = True
        tab.update_mode()
        tab.last_state = tab.snapshot()
        dialog.destroy()
    ttk.Button(dialog, text='Create category', command=create).pack(anchor='e', padx=12, pady=12)
    dialog.bind(sequence(app.controls['dialog_dismiss']), lambda e: dialog.destroy())
    entry.focus_set()
    return dialog
