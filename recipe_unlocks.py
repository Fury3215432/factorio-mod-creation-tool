"""Resolve recipes that are locked without a technology unlock."""
import copy
import re
from time import time_ns
import weakref
import tkinter as tk
from tkinter import ttk, messagebox

from core import Catalog
from controls import sequence, BUTTONS
from ui import help_label, entry_undo


def assign_unlock(owner, recipe_name, technology):
    app = owner.app
    if recipe_name not in app.catalog.recipes or technology not in app.catalog.raw.get('technology', {}):
        raise ValueError('Choose a currently loaded recipe and technology.')
    before = copy.deepcopy(app.project.data)
    try:
        saved = copy.deepcopy(app.project.data['technologies'].get(technology, {}))
        prototype = copy.deepcopy(app.catalog.raw['technology'][technology])
        effects = prototype.setdefault('effects', [])
        if not any(e.get('type') == 'unlock-recipe' and e.get('recipe') == recipe_name for e in effects):
            effects.append({'type': 'unlock-recipe', 'recipe': recipe_name})
        saved.update(prototype=prototype, created_at=saved.get('created_at', time_ns()))
        app.project.data['technologies'][technology] = saved
        if recipe_name in app.project.data['recipes']:
            app.project.data['recipes'][recipe_name]['enabled'] = False
        app.project.compile(Catalog(app.base_raw))
        app.persist()
        app.record_undo('Assign recipe technology', owner, owner.snapshot(), before)
        related = []
        for widget in app.tabs.winfo_children():
            if getattr(widget, 'selected', None) == technology and hasattr(widget, 'editor_vars'):
                related.append((weakref.ref(widget), widget.snapshot()))
                widget.editor_tracking = False
                variable = widget.editor_vars['unlocks']
                names = [name.strip() for name in variable.get().split(',') if name.strip()]
                expected = [e['recipe'] for e in app.project.data['technologies'][technology]['prototype'].get('effects', []) if e.get('type') == 'unlock-recipe']
                variable.set(', '.join(names + [name for name in expected if name not in names]))
                widget.editor_tracking = True
                widget.last_editor_state = widget.snapshot()
        app.undo_stack[-1]['related'] = related
        app.refresh_catalog()
        return True
    except (ValueError, OSError, KeyError):
        app.project.data = before
        raise


def new_technology(owner, recipe_name):
    app = owner.app
    tree = app.tech_tab()
    if not tree.confirm_switch():
        return False
    from editors import technology_dialog
    technology_dialog(tree, None, force=True)
    base = recipe_name + '_technology'
    name, suffix = base, 2
    while name in app.catalog.raw.get('technology', {}):
        name, suffix = base + '_' + str(suffix), suffix + 1
    tree.editor_vars['tech_id'].set(name)
    tree.editor_vars['title'].set(recipe_name.replace('_', ' ').replace('-', ' ').title())
    tree.editor_vars['unlocks'].set(recipe_name)
    tree.dirty = True
    return tree


def unlock_dialog(owner, recipe_name):
    app = owner.app
    if recipe_name not in app.catalog.recipes:
        return
    dialog = tk.Toplevel(app)
    dialog.title('Assign recipe to a technology')
    dialog.geometry('660x500')
    dialog.transient(app)
    ttk.Label(dialog, text='Unlock recipe: ' + recipe_name, padding=12, font=('Segoe UI', 13, 'bold')).pack(anchor='w')
    query = tk.StringVar()
    entry = ttk.Entry(dialog, textvariable=query)
    entry.pack(fill='x', padx=12)
    entry_undo(entry, query)
    help_label(dialog, 'Search technology IDs. Only the selected recipe is assigned; ingredient recipes need their own unlocks. Create new technology opens its editor with this recipe already in Recipe unlocks; finish its settings and save.', wraplength=620, padx=12)
    listing = tk.Listbox(dialog, bg='#273240', fg='#e6edf3', selectbackground='#45566c', exportselection=False)
    listing.pack(fill='both', expand=True, padx=12, pady=6)
    matches = []
    def refresh(*_):
        terms = re.split(r'[\s_-]+', query.get().casefold().strip())
        matches[:] = [name for name in sorted(app.catalog.raw.get('technology', {})) if all(term in re.sub(r'[_-]+', ' ', name.casefold()) for term in terms)]
        listing.delete(0, 'end')
        for name in matches:
            listing.insert('end', name)
        if matches:
            listing.selection_set(0)
    def assign(*_):
        if listing.curselection():
            try:
                assign_unlock(owner, recipe_name, matches[listing.curselection()[0]])
                dialog.destroy()
            except (ValueError, OSError, KeyError) as exc:
                messagebox.showerror('Cannot assign technology', str(exc), parent=dialog)
    def create():
        if new_technology(owner, recipe_name):
            dialog.destroy()
    footer = ttk.Frame(dialog, padding=12)
    footer.pack(fill='x')
    ttk.Button(footer, text='Add to selected technology', command=assign).pack(side='left')
    ttk.Button(footer, text='Create new technology', command=create).pack(side='left', padx=8)
    listing.bind('<Double-Button-%d>' % BUTTONS[app.controls['picker_button']], assign)
    listing.bind(sequence(app.controls['picker_accept']), assign)
    trace = query.trace_add('write', refresh)
    def cleanup(event):
        if event.widget is dialog:
            query.trace_remove('write', trace)
    dialog.bind('<Destroy>', cleanup, add='+')
    dialog.bind(sequence(app.controls['dialog_dismiss']), lambda e: dialog.destroy())
    refresh()
    entry.focus_set()
    return dialog
