"""Browse the current project's saved items, fluids and machines."""
import tkinter as tk
import copy
import weakref
from tkinter import ttk, messagebox

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
        help_label(self, 'Search your creations, saved edits, and items/recipes from loaded mods. Filter by type or Loaded/Created/Edited. Double-click to edit.', wraplength=900, padx=12)
        filters = ttk.Frame(self, padding=(12, 0, 12, 6))
        filters.pack(fill='x')
        self.kind_filter = tk.StringVar(value='All types')
        self.change_filter = tk.StringVar(value='All changes')
        for label, variable, values in [('Type', self.kind_filter, ['All types', 'item', 'fluid', 'science pack', 'ore', 'machine', 'recipe', 'technology']),
                                         ('Change', self.change_filter, ['All changes', 'Loaded', 'Created', 'Edited'])]:
            ttk.Label(filters, text=label).pack(side='left', padx=(0, 6))
            ttk.Combobox(filters, textvariable=variable, values=values, state='readonly', width=18).pack(side='left', padx=(0, 16))
        ttk.Button(filters, text='Clear filters', command=self.clear_filters).pack(side='left')
        holder = ttk.Frame(self, padding=12)
        holder.pack(fill='both', expand=True)
        self.list = ttk.Treeview(holder, columns=('kind', 'id', 'title', 'status'), show='tree headings', selectmode='extended')
        self.list.heading('#0', text='Icon')
        self.list.column('#0', width=64, stretch=False)
        for key, label in [('kind', 'Type'), ('id', 'ID'), ('title', 'Display name'), ('status', 'Change')]:
            self.list.heading(key, text=label)
            self.list.column(key, width=200)
        scrollbar = ttk.Scrollbar(holder, orient='vertical', command=self.list.yview)
        self.list.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side='right', fill='y')
        self.list.pack(fill='both', expand=True)
        self.list.bind('<Double-Button-1>', lambda e: self.edit_selected())
        self.list.bind(sequence(app.controls['picker_accept']), lambda e: self.edit_selected())
        self.list.bind('<Delete>', lambda e: self.delete_selected())
        self.list.bind('<Button-%d>' % BUTTONS[app.controls['context_button']], self.context)
        actions = ttk.Frame(self, padding=12)
        actions.pack(fill='x')
        ttk.Button(actions, text='Edit selected', command=self.edit_selected).pack(side='left')
        self.diagram_button = ttk.Button(actions, text='Read recipes as diagram', command=self.read_recipe_diagrams)
        self.diagram_button.pack(side='left', padx=6)
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

    def refresh(self):
        selected = self.list.selection()
        self.list.delete(*self.list.get_children())
        self.rows = {}
        self.images = []
        terms = self.query.get().lower().split()
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
        for kind, name, data in rows:
            proto = self.app.catalog.raw.get(kind, {}).get(name, {}) if kind in ('recipe', 'technology') else {}
            title = data.get('title') or proto.get('localised_name') or name.replace('-', ' ').title()
            if not isinstance(title, str):
                title = name.replace('-', ' ').title()
            status = 'Loaded' if data.get('loaded') else 'Edited' if data.get('operation') == 'edit' or name in self.app.base_raw.get(kind, {}) else 'Created'
            if self.kind_filter.get() not in ('All types', kind) or self.change_filter.get() not in ('All changes', status):
                continue
            if not all(term in (kind + ' ' + name + ' ' + title + ' ' + status).lower() for term in terms):
                continue
            row_id = kind + ':' + name
            self.rows[row_id] = (kind, name, data)
            key = ('item', placed_item_name(name, data)) if kind == 'machine' else ('fluid' if kind == 'fluid' else 'item', name)
            if kind in ('recipe', 'technology'):
                icon = prototype_image(self.app, proto, 20, data.get('icon') if kind == 'technology' else None)
                if not icon and kind == 'recipe' and data.get('results'):
                    product = data['results'][0]
                    icon = self.app.icon((product['type'], product['name']), size=20)
            else:
                icon = self.app.icon(key, size=20)
            options = {'image': icon} if icon else {}
            if icon:
                self.images.append(icon)
            self.list.insert('', 'end', iid=row_id, values=(kind, name, title, status), **options)
        retained = [row_id for row_id in selected if row_id in self.rows]
        if retained:
            self.list.selection_set(*retained)
        self.status.configure(text=f'{len(self.rows)} creations, edits and loaded mod entries' if self.rows else 'No matching creations, edits or loaded mod entries.')
        self.update_actions()

    def update_actions(self):
        selected = self.list.selection()
        row = self.selected() if len(selected) == 1 else None
        state = 'normal' if row and row[0] not in ('recipe', 'technology') else 'disabled'
        for button in self.use_buttons:
            button.configure(state=state)
        self.delete_button.configure(state='normal' if self.can_delete(row) else 'disabled')
        self.delete_mod_button.configure(state='normal' if self.can_delete_from_mod(row) else 'disabled')
        self.diagram_button.configure(state='normal' if any(self.rows.get(row_id, (None,))[0] == 'recipe' for row_id in selected) else 'disabled')

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

    def selected(self):
        selection = self.list.selection()
        return self.rows.get(selection[0]) if selection else None

    def context(self, event):
        row_id = self.list.identify_row(event.y)
        row = self.rows.get(row_id)
        if not row:
            return
        self.list.selection_set(row_id)
        self.update_actions()
        kind, name, data = row
        key = ('item', placed_item_name(name, data)) if kind == 'machine' else ('fluid' if kind == 'fluid' else 'item', name)
        if hasattr(self, 'context_menu'):
            self.context_menu.destroy()
        menu = tk.Menu(self, tearoff=False)
        self.context_menu = menu
        if kind == 'recipe':
            menu.add_command(label='Read recipes as diagram', command=self.read_recipe_diagrams)
        if kind not in ('recipe', 'technology'):
            menu.add_command(label='See all recipes containing this item' if key[0] == 'item' else 'See all recipes containing this fluid',
                             command=lambda: recipes_containing(self.app, key))
        if self.can_undo_edit(row):
            menu.add_command(label='Undo edit', command=self.undo_edit)
        elif self.can_delete(row):
            menu.add_command(label='Delete ' + kind, command=self.delete_selected)
        if self.can_delete_from_mod(row):
            menu.add_command(label='Delete from loaded mod', command=self.delete_from_mod)
        if kind not in ('recipe', 'technology', 'machine') and (self.can_delete(row) or self.can_delete_from_mod(row)):
            from delete_items import delete_with_recipes
            menu.add_command(label='Delete item and recipes containing it' if key[0] == 'item' else 'Delete fluid and recipes containing it', command=lambda: delete_with_recipes(self, key))
        if menu.index('end') is not None:
            menu.tk_popup(event.x_root, event.y_root)
        # tk_popup returns before the user selects an entry. Keep the menu
        # alive so its commands remain clickable after this handler returns.

    def undo_edit(self):
        if len(self.list.selection()) != 1:
            return False
        row = self.selected()
        if not self.can_undo_edit(row):
            return False
        from core import Catalog
        kind, name, data = row
        related = []
        if kind not in ('technology', 'machine'):
            for tab in self.app.tabs.winfo_children():
                if kind != 'recipe' and hasattr(tab, 'item_draft') and tab.item_draft and tab.item_draft.get('name') == name:
                    related.append((tab, tab.snapshot()))
            if not self.delete_selected(row=row):
                return False
            entry = self.app.undo_stack[-1]
            entry['label'] = 'Undo edit: ' + name
            entry['related'].extend((weakref.ref(tab), state) for tab, state in related)
            for tab, _ in related:
                state = tab.snapshot()
                state['item_draft'] = None
                tab.restore(state)
            self.set_deletion_status('Restored original ' + name + '. Ctrl+Z restores your edit.')
            return True
        before = copy.deepcopy(self.app.project.data)
        try:
            for tab in self.app.tabs.winfo_children():
                if kind == 'technology' and getattr(tab, 'selected', None) == name and hasattr(tab, 'editor_vars'):
                    related.append((tab, tab.snapshot()))
                elif kind == 'machine' and getattr(tab, 'saved_name', None) == name and hasattr(tab, 'entity_type'):
                    related.append((tab, tab.snapshot()))
            self.app.project.data['technologies' if kind == 'technology' else 'machines'].pop(name)
            if any(self.app.project.data[group] for group in ('items', 'recipes', 'technologies', 'machines', 'deleted')):
                self.app.project.compile(Catalog(self.app.base_raw))
            self.app.persist()
            self.app.record_undo('Undo edit: ' + name, self, self.snapshot(), before)
            self.app.undo_stack[-1]['related'] = [(weakref.ref(tab), state) for tab, state in related]
            self.app.refresh_catalog()
            for tab, _ in related:
                if kind == 'technology':
                    from editors import technology_dialog
                    technology_dialog(tab, name, force=True)
                else:
                    tab.configure_source(data.get('entity_type', 'assembling-machine'), name, 'edit')
            self.set_deletion_status('Restored original ' + name + '. Ctrl+Z restores your edit.')
            return True
        except (ValueError, OSError, KeyError) as exc:
            self.app.project.data = before
            messagebox.showerror('Cannot undo edit', str(exc), parent=self)
            return False

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
    matches = []
    for name, prototype in app.catalog.recipes.items():
        ingredient = any((entry['type'], entry['name']) == key for entry in entries(prototype, 'ingredients'))
        product = any((entry['type'], entry['name']) == key for entry in entries(prototype, 'results'))
        if ingredient or product:
            matches.append((name, ingredient, product))
    count = ttk.Label(dialog, padding=(12, 0))
    count.pack(anchor='w')
    def refresh(*_):
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
