"""Resolve missing custom-item icons and export an artist-friendly task list."""
import copy
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from core import Catalog
from project import png_asset, default_icon_asset
from ui import help_label, accept_file_drops
from controls import sequence, BUTTONS


class PendingTab(ttk.Frame):
    def __init__(self, app):
        super().__init__(app.tabs)
        self.app = app
        self.dirty = False
        bar = ttk.Frame(self, padding=12)
        bar.pack(fill='x')
        ttk.Label(bar, text='Suggested actions', font=('Segoe UI', 16, 'bold')).pack(side='left')
        self.export_button = ttk.Button(bar, text='Export as text', command=self.export_text)
        self.export_button.pack(side='right')
        self.status = tk.StringVar()
        ttk.Label(self, textvariable=self.status, padding=(12, 0, 12, 8)).pack(anchor='w')
        self.groups = ttk.Notebook(self)
        self.groups.pack(fill='both', expand=True, padx=12, pady=(0, 12))
        self.icons_page, self.recipes_page, self.unlocks_page, self.unused_page, self.machines_page = [ttk.Frame(self.groups) for _ in range(5)]
        for page, title in [(self.icons_page, 'Missing icons'), (self.recipes_page, 'Missing recipes'), (self.unlocks_page, 'Missing technology unlocks'), (self.unused_page, 'Unused ingredients'), (self.machines_page, 'Machines')]:
            self.groups.add(page, text=title)
        self.doubled_page = ttk.Frame(self.groups)
        self.groups.add(self.doubled_page, text='Doubled tech unlocks')
        help_label(self.doubled_page, 'These technologies repeat a recipe unlock already granted by a direct or indirect prerequisite. Different recipes producing the same item are kept separate. Double-click to remove the repeated unlock from the later technology. Ctrl+Z restores it. Use Open technology to edit its other settings.', wraplength=1000, padx=12)
        duplicate_holder = ttk.Frame(self.doubled_page, padding=12)
        duplicate_holder.pack(fill='both', expand=True)
        self.doubled = ttk.Treeview(duplicate_holder, columns=('technology', 'recipe', 'products', 'earlier'), show='headings', selectmode='browse')
        for key, title in [('technology', 'Technology'), ('recipe', 'Repeated recipe unlock'), ('products', 'Products'), ('earlier', 'Already unlocked by')]:
            self.doubled.heading(key, text=title)
            self.doubled.column(key, width=220)
        duplicate_scroll = ttk.Scrollbar(duplicate_holder, orient='vertical', command=self.doubled.yview)
        self.doubled.configure(yscrollcommand=duplicate_scroll.set)
        duplicate_scroll.pack(side='right', fill='y')
        self.doubled.pack(fill='both', expand=True)
        self.doubled.bind('<Double-Button-1>', self.remove_doubled_technology_unlock)
        self.doubled.bind(sequence(app.controls['picker_accept']), lambda e: self.open_doubled_technology())
        ttk.Button(self.doubled_page, text='Open technology', command=self.open_doubled_technology).pack(anchor='w', padx=12, pady=8)
        self.multi_tech_page = ttk.Frame(self.groups)
        self.groups.add(self.multi_tech_page, text='Multi-tech recipes')
        help_label(self.multi_tech_page, 'The same recipe unlocked by two or more technologies. Different recipes that produce the same item are not grouped together. Unchanged base-game duplicates are excluded. Right-click to hide an entry. Informational only: these entries do not increase the Suggested actions badge. Double-click to choose a technology to edit.', wraplength=1000, padx=12)
        self.show_hidden_multi = tk.BooleanVar(value=False)
        ttk.Checkbutton(self.multi_tech_page, text='Show hidden entries', variable=self.show_hidden_multi, command=self.refresh).pack(anchor='w', padx=12, pady=4)
        multi_holder = ttk.Frame(self.multi_tech_page, padding=12)
        multi_holder.pack(fill='both', expand=True)
        ttk.Style(self).configure('MultiTech.Treeview', rowheight=28)
        self.multi_tech = ttk.Treeview(multi_holder, columns=('products', 'technologies'), show='tree headings', style='MultiTech.Treeview', selectmode='extended')
        self.multi_tech.heading('#0', text='Recipe')
        self.multi_tech.column('#0', width=240)
        for key, title in [('products', 'Products'), ('technologies', 'Unlocking technologies')]:
            self.multi_tech.heading(key, text=title)
            self.multi_tech.column(key, width=240)
        multi_scroll = ttk.Scrollbar(multi_holder, orient='vertical', command=self.multi_tech.yview)
        self.multi_tech.configure(yscrollcommand=multi_scroll.set)
        multi_scroll.pack(side='right', fill='y')
        self.multi_tech.pack(fill='both', expand=True)
        self.multi_tech.bind('<Double-Button-1>', lambda e: self.open_multi_technology())
        self.multi_tech.bind('<Button-%d>' % BUTTONS[app.controls['context_button']], self.multi_tech_context)
        self.multi_tech.bind(sequence(app.controls['picker_accept']), lambda e: self.open_multi_technology())
        ttk.Button(self.multi_tech_page, text='Open a technology…', command=self.open_multi_technology).pack(anchor='w', padx=12, pady=8)
        ttk.Button(self.multi_tech_page, text='Create prerequisite technology', command=self.create_multi_prerequisite).pack(anchor='w', padx=12, pady=4)
        ttk.Button(self.multi_tech_page, text='Add to technology', command=self.assign_multi_technology).pack(anchor='w', padx=12, pady=4)
        help_label(self.multi_tech_page, 'Ctrl/Shift-select recipes to move their unlocks into one new prerequisite technology. Existing unlocking technologies will require the new one.', wraplength=1000, padx=12)
        help_label(self.icons_page, 'Drop a square PNG file onto an item row, or click an item to choose its icon. Replacement icons are saved immediately and updated in all flowcharts.', wraplength=900, padx=12)
        ttk.Label(self.icons_page, text='Items without icons', padding=(12, 6), foreground='#e9aa52').pack(anchor='w')
        holder = ttk.Frame(self.icons_page, padding=(12, 0, 12, 12))
        holder.pack(fill='both', expand=True)
        self.items = ttk.Treeview(holder, columns=('id', 'name', 'requirement'), show='headings', selectmode='browse', height=6)
        for column, title, width in [('id', 'Item ID', 250), ('name', 'Display name', 250), ('requirement', 'Requirement', 360)]:
            self.items.heading(column, text=title)
            self.items.column(column, width=width)
        bar = ttk.Scrollbar(holder, orient='vertical', command=self.items.yview)
        self.items.configure(yscrollcommand=bar.set)
        bar.pack(side='right', fill='y')
        self.items.pack(fill='both', expand=True)
        accept_file_drops(self.items, self.drop_icon)
        self.items.bind('<ButtonRelease-1>', self.clicked)
        self.items.bind(sequence(app.controls['picker_accept']), lambda e: self.choose_selected())
        ttk.Label(self.recipes_page, text='Items and fluids without crafting recipes', padding=(12, 6), foreground='#e9aa52').pack(anchor='w')
        recipe_holder = ttk.Frame(self.recipes_page, padding=(12, 0, 12, 6))
        recipe_holder.pack(fill='both', expand=True)
        self.recipes = ttk.Treeview(recipe_holder, columns=('type', 'id', 'name'), show='headings', selectmode='browse', height=6)
        for column, title in [('type', 'Type'), ('id', 'Item / fluid ID'), ('name', 'Display name')]:
            self.recipes.heading(column, text=title)
        scrollbar = ttk.Scrollbar(recipe_holder, orient='vertical', command=self.recipes.yview)
        self.recipes.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side='right', fill='y')
        self.recipes.pack(fill='both', expand=True)
        self.recipes.bind('<Double-Button-1>', lambda e: self.fix_recipe())
        self.recipes.bind(sequence(app.controls['picker_accept']), lambda e: self.fix_recipe())
        ttk.Button(self.recipes_page, text='Fix selected recipe', command=self.fix_recipe).pack(anchor='w', padx=12, pady=4)
        help_label(self.recipes_page, 'Lists your created and loaded-mod items/fluids with no recipe producing them. Double-click or select Fix to start a recipe. Mined resources may intentionally have no crafting recipe.', wraplength=950, padx=12)
        help_label(self.unlocks_page, 'These recipes are locked from the start and no technology unlocks them. Ctrl-click or Shift-click to select multiple recipes, then use Assign or create technology to assign them together. Double-click a row to assign one recipe.', wraplength=1000, padx=12)
        unlock_holder = ttk.Frame(self.unlocks_page, padding=12)
        unlock_holder.pack(fill='both', expand=True)
        self.unlocks = ttk.Treeview(unlock_holder, columns=('recipe', 'products'), show='headings', selectmode='extended')
        self.unlocks.heading('recipe', text='Recipe ID')
        self.unlocks.heading('products', text='Products')
        scrollbar = ttk.Scrollbar(unlock_holder, orient='vertical', command=self.unlocks.yview)
        self.unlocks.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side='right', fill='y')
        self.unlocks.pack(fill='both', expand=True)
        self.unlocks.bind('<Double-Button-1>', self.unlock_clicked)
        self.unlocks.bind(sequence(app.controls['picker_accept']), lambda e: self.fix_unlock())
        ttk.Button(self.unlocks_page, text='Assign or create technology', command=self.fix_unlock).pack(anchor='w', padx=12, pady=8)
        ttk.Button(self.unlocks_page, text='Unlock from start', command=self.unlock_selected_from_start).pack(anchor='w', padx=12, pady=4)
        ttk.Label(self.unused_page, text='Items not used as ingredients in any recipe', padding=12, foreground='#e9aa52').pack(anchor='w')
        unused_holder = ttk.Frame(self.unused_page, padding=12)
        unused_holder.pack(fill='both', expand=True)
        self.unused = ttk.Treeview(unused_holder, columns=('type', 'id', 'name'), show='headings', selectmode='extended')
        for column, title in [('type', 'Type'), ('id', 'Item / fluid ID'), ('name', 'Display name')]:
            self.unused.heading(column, text=title)
        scrollbar = ttk.Scrollbar(unused_holder, orient='vertical', command=self.unused.yview)
        self.unused.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side='right', fill='y')
        self.unused.pack(fill='both', expand=True)
        self.unused.bind('<Double-Button-1>', lambda e: self.open_unused_recipe())
        self.unused.bind(sequence(app.controls['picker_accept']), lambda e: self.open_unused_recipe())
        for listing in (self.items, self.recipes, self.unused, self.unlocks):
            listing.bind('<Button-%d>' % BUTTONS[app.controls['context_button']], self.context)
        ttk.Button(self.unused_page, text='Edit selected item', command=self.edit_unused).pack(anchor='w', padx=12, pady=6)
        ttk.Button(self.unused_page, text='Bulk edit selected', command=self.bulk_edit_unused).pack(anchor='w', padx=12, pady=4)
        help_label(self.unused_page, 'Ctrl-click or Shift-click to select several entries, then Bulk edit selected. Only enabled fields change; Ctrl+Z restores the entire batch.', wraplength=1000, padx=12)
        help_label(self.unused_page, 'Double-click an entry to open its crafting recipe. If several recipes produce it, choose one. If none exists, a new recipe starts with this item as its result. Right-click → Edit item opens its properties.', wraplength=1000, padx=12)
        help_label(self.unused_page, 'Placeable buildings, belts, inserters, equipment and other finished products are excluded automatically. Edit an item and mark it as a finished product to exclude it from this list. Missing icons and recipes are tracked separately.', wraplength=1000, padx=12)
        self.machine_section = ttk.Frame(self.machines_page, padding=12)
        self.machine_section.pack(fill='x')
        self.refresh()

    def context(self, event):
        listing = event.widget
        if listing.identify_region(event.x, event.y) not in ('cell', 'tree'):
            return
        row_id = listing.identify_row(event.y)
        if not row_id:
            return
        if row_id not in listing.selection():
            listing.selection_set(row_id)
        if listing is self.items:
            item = self.app.project.data['items'].get(row_id)
            key = ('fluid' if item and item.get('kind') == 'fluid' else 'item', row_id)
        elif listing is self.unlocks:
            from core import entries
            products = entries(self.app.catalog.recipes.get(row_id, {}), 'results')
            key = (products[0]['type'], products[0]['name']) if products else None
        else:
            key = (self.recipe_keys if listing is self.recipes else self.unused_keys).get(row_id)
        if key:
            self.item_menu(event, key)

    def item_menu(self, event, key):
        if hasattr(self, 'context_menu'):
            self.context_menu.destroy()
        self.context_menu = tk.Menu(self, tearoff=False)
        from creations_ui import edit_item
        self.context_menu.add_command(label='Edit item' if key[0] == 'item' else 'Edit fluid', command=lambda: edit_item(self, key))
        from creations_ui import rename_item
        self.context_menu.add_command(label='Rename item' if key[0] == 'item' else 'Rename fluid', command=lambda: rename_item(self, key))
        from creations_ui import open_item_recipe
        self.context_menu.add_command(label='Open recipe', command=lambda: open_item_recipe(self.app, key))
        if key[0] == 'item':
            from creations_ui import convert_to_machine
            self.context_menu.add_command(label='Convert to machine', command=lambda: convert_to_machine(self, key))
        if event.widget is self.unused:
            self.context_menu.add_command(label='Bulk edit selected', command=self.bulk_edit_unused)
            self.context_menu.add_command(label='Delete selected items and recipes', command=self.delete_unused_batch)
        if event.widget is self.unlocks:
            from creations_ui import rename_recipe
            selected = self.unlocks.selection()
            if len(selected) == 1:
                self.context_menu.add_command(label='Rename recipe', command=lambda: rename_recipe(self, selected[0]))
            self.context_menu.add_command(label='Add selected recipes to technology', command=self.fix_unlock)
            self.context_menu.add_command(label='Unlock from start', command=self.unlock_selected_from_start)
        from creations_ui import recipes_containing
        self.context_menu.add_command(label='See recipes containing this item' if key[0] == 'item' else 'See recipes containing this fluid',
                                      command=lambda: recipes_containing(self.app, key))
        from creations_ui import load_direct_recipes
        self.context_menu.add_command(label='Load all direct recipes', command=lambda: load_direct_recipes(self.app, key))
        from creations_ui import open_all_recipes_containing
        self.context_menu.add_command(label='Open all recipes containing this item' if key[0] == 'item' else 'Open all recipes containing this fluid',
                                      command=lambda: open_all_recipes_containing(self.app, key))
        if key[1] in self.app.project.data['items'] or key in self.app.loaded_items:
            self.context_menu.add_separator()
            self.context_menu.add_command(label='Delete item' if key[0] == 'item' else 'Delete fluid', command=lambda: self.delete_item(key))
            from delete_items import delete_with_recipes
            self.context_menu.add_command(label='Delete item and recipes containing it' if key[0] == 'item' else 'Delete fluid and recipes containing it', command=lambda: delete_with_recipes(self, key))
        self.context_menu.tk_popup(event.x_root, event.y_root)

    def delete_item(self, key):
        if key not in self.app.catalog.items:
            return False
        from creations_ui import CreationsTab
        data = self.app.project.editable_item(key, self.app.catalog)
        row = (data['kind'], key[1], data)
        if key in self.app.loaded_items or data.get('operation') == 'edit':
            return CreationsTab.delete_from_mod(self, row=row)
        return CreationsTab.delete_selected(self, row=row)

    def set_deletion_status(self, text):
        self.status.set(text)

    def clicked(self, event):
        if self.items.identify_region(event.x, event.y) not in ('cell', 'tree'):
            return
        name = self.items.identify_row(event.y)
        if name:
            self.replace_icon(name)

    def drop_icon(self, paths, x, y):
        if self.groups.select() != str(self.icons_page):
            return False
        name = self.items.identify_row(y)
        if not name or name not in self.app.project.items_missing_icons():
            return False
        if len(paths) != 1 or Path(paths[0]).suffix.lower() != '.png':
            messagebox.showerror('Cannot replace icon', 'Drop one square PNG image onto the item row.', parent=self)
            return False
        self.items.selection_set(name)
        return self.replace_icon(name, paths[0])

    def choose_selected(self):
        selected = self.items.selection()
        if selected:
            self.replace_icon(selected[0])

    def replace_icon(self, name, path=None):
        if name not in self.app.project.data['items']:
            return False

        if path is None:
            path = filedialog.askopenfilename(parent=self, title='Choose icon for ' + name, filetypes=[('PNG item icon', '*.png')])
        if not path:
            return False
        before = copy.deepcopy(self.app.project.data)
        try:
            icon = png_asset(path)
            tk.PhotoImage(master=self, data=icon['data'])
            item = self.app.project.data['items'][name]
            item.update(icon=icon, icon_path=str(path), icon_is_default=icon['data'] == default_icon_asset()['data'])
            self.app.project.compile(Catalog(self.app.base_raw))
            self.app.persist()
            self.app.record_undo('Replace item icon', self, project=before)
            self.app.refresh_catalog()
            return True
        except (OSError, ValueError, tk.TclError) as exc:
            self.app.project.data = before
            messagebox.showerror('Cannot replace icon', str(exc), parent=self)
            return False

    def unlock_clicked(self, event):
        if self.unlocks.identify_region(event.x, event.y) in ('cell', 'tree'):
            row = self.unlocks.identify_row(event.y)
            if row:
                if row not in self.unlocks.selection():
                    self.unlocks.selection_set(row)
                self.fix_unlock()

    def unlock_selected_from_start(self):
        selected = self.unlocks.selection()
        if not selected:
            return False
        from recipe_unlocks import unlock_from_start
        try:
            return unlock_from_start(self, list(selected))
        except (ValueError, OSError, KeyError) as exc:
            messagebox.showerror('Cannot unlock recipes', str(exc), parent=self)
            return False

    def fix_unlock(self):
        selected = self.unlocks.selection()
        if selected:
            from recipe_unlocks import unlock_dialog
            return unlock_dialog(self, list(selected))

    def remove_doubled_technology_unlock(self, event=None):
        if event is not None:
            row_id = self.doubled.identify_row(event.y)
            if not row_id:
                return False
            self.doubled.selection_set(row_id)
        selected = self.doubled.selection()
        if not selected:
            return False
        row = self.doubled_rows.get(selected[0])
        if not row:
            return False
        from recipe_unlocks import remove_doubled_unlock
        try:
            return remove_doubled_unlock(self, row['technology'], row['recipe'])
        except (ValueError, OSError, KeyError) as exc:
            messagebox.showerror('Cannot remove doubled unlock', str(exc), parent=self)
            return False

    def multi_tech_context(self, event):
        row_id = self.multi_tech.identify_row(event.y)
        row = self.multi_tech_rows.get(row_id)
        if not row:
            return
        if row_id not in self.multi_tech.selection():
            self.multi_tech.selection_set(row_id)
        if hasattr(self, 'multi_context_menu'):
            self.multi_context_menu.destroy()
        self.multi_context_menu = tk.Menu(self, tearoff=False)
        token = row['type'] + ':' + row['name']
        hidden = self.app.project.is_multi_tech_hidden(self.app.catalog, row)
        self.multi_context_menu.add_command(label='Unhide entry' if hidden else 'Hide entry', command=lambda: self.hide_multi_technology(row, not hidden))
        self.multi_context_menu.add_command(label='Open a technology…', command=self.open_multi_technology)
        self.multi_context_menu.add_command(label='Create prerequisite technology', command=self.create_multi_prerequisite)
        self.multi_context_menu.add_command(label='Add to technology', command=self.assign_multi_technology)
        self.multi_context_menu.tk_popup(event.x_root, event.y_root)

    def hide_multi_technology(self, row, hidden=True):
        before = copy.deepcopy(self.app.project.data)
        token = row['type'] + ':' + row['name']
        if hidden:
            self.app.project.data['hidden_multi_tech'][token] = True
        else:
            self.app.project.data['hidden_multi_tech'].pop(token, None)
            from core import entries
            for product in entries(self.app.catalog.recipes[row['name']], 'results'):
                self.app.project.data['hidden_multi_tech'].pop(product['type'] + ':' + product['name'], None)
        try:
            self.app.persist()
        except OSError as exc:
            self.app.project.data = before
            messagebox.showerror('Cannot save hidden suggestion', str(exc), parent=self)
            return False
        self.app.record_undo('Hide multi-tech suggestion' if hidden else 'Unhide multi-tech suggestion', self, self.snapshot(), before)
        self.refresh()
        return True

    def assign_multi_technology(self):
        recipes = [self.multi_tech_rows[key]['name'] for key in self.multi_tech.selection() if key in self.multi_tech_rows]
        if recipes:
            from recipe_unlocks import unlock_dialog
            return unlock_dialog(self, recipes)

    def create_multi_prerequisite(self):
        rows = [self.multi_tech_rows[key] for key in self.multi_tech.selection() if key in self.multi_tech_rows]
        if not rows:
            return
        recipes = list(dict.fromkeys(row['name'] for row in rows))
        targets = sorted({name for row in rows for name in row['technologies']})
        source = self.app.catalog.raw['technology'][targets[0]]
        from editors import field, select_names, split_names
        from ui import scroll_form
        from project import positive, png_asset
        dialog = tk.Toplevel(self.app)
        dialog.title('Create prerequisite technology')
        dialog.transient(self.app)
        dialog.geometry('760x700')
        footer = ttk.Frame(dialog, padding=12)
        footer.pack(side='bottom', fill='x')
        body = scroll_form(dialog)
        ttk.Label(body, text=f'Move {len(recipes)} recipe unlocks into a shared prerequisite', font=('Segoe UI', 13, 'bold'), padding=12).pack(anchor='w')
        help_label(body, 'Selected recipes: ' + ', '.join(recipes) + '\nThese technologies will require the new technology: ' + ', '.join(targets), wraplength=680)
        base = recipes[0] + '_technology'
        proposed, index = base, 2
        while proposed in self.app.catalog.raw.get('technology', {}):
            proposed, index = base + '_' + str(index), index + 1
        tech_id, _, _ = field(body, 'Technology ID', proposed)
        title, _, _ = field(body, 'Display name', proposed.replace('_', ' ').replace('-', ' ').title())
        prerequisites, row, _ = field(body, 'Prerequisites', '')
        ttk.Button(row, text='Choose…', command=lambda: select_names(self.app, 'Prerequisites for new technology',
            [name for name in self.app.catalog.raw['technology'] if name not in targets],
            lambda names: prerequisites.set(', '.join(dict.fromkeys(split_names(prerequisites.get()) + names))))).pack(side='right')
        unit = source.get('unit', {})
        count, _, _ = field(body, 'Research count', unit.get('count', 50))
        seconds, _, _ = field(body, 'Seconds per research unit', unit.get('time', 30))
        packs = [str(entry.get('name')) + ':' + str(entry.get('amount', 1)) if isinstance(entry, dict) else str(entry[0]) + ':' + str(entry[1]) for entry in unit.get('ingredients', [['automation-science-pack', 1]])]
        science, row, _ = field(body, 'Science packs', ', '.join(packs))
        ttk.Button(row, text='Choose…', command=lambda: select_names(self.app, 'Science packs', self.app.catalog.raw.get('tool', {}),
            lambda names: science.set(', '.join(dict.fromkeys(split_names(science.get()) + [name + ':1' for name in names]))))).pack(side='right')
        help_label(body, 'Science format: automation-science-pack:1. Research settings and icon initially come from one of the current unlocking technologies. Adjust them before creating.', wraplength=680)
        icon_path, row, _ = field(body, 'Custom icon PNG (optional)', '')
        def choose_icon():
            path = filedialog.askopenfilename(parent=dialog, title='Choose technology icon', filetypes=[('PNG icon', '*.png')])
            if path:
                icon_path.set(path)
        ttk.Button(row, text='Browse…', command=choose_icon).pack(side='right')
        icon_choices = {}
        def choose_from_unlocks():
            from editors import unlock_icon_picker
            def selected(asset, marker):
                icon_choices[marker] = asset
                icon_path.set(marker)
            return unlock_icon_picker(self, recipes, selected)
        ttk.Button(body, text='Choose icon from unlocks…', command=choose_from_unlocks).pack(anchor='w', padx=16, pady=4)

        def create():
            from recipe_unlocks import create_shared_prerequisite
            try:
                ingredients = []
                for value in split_names(science.get()):
                    parts = value.split(':')
                    ingredients.append([parts[0].strip(), positive(parts[1] if len(parts) > 1 else 1, 'Science pack amount', True)])
                proto = {key: copy.deepcopy(source[key]) for key in ('icon', 'icons', 'icon_size') if key in source}
                proto.update(type='technology', name=tech_id.get().strip(), localised_name=title.get().strip() or tech_id.get().strip(),
                             prerequisites=split_names(prerequisites.get()), unit={'count': positive(count.get(), 'Research count', True),
                             'time': positive(seconds.get(), 'Research time'), 'ingredients': ingredients})
                asset = icon_choices.get(icon_path.get()) if icon_path.get().startswith('@unlock:') else png_asset(icon_path.get()) if icon_path.get().strip() else None
                create_shared_prerequisite(self, recipes, proto, asset, icon_path.get())
                dialog.destroy()
            except (ValueError, OSError, KeyError) as exc:
                messagebox.showerror('Cannot create prerequisite technology', str(exc), parent=dialog)
        ttk.Button(footer, text='Create technology', command=create).pack(side='right')
        ttk.Button(footer, text='Cancel', command=dialog.destroy).pack(side='left')
        return dialog

    def open_multi_technology(self):
        selected = self.multi_tech.selection()
        if not selected:
            return
        row = self.multi_tech_rows.get(selected[0])
        if not row:
            return
        dialog = tk.Toplevel(self.app)
        dialog.title('Technologies unlocking recipe ' + row['name'])
        dialog.transient(self.app)
        dialog.geometry('540x380')
        ttk.Label(dialog, text=row['name'], font=('Segoe UI', 13, 'bold'), padding=12).pack(anchor='w')
        listing = tk.Listbox(dialog, exportselection=False)
        listing.pack(fill='both', expand=True, padx=12, pady=8)
        for technology in row['technologies']:
            listing.insert('end', technology)
        listing.selection_set(0)
        def open_selected(*_):
            if listing.curselection():
                name = row['technologies'][listing.curselection()[0]]
                dialog.destroy()
                self.app.tech_tab().edit(name)
        ttk.Button(dialog, text='Open technology', command=open_selected).pack(anchor='e', padx=12, pady=12)
        listing.bind('<Double-Button-1>', open_selected)
        return dialog

    def open_doubled_technology(self):
        selected = self.doubled.selection()
        if selected:
            row = self.doubled_rows.get(selected[0])
            if row:
                tree = self.app.tech_tab()
                tree.edit(row['technology'])
                return tree

    def refresh(self):
        names = self.app.project.items_missing_icons()
        self.items.delete(*self.items.get_children())
        for name in names:
            item = self.app.project.data['items'][name]
            self.items.insert('', 'end', iid=name, values=(name, item.get('title', name), 'Custom icon missing — using checkerboard'))
        missing = self.app.project.items_missing_recipes(self.app.catalog, self.app.loaded_items)
        self.recipes.delete(*self.recipes.get_children())
        self.recipe_keys = {}
        for key in missing:
            kind, name = key
            proto = self.app.catalog.items[key]
            title = proto.get('localised_name')
            title = title if isinstance(title, str) else name.replace('-', ' ').title()
            row_id = kind + ':' + name
            self.recipe_keys[row_id] = key
            self.recipes.insert('', 'end', iid=row_id, values=(kind, name, title))
        unused = self.app.project.items_unused(self.app.catalog, self.app.loaded_items)
        self.unused.delete(*self.unused.get_children())
        self.unused_keys = {}
        for key in unused:
            kind, name = key
            title = self.app.catalog.items[key].get('localised_name')
            title = title if isinstance(title, str) else name.replace('-', ' ').title()
            row_id = kind + ':' + name
            self.unused_keys[row_id] = key
            self.unused.insert('', 'end', iid=row_id, values=(kind, name, title))
        locked = self.app.project.recipes_missing_unlocks(self.app.catalog, self.app.loaded_recipes)
        self.unlocks.delete(*self.unlocks.get_children())
        from core import entries
        for name in locked:
            products = ', '.join(e['name'] for e in entries(self.app.catalog.recipes[name], 'results'))
            self.unlocks.insert('', 'end', iid=name, values=(name, products))
        self.groups.tab(self.unlocks_page, text=f'Missing technology unlocks ({len(locked)})')
        doubled = self.app.project.doubled_technology_unlocks(self.app.catalog)
        self.doubled.delete(*self.doubled.get_children())
        self.doubled_rows = {}
        for index, row in enumerate(doubled):
            row_id = str(index)
            self.doubled_rows[row_id] = row
            products = ', '.join(e['name'] for e in entries(self.app.catalog.recipes[row['recipe']], 'results'))
            self.doubled.insert('', 'end', iid=row_id, values=(row['technology'], row['recipe'], products, ', '.join(row['prerequisites'])))
        self.groups.tab(self.doubled_page, text=f'Doubled tech unlocks ({len(doubled)})')
        multi_tech = self.app.project.multi_technology_suggestions(self.app.catalog, self.app.vanilla_unlock_baseline, self.show_hidden_multi.get())
        self.multi_tech.delete(*self.multi_tech.get_children())
        self.multi_tech_rows = {}
        self.multi_tech_images = []
        for index, row in enumerate(multi_tech):
            row_id = str(index)
            self.multi_tech_rows[row_id] = row
            from flow import prototype_image
            recipe = self.app.catalog.recipes[row['name']]
            products = entries(recipe, 'results')
            image = prototype_image(self.app, recipe, 24)
            if not image and products:
                image = self.app.icon((products[0]['type'], products[0]['name']), size=24)
            options = {'image': image} if image else {}
            if image:
                self.multi_tech_images.append(image)
            self.multi_tech.insert('', 'end', iid=row_id, text=row['name'], values=(', '.join(e['name'] for e in products), ', '.join(row['technologies'])), **options)
        self.groups.tab(self.multi_tech_page, text=f'Multi-tech recipes ({len(multi_tech)})')
        self.status.set(f'{len(names)} missing icons · {len(missing)} missing recipes · {len(locked)} missing unlocks · {len(unused)} unused ingredients · {len(doubled)} doubled unlocks')
        self.export_button.configure(state='normal' if names else 'disabled')
        for page, title, count in [(self.icons_page, 'Missing icons', len(names)), (self.recipes_page, 'Missing recipes', len(missing)), (self.unused_page, 'Unused ingredients', len(unused))]:
            self.groups.tab(page, text=f'{title} ({count})')
        for child in self.machine_section.winfo_children():
            child.destroy()
        machines = self.app.project.missing_machine_recipes(Catalog(self.app.base_raw))
        drafts = self.app.project.data['machine_drafts']
        self.groups.tab(self.machines_page, text=f'Machines ({len(machines) + len(drafts)})')
        if drafts:
            ttk.Label(self.machine_section, text='Incomplete item → machine conversions', foreground='#e9aa52').pack(anchor='w')
            for name, draft in sorted(drafts.items()):
                row = ttk.Frame(self.machine_section)
                row.pack(fill='x', pady=4)
                ttk.Label(row, text=name + ' — missing Building PNG / animation sprite sheet', wraplength=780).pack(side='left')
                ttk.Button(row, text='Complete machine', command=lambda n=name: self.app.new_machine_tab(name=n)).pack(side='left', padx=8)
            help_label(self.machine_section, 'Drafts preserve their original items and recipes. Complete and save the machine to make the item placeable; unfinished drafts are not exported as buildings.', wraplength=1000, padx=0)
        if not machines and not drafts:
            ttk.Label(self.machine_section, text='All saved machines have crafting recipes.').pack(anchor='w')
        if machines:
            ttk.Label(self.machine_section, text='Machines without crafting recipes', foreground='#e9aa52').pack(anchor='w')
            for name in machines:
                row = ttk.Frame(self.machine_section)
                row.pack(fill='x', pady=3)
                label = ttk.Label(row, text=name)
                label.pack(side='left')
                from machine_model import placed_item_name
                key = ('item', placed_item_name(name, self.app.project.data['machines'][name]))
                label.bind('<Button-%d>' % BUTTONS[self.app.controls['context_button']], lambda e, k=key: self.item_menu(e, k))
                ttk.Button(row, text='Fix', style='Small.TButton', command=lambda n=name: self.app.fix_machine_recipe(n)).pack(side='left', padx=8)

    def fix_recipe(self):
        selected = self.recipes.selection()
        if not selected:
            return
        key = self.recipe_keys.get(selected[0])
        if not key:
            return
        for tab in self.app.tabs.winfo_children():
            if hasattr(tab, 'loaded_name') and not tab.loaded_name and any((e['type'], e['name']) == key for e in tab.recipe.results):
                self.app.tabs.select(tab)
                return tab
        tab = self.app.new_tab()
        tab.add_entry('results', key)
        return tab

    def open_unused_recipe(self):
        selected = self.unused.selection()
        key = self.unused_keys.get(selected[0]) if selected else None
        if not key:
            return None
        from creations_ui import open_item_recipe
        return open_item_recipe(self.app, key)

    def edit_unused(self):
        selected = self.unused.selection()
        if selected:
            key = self.unused_keys.get(selected[0])
            if key:
                from editors import item_dialog
                item_dialog(self, self.app.project.editable_item(key, self.app.catalog))

    def bulk_edit_unused(self):
        keys = [self.unused_keys[row] for row in self.unused.selection() if row in self.unused_keys]
        if not keys:
            return
        dialog = tk.Toplevel(self.app)
        dialog.title('Bulk edit unused ingredients')
        dialog.transient(self.app)
        dialog.geometry('710x650')
        from ui import scroll_form
        from editors import field
        footer = ttk.Frame(dialog, padding=12)
        footer.pack(side='bottom', fill='x')
        body = scroll_form(dialog)
        ttk.Label(body, text=f'Edit {len(keys)} selected items/fluids', padding=12, font=('Segoe UI', 13, 'bold')).pack(anchor='w')
        help_label(body, 'Tick the fields to change for every selected entry. Unticked fields are preserved. Stack size applies only to solid items. A blank enabled fuel value removes fuel behavior.', wraplength=650)
        finished, row, entry = field(body, 'Finished product', 'Keep unchanged')
        entry.destroy()
        ttk.Combobox(row, textvariable=finished, state='readonly', values=['Keep unchanged', 'Mark as finished product', 'Mark as ingredient']).pack(fill='x')
        fields = {}
        for key, label, value in [('stack_size', 'Stack size', '100'), ('subgroup', 'Inventory subgroup', 'intermediate-product'),
                                  ('description', 'Description', ''), ('fuel_value', 'Fuel value', ''), ('fuel_category', 'Fuel category', 'chemical')]:
            enabled = tk.BooleanVar(value=False)
            ttk.Checkbutton(body, text='Change ' + label.lower(), variable=enabled).pack(anchor='w', padx=16, pady=(8, 0))
            variable, row, entry = field(body, label, value)
            if key in ('subgroup', 'fuel_category'):
                entry.destroy()
                group = 'item-subgroup' if key == 'subgroup' else 'fuel-category'
                ttk.Combobox(row, textvariable=variable, values=sorted(self.app.catalog.raw.get(group, {})), state='readonly').pack(fill='x')
            fields[key] = enabled, variable
        def apply():
            changes = {key: value.get() for key, (enabled, value) in fields.items() if enabled.get()}
            if finished.get() != 'Keep unchanged':
                changes['finished_product'] = finished.get() == 'Mark as finished product'
            if not changes:
                return
            if self.apply_unused_edits(keys, changes):
                dialog.destroy()
        ttk.Button(footer, text='Apply to selected', command=apply).pack(side='right')
        def delete():
            if self.delete_unused_batch(keys):
                dialog.destroy()
        ttk.Button(footer, text='Delete selected items and recipes', command=delete).pack(side='left')
        return dialog

    def delete_unused_batch(self, keys=None):
        if keys is None:
            keys = [self.unused_keys[row] for row in self.unused.selection() if row in self.unused_keys]
        from delete_items import bulk_delete_with_recipes
        return bulk_delete_with_recipes(self, keys)

    def apply_unused_edits(self, keys, changes):
        from project import positive, fuel_energy
        before = copy.deepcopy(self.app.project.data)
        try:
            for key in keys:
                if key not in self.app.catalog.items:
                    raise ValueError('Item is no longer loaded: ' + key[1])
                item = self.app.project.editable_item(key, self.app.catalog)
                for field, value in changes.items():
                    if field == 'stack_size':
                        value = positive(value, 'Stack size', True)
                        if key[0] == 'fluid':
                            continue
                    elif field == 'fuel_value':
                        value = fuel_energy(value)
                    elif field in ('subgroup', 'fuel_category'):
                        group = 'item-subgroup' if field == 'subgroup' else 'fuel-category'
                        if value not in self.app.catalog.raw.get(group, {}):
                            raise ValueError('Choose a loaded ' + field.replace('_', ' ') + '.')
                        if field == 'fuel_category' and key[0] == 'fluid':
                            continue
                    elif field not in ('description', 'finished_product'):
                        raise ValueError('Unsupported bulk field: ' + field)
                    item[field] = value
                    if field == 'fuel_category' and item.get('fuel_categories'):
                        item['fuel_categories'] = [value]
                self.app.project.data['items'][key[1]] = item
            self.app.project.compile(Catalog(self.app.base_raw))
            self.app.persist()
        except (ValueError, OSError, KeyError) as exc:
            self.app.project.data = before
            messagebox.showerror('Cannot bulk edit ingredients', str(exc), parent=self)
            return False
        self.app.record_undo('Bulk edit unused ingredients', self, self.snapshot(), before)
        self.app.refresh_catalog()
        self.status.set(f'Updated {len(keys)} entries. Ctrl+Z restores the whole batch.')
        return True

    def snapshot(self):
        return {}

    def restore(self, state):
        self.refresh()

    def export_text(self, path=None):
        names = self.app.project.items_missing_icons()
        if not names:
            return False
        if path is None:
            path = filedialog.asksaveasfilename(parent=self, title='Export item IDs without icons', initialfile='items-without-icons.txt', defaultextension='.txt', filetypes=[('Text file', '*.txt')])
        if not path:
            return False
        try:
            Path(path).write_text('\n'.join(names) + '\n', encoding='utf-8')
            return True
        except OSError as exc:
            messagebox.showerror('Cannot export list', str(exc), parent=self)
            return False

    def save_changes(self, quiet=False):
        return True

    def close(self):
        self.destroy()
