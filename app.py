"""Run with python app.py. No third-party dependencies."""
import base64
import copy
import json
import math
import queue
import re
import tempfile
import threading
import tkinter as tk
import tkinter.font as tkfont
from pathlib import Path
from tkinter import ttk, filedialog, messagebox
import zipfile
import time
import weakref
import sys

from core import Catalog, Recipe, load_game
from project import Project
from installation import find_installation
from flow import bind_navigation, zoom_at, prototype_image, scale_image, select_event
from ui import configure_theme, BrowserNotebook, help_label, entry_undo
from controls import load_controls, sequence, settings_dialog, KEYS, BUTTONS

BG = '#171c24'
CARD = '#273240'
TEXT = '#e6edf3'
ACCENT = '#e9aa52'


class Picker(tk.Toplevel):
    def __init__(self, app, callback, recipes_only=False, initial='', recipe_names=False, kind_filter=None):
        super().__init__(app)
        self.title('Search loaded items & fluids')
        self.geometry('580x500')
        self.transient(app)
        self.callback = callback
        self.app = app
        self.recipes_only = recipes_only
        self.recipe_names = recipe_names
        self.kind_filter = kind_filter
        if recipe_names:
            self.title('Load recipe')
        ttk.Label(self, text='Search by recipe ID' if recipe_names else 'Search by item name', padding=12).pack(anchor='w')
        self.query = tk.StringVar(value=initial)
        entry = ttk.Entry(self, textvariable=self.query)
        entry.pack(fill='x', padx=12)
        entry_undo(entry, self.query)
        help_label(self, 'Filters loaded recipe IDs. Select a recipe to edit its flowchart.' if recipe_names else 'Filters loaded item and fluid IDs. Select a match to use it in the recipe.', wraplength=540)
        self.list = tk.Listbox(self, bg=BG, fg=TEXT, selectbackground='#45566c', borderwidth=0, font=('Segoe UI', 11))
        self.list.pack(fill='both', expand=True, padx=12, pady=12)
        self.list.bind('<Double-Button-%d>' % BUTTONS[app.controls['picker_button']], self.choose)
        self.list.bind(sequence(app.controls['picker_accept']), self.choose)
        ttk.Button(self, text='Load recipe' if recipe_names else 'Select item', command=self.choose).pack(pady=(0, 12))
        self.query.trace_add('write', self.refresh)
        self.bind(sequence(app.controls['dialog_dismiss']), lambda e: self.destroy())
        self.refresh()
        entry.focus_set()

    def refresh(self, *_):
        terms = re.split(r'[\s_-]+', self.query.get().casefold().strip())
        source = [('recipe', name) for name in self.app.catalog.recipes] if self.recipe_names else self.app.catalog.items
        from machine_model import placed_item_name
        recent = {(('item', placed_item_name(name, data)) if kind == 'machine' else ('fluid' if kind == 'fluid' else 'item', name)): index
                  for index, (kind, name, data) in enumerate(self.app.project.creations())}
        def matches(key):
            title = self.app.catalog.items.get(key, {}).get('localised_name', '') if not self.recipe_names else ''
            searchable = re.sub(r'[\s_-]+', ' ', key[1].casefold() + ' ' + (title.casefold() if isinstance(title, str) else ''))
            return (not self.kind_filter or key[0] == self.kind_filter) and all(term in searchable for term in terms) and (not self.recipes_only or key in self.app.catalog.by_product)
        self.matches = [key for key in sorted(source, key=lambda k: (recent.get(k, len(recent)), k[1].casefold())) if matches(key)]
        self.list.delete(0, 'end')
        for kind, name in self.matches:
            self.list.insert('end', f'{name}   ·   {kind}')
        if self.matches:
            self.list.selection_set(0)

    def choose(self, *_):
        if self.list.curselection():
            key = self.matches[self.list.curselection()[0]]
            self.destroy()
            self.callback(key)


class RecipeTab(ttk.Frame):
    def __init__(self, app, new_item=False):
        super().__init__(app.tabs)
        self.app = app
        self.recipe = None
        self.loaded_name = None
        self.tracking = False
        self.last_state = None
        self.dirty = False
        self.is_custom = True
        self.item_draft = None
        self.result_machine = None
        self.saved_key = None
        self.auto_name = True
        self.availability_override = False
        self.expanded_recipes = {}
        self.graph_nodes = {}
        self.zoom = 1.0
        self.purpose = tk.StringVar()
        ttk.Label(self, textvariable=self.purpose, padding=(12, 10, 12, 0), foreground=ACCENT).pack(anchor='w')
        self.purpose.set('NEW RECIPE — Right-click to add ingredients/results, create an item, or load a recipe.')
        top = ttk.Frame(self, padding=12)
        top.pack(fill='x')
        self.collapse_button = ttk.Button(top, text='Collapse expanded recipes', command=self.collapse_recipes)
        self.commit_text = tk.StringVar(value='Save as new recipe')
        self.commit_button = ttk.Button(top, textvariable=self.commit_text, command=self.save_changes)
        self.commit_button.pack(side='right', anchor='n')
        self.copy_button = ttk.Button(top, text='Save as new recipe', command=self.save_as_new)
        settings = ttk.Frame(self, padding=(12, 0, 12, 10))
        settings.pack(fill='x')
        self.name = tk.StringVar()
        self.seconds = tk.StringVar(value='0.5')
        self.enabled = tk.BooleanVar(value=False)
        self.category = tk.StringVar(value='crafting')
        for label, var, width, note in [('Recipe ID', self.name, 26, 'Unique ID for a new recipe; loaded recipe IDs stay fixed.'), ('Crafting seconds', self.seconds, 10, 'Base time for one craft at machine speed 1.')]:
            group = ttk.Frame(settings)
            group.pack(side='left', padx=(0, 14), anchor='n')
            ttk.Label(group, text=label).pack(anchor='w')
            input_entry = ttk.Entry(group, textvariable=var, width=width)
            input_entry.pack(fill='x')
            if var is self.name:
                self.name_entry = input_entry
            help_label(group, note, wraplength=205 if width > 20 else 130, padx=0)
        group = ttk.Frame(settings)
        group.pack(side='left', padx=(0, 12), anchor='n')
        ttk.Label(group, text='Made in / recipe category').pack(anchor='w')
        categories = sorted(c for c in app.catalog.raw.get('recipe-category', {'crafting': {}, 'smelting': {}}) if not c.startswith('recipe-studio-only-'))
        self.category_labels = {}
        for category in categories:
            kinds = [title for kind, title in [('assembling-machine', 'Assemblers'), ('furnace', 'Furnaces'), ('rocket-silo', 'Rocket silos'), ('character', 'Player')] if any(category in p.get('crafting_categories', []) for p in app.catalog.raw.get(kind, {}).values())]
            self.category_labels[category] = category + (' — ' + ', '.join(kinds) if kinds else '')
        self.machine_selection = tk.StringVar(value=self.category_labels.get('crafting', 'crafting'))
        self.machine_choice = ttk.Combobox(group, textvariable=self.machine_selection, values=list(self.category_labels.values()), state='readonly', width=28)
        self.machine_choice.bind('<<ComboboxSelected>>', lambda e: self.category.set(next(k for k, v in self.category_labels.items() if v == self.machine_selection.get())))
        self.machine_choice.pack(fill='x')
        help_label(group, 'Category determines compatible machines. See the machine list below.', wraplength=235, padx=0)
        self.machines_text = tk.StringVar()
        ttk.Label(self, textvariable=self.machines_text, padding=(12, 0, 12, 6), wraplength=1000, style='Help.TLabel').pack(anchor='w')
        self.enabled_button = ttk.Checkbutton(settings, text='Available from start', variable=self.enabled, command=self.availability_changed)
        self.enabled_button.pack(side='left')
        self.unlock_text = tk.StringVar()
        ttk.Label(self, textvariable=self.unlock_text, padding=(12, 0, 12, 4), style='Help.TLabel', wraplength=1000).pack(anchor='w')
        for var in (self.name, self.seconds, self.enabled, self.category):
            var.trace_add('write', lambda *_, v=var: self.mark(coalesce=str(v)))
        self.category.trace_add('write', lambda *_: self.update_machines())
        holder = ttk.Frame(self)
        holder.pack(fill='both', expand=True)
        self.canvas = tk.Canvas(holder, bg=BG, highlightthickness=0)
        ybar = ttk.Scrollbar(holder, orient='vertical', command=self.canvas.yview)
        xbar = ttk.Scrollbar(holder, orient='horizontal', command=self.canvas.xview)
        self.canvas.configure(yscrollcommand=ybar.set, xscrollcommand=xbar.set)
        ybar.pack(side='right', fill='y')
        xbar.pack(side='bottom', fill='x')
        self.canvas.pack(fill='both', expand=True)
        self.canvas.bind('<Button-3>', self.context)
        bind_navigation(self, self.draw)
        ttk.Label(self, text='Click a node to edit · Drag empty space to pan · Controls can be changed in Settings → Keyboard', padding=10).pack(anchor='w')
        self.update_machines()
        self.recipe = Recipe('new-recipe', {'type': 'recipe', 'name': 'new-recipe', 'ingredients': [], 'results': []})
        self.name.set('new-recipe')
        self.dirty = False
        self.draw()
        self.tracking = True
        self.last_state = self.snapshot()

    def snapshot(self):
        return {'recipe': copy.deepcopy(self.recipe), 'name': self.name.get(), 'seconds': self.seconds.get(),
                'enabled': self.enabled.get(), 'category': self.category.get(), 'loaded_name': self.loaded_name,
                'is_custom': self.is_custom, 'saved_key': self.saved_key, 'result_machine': self.result_machine,
                'item_draft': copy.deepcopy(self.item_draft), 'dirty': self.dirty, 'auto_name': self.auto_name,
                'expanded_recipes': copy.deepcopy(self.expanded_recipes), 'availability_override': self.availability_override}

    def restore(self, state):
        self.tracking = False
        self.recipe = copy.deepcopy(state['recipe'])
        self.auto_name = state.get('auto_name', False)
        self.availability_override = state.get('availability_override', False)
        self.expanded_recipes = copy.deepcopy(state.get('expanded_recipes', {}))
        for key in ('loaded_name', 'is_custom', 'saved_key', 'result_machine', 'item_draft', 'dirty'):
            setattr(self, key, copy.deepcopy(state[key]))
        for key in ('name', 'seconds', 'enabled', 'category'):
            getattr(self, key).set(state[key])
        self.tracking = True
        self.update_mode()
        self.draw()
        self.last_state = self.snapshot()

    def update_mode(self):
        unlocks = self.app.project.recipe_unlocks(self.loaded_name, self.app.base_raw) if self.loaded_name else []
        self.enabled_button.configure(state='normal')
        self.unlock_text.set(('Available from start: applying this edit removes all technology unlocks.' if self.enabled.get() else 'Unlocked by: ' + ', '.join(unlocks) + '. Edits keep these technology unlocks.') if unlocks else '' if self.enabled.get() else 'Locked from start. Assign a technology in Pending requirements after saving.')
        self.commit_text.set('Apply edit' if self.loaded_name else 'Save as new recipe')
        if self.loaded_name:
            self.copy_button.pack(side='right', anchor='n', padx=(0, 8))
        else:
            self.copy_button.pack_forget()
        self.name_entry.configure(state='readonly' if self.loaded_name else 'normal')
        self.purpose.set('EDIT RECIPE — Apply changes to ' + self.loaded_name + '.' if self.loaded_name else 'NEW RECIPE — Add ingredients/results, create items, then save the recipe.')
        if self in self.app.tabs.winfo_children():
            try:
                self.app.tabs.tab(self, text=(self.loaded_name or self.name.get() or 'New recipe') + (' *' if self.dirty else ''))
            except tk.TclError:
                pass

    def save_as_new(self, new_name=None):
        if new_name is None:
            if not self.loaded_name:
                return self.save_changes()
            dialog = tk.Toplevel(self.app)
            dialog.title('Save recipe as a new recipe')
            dialog.transient(self.app)
            dialog.geometry('540x230')
            ttk.Label(dialog, text='New recipe ID', padding=(16, 16, 16, 6)).pack(anchor='w')
            base_name = (self.recipe.results[0]['name'] if self.recipe.results else self.loaded_name) + '_recipe'
            default = base_name
            index = 2
            while default in self.app.catalog.recipes:
                default = base_name + '_' + str(index)
                index += 1
            name = tk.StringVar(value=default)
            entry = ttk.Entry(dialog, textvariable=name)
            entry.pack(fill='x', padx=16)
            entry_undo(entry, name)
            help_label(dialog, 'A unique ID for the copied recipe. Your current ingredients, results and settings are copied; the original recipe is kept.', wraplength=500)
            def save():
                if self.save_as_new(name.get().strip()):
                    dialog.destroy()
            ttk.Button(dialog, text='Save as new recipe', command=save).pack(anchor='e', padx=16, pady=12)
            entry.focus_set()
            entry.selection_range(0, 'end')
            return
        before = copy.deepcopy(self.app.project.data)
        state_before = self.snapshot()
        try:
            if new_name in self.app.catalog.recipes:
                raise ValueError('That recipe ID already exists. Choose a unique name for the copy.')
            self.app.project.save_recipe(self.recipe, new_name, self.seconds.get(), bool(self.availability_override and self.enabled.get()), self.is_custom, self.category.get())
            self.app.project.compile(Catalog(self.app.base_raw))
            self.app.persist()
            self.app.record_undo('Save recipe copy', self, state_before, before)
            self.app.refresh_catalog()
            # Continue editing the new copy, so export cannot apply the draft
            # to the original recipe as a side effect of saving open tabs.
            self.tracking = False
            self.load(new_name)
            return True
        except (ValueError, OSError, KeyError) as exc:
            self.app.project.data = before
            messagebox.showerror('Cannot save recipe copy', str(exc), parent=self)
            return False

    def update_machines(self):
        self.machine_selection.set(self.category_labels.get(self.category.get(), self.category.get()))
        machines = []
        for kind in ('assembling-machine', 'furnace', 'rocket-silo', 'character'):
            for name, proto in self.app.catalog.raw.get(kind, {}).items():
                if self.category.get() in proto.get('crafting_categories', []):
                    machines.append(name.replace('-', ' '))
        if self.recipe:
            machines.extend(name.replace('-', ' ') for name, m in self.app.project.data['machines'].items() if self.recipe.name in m['recipes'])
        self.machines_text.set('Compatible producers: ' + (', '.join(machines) if machines else 'No loaded machine supports this category.'))

    def save_changes(self, quiet=False):
        if not self.recipe:
            return True
        before = copy.deepcopy(self.app.project.data)
        state_before = self.snapshot()
        try:
            name = self.loaded_name or self.name.get().strip()
            affected_techs = []
            if self.availability_override and self.enabled.get():
                affected_techs = self.app.project.remove_recipe_unlocks(name, self.app.base_raw)
            if self.app.project.recipe_unlocks(name, self.app.base_raw):
                tracking = self.tracking
                self.tracking = False
                self.enabled.set(False)
                self.tracking = tracking
            if not self.dirty and self.saved_key == name:
                return True
            if not self.loaded_name and name in self.app.catalog.recipes:
                raise ValueError('That recipe ID already exists. Load it to apply edits, or choose a unique name for a new recipe.')
            self.app.project.save_recipe(self.recipe, name, self.seconds.get(), self.enabled.get(), self.is_custom, self.category.get())
            self.app.project.compile(Catalog(self.app.base_raw))
            self.app.persist()
            self.app.record_undo('Apply recipe' if self.loaded_name else 'Save new recipe', self, state_before, before)
            related = []
            for widget in self.app.tabs.winfo_children():
                if getattr(widget, 'selected', None) in affected_techs and hasattr(widget, 'editor_vars'):
                    related.append((weakref.ref(widget), widget.snapshot()))
                    widget.editor_tracking = False
                    variable = widget.editor_vars['unlocks']
                    variable.set(', '.join(value.strip() for value in variable.get().split(',') if value.strip() and value.strip() != name))
                    widget.editor_tracking = True
                    widget.last_editor_state = widget.snapshot()
            self.app.undo_stack[-1]['related'] = related
            self.availability_override = False
            self.saved_key = name
            self.dirty = False
            self.update_mode()
            self.app.refresh_catalog()
            self.last_state = self.snapshot()
            return True
        except (ValueError, OSError, KeyError) as exc:
            self.app.project.data = before
            messagebox.showerror('Cannot save changes', str(exc), parent=self)
            return False

    def availability_changed(self):
        self.availability_override = self.enabled.get()
        self.update_mode()
        self.last_state = self.snapshot()

    def mark(self, coalesce=None):
        if self.recipe and self.tracking:
            if coalesce == str(self.name):
                self.auto_name = False
            if self.auto_name and not self.loaded_name and not self.saved_key:
                suggested = self.recipe.results[0]['name'] + '_recipe' if self.recipe.results else 'new-recipe'
                self.tracking = False
                self.name.set(suggested)
                self.tracking = True
            if self.last_state and not self.app.undoing:
                self.app.record_undo('Edit recipe', self, self.last_state, coalesce=(id(self), coalesce) if coalesce else None)
            self.dirty = True
            self.update_mode()
            self.last_state = self.snapshot()

    def close(self):
        if self.dirty:
            answer = messagebox.askyesnocancel('Close recipe', 'Save changes to the project before closing?', parent=self)
            if answer is None or (answer and not self.save_changes()):
                return
        self.destroy()

    def destroy(self):
        self.tracking = False
        super().destroy()

    def pick(self):
        self.load_recipe_picker()

    def load_recipe_picker(self):
        def choose(name):
            if self.dirty and not messagebox.askyesno('Load recipe', 'Discard the current unsaved flowchart changes?', parent=self):
                return
            self.load(name[1])
        Picker(self.app, choose, recipe_names=True)

    def select_item(self, key):
        from machine_model import placed_item_name
        machine_name = next((name for name, m in self.app.project.data['machines'].items() if placed_item_name(name, m) == key[1]), None) if key[0] == 'item' else None
        if machine_name:
            if key not in self.app.catalog.by_product:
                self.app.fix_machine_recipe(machine_name)
                return
        names = self.app.catalog.by_product.get(key, [])
        if not names:
            messagebox.showinfo('No crafting recipe', 'This item has no loaded recipe. It may be mined or obtained another way. You can still use it as an ingredient.')
            return
        if self.dirty and not messagebox.askyesno('Replace recipe', 'Discard the current unsaved changes?'):
            return
        if len(names) == 1:
            self.load(names[0])
        else:
            dialog = tk.Toplevel(self.app)
            dialog.title('Choose crafting recipe')
            ttk.Label(dialog, text='Multiple recipes produce this item.', padding=12).pack()
            listing = tk.Listbox(dialog, width=60, height=min(15, len(names)))
            listing.pack(padx=12, pady=8)
            for name in names:
                listing.insert('end', name)
            listing.selection_set(0)
            def choose(*_):
                if listing.curselection():
                    selected = names[listing.curselection()[0]]
                    dialog.destroy()
                    self.load(selected)
            listing.bind('<Double-Button-%d>' % BUTTONS[self.app.controls['picker_button']], choose)
            listing.bind(sequence(self.app.controls['picker_accept']), choose)
            ttk.Button(dialog, text='Load recipe', command=choose).pack(pady=12)

    def load(self, name):
        if self.tracking:
            self.app.record_undo('Load recipe', self, self.snapshot())
        self.tracking = False
        self.loaded_name = name
        self.availability_override = False
        self.expanded_recipes = {}
        self.auto_name = False
        self.saved_key = name if name in self.app.project.data['recipes'] else None
        saved = self.app.project.data['recipes'].get(name)
        self.recipe = self.app.project.recipe(name) if saved else Recipe(name, self.app.catalog.recipes[name])
        self.is_custom = bool(saved and saved.get('custom'))
        from machine_model import placed_item_name
        self.result_machine = next((n for n, m in self.app.project.data['machines'].items() if placed_item_name(n, m) == self.recipe.results[0]['name']), None) if self.is_custom and self.recipe.results else None
        self.item_draft = copy.deepcopy(self.app.project.data['items'].get(self.recipe.results[0]['name'])) if self.is_custom and self.recipe.results else None
        self.name.set(name)
        source = self.recipe.original.get('normal', self.recipe.original)
        self.seconds.set(str(saved['seconds'] if saved else source.get('energy_required', 0.5)))
        self.enabled.set(False if self.app.project.recipe_unlocks(name, self.app.base_raw) else saved['enabled'] if saved else source.get('enabled', True))
        base_recipe = self.app.base_raw.get('recipe', {}).get(name, source)
        base_category = base_recipe.get('normal', base_recipe).get('category', 'crafting')
        self.category.set(saved.get('category', base_category) if saved else base_category)
        self.dirty = False
        self.tracking = True
        self.update_mode()
        self.draw()
        self.last_state = self.snapshot()

    def draw(self):
        if self.expanded_recipes:
            from recipe_graph import draw_recipes
            draw_recipes(self)
            if not self.expanded_recipes:
                self.draw()
                return
            self.collapse_button.pack(side='left')
            return
        self.graph_nodes = {}
        self.collapse_button.pack_forget()
        c = self.canvas
        c.delete('all')
        self.flow_images = []
        if not self.recipe:
            c.create_text(430, 180, text='Edit a recipe\n\nSearch for an item above to start crafting.', fill=TEXT, font=('Segoe UI', 17), justify='center')
            return
        rows = max(len(self.recipe.ingredients), len(self.recipe.results), 1)
        height = max(460, rows * 120 + 120)
        c.configure(scrollregion=(0, 0, 1040, height))
        c.create_text(190, 36, text='INGREDIENTS', fill=ACCENT, font=('Segoe UI', 12, 'bold'))
        c.create_text(820, 36, text='RESULTS', fill=ACCENT, font=('Segoe UI', 12, 'bold'))
        mid = 80 + rows * 60
        c.create_rectangle(444, mid - 42, 596, mid + 42, fill='#364352', outline=ACCENT, width=2)
        c.create_text(520, mid, text='CRAFT\n' + self.seconds.get() + ' seconds', fill=TEXT, font=('Segoe UI', 12), justify='center')
        for side, values in (('ingredients', self.recipe.ingredients), ('results', self.recipe.results)):
            x = 60 if side == 'ingredients' else 690
            for index, value in enumerate(values):
                y = 80 + index * 120
                if side == 'ingredients':
                    c.create_line(x + 260, y + 44, 390, y + 44, 390, mid, 444, mid, fill='#687b91', width=2, arrow='last')
                else:
                    c.create_line(596, mid, 640, mid, 640, y + 44, x, y + 44, fill=ACCENT, width=2, arrow='last')
                tag = f'{side}_{index}'
                c.create_rectangle(x, y, x + 260, y + 88, fill=CARD, outline='#4b6075', width=2, tags=tag)
                image = self.app.icon((value['type'], value['name']), size=48 * self.zoom)
                if self.item_draft and self.item_draft.get('icon') and value['name'] == self.item_draft['name']:
                    try:
                        draft_image = tk.PhotoImage(data=self.item_draft['icon']['data'])
                        self.draft_image = scale_image(draft_image, 48 * self.zoom)
                        image = self.draft_image
                    except tk.TclError:
                        pass
                if image:
                    self.flow_images.append(image)
                    c.create_image(x + 40, y + 43, image=image, tags=tag)
                else:
                    c.create_text(x + 38, y + 43, text='◈', fill=ACCENT, font=('Segoe UI', 28), tags=tag)
                label = value['name'].replace('-', ' ')
                c.create_text(x + 78, y + 24, text=label, width=175, anchor='w', fill=TEXT, font=('Segoe UI', 10, 'bold'), tags=tag)
                amount = value.get('amount', f"{value.get('amount_min', '?')}–{value.get('amount_max', '?')}")
                probability = f" · {value['probability']:g} chance" if 'probability' in value else ''
                c.create_text(x + 78, y + 61, text=f'× {amount}{probability}', anchor='w', fill=ACCENT, font=('Segoe UI', 11), tags=tag)
                c.tag_bind(tag, select_event(self), lambda e, s=side, i=index: self.edit(s, i))
        c.scale('all', 0, 0, self.zoom, self.zoom)
        for item in c.find_all():
            if c.type(item) == 'text':
                font = tkfont.Font(font=c.itemcget(item, 'font'))
                c.itemconfigure(item, font=(font.actual('family'), max(5, round(font.actual('size') * self.zoom)), font.actual('weight')))
                width = float(c.itemcget(item, 'width'))
                if width:
                    c.itemconfigure(item, width=width * self.zoom)
        c.configure(scrollregion=(0, 0, 1040 * self.zoom, height * self.zoom))

    def context(self, event):
        if not self.recipe:
            return
        menu = tk.Menu(self, tearoff=False)
        current = self.canvas.find_withtag('current')
        if current:
            for tag in self.canvas.gettags(current[0]):
                node = self.graph_nodes.get(tag)
                if node:
                    path = node['path']
                    if node['side'] is None:
                        if path:
                            menu.add_command(label='Edit this recipe', command=lambda p=path: self.edit_expanded_recipe(p))
                            menu.add_command(label='Hide recipe', command=lambda p=path: self.collapse_recipes(p))
                        else:
                            menu.add_command(label='Collapse expanded recipes', command=self.collapse_recipes)
                        menu.tk_popup(event.x_root, event.y_root)
                        return
                    self.item_context(menu, node['value'], node['side'], path + (node['index'],))
                    menu.tk_popup(event.x_root, event.y_root)
                    return
                match = re.fullmatch(r'(ingredients|results)_(\d+)', tag)
                if match:
                    value = getattr(self.recipe, match[1])[int(match[2])]
                    self.item_context(menu, value, match[1], (int(match[2]),))
                    menu.tk_popup(event.x_root, event.y_root)
                    return
            menu.destroy()
            return
        menu.add_command(label='Add new ingredient', command=lambda: self.add('ingredients'))
        menu.add_command(label='Add new result', command=lambda: self.add('results'))
        menu.add_separator()
        menu.add_command(label='Load recipe', command=self.load_recipe_picker)
        menu.add_command(label='Create item', command=self.edit_item)
        menu.add_command(label='Create item as ingredient', command=lambda: self.edit_item(as_ingredient=True))
        from bulk_items import bulk_item_dialog
        menu.add_command(label='Bulk ingredient creation', command=lambda: bulk_item_dialog(self))
        menu.tk_popup(event.x_root, event.y_root)

    def item_context(self, menu, value, side, path):
        key = (value['type'], value['name'])
        if side == 'ingredients':
            menu.add_command(label='Show recipe', command=lambda: self.show_recipe(path, key))
            if path in self.expanded_recipes:
                menu.add_command(label='Hide recipe', command=lambda: self.collapse_recipes(path))
            menu.add_separator()
        menu.add_command(label='Use as ingredient in new recipe', command=lambda: self.open_with_item('ingredients', key))
        menu.add_command(label='Use as product in new recipe', command=lambda: self.open_with_item('results', key))
        from creations_ui import recipes_containing
        menu.add_separator()
        menu.add_command(label='See all recipes containing this item' if key[0] == 'item' else 'See all recipes containing this fluid',
                         command=lambda: recipes_containing(self.app, key))
        from replace_ingredient import replacement_dialog
        menu.add_separator()
        menu.add_command(label='Replace ingredient in all recipes', command=lambda: replacement_dialog(self, key))

    def show_recipe(self, path, key, recipe_name=None):
        path = tuple(path)
        ancestors = {self.loaded_name or self.name.get()}
        ancestors.update(self.expanded_recipes[parent]['name'] for parent in self.expanded_recipes if len(parent) < len(path) and path[:len(parent)] == parent)
        names = sorted(name for name in self.app.catalog.by_product.get(key, []) if name not in ancestors)
        if recipe_name is None and len(names) > 1:
            dialog = tk.Toplevel(self.app)
            dialog.title('Choose recipe to show')
            dialog.transient(self.app)
            ttk.Label(dialog, text='Recipes producing ' + key[1], padding=12).pack(anchor='w')
            listing = tk.Listbox(dialog, width=65, height=min(15, len(names)), bg=BG, fg=TEXT, selectbackground='#45566c')
            listing.pack(fill='both', expand=True, padx=12, pady=8)
            for name in names:
                listing.insert('end', name)
            listing.selection_set(0)
            def choose(*_):
                if listing.curselection():
                    name = names[listing.curselection()[0]]
                    dialog.destroy()
                    self.show_recipe(path, key, name)
            listing.bind('<Double-Button-%d>' % BUTTONS[self.app.controls['picker_button']], choose)
            listing.bind(sequence(self.app.controls['picker_accept']), choose)
            ttk.Button(dialog, text='Show recipe', command=choose).pack(pady=12)
            return
        name = recipe_name or (names[0] if names else None)
        if name not in names:
            messagebox.showinfo('No crafting recipe to show', 'No non-cyclic crafting recipe is available for ' + key[1] + '. It may be mined or obtained another way.', parent=self)
            return False
        if self.expanded_recipes.get(path) == {'name': name, 'key': key}:
            return True
        self.app.record_undo('Show ingredient recipe', self, self.snapshot())
        self.expanded_recipes = {p: entry for p, entry in self.expanded_recipes.items() if p[:len(path)] != path}
        self.expanded_recipes[path] = {'name': name, 'key': key}
        self.draw()
        target_zoom = min(self.zoom, max(.25, (max(800, self.canvas.winfo_width()) - 30) / self.graph_width))
        if target_zoom != self.zoom:
            self.zoom = target_zoom
            self.draw()
        self.canvas.xview_moveto(0)
        self.canvas.yview_moveto(0)
        self.last_state = self.snapshot()
        return True

    def collapse_recipes(self, path=None):
        if not self.expanded_recipes:
            return
        self.app.record_undo('Hide ingredient recipes', self, self.snapshot())
        self.expanded_recipes = {} if path is None else {p: entry for p, entry in self.expanded_recipes.items() if p[:len(path)] != path}
        self.draw()
        self.last_state = self.snapshot()

    def edit_expanded_recipe(self, path):
        entry = self.expanded_recipes.get(tuple(path))
        if entry and entry['name'] in self.app.catalog.recipes:
            from creations_ui import open_recipe
            return open_recipe(self.app, entry['name'])

    def open_with_item(self, side, key):
        tab = self.app.new_tab()
        tab.add_entry(side, key)
        return tab

    def add(self, side):
        def selected(key):
            self.add_entry(side, key)
        Picker(self.app, selected)

    def add_entry(self, side, key, amount=None):
        if amount is None:
            amount = self.app.project.data['items'].get(key[1], {}).get('default_amount', 1)
        getattr(self.recipe, side).append({'type': key[0], 'name': key[1], 'amount': amount})
        self.mark()
        self.draw()

    def edit(self, side, index):
        values = getattr(self.recipe, side)
        original = values[index]
        draft = copy.deepcopy(original)
        dialog = tk.Toplevel(self.app)
        dialog.title('Edit ' + side[:-1])
        dialog.transient(self.app)
        label = tk.StringVar(value=draft['name'])
        ttk.Label(dialog, textvariable=label, padding=16).pack()
        def changed(key):
            draft['type'], draft['name'] = key
            label.set(key[1])
        if not (self.result_machine and side == 'results'):
            ttk.Button(dialog, text='Change item', command=lambda: Picker(self.app, changed)).pack()
        ttk.Label(dialog, text='Quantity (enter a number to replace a random range)', padding=10).pack()
        amount = tk.StringVar(value=str(draft.get('amount', '')))
        amount_entry = ttk.Entry(dialog, textvariable=amount)
        amount_entry.pack(padx=16)
        entry_undo(amount_entry, amount)
        help_label(dialog, 'Amount consumed or produced by one craft. Leave blank to retain an existing random result range.')
        ttk.Label(dialog, text='Existing temperature, probability and other properties\nare preserved unless the item is changed.', padding=12).pack()
        def save():
            try:
                changed_item = (draft['type'], draft['name']) != (original['type'], original['name'])
                if changed_item:
                    new = {'type': draft['type'], 'name': draft['name']}
                else:
                    new = copy.deepcopy(draft)
                if amount.get().strip():
                    number = float(amount.get())
                    if not math.isfinite(number) or number <= 0 or (new['type'] == 'item' and not number.is_integer()):
                        raise ValueError('Use a positive quantity; item amounts must be whole numbers.')
                    new['amount'] = int(number) if number.is_integer() else number
                    new.pop('amount_min', None)
                    new.pop('amount_max', None)
                elif changed_item:
                    raise ValueError('Enter a quantity for the new item.')
                values[index] = new
                self.mark()
                self.draw()
                dialog.destroy()
            except ValueError as exc:
                messagebox.showerror('Invalid quantity', str(exc), parent=dialog)
        ttk.Button(dialog, text='Save changes', command=save).pack(pady=8)
        def remove():
            values.pop(index)
            self.mark()
            self.draw()
            dialog.destroy()
        if not (self.result_machine and side == 'results'):
            ttk.Button(dialog, text='Remove rectangle', command=remove).pack(pady=(0, 16))

    def edit_item(self, as_ingredient=False):
        from editors import item_dialog
        item_dialog(self, as_ingredient=as_ingredient)



class App(tk.Tk):
    def __init__(self):
        if sys.platform == 'win32':
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID('FuryziN.FactorioModCreationTool')
        super().__init__()
        self.title('Factorio Mod Creation Tool — by FuryziN')
        self.app_icon = tk.PhotoImage(file=str(Path(__file__).resolve().parent / 'assets' / 'app-icon.png'), master=self)
        self.iconphoto(True, self.app_icon)
        self.geometry('1200x790')
        self.minsize(900, 600)
        self.configure(bg=BG)
        configure_theme(self)
        self.bind_class('Toplevel', '<Map>', self.configure_dialog, add='+')
        self.catalog = None
        self.project = Project()
        self.undo_stack = []
        self.undoing = False
        self.autosave_path = Path(__file__).resolve().parent / '.studio' / 'project.json'
        self.project_path = None
        self.controls_path = Path(__file__).resolve().parent / '.studio' / 'settings.json'
        self.controls = load_controls(self.controls_path)
        self.shortcut_bindings = []
        self.images = {}
        self.mods_selected = []
        self.events = queue.Queue()
        self.protocol('WM_DELETE_WINDOW', self.close)
        self.poll_job = self.after(100, self.poll)
        self.setup()
        self.apply_controls()

    def apply_controls(self):
        for binding in self.shortcut_bindings:
            self.unbind(binding)
        self.shortcut_bindings = []
        for action, key in self.controls['keys'].items():
            binding = sequence(key)
            self.bind(binding, lambda e, a=action: self.shortcut(a))
            self.shortcut_bindings.append(binding)
        if hasattr(self, 'tabs'):
            for tab in self.tabs.winfo_children():
                if hasattr(tab, 'canvas'):
                    bind_navigation(tab, tab.draw)
                    tab.draw()
        def visit(widget):
            if isinstance(widget, tk.Text) and widget.winfo_toplevel() is self:
                self.bind_text_undo(widget)
            for child in widget.winfo_children():
                visit(child)
        visit(self)

    def bind_text_undo(self, widget):
        previous = getattr(widget, 'project_undo_binding', None)
        if previous:
            widget.unbind(*previous)
        binding = sequence(self.controls['keys']['undo'])
        funcid = widget.bind(binding, lambda event: self.shortcut('undo'))
        widget.project_undo_binding = (binding, funcid)

    def configure_dialog(self, event):
        dialog = event.widget
        if isinstance(dialog, tk.Toplevel):
            dialog.configure(background=BG)
            dialog.bind(sequence(self.controls['dialog_dismiss']), lambda e: dialog.destroy())

    def shortcut(self, action):
        if action == 'undo':
            self.undo()
            return 'break'
        if action == 'settings':
            settings_dialog(self)
            return 'break'
        if not hasattr(self, 'tabs'):
            return 'break'
        current = self.nametowidget(self.tabs.select()) if self.tabs.select() else None
        actions = {'export': self.export_project, 'edit': self.new_tab, 'item': self.new_item_tab, 'tech': self.tech_tab, 'machine': self.new_machine_tab,
                   'save': lambda: current.save_changes() if current else None,
                   'close': lambda: current.close() if current else None,
                   'find': lambda: current.load_recipe_picker() if isinstance(current, RecipeTab) else getattr(current, 'tree_search_entry', self).focus_set()}
        if action in actions:
            actions[action]()
        return 'break'

    def record_undo(self, label, tab=None, state=None, project=None, coalesce=None):
        if self.undoing:
            return
        now = time.monotonic()
        if coalesce and self.undo_stack and self.undo_stack[-1]['coalesce'] == coalesce and now - self.undo_stack[-1]['time'] < .75:
            self.undo_stack[-1]['time'] = now
            return
        self.undo_stack.append({'label': label, 'tab': weakref.ref(tab) if tab else None,
                                'state': copy.deepcopy(state), 'project': copy.deepcopy(project),
                                'coalesce': coalesce, 'time': now})
        self.undo_stack = self.undo_stack[-100:]

    def undo(self):
        while self.undo_stack:
            entry = self.undo_stack.pop()
            tab = entry['tab']() if entry['tab'] else None
            live = tab is not None and tab.winfo_exists()
            if not live and entry['project'] is None:
                continue
            current_project = copy.deepcopy(self.project.data)
            self.undoing = True
            try:
                if entry['project'] is not None:
                    self.project.data = copy.deepcopy(entry['project'])
                    self.persist()
                    self.refresh_catalog()
                    for widget in self.tabs.winfo_children():
                        if isinstance(widget, RecipeTab) and widget is not tab and not widget.dirty and widget.saved_key in self.project.data['recipes']:
                            widget.tracking = False
                            widget.enabled.set(self.project.data['recipes'][widget.saved_key]['enabled'])
                            widget.tracking = True
                            widget.last_state = widget.snapshot()
                if live and entry['state'] is not None:
                    tab.restore(entry['state'])
                    self.tabs.select(tab)
                elif live and hasattr(tab, 'saved_name'):
                    tab.dirty = False
                    if tab.saved_name in self.project.data['machines']:
                        tab.load(tab.saved_name)
                    else:
                        tab.saved_name = None
                        tab.ready = False
                        for child, _ in tab.form_children:
                            child.pack_forget()
                        tab.placeholder.pack(fill='both', expand=True)
                        self.tabs.tab(tab, text='Create machine')
                elif live and hasattr(tab, 'selected'):
                    from editors import technology_dialog
                    name = tab.selected if tab.selected in self.catalog.raw.get('technology', {}) else None
                    technology_dialog(tab, name, force=True)
                for reference, state in entry.get('related', []):
                    widget = reference()
                    if widget is not None and widget.winfo_exists():
                        widget.restore(state)
                if self.undo_stack:
                    self.undo_stack[-1]['coalesce'] = None
                return True
            except (OSError, ValueError, KeyError, tk.TclError) as exc:
                self.project.data = current_project
                self.undo_stack.append(entry)
                messagebox.showerror('Cannot undo', str(exc))
                return False
            finally:
                self.undoing = False
        return False

    def setup(self):
        self.setup_frame = ttk.Frame(self, padding=42)
        self.setup_frame.pack(fill='both', expand=True)
        f = self.setup_frame
        ttk.Label(f, text='FACTORIO MOD CREATION TOOL · by FuryziN', foreground=ACCENT, font=('Segoe UI', 12, 'bold')).pack(anchor='w')
        ttk.Button(f, text='Settings', command=lambda: settings_dialog(self)).pack(anchor='e')
        ttk.Label(f, text='Build your next production chain.', font=('Segoe UI', 26, 'bold'), padding=(0, 16)).pack(anchor='w')
        ttk.Label(f, text='Load game data, edit flowcharts, and export a ready-to-install mod.').pack(anchor='w', pady=(0, 28))
        self.install = tk.StringVar()
        default = find_installation()
        if default:
            self.install.set(str(default))
        ttk.Label(f, text='Factorio installation folder (contains bin and data)').pack(anchor='w')
        row = ttk.Frame(f)
        row.pack(fill='x', pady=10)
        ttk.Entry(row, textvariable=self.install).pack(side='left', fill='x', expand=True)
        ttk.Button(row, text='Browse…', command=self.browse_game).pack(side='left', padx=(12, 0))
        help_label(f, 'Path to the installed game. The app uses its data and executable to load prototypes.', wraplength=850, padx=0)
        ttk.Label(f, text='Optional mods · add a mod ZIP, unpacked mod, or a folder of mods including dependencies').pack(anchor='w', pady=(20, 8))
        self.mod_list = tk.Listbox(f, bg=CARD, fg=TEXT, height=5, borderwidth=0)
        self.mod_list.pack(fill='x')
        actions = ttk.Frame(f)
        actions.pack(fill='x', pady=10)
        ttk.Button(actions, text='Add mod ZIP', command=self.add_zip).pack(side='left')
        ttk.Button(actions, text='Add mod folder', command=self.add_folder).pack(side='left', padx=10)
        ttk.Button(actions, text='Clear mods', command=self.clear_mods).pack(side='left')
        self.load_button = ttk.Button(f, text='Load game data →', command=self.start_load)
        self.load_button.pack(anchor='w', pady=(24, 12))
        self.status = tk.StringVar(value='Factorio 1.1.77+ or 2.x required. Your game settings and installed mods are kept separate.')
        ttk.Label(f, textvariable=self.status, wraplength=1000).pack(anchor='w')
        self.progress = ttk.Progressbar(f, mode='indeterminate')
        self.progress.pack(fill='x', pady=12)

    def browse_game(self):
        path = filedialog.askdirectory(title='Select Factorio installation')
        if path:
            self.install.set(path)

    def add_zip(self):
        for path in filedialog.askopenfilenames(filetypes=[('Factorio mod ZIP', '*.zip')]):
            self.mods_selected.append(path)
            self.mod_list.insert('end', path)

    def add_folder(self):
        path = filedialog.askdirectory(title='Select unpacked mod or mods folder')
        if path:
            self.mods_selected.append(path)
            self.mod_list.insert('end', path)

    def clear_mods(self):
        self.mods_selected.clear()
        self.mod_list.delete(0, 'end')

    def start_load(self):
        self.load_button.configure(state='disabled')
        self.progress.start()
        self.status.set('Loading with the Factorio engine… This can take a few minutes. Close any other Factorio instances.')
        install, mods = self.install.get(), list(self.mods_selected)
        cache = Path(__file__).resolve().parent / '.cache'
        cache.mkdir(exist_ok=True)
        workspace = Path(tempfile.mkdtemp(prefix='session-', dir=cache))
        def work():
            try:
                self.events.put(('loaded', load_game(install, mods, workspace, track_mod_content=True)))
            except Exception as exc:
                self.events.put(('error', str(exc)))
        threading.Thread(target=work, daemon=True).start()

    def poll(self):
        try:
            kind, value = self.events.get_nowait()
            self.progress.stop()
            if kind == 'error':
                self.load_button.configure(state='normal')
                self.status.set('Loading failed. Correct the path or mods and try again.')
                messagebox.showerror('Could not load Factorio', value)
            else:
                self.catalog, self.root_path, self.mods_path = value
                self.setup_frame.destroy()
                self.workspace()
        except queue.Empty:
            pass
        self.poll_job = self.after(100, self.poll)

    def destroy(self):
        if getattr(self, 'poll_job', None):
            self.after_cancel(self.poll_job)
            self.poll_job = None
        super().destroy()

    def workspace(self):
        self.loaded_items = set(getattr(self.catalog, 'loaded_items', set()))
        self.loaded_recipes = set(getattr(self.catalog, 'loaded_recipes', set()))
        self.base_raw = copy.deepcopy(self.catalog.raw)
        toolbar = ttk.Frame(self, padding=12)
        toolbar.pack(fill='x')
        ttk.Label(toolbar, text='FACTORIO MOD CREATION TOOL\nby FuryziN', foreground=ACCENT, font=('Segoe UI', 10, 'bold')).pack(side='left', padx=(0, 14))
        ttk.Button(toolbar, text='New item/edit recipe', command=self.new_tab).pack(side='left', padx=(0, 6))
        ttk.Button(toolbar, text='Edit tech tree', command=self.tech_tab).pack(side='left')
        self.create_machine_button = ttk.Button(toolbar, text='Create machine', command=self.new_machine_tab)
        self.create_machine_button.pack(side='left', padx=6)
        ttk.Button(toolbar, text='Browse creations', command=self.browse_creations).pack(side='left', padx=(0, 6))
        self.pending_button = ttk.Button(toolbar, text='Pending requirements', command=self.pending_tab)
        ttk.Button(toolbar, text='Export mod file', command=self.export_project).pack(side='right')
        project_bar = ttk.Frame(self, padding=(12, 0, 12, 8))
        project_bar.pack(fill='x')
        ttk.Button(project_bar, text='Save project as…', command=self.save_project_as).pack(side='left')
        ttk.Button(project_bar, text='Open project…', command=self.open_project).pack(side='left', padx=6)
        ttk.Button(project_bar, text='Settings', command=lambda: settings_dialog(self)).pack(side='left', padx=6)
        ttk.Button(project_bar, text='Read equations', command=self.equations_tab).pack(side='left', padx=6)
        self.project_status = tk.StringVar(value='No saved changes')
        summary = ttk.Frame(project_bar)
        summary.pack(side='right', anchor='n')
        ttk.Label(summary, textvariable=self.project_status).pack(anchor='e')
        self.warning_area = ttk.Frame(summary)
        self.warning_area.pack(fill='x')
        self.tabs = BrowserNotebook(self)
        self.tabs.pack(fill='both', expand=True, padx=12, pady=(0, 12))
        self.new_tab()
        self.update_pending_button()
        if self.autosave_path.exists() and messagebox.askyesno('Restore project', 'Restore your saved recipes, items, technologies and machines?'):
            self.restore_project(self.autosave_path)

    def persist(self):
        self.project.save(self.autosave_path)
        if self.project_path and self.project_path != self.autosave_path:
            self.project.save(self.project_path)
        self.update_project_status()

    def update_project_status(self):
        if hasattr(self, 'project_status'):
            d = self.project.data
            deleted = sum(len(names) for names in d.get('deleted', {}).values())
            self.project_status.set(f"Saved: {len(d['recipes'])} recipes · {len(d['items'])} items · {len(d['technologies'])} techs · {len(d['machines'])} machines" + (f' · {deleted} deleted' if deleted else ''))
            self.update_machine_warnings()
            self.update_pending_button()

    def update_pending_button(self):
        if not hasattr(self, 'pending_button'):
            return
        count = len(self.project.items_missing_icons()) + len(self.project.missing_machine_recipes(Catalog(self.base_raw))) + len(self.project.items_missing_recipes(self.catalog, self.loaded_items)) + len(self.project.items_unused(self.catalog, self.loaded_items)) + len(self.project.recipes_missing_unlocks(self.catalog, self.loaded_recipes))
        if count:
            self.pending_button.configure(text=f'Pending requirements ({count})')
            self.pending_button.pack(side='left', after=self.create_machine_button, padx=6)
        else:
            self.pending_button.pack_forget()

    def pending_tab(self):
        from pending_ui import PendingTab
        for widget in self.tabs.winfo_children():
            if isinstance(widget, PendingTab):
                self.tabs.select(widget)
                widget.refresh()
                return
        tab = PendingTab(self)
        self.tabs.add(tab, text='Pending requirements')
        self.tabs.select(tab)

    def update_machine_warnings(self):
        if not hasattr(self, 'warning_area'):
            return
        for widget in self.warning_area.winfo_children():
            widget.destroy()
        missing = self.project.missing_machine_recipes(Catalog(self.base_raw))
        for name in missing:
            row = ttk.Frame(self.warning_area)
            row.pack(anchor='e', pady=2)
            ttk.Label(row, text=f"Machine {name} doesn't have a crafting recipe", foreground=ACCENT, wraplength=400).pack(side='left')
            ttk.Button(row, text='Fix', style='Small.TButton', command=lambda n=name: self.fix_machine_recipe(n)).pack(side='left', padx=(6, 0))

    def fix_machine_recipe(self, machine_name):
        from machine_model import placed_item_name
        result_item = placed_item_name(machine_name, self.project.data['machines'][machine_name])
        for widget in self.tabs.winfo_children():
            if isinstance(widget, RecipeTab) and widget.result_machine == machine_name:
                self.tabs.select(widget)
                return
        names = self.catalog.by_product.get(('item', result_item), [])
        tab = RecipeTab(self, new_item=True)
        self.tabs.add(tab, text='Recipe: ' + machine_name)
        self.tabs.select(tab)
        if names:
            tab.load(names[0])
            return
        recipe_name = machine_name
        suffix = 1
        while recipe_name in self.catalog.recipes:
            suffix += 1
            recipe_name = machine_name + '-recipe-' + str(suffix)
        tab.recipe = Recipe(recipe_name, {'type': 'recipe', 'name': recipe_name, 'ingredients': [], 'results': [{'type': 'item', 'name': result_item, 'amount': 1}]})
        tab.result_machine = machine_name
        tab.name.set(recipe_name)
        tab.enabled.set(False)
        tab.purpose.set('CREATE AN ITEM — Create the crafting recipe for machine ' + machine_name + '.')
        tab.draw()

    def refresh_catalog(self):
        self.catalog = Catalog(self.project.merged_raw(self.base_raw))
        self.images.clear()
        self.update_project_status()
        for widget in self.tabs.winfo_children():
            if isinstance(widget, RecipeTab):
                widget.update_mode()
                widget.draw()
            elif hasattr(widget, 'refresh'):
                widget.refresh()
                selected = getattr(widget, 'selected', None)
                if hasattr(widget, 'editor_vars') and not widget.dirty and selected in self.catalog.raw.get('technology', {}):
                    shown = {name.strip() for name in widget.editor_vars['unlocks'].get().split(',') if name.strip()}
                    expected = {effect['recipe'] for effect in self.catalog.raw['technology'][selected].get('effects', []) if effect.get('type') == 'unlock-recipe'}
                    if shown != expected:
                        from editors import technology_dialog
                        technology_dialog(widget, selected, force=True)

    def save_all(self):
        for tab in self.tabs.winfo_children():
            if getattr(tab, 'dirty', False) and hasattr(tab, 'save_changes'):
                if not tab.save_changes(quiet=True):
                    # Prior successfully saved tabs remain saved even when one draft fails.
                    return False
        return True

    def save_project_as(self):
        if not self.save_all():
            return
        path = filedialog.asksaveasfilename(title='Save Factorio Mod Creation Tool project', defaultextension='.json', initialfile='my-mod.studio.json', filetypes=[('Factorio Mod Creation Tool project', '*.json')])
        if path:
            try:
                self.project.save(path)
                self.project_path = Path(path)
            except OSError as exc:
                messagebox.showerror('Cannot save project', str(exc))

    def restore_project(self, path):
        try:
            project = Project.open(path)
            if any(project.data[k] for k in ('recipes', 'items', 'technologies', 'machines', 'deleted')):
                project.compile(Catalog(self.base_raw))
            self.project = project
            self.undo_stack.clear()
            self.project_path = Path(path) if Path(path) != self.autosave_path else None
            for tab in self.tabs.winfo_children():
                tab.destroy()
            self.refresh_catalog()
            self.new_tab()
            self.persist()
        except (OSError, ValueError, KeyError, TypeError) as exc:
            messagebox.showerror('Cannot open project', str(exc))

    def open_project(self):
        if not self.save_all():
            return
        path = filedialog.askopenfilename(title='Open Factorio Mod Creation Tool project', filetypes=[('Factorio Mod Creation Tool project', '*.json')])
        if path:
            self.restore_project(path)

    def export_project(self):
        if self.save_all():
            from editors import export_project_dialog
            export_project_dialog(self)

    def new_item_tab(self):
        self.new_tab()

    def equations_tab(self):
        from equations import EquationsTab
        for tab in self.tabs.winfo_children():
            if isinstance(tab, EquationsTab):
                self.tabs.select(tab)
                return tab
        tab = EquationsTab(self)
        self.tabs.add(tab, text='Read equations')
        self.tabs.select(tab)
        return tab

    def browse_creations(self):
        from creations_ui import CreationsTab
        for tab in self.tabs.winfo_children():
            if isinstance(tab, CreationsTab):
                self.tabs.select(tab)
                tab.refresh()
                return tab
        tab = CreationsTab(self)
        self.tabs.add(tab, text='Browse creations')
        self.tabs.select(tab)
        return tab

    def tech_tab(self):
        from editors import TechTab
        for widget in self.tabs.winfo_children():
            if isinstance(widget, TechTab):
                self.tabs.select(widget)
                return widget
        tab = TechTab(self)
        self.tabs.add(tab, text='Technology tree')
        self.tabs.select(tab)
        return tab

    def new_tab(self):
        tab = RecipeTab(self)
        self.tabs.add(tab, text='New item/edit recipe')
        self.tabs.select(tab)
        return tab

    def new_machine_tab(self, name=None, source=None, mode='create'):
        from machine_ui import MachineTab
        if name:
            for widget in self.tabs.winfo_children():
                if isinstance(widget, MachineTab) and widget.saved_name == name:
                    self.tabs.select(widget)
                    return
        tab = MachineTab(self)
        self.tabs.add(tab, text='Create machine')
        self.tabs.select(tab)
        if name:
            tab.load(name)
        elif source:
            tab.configure_source(source[0], source[1], mode)
        else:
            tab.open_start_dialog()

    def icon(self, key, size=48, cached_only=False):
        proto = self.catalog.items.get(key, {})
        custom = self.project.data['items'].get(key[1])
        if custom and ('fluid' if custom.get('kind') == 'fluid' else 'item') != key[0]:
            custom = None
        from machine_model import placed_item_name
        machine = next((m for n, m in self.project.data['machines'].items() if placed_item_name(n, m) == key[1]), None) if key[0] == 'item' else None
        return prototype_image(self, proto, size, custom['icon'] if custom else (machine.get('icon') if machine else None), cached_only=cached_only)

    def close(self):
        if self.catalog and any(self.nametowidget(tab).dirty for tab in self.tabs.tabs()):
            answer = messagebox.askyesnocancel('Exit Factorio Mod Creation Tool', 'Save pending changes to the project before exiting?')
            if answer is None or (answer and not self.save_all()):
                return
        self.destroy()


if __name__ == '__main__':
    App().mainloop()
