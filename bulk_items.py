"""Create ingredient items from a space-separated list of names."""
import copy
import re
from time import time_ns
import tkinter as tk
from tkinter import ttk, messagebox

from core import Catalog
from project import identifier, default_icon_asset
from controls import sequence
from ui import help_label


def parse_items(text):
    items = []
    seen = set()
    for value in re.split(r' {2,}|[\r\n\t]+', text.strip()):
        title = value.strip()
        if not title:
            continue
        name = identifier(title.replace(' ', '_'))
        if name in seen:
            raise ValueError('Duplicate item ID in the list: ' + name)
        seen.add(name)
        items.append((name, title))
    if not items:
        raise ValueError('Enter at least one item name.')
    return items


def validate_items(app, text):
    items = parse_items(text)
    existing = {name for _, name in app.catalog.items} | set(app.project.data['items'])
    duplicates = [name for name, _ in items if name in existing]
    if duplicates:
        raise ValueError('These IDs already exist; no items were created:\n' + '\n'.join(duplicates))
    return items


def create_items(tab, text):
    app = tab.app
    items = validate_items(app, text)
    before = copy.deepcopy(app.project.data)
    state = tab.snapshot()
    try:
        stamp = time_ns()
        for index, (name, title) in enumerate(items):
            app.project.data['items'][name] = {
                'name': name, 'title': title, 'kind': 'item', 'description': '',
                'stack_size': 100, 'subgroup': 'intermediate-product', 'default_amount': 1,
                'icon': copy.deepcopy(default_icon_asset()), 'icon_path': '', 'icon_is_default': True,
                'created_at': stamp + index}
        app.project.compile(Catalog(app.base_raw))
        app.persist()
        app.record_undo('Bulk ingredient creation', tab, state, before)
        app.refresh_catalog()
        return items
    except (ValueError, OSError, KeyError):
        app.project.data = before
        raise


def bulk_item_dialog(tab):
    app = tab.app
    dialog = tk.Toplevel(app)
    dialog.title('Bulk ingredient creation')
    dialog.geometry('760x600')
    dialog.transient(app)
    footer = ttk.Frame(dialog, padding=12)
    footer.pack(side='bottom', fill='x')
    ttk.Label(dialog, text='Item names', padding=12, font=('Segoe UI', 13, 'bold')).pack(anchor='w')
    text = tk.Text(dialog, height=5, wrap='word', undo=True, bg='#273240', fg='#e6edf3', insertbackground='#e6edf3')
    text.pack(fill='x', padx=12)
    help_label(dialog, 'One space joins words in an item name and becomes _ in its ID. Two or more spaces separate items. New lines and tabs also separate items.\nExample: copper plate  iron ore → copper_plate and iron_ore. Display names keep the words you entered.', wraplength=720, padx=12)
    help_label(dialog, 'Apply saves normal ingredient items with stack size 100 and the default checkerboard icon. They become available in pickers and Browse creations. Add their recipes and icons afterward in Pending requirements. No rectangles are added automatically.', wraplength=720, padx=12)
    holder = ttk.Frame(dialog, padding=12)
    holder.pack(fill='both', expand=True)
    preview = ttk.Treeview(holder, columns=('id', 'title'), show='headings', height=6)
    preview.heading('id', text='Item ID')
    preview.heading('title', text='Display name')
    scrollbar = ttk.Scrollbar(holder, orient='vertical', command=preview.yview)
    preview.configure(yscrollcommand=scrollbar.set)
    scrollbar.pack(side='right', fill='y')
    preview.pack(fill='both', expand=True)
    status = ttk.Label(footer, wraplength=570)
    status.pack(side='left', fill='x', expand=True)
    def apply():
        try:
            create_items(tab, text.get('1.0', 'end-1c'))
            dialog.destroy()
        except (ValueError, OSError, KeyError) as exc:
            messagebox.showerror('Cannot create items', str(exc), parent=dialog)
    apply_button = ttk.Button(footer, text='Apply', command=apply)
    apply_button.pack(side='right')
    def refresh(event=None):
        if event is not None and not text.edit_modified():
            return
        text.edit_modified(False)
        preview.delete(*preview.get_children())
        try:
            items = validate_items(app, text.get('1.0', 'end-1c'))
            for name, title in items:
                preview.insert('', 'end', values=(name, title))
            status.configure(text=f'{len(items)} items ready. Ctrl+Z can undo the whole batch.')
            apply_button.configure(state='normal')
        except ValueError as exc:
            status.configure(text=str(exc))
            apply_button.configure(state='disabled')
    def undo_text(event):
        try:
            text.edit_undo()
        except tk.TclError:
            pass
        return 'break'
    text.bind(sequence(app.controls['keys']['undo']), undo_text)
    text.bind('<<Modified>>', refresh)
    dialog.bind(sequence(app.controls['dialog_dismiss']), lambda e: dialog.destroy())
    refresh()
    text.focus_set()
    return dialog
