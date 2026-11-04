"""Browse the current project's saved items, fluids and machines."""
import tkinter as tk
import copy
import weakref
from tkinter import ttk, messagebox, simpledialog

from controls import sequence, BUTTONS
from ui import help_label
from machine_model import placed_item_name
from flow import prototype_image


class CreationsTab(ttk.Frame):
    def __init__(self, app):
        super().__init__(app.tabs)
        self.app = app
        self.dirty = False
        ttk.Label(self, text='Browse creations', font=('Segoe UI', 16, 'bold'), padding=12).pack(anchor='w')
        self.query = tk.StringVar()
        ttk.Entry(self, textvariable=self.query).pack(fill='x', padx=12)
        help_label(self, 'Search IDs only (partial matches, case-insensitive). Includes creations, saved edits, and loaded-mod entries. Filter by type or Loaded/Created/Edited. Double-click to edit. Use Ctrl-click or Shift-click to select multiple entries, then Undo edits to restore their originals.', wraplength=900, padx=12)
        filters = ttk.Frame(self, padding=(12, 0, 12, 6))
        filters.pack(fill='x')
        self.kind_filter = tk.StringVar(value='All types')
        self.change_filter = tk.StringVar(value='All changes')
        for label, variable, values in [('Type', self.kind_filter, ['All types', 'item', 'fluid', 'science pack', 'ore', 'machine', 'recipe', 'technology']),
                                         ('Change', self.change_filter, ['All changes', 'Loaded', 'Created', 'Edited'])]:
            ttk.Label(filters, text=label).pack(side='left', padx=(0, 6))
            ttk.Combobox(filters, textvariable=variable, values=values, state='readonly', width=18).pack(side='left', padx=(0, 16))
        ttk.Button(filters, text='Clear filters', command=self.clear_filters).pack(side='left')
        self.technology_button = ttk.Button(filters, text='Add recipes to technology', command=self.assign_technology)
        self.technology_button.pack(side='left', padx=8)
        icons = ttk.LabelFrame(self, text='Icons', padding=(10, 6))
        icons.pack(fill='x', padx=12, pady=(0, 6))
        self.icon_size = getattr(app, 'browse_icon_size', 20)
        self.icon_size_var = tk.StringVar(value=str(self.icon_size))
        ttk.Label(icons, text='Display size (pixels)').pack(side='left', padx=(0, 8))
        size_control = ttk.Combobox(icons, textvariable=self.icon_size_var,
                                   values=(16, 20, 24, 32, 48, 64, 96, 128), width=6)
        size_control.pack(side='left')
        size_control.bind('<<ComboboxSelected>>', lambda event: self.apply_icon_size())
        size_control.bind('<Return>', lambda event: (self.apply_icon_size(), 'break')[1])
        ttk.Button(icons, text='Apply size', command=self.apply_icon_size).pack(side='left', padx=8)
        ttk.Label(icons, text='Changes icon display size in this list.', style='Help.TLabel').pack(side='left', padx=6)
        holder = ttk.Frame(self, padding=12)
        holder.pack(fill='both', expand=True)
        self.list_style = f'BrowseCreations{id(self)}.Treeview'
        ttk.Style(self).configure(self.list_style, rowheight=max(30, self.icon_size+8))
        self.list = ttk.Treeview(holder, columns=('kind', 'id', 'title', 'status', 'unlocks'), show='tree headings', selectmode='extended', style=self.list_style)
        self.list.heading('#0', text='Icon')
        self.list.column('#0', width=max(64,self.icon_size+24), stretch=False)
        for key, label in [('kind', 'Type'), ('id', 'ID'), ('title', 'Display name'), ('status', 'Change'), ('unlocks', 'Unlocked by')]:
            self.list.heading(key, text=label)
            self.list.column(key, width=200)
        scrollbar = ttk.Scrollbar(holder, orient='vertical', command=self.list.yview)
        self.list.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side='right', fill='y')
        horizontal = ttk.Scrollbar(holder, orient='horizontal', command=self.list.xview)
        self.list.configure(xscrollcommand=horizontal.set)
        horizontal.pack(side='bottom', fill='x')
        self.list.pack(fill='both', expand=True)
        self.list.bind('<Double-Button-1>', lambda e: self.edit_selected())
        self.list.bind(sequence(app.controls['picker_accept']), lambda e: self.edit_selected())
        self.list.bind('<Delete>', lambda e: self.delete_selected())
        self.list.bind('<Button-%d>' % BUTTONS[app.controls['context_button']], self.context)
        actions = ttk.Frame(self, padding=12)
        actions.pack(fill='x')
        ttk.Button(actions, text='Edit selected', command=self.edit_selected).pack(side='left')
        self.bulk_button = ttk.Button(actions, text='Edit in bulk', command=self.bulk_edit)
        self.bulk_button.pack(side='left', padx=6)
        self.diagram_button = ttk.Button(actions, text='Read recipes as diagram', command=self.read_recipe_diagrams)
        self.diagram_button.pack(side='left', padx=6)
        self.undo_button = ttk.Button(actions, text='Undo edits', command=self.undo_edit)
        self.undo_button.pack(side='left', padx=6)
        self.delete_button = ttk.Button(actions, text='Delete selected', command=self.delete_selected)
        self.delete_button.pack(side='left', padx=6)
        self.delete_mod_button = ttk.Button(actions, text='Delete from loaded mod', command=self.delete_from_mod)
        self.delete_mod_button.pack(side='left', padx=6)
        self.use_buttons = []
        for side, label in [('ingredients', 'Use as ingredient'), ('results', 'Use as product')]:
            button = ttk.Button(actions, text=label, command=lambda s=side: self.use_selected(s))
            button.pack(side='left', padx=6)
            self.use_buttons.append(button)
        self.list.bind('<<TreeviewSelect>>', lambda e: self.update_actions())
        self.status = ttk.Label(self, padding=12)
        self.status.pack(anchor='w')
        self.query_trace = self.query.trace_add('write', lambda *_: self.refresh())
        self.filter_traces = [(variable, variable.trace_add('write', lambda *_: self.refresh()))
                              for variable in (self.kind_filter, self.change_filter)]
        self.refresh()

    def clear_filters(self):
        self.kind_filter.set('All types')
        self.change_filter.set('All changes')
        self.query.set('')

    def apply_icon_size(self):
        try:
            size=int(self.icon_size_var.get())
            if not 16<=size<=128:
                raise ValueError
        except ValueError:
            messagebox.showerror('Invalid icon size', 'Choose a whole number from 16 to 128 pixels.', parent=self)
            return
        view=self.list.yview()
        self.icon_size=self.app.browse_icon_size=size
        ttk.Style(self).configure(self.list_style,rowheight=max(30,size+8))
        self.list.column('#0',width=max(64,size+24))
        self.refresh()
        if view:
            self.list.yview_moveto(view[0])

    def refresh(self):
        selected = self.list.selection()
        self.list.delete(*self.list.get_children())
        self.rows = {}
        self.images = []
        query = self.query.get().strip().casefold()
        rows = self.app.project.creations(include_edits=True)
        for key in sorted(getattr(self.app, 'loaded_items', set())):
            kind, name = key
            if name in self.app.project.data['items'] or key not in self.app.catalog.items:
                continue
            data = self.app.project.editable_item(key, self.app.catalog)
            kind = data['kind']
            data['loaded'] = True
            rows.append((kind, name, data))
        rows.extend(('recipe', name, {'loaded': True}) for name in sorted(getattr(self.app, 'loaded_recipes', set()))
                    if name not in self.app.project.data['recipes'] and name in self.app.catalog.recipes)
        from core import entries
        recipe_technologies = {}
        for technology, proto in self.app.catalog.raw.get('technology', {}).items():
            for effect in proto.get('effects', []):
                if effect.get('type') == 'unlock-recipe':
                    recipe_technologies.setdefault(effect.get('recipe'), set()).add(technology)
        mined = {(e['type'], e['name']) for resource in self.app.catalog.raw.get('resource', {}).values()
                 for e in entries(resource.get('minable', {}), 'results')}
        def unlock_description(kind, name, data):
            if kind == 'technology':
                return '—'
            key = ('item', placed_item_name(name, data)) if kind == 'machine' else ('fluid' if kind == 'fluid' else 'item', name)
            recipes = [name] if kind == 'recipe' else self.app.catalog.by_product.get(key, [])
            technologies = set()
            available = False
            found = False
            for recipe_name in recipes:
                recipe = self.app.catalog.recipes.get(recipe_name)
                if recipe is None:
                    continue
                source = recipe.get('normal', recipe)
                if kind != 'recipe' and (source.get('category') == 'recycling' or recipe_name.endswith('-recycling')):
                    continue
                found = True
                available = available or bool(source.get('enabled', True))
                technologies.update(recipe_technologies.get(recipe_name, set()))
            labels = ['Available from start'] if available else []
            if kind != 'recipe' and key in mined:
                labels.append('Mined resource')
            labels.extend(sorted(technologies))
            return '; '.join(labels) or ('Locked — no technology' if found else 'No crafting recipe')
        for kind, name, data in rows:
            proto = self.app.catalog.raw.get(kind, {}).get(name, {}) if kind in ('recipe', 'technology') else {}
            title = data.get('title') or proto.get('localised_name') or name.replace('-', ' ').title()
            if not isinstance(title, str):
                title = name.replace('-', ' ').title()
            status = 'Loaded' if data.get('loaded') else 'Edited' if data.get('operation') == 'edit' or name in self.app.base_raw.get(kind, {}) else 'Created'
            if self.kind_filter.get() not in ('All types', kind) or self.change_filter.get() not in ('All changes', status):
                continue
            unlocked_by = unlock_description(kind, name, data)
            if query and query not in name.casefold():
                continue
            row_id = kind + ':' + name
            self.rows[row_id] = (kind, name, data)
            key = ('item', placed_item_name(name, data)) if kind == 'machine' else ('fluid' if kind == 'fluid' else 'item', name)
            if kind in ('recipe', 'technology'):
                icon = prototype_image(self.app, proto, self.icon_size, data.get('icon') if kind == 'technology' else None)
                if not icon and kind == 'recipe' and data.get('results'):
                    product = data['results'][0]
                    icon = self.app.icon((product['type'], product['name']), size=self.icon_size)
            else:
                icon = self.app.icon(key, size=self.icon_size)
            options = {'image': icon} if icon else {}
            if icon:
                self.images.append(icon)
            self.list.insert('', 'end', iid=row_id, values=(kind, name, title, status, unlocked_by), **options)
        retained = [row_id for row_id in selected if row_id in self.rows]
        if retained:
            self.list.selection_set(*retained)
        self.status.configure(text=f'{len(self.rows)} creations, edits and loaded mod entries' if self.rows else 'No matching creations, edits or loaded mod entries.')
        self.update_actions()

    def update_actions(self):
        selected = self.list.selection()
        self.bulk_button.configure(state='normal' if selected else 'disabled')
        row = self.selected() if len(selected) == 1 else None
        state = 'normal' if row and row[0] not in ('recipe', 'technology') else 'disabled'
        for button in self.use_buttons:
            button.configure(state=state)
        self.delete_button.configure(state='normal' if self.can_delete(row) else 'disabled')
        self.delete_mod_button.configure(state='normal' if self.can_delete_from_mod(row) else 'disabled')
        self.technology_button.configure(state='normal' if any(self.rows.get(row_id, (None,))[0] == 'recipe' for row_id in selected) else 'disabled')
        self.undo_button.configure(state='normal' if any(self.can_undo_edit(self.rows.get(row_id)) for row_id in selected) else 'disabled')
        self.diagram_button.configure(state='normal' if any(self.rows.get(row_id, (None,))[0] == 'recipe' for row_id in selected) else 'disabled')

    def assign_technology(self):
        names = [self.rows[row_id][1] for row_id in self.list.selection()
                 if row_id in self.rows and self.rows[row_id][0] == 'recipe']
        if names:
            from recipe_unlocks import unlock_dialog
            return unlock_dialog(self, names)

    def read_recipe_diagrams(self):
        names = [self.rows[row_id][1] for row_id in self.list.selection()
                 if row_id in self.rows and self.rows[row_id][0] == 'recipe']
        return [open_recipe(self.app, name) for name in names]

    def can_delete_from_mod(self, row):
        if not row:
            return False
        kind, name, data = row
        if kind == 'recipe':
            return name in getattr(self.app, 'loaded_recipes', set())
        return kind in ('item', 'fluid', 'science pack') and (('fluid' if kind == 'fluid' else 'item', name) in getattr(self.app, 'loaded_items', set())
                    or data.get('operation') == 'edit' and name in self.app.project.data['items'])

    def can_delete(self, row):
        if row and row[0] == 'technology':
            return row[1] in self.app.catalog.raw.get('technology', {})
        return bool(row and row[0] in ('item', 'fluid', 'science pack', 'ore', 'recipe')
                    and row[1] in self.app.project.data['recipes' if row[0] == 'recipe' else 'items'])

    def can_undo_edit(self, row):
        if not row:
            return False
        kind, name, data = row
        if kind in ('recipe', 'technology'):
            group = 'recipes' if kind == 'recipe' else 'technologies'
            return name in self.app.project.data[group] and name in self.app.base_raw.get(kind, {})
        if kind == 'machine':
            return data.get('operation') == 'edit' and name in self.app.base_raw.get(data.get('entity_type', 'assembling-machine'), {})
        return data.get('operation') == 'edit' and name in self.app.project.data['items']

    def bulk_edit(self):
        rows = [self.rows[i] for i in self.list.selection() if i in self.rows]
        if not rows:
            return
        from editors import field
        from ui import scroll_form
        dialog = tk.Toplevel(self.app)
        dialog.title('Edit creations in bulk')
        dialog.transient(self.app)
        dialog.geometry('730x700')
        footer = ttk.Frame(dialog, padding=12)
        footer.pack(side='bottom', fill='x')
        body = scroll_form(dialog)
        ttk.Label(body, text=f'Edit {len(rows)} selected entries', padding=12,
                  font=('Segoe UI', 13, 'bold')).pack(anchor='w')
        help_label(body, 'Tick only the fields you want to change. Each section applies to its matching types; other values stay unchanged. Ctrl+Z restores the entire batch. Open editor drafts are preserved; reopen an entry to see these saved changes.', wraplength=660)
        groups = {self.bulk_group(row[0]) for row in rows}
        definitions = {
            'items': [('description', 'Description', ''), ('stack_size', 'Stack size', '100'),
                      ('subgroup', 'Inventory subgroup', 'intermediate-product'),
                      ('fuel_value', 'Fuel value', ''), ('fuel_category', 'Fuel category', 'chemical'),
                      ('finished_product', 'Finished product', 'Yes')],
            'recipes': [('seconds', 'Crafting seconds', '1'), ('category', 'Recipe category', 'crafting')],
            'technologies': [('count', 'Research count', '100'), ('time', 'Research time', '30')],
            'machines': [('health', 'Health', '300'), ('stack_size', 'Stack size', '50')],
        }
        fields = {}
        for group in definitions:
            if group not in groups:
                continue
            ttk.Label(body, text={'items': 'Items / fluids / science packs / ores', 'recipes': 'Recipes',
                                 'technologies': 'Technologies (science research only)', 'machines': 'Machines'}[group],
                      padding=12, font=('Segoe UI', 11, 'bold')).pack(anchor='w')
            for key, label, default in definitions[group]:
                enabled = tk.BooleanVar(value=False)
                ttk.Checkbutton(body, text='Change ' + label.lower(), variable=enabled).pack(anchor='w', padx=16)
                value, holder, entry = field(body, label, default)
                options = None
                if key == 'finished_product':
                    options = ['Yes', 'No']
                elif key in ('subgroup', 'fuel_category', 'category'):
                    prototype = {'subgroup': 'item-subgroup', 'fuel_category': 'fuel-category', 'category': 'recipe-category'}[key]
                    options = sorted(self.app.catalog.raw.get(prototype, {}))
                if options is not None:
                    entry.destroy()
                    ttk.Combobox(holder, textvariable=value, values=options, state='readonly').pack(fill='x')
                fields[group, key] = enabled, value
        def apply():
            changes = {}
            for (group, key), (enabled, value) in fields.items():
                if enabled.get():
                    changes.setdefault(group, {})[key] = value.get()
            if changes and self.apply_bulk_edits(rows, changes):
                dialog.destroy()
        ttk.Button(footer, text='Apply to selected', command=apply).pack(side='right')
        ttk.Button(footer, text='Cancel', command=dialog.destroy).pack(side='right', padx=8)
        return dialog

    @staticmethod
    def bulk_group(kind):
        return {'recipe': 'recipes', 'technology': 'technologies', 'machine': 'machines'}.get(kind, 'items')

    def apply_bulk_edits(self, rows, changes):
        from core import Catalog, Recipe
        from project import positive, fuel_energy
        before = copy.deepcopy(self.app.project.data)
        project, catalog = self.app.project, self.app.catalog
        updated = 0
        try:
            for kind, name, data in rows:
                group = self.bulk_group(kind)
                values = changes.get(group, {})
                if not values:
                    continue
                if group == 'items':
                    key = ('fluid' if kind == 'fluid' else 'item', name)
                    item = project.editable_item(key, catalog)
                    for field, value in values.items():
                        if field == 'stack_size':
                            value = positive(value, 'Stack size', True)
                            if kind == 'fluid':
                                continue
                        elif field == 'fuel_value':
                            value = fuel_energy(value)
                        elif field == 'finished_product':
                            value = value in (True, 'Yes')
                        elif field in ('subgroup', 'fuel_category'):
                            prototype = 'item-subgroup' if field == 'subgroup' else 'fuel-category'
                            if value not in catalog.raw.get(prototype, {}):
                                raise ValueError('Choose a loaded ' + field.replace('_', ' ') + '.')
                            if field == 'fuel_category' and kind == 'fluid':
                                continue
                            if field == 'fuel_category' and item.get('fuel_categories'):
                                item['fuel_categories'] = [value]
                        elif field != 'description':
                            raise ValueError('Unsupported item field: ' + field)
                        item[field] = value
                    project.data['items'][name] = item
                elif group == 'recipes':
                    if set(values) - {'seconds', 'category'}:
                        raise ValueError('Unsupported recipe field.')
                    if name not in project.data['recipes']:
                        proto = self.app.base_raw.get('recipe', {}).get(name, catalog.recipes[name])
                        source = proto.get('normal', proto)
                        project.save_recipe(Recipe(name, proto), name, source.get('energy_required', .5),
                                            source.get('enabled', True), category=source.get('category', 'crafting'))
                    saved = project.data['recipes'][name]
                    if 'seconds' in values:
                        saved['seconds'] = positive(values['seconds'], 'Crafting seconds')
                    if 'category' in values:
                        if values['category'] not in catalog.raw.get('recipe-category', {}):
                            raise ValueError('Choose a loaded recipe category.')
                        saved['category'] = values['category']
                elif group == 'technologies':
                    if set(values) - {'count', 'time'}:
                        raise ValueError('Unsupported technology field.')
                    record = copy.deepcopy(project.data['technologies'].get(name, {'prototype': catalog.raw['technology'][name]}))
                    proto = record['prototype']
                    if proto.get('research_trigger'):
                        raise ValueError(name + ' uses a research trigger, not science research.')
                    for field, value in values.items():
                        proto.setdefault('unit', {})[field] = positive(value, 'Research ' + field, field == 'count')
                        if field == 'count':
                            proto['unit'].pop('count_formula', None)
                    project.validate_technology(proto, catalog, name)
                    project.data['technologies'][name] = record
                else:
                    if set(values) - {'health', 'stack_size'}:
                        raise ValueError('Unsupported machine field.')
                    machine = project.data['machines'][name]
                    for field, value in values.items():
                        machine[field] = positive(value, field.replace('_', ' ').title(), True)
                updated += 1
            if not updated:
                return False
            project.compile(Catalog(self.app.base_raw))
            self.app.persist()
        except (ValueError, OSError, KeyError) as exc:
            project.data = before
            messagebox.showerror('Cannot bulk edit creations', str(exc), parent=self)
            return False
        self.app.record_undo('Bulk edit creations', self, self.snapshot(), before)
        self.app.refresh_catalog()
        self.status.configure(text=f'Updated {updated} entries. Ctrl+Z restores the entire batch.')
        return True

    def selected(self):
        selection = self.list.selection()
        return self.rows.get(selection[0]) if selection else None

    def context(self, event):
        row_id = self.list.identify_row(event.y)
        row = self.rows.get(row_id)
        if not row:
            return
        if row_id not in self.list.selection():
            self.list.selection_set(row_id)
        self.update_actions()
        kind, name, data = row
        key = ('item', placed_item_name(name, data)) if kind == 'machine' else ('fluid' if kind == 'fluid' else 'item', name)
        if hasattr(self, 'context_menu'):
            self.context_menu.destroy()
        menu = tk.Menu(self, tearoff=False)
        self.context_menu = menu
        menu.add_command(label='Edit in bulk', command=self.bulk_edit)
        if kind == 'recipe':
            menu.add_command(label='Rename recipe', command=lambda: rename_recipe(self, name))
            menu.add_command(label='Read recipes as diagram', command=self.read_recipe_diagrams)
            if len(self.list.selection()) == 1:
                from delete_items import delete_recipe
                menu.add_command(label='Delete this recipe', command=lambda: delete_recipe(self, name))
        if kind == 'technology' and len(self.list.selection()) == 1:
            from delete_items import delete_technology
            menu.add_command(label='Delete technology', command=lambda: delete_technology(self, name))
        if kind not in ('recipe', 'technology'):
            menu.add_command(label='Edit item' if key[0] == 'item' else 'Edit fluid', command=lambda: edit_item(self, key))
            menu.add_command(label='Rename item' if key[0] == 'item' else 'Rename fluid', command=lambda: rename_item(self, key))
            menu.add_command(label='Open recipe', command=lambda: open_item_recipe(self.app, key))
            if key[0] == 'item':
                menu.add_command(label='Convert to machine', command=lambda: convert_to_machine(self, key))
            menu.add_command(label='See all recipes containing this item' if key[0] == 'item' else 'See all recipes containing this fluid',
                             command=lambda: recipes_containing(self.app, key))
            menu.add_command(label='Load all direct recipes', command=lambda: load_direct_recipes(self.app, key))
            menu.add_command(label='Open all recipes containing this item' if key[0] == 'item' else 'Open all recipes containing this fluid',
                             command=lambda: open_all_recipes_containing(self.app, key))
        if any(self.rows.get(selected, (None,))[0] == 'recipe' for selected in self.list.selection()):
            menu.add_command(label='Add selected recipes to technology', command=self.assign_technology)
        multiple = len(self.list.selection()) > 1
        if any(self.can_undo_edit(self.rows.get(selected)) for selected in self.list.selection()):
            menu.add_command(label='Undo selected edits' if multiple else 'Undo edit', command=self.undo_edit)
        elif not multiple and kind != 'technology' and self.can_delete(row):
            menu.add_command(label='Delete ' + kind, command=self.delete_selected)
        if not multiple and self.can_delete_from_mod(row):
            menu.add_command(label='Delete from loaded mod', command=self.delete_from_mod)
        if not multiple and kind not in ('recipe', 'technology', 'machine') and (self.can_delete(row) or self.can_delete_from_mod(row)):
            from delete_items import delete_with_recipes
            menu.add_command(label='Delete item and recipes containing it' if key[0] == 'item' else 'Delete fluid and recipes containing it', command=lambda: delete_with_recipes(self, key))
        if menu.index('end') is not None:
            menu.tk_popup(event.x_root, event.y_root)
        # tk_popup returns before the user selects an entry. Keep the menu
        # alive so its commands remain clickable after this handler returns.

    def undo_edit(self):
        rows = [self.rows[row_id] for row_id in self.list.selection()
                if self.can_undo_edit(self.rows.get(row_id))]
        if not rows:
            return False
        from core import Catalog
        app = self.app
        before = copy.deepcopy(app.project.data)
        related = []
        updates = []
        recipe_names = {name for kind, name, _ in rows if kind == 'recipe'}
        item_names = {name for kind, name, _ in rows if kind not in ('recipe', 'technology', 'machine')}
        technologies = {name for kind, name, _ in rows if kind == 'technology'}
        machines = {name: data for kind, name, data in rows if kind == 'machine'}
        try:
            for tab in app.tabs.winfo_children():
                recipe = hasattr(tab, 'loaded_name') and (tab.loaded_name in recipe_names or tab.saved_key in recipe_names)
                item = bool(getattr(tab, 'item_draft', None) and tab.item_draft.get('name') in item_names)
                tech = hasattr(tab, 'editor_vars') and getattr(tab, 'selected', None) in technologies
                machine = hasattr(tab, 'entity_type') and getattr(tab, 'saved_name', None) in machines
                if recipe or item or tech or machine:
                    related.append((tab, tab.snapshot()))
                    updates.append((tab, recipe, item, tech, tab.saved_name if machine else None))
            for kind, name, _ in rows:
                group = {'recipe': 'recipes', 'technology': 'technologies', 'machine': 'machines'}.get(kind, 'items')
                app.project.data[group].pop(name)
            if any(app.project.data[group] for group in ('items', 'recipes', 'technologies', 'machines', 'deleted')):
                app.project.compile(Catalog(app.base_raw))
            app.persist()
        except (ValueError, OSError, KeyError) as exc:
            app.project.data = before
            messagebox.showerror('Cannot undo edits', str(exc), parent=self)
            return False
        app.record_undo('Undo edits: ' + ', '.join(name for _, name, _ in rows), self, self.snapshot(), before)
        app.undo_stack[-1]['related'] = [(weakref.ref(tab), state) for tab, state in related]
        app.refresh_catalog()
        for tab, recipe, item, tech, machine in updates:
            if recipe:
                name = tab.loaded_name if tab.loaded_name in recipe_names else tab.saved_key
                tab.tracking = False
                tab.load(name)
            if item:
                state = tab.snapshot()
                state['item_draft'] = None
                tab.restore(state)
            if tech:
                from editors import technology_dialog
                technology_dialog(tab, tab.selected, force=True)
            if machine:
                name = machine
                tab.configure_source(machines[name].get('entity_type', 'assembling-machine'), name, 'edit')
        self.set_deletion_status(f'Restored {len(rows)} original entries. New creations and unedited entries were kept. Ctrl+Z restores the entire batch.')
        return True

    def delete_from_mod(self, row=None):
        if row is None:
            if len(self.list.selection()) != 1:
                return False
            row = self.selected()
        if not CreationsTab.can_delete_from_mod(self, row):
            return False
        from core import Catalog, Recipe, entries
        kind, name, data = row
        app = self.app
        before = copy.deepcopy(app.project.data)
        related = []
        try:
            blockers = []
            if kind == 'recipe':
                prototype_type = 'recipe'
                blockers.extend('Machine: ' + n for n, m in app.project.data['machines'].items() if name in m.get('recipes', []))
                for group, prototypes in app.catalog.raw.items():
                    for n, proto in prototypes.items():
                        if proto.get('fixed_recipe') == name:
                            blockers.append(group + ': ' + n + ' (fixed recipe)')
            else:
                key = ('fluid' if kind == 'fluid' else 'item', name)
                original = app.catalog.items[key]
                prototype_type = original['type']
                for n, proto in app.catalog.recipes.items():
                    if any((e['type'], e['name']) == key for e in entries(proto, 'ingredients') + entries(proto, 'results')):
                        blockers.append('Recipe: ' + n)
                for tab in app.tabs.winfo_children():
                    if hasattr(tab, 'loaded_name') and any((e['type'], e['name']) == key for e in tab.recipe.ingredients + tab.recipe.results):
                        blockers.append('Open flowchart: ' + tab.name.get())
                for group, prototypes in app.catalog.raw.items():
                    if group == 'recipe':
                        continue
                    for n, proto in prototypes.items():
                        references = []
                        if key[0] == 'item':
                            references.extend(e['name'] for e in entries(proto.get('minable', {}), 'results') if e['type'] == 'item')
                            references.extend(e.get('item') for e in proto.get('loot', []))
                            references.extend(proto.get(field) for field in ('burnt_result', 'spoil_result'))
                            references.extend(e.get('name') for e in proto.get('rocket_launch_products', []) if isinstance(e, dict))
                            if group == 'technology':
                                references.extend(e.get('name') if isinstance(e, dict) else e[0] for e in proto.get('unit', {}).get('ingredients', []))
                        elif proto.get('minable', {}).get('required_fluid') == name:
                            references.append(name)
                        if key[0] == 'fluid':
                            def fluid_reference(value):
                                if isinstance(value, dict):
                                    if any(value.get(field) == name for field in ('filter', 'fluid', 'input_fluid_filter', 'output_fluid_filter')):
                                        return True
                                    return any(fluid_reference(child) for child in value.values() if isinstance(child, (list, dict)))
                                return any(fluid_reference(child) for child in value) if isinstance(value, list) else False
                            if fluid_reference(proto):
                                references.append(name)
                        if name in references:
                            blockers.append(group + ': ' + n)
            if blockers:
                raise ValueError('Remove or edit these references before deleting from the mod:\n\n' + '\n'.join(sorted(set(blockers))))
            group = 'recipes' if kind == 'recipe' else 'items'
            app.project.data[group].pop(name, None)
            app.project.data.setdefault('deleted', {}).setdefault(prototype_type, {})[name] = True
            if kind == 'recipe':
                for tab in app.tabs.winfo_children():
                    if hasattr(tab, 'loaded_name') and (tab.loaded_name == name or tab.saved_key == name):
                        related.append((tab, tab.snapshot()))
            app.project.compile(Catalog(app.base_raw))
            app.persist()
            app.record_undo('Delete loaded ' + kind, self, self.snapshot(), before)
            app.undo_stack[-1]['related'] = [(weakref.ref(tab), state) for tab, state in related]
            app.refresh_catalog()
            for tab, prior in related:
                tab.restore(dict(prior, recipe=Recipe('new-recipe', {'ingredients': [], 'results': []}), name='new-recipe',
                                 loaded_name=None, saved_key=None, result_machine=None, item_draft=None, is_custom=True, dirty=False, auto_name=True, enabled=False, availability_override=False, expanded_recipes={}))
            self.set_deletion_status('Deleted ' + name + ' from the exported mod. Ctrl+Z restores it.')
            return True
        except (ValueError, OSError, KeyError) as exc:
            app.project.data = before
            messagebox.showerror('Cannot delete from loaded mod', str(exc), parent=self)
            return False

    def delete_selected(self, row=None):
        if row is None:
            if len(self.list.selection()) != 1:
                return False
            row = self.selected()
        if row and row[0] == 'technology':
            from delete_items import delete_technology
            return delete_technology(self, row[1])
        if not CreationsTab.can_delete(self, row):
            return False
        from core import Catalog, Recipe
        kind, name, data = row
        before = copy.deepcopy(self.app.project.data)
        related = []
        try:
            if kind != 'recipe' and data.get('operation') == 'edit':
                del self.app.project.data['items'][name]
            elif kind != 'recipe':
                key = ('fluid' if kind == 'fluid' else 'item', name)
                from core import entries
                blockers = ['Recipe: ' + n for n, p in self.app.catalog.recipes.items()
                            if any((e['type'], e['name']) == key for e in entries(p, 'ingredients') + entries(p, 'results'))]
                for tab in self.app.tabs.winfo_children():
                    if hasattr(tab, 'loaded_name') and any((e['type'], e['name']) == key for e in tab.recipe.ingredients + tab.recipe.results):
                        blockers.append('Open flowchart: ' + tab.name.get())
                if kind == 'science pack':
                    for tech_name, proto in self.app.catalog.raw.get('technology', {}).items():
                        if any((e.get('name') if isinstance(e, dict) else e[0]) == name for e in proto.get('unit', {}).get('ingredients', [])):
                            blockers.append('Technology: ' + tech_name)
                if blockers:
                    raise ValueError('Remove references before deleting this creation:\n\n' + '\n'.join(sorted(set(blockers))))
                del self.app.project.data['items'][name]
            else:
                if name not in self.app.base_raw.get('recipe', {}):
                    blockers = ['Machine: ' + n for n, machine in self.app.project.data['machines'].items() if name in machine.get('recipes', [])]
                    blockers.extend('Technology: ' + n for n, proto in self.app.catalog.raw.get('technology', {}).items()
                                    if any(e.get('type') == 'unlock-recipe' and e.get('recipe') == name for e in proto.get('effects', [])))
                    if blockers:
                        raise ValueError('Remove references before deleting this recipe:\n\n' + '\n'.join(blockers))
                del self.app.project.data['recipes'][name]
                for tab in self.app.tabs.winfo_children():
                    if hasattr(tab, 'loaded_name') and (tab.loaded_name == name or tab.saved_key == name):
                        related.append((tab, tab.snapshot()))
            if any(self.app.project.data[group] for group in ('items', 'recipes', 'technologies', 'machines')):
                self.app.project.compile(Catalog(self.app.base_raw))
            self.app.persist()
            self.app.record_undo('Delete ' + kind, self, self.snapshot(), before)
            self.app.undo_stack[-1]['related'] = [(weakref.ref(tab), state) for tab, state in related]
            self.app.refresh_catalog()
            for tab, prior in related:
                if name in self.app.catalog.recipes:
                    tab.tracking = False
                    tab.load(name)
                else:
                    state = dict(prior, recipe=Recipe('new-recipe', {'type': 'recipe', 'name': 'new-recipe', 'ingredients': [], 'results': []}),
                                 name='new-recipe', loaded_name=None, saved_key=None, result_machine=None, item_draft=None, is_custom=True, dirty=False, auto_name=True, enabled=False, availability_override=False, expanded_recipes={})
                    tab.restore(state)
            reverted = data.get('operation') == 'edit' or kind == 'recipe' and name in self.app.base_raw.get('recipe', {})
            self.set_deletion_status('Removed saved edit for ' + name + '; the loaded original is restored. Ctrl+Z restores the edit.' if reverted else 'Deleted ' + name + '. Ctrl+Z restores it.')
            return True
        except (ValueError, OSError, KeyError) as exc:
            self.app.project.data = before
            messagebox.showerror('Cannot delete creation', str(exc), parent=self)
            return False

    def set_deletion_status(self, text):
        self.status.configure(text=text)

    def edit_selected(self):
        row = self.selected()
        if row:
            kind, name, data = row
            if kind == 'machine':
                self.app.new_machine_tab(name=name)
            elif kind == 'recipe':
                open_recipe(self.app, name)
            elif kind == 'technology':
                self.app.tech_tab().edit(name)
            else:
                from editors import item_dialog
                item_dialog(self, data)

    def use_selected(self, side):
        row = self.selected()
        if row and row[0] not in ('recipe', 'technology'):
            kind, name, data = row
            key = ('item', placed_item_name(name, data)) if kind == 'machine' else ('fluid' if kind == 'fluid' else 'item', name)
            self.app.new_tab().add_entry(side, key)

    def snapshot(self):
        return {}

    def restore(self, state):
        self.refresh()

    def close(self):
        self.destroy()

    def save_changes(self, quiet=False):
        return True

    def destroy(self):
        if hasattr(self, 'query_trace'):
            self.query.trace_remove('write', self.query_trace)
            del self.query_trace
        for variable, trace in getattr(self, 'filter_traces', []):
            variable.trace_remove('write', trace)
        self.filter_traces = []
        super().destroy()


def open_recipe(app, name):
    for tab in app.tabs.winfo_children():
        if hasattr(tab, 'loaded_name') and (tab.loaded_name == name or getattr(tab, 'saved_key', None) == name):
            app.tabs.select(tab)
            return tab
    tab = app.new_tab()
    tab.load(name)
    return tab


def open_item_recipe(app, key):
    names = sorted(app.catalog.by_product.get(key, []), key=lambda name: ('recycling' in name.casefold(), name))
    if not names:
        tab = app.new_tab()
        tab.add_entry('results', key)
        return tab
    if len(names) == 1:
        return open_recipe(app, names[0])
    dialog = tk.Toplevel(app)
    dialog.title('Choose crafting recipe')
    dialog.transient(app)
    ttk.Label(dialog, text='Recipes producing ' + key[1], padding=12).pack(anchor='w')
    listing = tk.Listbox(dialog, width=70, height=min(15, len(names)), bg='#273240', fg='#e6edf3')
    listing.pack(fill='both', expand=True, padx=12, pady=8)
    for name in names:
        listing.insert('end', name)
    listing.selection_set(0)
    def choose(*_):
        selected = listing.curselection()
        if selected:
            name = names[selected[0]]
            dialog.destroy()
            return open_recipe(app, name)
    listing.bind('<Double-Button-%d>' % BUTTONS[app.controls['picker_button']], choose)
    listing.bind(sequence(app.controls['picker_accept']), choose)
    ttk.Button(dialog, text='Open recipe', command=choose).pack(anchor='e', padx=12, pady=12)
    return dialog


def convert_to_machine(owner, key):
    app = owner.app
    proto = app.catalog.items.get(key)
    if key[0] != 'item' or proto is None:
        return False
    name = key[1]
    if name in app.project.data['machines'] or name in app.project.data['machine_drafts']:
        app.new_machine_tab(name=name)
        return True
    if proto.get('type') != 'item' or proto.get('place_result') or name in app.catalog.raw.get('resource', {}):
        messagebox.showerror('Cannot convert item', 'Choose a normal, non-placeable item. Science packs, ores, equipment items and existing buildings keep their specialized behavior.', parent=owner)
        return False
    from machine_model import zero_config
    from core import Catalog
    before = copy.deepcopy(app.project.data)
    config = zero_config()
    item = app.project.editable_item(key, app.catalog)
    config.update(title=item.get('title', name), description=item.get('description', ''), stack_size=item.get('stack_size', 50),
                  converted_item=name, converted_original=copy.deepcopy(proto))
    if item.get('icon'):
        config.update(icon=copy.deepcopy(item['icon']), icon_path=item.get('icon_path', ''))
    else:
        config['icon'] = None
    try:
        app.project.data['machine_drafts'][name] = config
        if any(app.project.data[group] for group in ('items', 'recipes', 'machines', 'technologies', 'categories', 'deleted')):
            app.project.compile(Catalog(app.base_raw))
        app.persist()
    except (OSError, ValueError, KeyError) as exc:
        app.project.data = before
        messagebox.showerror('Cannot convert item', str(exc), parent=owner)
        return False
    app.record_undo('Convert item to machine', owner, owner.snapshot(), before)
    app.refresh_catalog()
    app.new_machine_tab(name=name)
    return True


def rename_item(owner, key, title=None, new_id=None):
    from core import Catalog
    app = owner.app
    if key not in app.catalog.items:
        return False
    item = app.project.editable_item(key, app.catalog)
    machine = next((name for name, data in app.project.data['machines'].items()
                    if key == ('item', placed_item_name(name, data))), None)
    editable_id = item.get('operation') != 'edit' and machine is None and key[1] not in app.project.data['machine_drafts']
    if title is None:
        from editors import field
        dialog = tk.Toplevel(app)
        dialog.title('Rename item' if key[0] == 'item' else 'Rename fluid')
        dialog.transient(app)
        current_title = app.project.data['machines'][machine].get('title', item['title']) if machine else item['title']
        title_var, _, entry = field(dialog, 'Display name', current_title)
        id_var, _, id_entry = field(dialog, 'Item ID', key[1])
        if not editable_id:
            id_entry.configure(state='readonly')
            help_label(dialog, 'Loaded items and machine items keep their internal ID. You can change their display name.', wraplength=580)
        else:
            help_label(dialog, 'Changing the ID updates saved recipe references and open flowcharts. Display name is what players see.', wraplength=580)
        def save():
            if rename_item(owner, key, title_var.get(), id_var.get()):
                dialog.destroy()
        ttk.Button(dialog, text='Rename', command=save).pack(anchor='e', padx=16, pady=12)
        entry.focus_set(); entry.selection_range(0, 'end')
        return dialog
    before = copy.deepcopy(app.project.data)
    state = owner.snapshot()
    related = []
    try:
        title = title.strip()
        if not title:
            raise ValueError('Enter a display name.')
        new_id = key[1] if new_id is None else new_id.strip()
        if not editable_id and new_id != key[1]:
            raise ValueError('Loaded items and machine items keep their internal ID. Change the display name instead.')
        if machine:
            app.project.data['machines'][machine]['title'] = title
            remap = (key, key)
        else:
            app.project.data['items'].setdefault(key[1], copy.deepcopy(item))
            item.update(name=new_id, title=title)
            remap = app.project.update_creation(key[1], item, app.catalog)
            if key[1] in app.project.data['machine_drafts']:
                app.project.data['machine_drafts'][key[1]]['title'] = title
        if remap[0] != remap[1]:
            for tab in app.tabs.winfo_children():
                if not hasattr(tab, 'recipe') or not hasattr(tab, 'loaded_name'):
                    continue
                prior = tab.snapshot(); changed = copy.deepcopy(prior)
                for entry in changed['recipe'].ingredients + changed['recipe'].results:
                    if (entry['type'], entry['name']) == remap[0]:
                        entry.update(type=remap[1][0], name=remap[1][1])
                for entry in changed.get('expanded_recipes', {}).values():
                    if tuple(entry['key']) == remap[0]:
                        entry['key'] = remap[1]
                if changed.get('item_draft') and changed['item_draft'].get('name') == key[1]:
                    changed['item_draft'] = copy.deepcopy(item)
                if changed.get('auto_name') and not changed['loaded_name'] and not changed['saved_key'] and changed['recipe'].results:
                    changed['name'] = changed['recipe'].results[0]['name'] + '_recipe'
                if changed.get('direct_key') == remap[0]:
                    changed['direct_key'] = remap[1]
                related.append((tab, prior, changed))
        app.project.compile(Catalog(app.base_raw))
        app.persist()
    except (ValueError, OSError, KeyError) as exc:
        app.project.data = before
        messagebox.showerror('Cannot rename item', str(exc), parent=owner)
        return False
    app.record_undo('Rename item: ' + key[1], owner, state, before)
    app.undo_stack[-1]['related'] = [(weakref.ref(tab), prior) for tab, prior, _ in related if tab is not owner]
    for tab, _, changed in related:
        tab.restore(changed)
    app.refresh_catalog()
    return True


def edit_item(owner, key):
    if key not in owner.app.catalog.items:
        return None
    if key[0] == 'item' and key[1] in owner.app.project.data['machine_drafts']:
        return owner.app.new_machine_tab(name=key[1])
    from machine_model import placed_item_name
    machine = next((name for name, data in owner.app.project.data['machines'].items()
                    if key == ('item', placed_item_name(name, data))), None)
    if machine:
        return owner.app.new_machine_tab(name=machine)
    from editors import item_dialog
    return item_dialog(owner, owner.app.project.editable_item(key, owner.app.catalog))


def open_all_recipes_containing(app, key):
    from core import entries
    names = sorted(name for name, proto in app.catalog.recipes.items()
                   if any((entry['type'], entry['name']) == key
                          for entry in entries(proto, 'ingredients') + entries(proto, 'results')))
    if not names:
        messagebox.showinfo('No matching recipes', 'No loaded recipes contain ' + key[1] + '.', parent=app)
        return None
    return app.direct_recipes_tab(key, names, containing=True)


def load_direct_recipes(app, key):
    from core import entries
    names = sorted(name for name, proto in app.catalog.recipes.items()
                   if (ingredients := entries(proto, 'ingredients'))
                   and all((entry['type'], entry['name']) == key for entry in ingredients))
    if not names:
        messagebox.showinfo('No direct recipes', 'No loaded recipes use only ' + key[1] + ' as their ingredient.', parent=app)
        return None
    return app.direct_recipes_tab(key, names)


def recipes_containing(app, key):
    """Search resolved base/mod/project recipes by exact item type and ID."""
    from core import entries
    dialog = tk.Toplevel(app)
    dialog.title('Recipes containing ' + key[1])
    dialog.transient(app)
    dialog.geometry('760x520')
    ttk.Label(dialog, text=key[1], font=('Segoe UI', 14, 'bold'), padding=12).pack(anchor='w')
    query = tk.StringVar()
    ttk.Entry(dialog, textvariable=query).pack(fill='x', padx=12)
    help_label(dialog, 'Search matching recipe IDs from the loaded game, mods and saved edits. Double-click a recipe to open its flowchart.', wraplength=700, padx=12)
    role = tk.StringVar(value='Ingredient or product')
    ttk.Combobox(dialog, textvariable=role, values=['Ingredient or product', 'Ingredient', 'Product'], state='readonly').pack(anchor='w', padx=12, pady=6)
    holder = ttk.Frame(dialog, padding=12)
    holder.pack(fill='both', expand=True)
    listing = ttk.Treeview(holder, columns=('recipe', 'role'), show='headings', selectmode='browse')
    listing.heading('recipe', text='Recipe ID')
    listing.heading('role', text='Used as')
    listing.column('recipe', width=480)
    listing.column('role', width=170)
    scrollbar = ttk.Scrollbar(holder, orient='vertical', command=listing.yview)
    listing.configure(yscrollcommand=scrollbar.set)
    scrollbar.pack(side='right', fill='y')
    listing.pack(fill='both', expand=True)
    count = ttk.Label(dialog, padding=(12, 0))
    count.pack(anchor='w')
    def refresh(*_):
        matches = []
        for name, prototype in app.catalog.recipes.items():
            ingredient = any((entry['type'], entry['name']) == key for entry in entries(prototype, 'ingredients'))
            product = any((entry['type'], entry['name']) == key for entry in entries(prototype, 'results'))
            if ingredient or product:
                matches.append((name, ingredient, product))
        listing.delete(*listing.get_children())
        for name, ingredient, product in sorted(matches):
            if not all(term in name.lower() for term in query.get().lower().split()):
                continue
            if role.get() == 'Ingredient' and not ingredient or role.get() == 'Product' and not product:
                continue
            listing.insert('', 'end', iid=name, values=(name, 'Ingredient + product' if ingredient and product else 'Ingredient' if ingredient else 'Product'))
        count.configure(text=f'{len(listing.get_children())} matching recipes' if listing.get_children() else 'No recipes contain this item or fluid.')
    def choose(*_):
        selection = listing.selection()
        if selection:
            open_recipe(app, selection[0])
            dialog.destroy()
    listing.bind('<Double-Button-%d>' % BUTTONS[app.controls['picker_button']], choose)
    listing.bind(sequence(app.controls['picker_accept']), choose)
    def context(event):
        name = listing.identify_row(event.y)
        if not name:
            return
        listing.selection_set(name)
        if hasattr(dialog, 'context_menu'):
            dialog.context_menu.destroy()
        dialog.context_menu = tk.Menu(dialog, tearoff=False)
        def rename():
            owner = app.nametowidget(app.tabs.select())
            if rename_recipe(owner, name):
                refresh()
        dialog.context_menu.add_command(label='Rename recipe', command=rename)
        dialog.context_menu.tk_popup(event.x_root, event.y_root)
    listing.bind('<Button-%d>' % BUTTONS[app.controls['context_button']], context)

    ttk.Button(dialog, text='Open recipe', command=choose).pack(anchor='e', padx=12, pady=12)
    traces = [(variable, variable.trace_add('write', refresh)) for variable in (query, role)]
    def cleanup(event):
        if event.widget is dialog:
            for variable, trace in traces:
                variable.trace_remove('write', trace)
            traces.clear()
    dialog.bind('<Destroy>', cleanup, add='+')
    dialog.bind(sequence(app.controls['dialog_dismiss']), lambda e: dialog.destroy())
    refresh()
    return dialog


def rename_recipe(owner, old, new=None):
    app = owner.app
    if new is None:
        new = simpledialog.askstring('Rename recipe', 'New recipe ID (letters, numbers, underscores or hyphens):', initialvalue=old, parent=owner)
    if new is None or new.strip() == old:
        return False
    new = new.strip()
    from project import identifier
    before = copy.deepcopy(app.project.data)
    states = [(tab, tab.snapshot()) for tab in app.tabs.winfo_children() if hasattr(tab, 'snapshot')]
    replace = False
    try:
        identifier(new)
        if old not in app.catalog.recipes and hasattr(owner, 'loaded_name') and not owner.loaded_name:
            if new in app.catalog.recipes:
                raise ValueError('That recipe ID already exists.')
            owner.name.set(new)
            return True
        if new in app.catalog.recipes or new in app.project.data['recipes']:
            replace = messagebox.askyesno('Recipe ID already exists',
                f'Replace the existing recipe "{new}" with "{old}"? Technology and machine references will use the renamed recipe. '
                'Other editors for the replaced recipe will reload. Ctrl+Z restores both recipes and editor drafts.', parent=owner)
            if not replace:
                return False
        app.project.rename_recipe(old, new, app.catalog, app.base_raw, replace=replace)
        app.project.compile(type(app.catalog)(app.base_raw))
        app.persist()
    except (ValueError, OSError, KeyError) as exc:
        app.project.data = before
        messagebox.showerror('Cannot rename recipe', str(exc), parent=owner)
        return False
    app.record_undo('Rename recipe: ' + old, owner, owner.snapshot(), before)
    app.undo_stack[-1]['related'] = [(weakref.ref(tab), state) for tab, state in states]
    app.refresh_catalog()
    for tab, state in states:
        state = copy.deepcopy(state)
        if 'loaded_name' in state:
            if replace and (state.get('loaded_name') == new or state.get('saved_key') == new):
                tab.tracking = False
                tab.load(new)
                continue
            renamed_root = state.get('loaded_name') == old or state.get('saved_key') == old
            for key in ('loaded_name', 'saved_key', 'name'):
                if state.get(key) == old:
                    state[key] = new
            if renamed_root:
                saved = app.project.data['recipes'][new]
                state['is_custom'] = bool(saved.get('custom'))
                # Preserve unsaved ingredient/result edits while rebasing the
                # source metadata used by subsequent saves under a reused ID.
                rebased = app.project.recipe(new)
                rebased.ingredients = state['recipe'].ingredients
                rebased.results = state['recipe'].results
                state['recipe'] = rebased
            for entry in state.get('expanded_recipes', {}).values():
                if entry['name'] == old:
                    entry['name'] = new
            if 'direct_roots' in state:
                state['direct_roots'] = {path: new if name == old else name for path, name in state['direct_roots'].items()}
            tab.restore(state)
        elif 'last_plan' in state and state['last_plan']:
            for row in state['last_plan']['recipes']:
                if row['name'] == old:
                    row['name'] = new
                    row['prototype']['name'] = new
            tab.restore(state)
        elif 'values' in state:
            for field in ('recipes', 'unlocks'):
                if field in state['values']:
                    state['values'][field] = ', '.join(new if n.strip() == old else n.strip() for n in state['values'][field].split(',') if n.strip())
            tab.restore(state)
    return True
