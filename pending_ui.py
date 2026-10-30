"""Resolve missing custom-item icons and export an artist-friendly task list."""
import copy
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from core import Catalog
from project import png_asset, default_icon_asset
from ui import help_label
from controls import sequence, BUTTONS


class PendingTab(ttk.Frame):
    def __init__(self, app):
        super().__init__(app.tabs)
        self.app = app
        self.dirty = False
        bar = ttk.Frame(self, padding=12)
        bar.pack(fill='x')
        ttk.Label(bar, text='Pending requirements', font=('Segoe UI', 16, 'bold')).pack(side='left')
        self.export_button = ttk.Button(bar, text='Export as text', command=self.export_text)
        self.export_button.pack(side='right')
        self.status = tk.StringVar()
        ttk.Label(self, textvariable=self.status, padding=(12, 0, 12, 8)).pack(anchor='w')
        self.groups = ttk.Notebook(self)
        self.groups.pack(fill='both', expand=True, padx=12, pady=(0, 12))
        self.icons_page, self.recipes_page, self.unlocks_page, self.unused_page, self.machines_page = [ttk.Frame(self.groups) for _ in range(5)]
        for page, title in [(self.icons_page, 'Missing icons'), (self.recipes_page, 'Missing recipes'), (self.unlocks_page, 'Missing technology unlocks'), (self.unused_page, 'Unused ingredients'), (self.machines_page, 'Machines')]:
            self.groups.add(page, text=title)
        help_label(self.icons_page, 'Click an item to choose a square PNG icon. Replacement icons are saved immediately and updated in all flowcharts.', wraplength=900, padx=12)
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
        help_label(self.unlocks_page, 'These recipes are locked from the start and no technology unlocks them. Click a row to assign an existing technology or create a new technology.', wraplength=1000, padx=12)
        unlock_holder = ttk.Frame(self.unlocks_page, padding=12)
        unlock_holder.pack(fill='both', expand=True)
        self.unlocks = ttk.Treeview(unlock_holder, columns=('recipe', 'products'), show='headings', selectmode='browse')
        self.unlocks.heading('recipe', text='Recipe ID')
        self.unlocks.heading('products', text='Products')
        scrollbar = ttk.Scrollbar(unlock_holder, orient='vertical', command=self.unlocks.yview)
        self.unlocks.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side='right', fill='y')
        self.unlocks.pack(fill='both', expand=True)
        self.unlocks.bind('<ButtonRelease-1>', self.unlock_clicked)
        self.unlocks.bind(sequence(app.controls['picker_accept']), lambda e: self.fix_unlock())
        ttk.Button(self.unlocks_page, text='Assign or create technology', command=self.fix_unlock).pack(anchor='w', padx=12, pady=8)
        ttk.Label(self.unused_page, text='Items not used as ingredients in any recipe', padding=12, foreground='#e9aa52').pack(anchor='w')
        unused_holder = ttk.Frame(self.unused_page, padding=12)
        unused_holder.pack(fill='both', expand=True)
        self.unused = ttk.Treeview(unused_holder, columns=('type', 'id', 'name'), show='headings', selectmode='browse')
        for column, title in [('type', 'Type'), ('id', 'Item / fluid ID'), ('name', 'Display name')]:
            self.unused.heading(column, text=title)
        scrollbar = ttk.Scrollbar(unused_holder, orient='vertical', command=self.unused.yview)
        self.unused.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side='right', fill='y')
        self.unused.pack(fill='both', expand=True)
        self.unused.bind('<Double-Button-1>', lambda e: self.edit_unused())
        self.unused.bind(sequence(app.controls['picker_accept']), lambda e: self.edit_unused())
        for listing in (self.items, self.recipes, self.unused, self.unlocks):
            listing.bind('<Button-%d>' % BUTTONS[app.controls['context_button']], self.context)
        ttk.Button(self.unused_page, text='Edit selected item', command=self.edit_unused).pack(anchor='w', padx=12, pady=6)
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
        from creations_ui import recipes_containing
        self.context_menu.add_command(label='See recipes containing this item' if key[0] == 'item' else 'See recipes containing this fluid',
                                      command=lambda: recipes_containing(self.app, key))
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
                self.unlocks.selection_set(row)
                self.fix_unlock()

    def fix_unlock(self):
        selected = self.unlocks.selection()
        if selected:
            from recipe_unlocks import unlock_dialog
            return unlock_dialog(self, selected[0])

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
        self.status.set(f'{len(names)} missing icons · {len(missing)} missing recipes · {len(locked)} missing unlocks · {len(unused)} unused ingredients')
        self.export_button.configure(state='normal' if names or missing or unused or locked else 'disabled')
        for page, title, count in [(self.icons_page, 'Missing icons', len(names)), (self.recipes_page, 'Missing recipes', len(missing)), (self.unused_page, 'Unused ingredients', len(unused))]:
            self.groups.tab(page, text=f'{title} ({count})')
        for child in self.machine_section.winfo_children():
            child.destroy()
        machines = self.app.project.missing_machine_recipes(Catalog(self.app.base_raw))
        self.groups.tab(self.machines_page, text=f'Machines ({len(machines)})')
        if not machines:
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

    def edit_unused(self):
        selected = self.unused.selection()
        if selected:
            key = self.unused_keys.get(selected[0])
            if key:
                from editors import item_dialog
                item_dialog(self, self.app.project.editable_item(key, self.app.catalog))

    def snapshot(self):
        return {}

    def restore(self, state):
        self.refresh()

    def export_text(self, path=None):
        names = self.app.project.items_missing_icons()
        missing = self.app.project.items_missing_recipes(self.app.catalog, self.app.loaded_items)
        unused = self.app.project.items_unused(self.app.catalog, self.app.loaded_items)
        locked = self.app.project.recipes_missing_unlocks(self.app.catalog, self.app.loaded_recipes)
        if not names and not missing and not unused and not locked:
            return False
        if path is None:
            path = filedialog.asksaveasfilename(parent=self, title='Export pending item requirements', initialfile='pending-requirements.txt', defaultextension='.txt', filetypes=[('Text file', '*.txt')])
        if not path:
            return False
        try:
            lines = ['Items without icons', f'Count: {len(names)}', '', 'These items currently use the default checkerboard texture.', '']
            lines += [f"- {name} — {self.app.project.data['items'][name].get('title', name)}" for name in names]
            lines += ['', 'Items and fluids without crafting recipes', f'Count: {len(missing)}', '']
            lines += [f'- {kind}: {name}' for kind, name in missing]
            lines += ['', 'Items not used as recipe ingredients', f'Count: {len(unused)}', '']
            lines += [f'- {kind}: {name}' for kind, name in unused]
            lines += ['', 'Locked recipes without a technology unlock', f'Count: {len(locked)}', '']
            lines += ['- ' + name for name in locked]
            Path(path).write_text('\n'.join(lines) + '\n', encoding='utf-8')
            return True
        except OSError as exc:
            messagebox.showerror('Cannot export list', str(exc), parent=self)
            return False

    def save_changes(self, quiet=False):
        return True

    def close(self):
        self.destroy()
