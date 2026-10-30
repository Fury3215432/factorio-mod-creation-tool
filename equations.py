"""Read simple crafting equations without executing input as code."""
import copy
import re
from time import time_ns
import tkinter as tk
from tkinter import ttk, messagebox

from core import Catalog, Recipe
from controls import sequence
from project import identifier, positive, default_icon_asset
from ui import help_label, entry_undo


def plan_equations(app, text, seconds='0.5', category='crafting'):
    seconds = positive(seconds, 'Crafting seconds')
    if category not in app.catalog.raw.get('recipe-category', {'crafting': {}}):
        raise ValueError('Choose a loaded recipe category.')
    known = dict(app.catalog.items)
    new_items, recipes = {}, []
    reserved = set(app.catalog.recipes) | set(app.base_raw.get('recipe', {}))
    deleted_items = {name for group, names in app.project.data.get('deleted', {}).items() if group != 'recipe' for name in names}

    def side(value):
        result = {}
        for term in value.split('+'):
            term = term.strip()
            if not term:
                raise ValueError('Each side needs item names separated by +.')
            amount = 1
            if re.match(r'^-\d', term):
                raise ValueError('Quantities must be positive.')
            match = re.match(r'^(\d+(?:\.\d+)?)\s*(?:\*\s*|\s+)(.+)$', term)
            if match:
                amount, term = positive(match[1], 'Quantity'), match[2].strip()
            force = None
            if term.startswith(('item:', 'fluid:')):
                force, term = term.split(':', 1)
                term = term.strip()
            if not term or re.search(r'\s{2,}|[\t\r\n]', term):
                raise ValueError('Use one space between words in a name; use + to separate items.')
            name = identifier(term.replace(' ', '_'))
            # Resolve readable names to existing hyphenated Factorio IDs too.
            candidates = [name, name.lower()]
            if ' ' in term:
                candidates += [term.replace(' ', '-'), term.lower().replace(' ', '-')]
            key = None
            for candidate in dict.fromkeys(candidates):
                matches = [(kind, candidate) for kind in ('item', 'fluid') if (kind, candidate) in known and (not force or kind == force)]
                if len(matches) > 1:
                    raise ValueError('Ambiguous item/fluid name: ' + term + '. Use item: or fluid: before its name.')
                if matches:
                    key = matches[0]
                    break
            if key is None:
                if force == 'fluid':
                    raise ValueError('Unknown fluid: ' + term + '. Create the fluid first, then read the equation.')
                if any(n == name for _, n in known):
                    raise ValueError('This ID is already used by a different item type: ' + name)
                if name in deleted_items:
                    raise ValueError(name + ' is marked for deletion. Undo that deletion before using it.')
                key = ('item', name)
                new_items[name] = term
                known[key] = {}
            if key[0] == 'item' and not float(amount).is_integer():
                raise ValueError('Item quantities must be whole numbers: ' + term)
            result[key] = result.get(key, 0) + amount
        return [{'type': kind, 'name': name, 'amount': int(amount) if float(amount).is_integer() else amount} for (kind, name), amount in result.items()]

    seen = set()
    for line_number, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            continue
        try:
            if line.count('=') != 1:
                raise ValueError('Use exactly one = between ingredients and products.')
            left, right = line.split('=')
            ingredients, results = side(left), side(right)
            signature = repr((ingredients, results))
            if signature in seen:
                raise ValueError('This equation appears more than once.')
            seen.add(signature)
            base_name = results[0]['name'] + '_recipe'
            name, index = base_name, 2
            while name in reserved:
                name, index = base_name + '_' + str(index), index + 1
            reserved.add(name)
            proto = {'type': 'recipe', 'name': name, 'ingredients': ingredients, 'results': results}
            Recipe(name, proto).export(name, seconds, True, category)
            recipes.append({'name': name, 'prototype': proto, 'seconds': seconds, 'category': category, 'line': line_number})
        except ValueError as exc:
            raise ValueError(f'Line {line_number}: {exc}') from exc
    if not recipes:
        raise ValueError('Enter at least one equation, with one equation per line.')
    return {'items': new_items, 'recipes': recipes}


def apply_equations(tab, plan):
    app = tab.app
    before, state = copy.deepcopy(app.project.data), tab.snapshot()
    try:
        stamp = time_ns()
        for index, (name, title) in enumerate(plan['items'].items()):
            if any(n == name for _, n in app.catalog.items):
                raise ValueError('Item already exists: ' + name + '. Preview the equations again.')
            app.project.data['items'][name] = {'name': name, 'title': title, 'kind': 'item', 'description': '',
                'stack_size': 100, 'subgroup': 'intermediate-product', 'default_amount': 1,
                'icon': copy.deepcopy(default_icon_asset()), 'icon_path': '', 'icon_is_default': True, 'created_at': stamp + index}
        for row in plan['recipes']:
            if row['name'] in app.catalog.recipes:
                raise ValueError('Recipe already exists: ' + row['name'] + '. Preview the equations again.')
            app.project.save_recipe(Recipe(row['name'], row['prototype']), row['name'], row['seconds'], False, custom=True, category=row['category'])
        app.project.compile(Catalog(app.base_raw))
        app.persist()
        app.record_undo('Read equations', tab, state, before)
        tab.last_plan = copy.deepcopy(plan)
        tab.applied_input = tab.current_input()
        tab.dirty = False
        app.refresh_catalog()
    except (ValueError, OSError, KeyError):
        app.project.data = before
        raise


class EquationsTab(ttk.Frame):
    def __init__(self, app):
        super().__init__(app.tabs)
        self.app, self.dirty = app, False
        self.last_plan, self.applied_input = None, None
        self.preview_job = None
        ttk.Label(self, text='Read equations', font=('Segoe UI', 16, 'bold'), padding=12).pack(anchor='w')
        self.text = tk.Text(self, height=6, wrap='none', undo=True, bg='#273240', fg='#e6edf3', insertbackground='#e6edf3')
        self.text.pack(fill='x', padx=12)
        help_label(self, 'One recipe per line: copper plate + iron plate = metal alloy\nOne space becomes _ in a new item ID. Use + between terms and = before products. Optional quantities: 2 copper plate + iron plate = 3 metal alloy. Existing items/fluids are reused; missing names create normal items.', wraplength=1100, padx=12)
        help_label(self, 'Readable names also match existing hyphenated game IDs (copper plate → copper-plate). New items use default icons and appear in Pending requirements. Existing recipes are kept; name collisions receive _2, _3, etc.', wraplength=1100, padx=12)
        bar = ttk.Frame(self, padding=12)
        bar.pack(fill='x')
        self.seconds = tk.StringVar(value='0.5')
        ttk.Label(bar, text='Crafting seconds').pack(side='left')
        entry = ttk.Entry(bar, textvariable=self.seconds, width=8)
        entry.pack(side='left', padx=8)
        entry_undo(entry, self.seconds)
        self.category = tk.StringVar(value='crafting')
        ttk.Label(bar, text='Recipe category').pack(side='left')
        ttk.Combobox(bar, textvariable=self.category, state='readonly', values=sorted(c for c in app.catalog.raw.get('recipe-category', {'crafting': {}}) if not c.startswith('recipe-studio-only-')), width=24).pack(side='left', padx=8)
        self.apply_button = ttk.Button(bar, text='Apply equations', command=self.save_changes)
        self.apply_button.pack(side='right')
        self.open_button = ttk.Button(bar, text='Open selected recipe', command=self.open_selected)
        self.open_button.pack(side='right', padx=6)
        help_label(self, 'Crafting seconds and category apply to every equation in this batch. The category determines which machines can craft it. Use chemistry or another fluid-capable category for fluid recipes.', wraplength=1100, padx=12)
        holder = ttk.Frame(self, padding=12)
        holder.pack(fill='both', expand=True)
        self.preview = ttk.Treeview(holder, columns=('recipe', 'ingredients', 'products'), show='headings')
        for name, title in [('recipe', 'Recipe ID'), ('ingredients', 'Ingredients (quantity × ID)'), ('products', 'Products (quantity × ID)')]:
            self.preview.heading(name, text=title)
            self.preview.column(name, width=300)
        scrollbar = ttk.Scrollbar(holder, orient='vertical', command=self.preview.yview)
        self.preview.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side='right', fill='y')
        self.preview.pack(fill='both', expand=True)
        self.preview.bind('<Double-Button-1>', lambda e: self.open_selected())
        self.status = ttk.Label(self, padding=12, wraplength=1100)
        self.status.pack(anchor='w')
        self.text.bind('<<Modified>>', self.modified)
        self.text.bind(sequence(app.controls['keys']['undo']), self.undo_text)
        self.traces = [(v, v.trace_add('write', lambda *_: self.changed())) for v in (self.seconds, self.category)]
        self.refresh()

    def current_input(self):
        return self.text.get('1.0', 'end-1c'), self.seconds.get(), self.category.get()

    def snapshot(self):
        return {'input': self.current_input(), 'dirty': self.dirty, 'last_plan': copy.deepcopy(self.last_plan), 'applied_input': self.applied_input}

    def restore(self, state):
        self.text.delete('1.0', 'end')
        self.text.insert('1.0', state['input'][0])
        self.text.edit_modified(False)
        self.seconds.set(state['input'][1])
        self.category.set(state['input'][2])
        self.last_plan, self.applied_input = copy.deepcopy(state['last_plan']), state['applied_input']
        self.dirty = state['dirty']
        self.refresh()

    def modified(self, event):
        if self.text.edit_modified():
            self.text.edit_modified(False)
            self.changed()

    def changed(self):
        self.dirty = bool(self.text.get('1.0', 'end-1c').strip()) and self.current_input() != self.applied_input
        if self.preview_job is not None:
            self.after_cancel(self.preview_job)
        self.preview_job = self.after(200, self.refresh)

    def refresh(self):
        if self.preview_job is not None:
            self.after_cancel(self.preview_job)
            self.preview_job = None
        selected = self.preview.selection()
        self.preview.delete(*self.preview.get_children())
        try:
            applied = self.current_input() == self.applied_input and self.last_plan is not None
            plan = self.last_plan if applied else plan_equations(self.app, *self.current_input())
            for row in plan['recipes']:
                describe = lambda side: ' + '.join(f"{entry['amount']:g} × {entry['name']}" for entry in row['prototype'][side])
                self.preview.insert('', 'end', iid=row['name'], values=(row['name'], describe('ingredients'), describe('results')))
            if selected and self.preview.exists(selected[0]):
                self.preview.selection_set(selected[0])
            self.status.configure(text=(f"Saved {len(plan['recipes'])} recipes and {len(plan['items'])} new items. Ctrl+Z undoes this batch." if applied else f"Ready: {len(plan['recipes'])} recipes. New items: " + (', '.join(plan['items']) or 'none')))
            self.apply_button.configure(state='disabled' if applied else 'normal')
            self.open_button.configure(state='normal' if applied else 'disabled')
        except ValueError as exc:
            self.status.configure(text=str(exc))
            self.apply_button.configure(state='disabled')
            self.open_button.configure(state='disabled')

    def save_changes(self, quiet=False):
        if self.current_input() == self.applied_input or not self.text.get('1.0', 'end-1c').strip():
            return True
        try:
            apply_equations(self, plan_equations(self.app, *self.current_input()))
            return True
        except (ValueError, OSError, KeyError) as exc:
            messagebox.showerror('Cannot read equations', str(exc), parent=self)
            return False

    def open_selected(self):
        selected = self.preview.selection()
        if selected and self.last_plan and self.current_input() == self.applied_input and selected[0] in self.app.catalog.recipes:
            from creations_ui import open_recipe
            return open_recipe(self.app, selected[0])

    def undo_text(self, event):
        if self.text.edit_modified():
            self.text.edit_modified(False)
        if self.applied_input == self.current_input():
            self.app.undo()
        else:
            try:
                self.text.edit_undo()
            except tk.TclError:
                pass
        return 'break'

    def close(self):
        if self.dirty:
            answer = messagebox.askyesnocancel('Close equations', 'Apply these equations to the project before closing?', parent=self)
            if answer is None or answer and not self.save_changes():
                return
        self.destroy()

    def destroy(self):
        if self.preview_job is not None:
            self.after_cancel(self.preview_job)
        for variable, trace in self.traces:
            variable.trace_remove('write', trace)
        super().destroy()
