"""Atomic bulk science-pack edits for selected technologies."""
import copy
from time import time_ns
import tkinter as tk
from tkinter import ttk, messagebox

from core import Catalog
from project import positive
from ui import help_label
from controls import sequence


def apply_science(tab, names, packs, mode, amount=1):
    app = tab.app
    if mode not in ('add', 'remove') or not packs:
        raise ValueError('Choose science packs and an add/remove action.')
    if any(pack not in app.catalog.raw.get('tool', {}) for pack in packs):
        raise ValueError('Choose loaded or created science packs.')
    amount = positive(amount, 'Science pack quantity', True) if mode == 'add' else 1
    before = copy.deepcopy(app.project.data)
    state = tab.snapshot() if tab.editor_frame is not None else None
    changed, skipped, updates = [], [], {}
    for name in sorted(set(names)):
        prototype = copy.deepcopy(app.catalog.raw['technology'][name])
        if prototype.get('research_trigger') or not prototype.get('unit'):
            skipped.append(name)
            continue
        ingredients = prototype['unit'].get('ingredients', [])
        pack_name = lambda entry: entry['name'] if isinstance(entry, dict) else entry[0]
        if mode == 'add':
            present = {pack_name(entry) for entry in ingredients}
            ingredients = ingredients + [[pack, amount] for pack in sorted(set(packs) - present)]
        else:
            ingredients = [entry for entry in ingredients if pack_name(entry) not in packs]
        if not ingredients:
            raise ValueError('Cannot remove every science pack from ' + name + '. Keep at least one pack; no changes were saved.')
        if ingredients == prototype['unit'].get('ingredients', []):
            continue
        prototype['unit']['ingredients'] = ingredients
        app.project.validate_technology(prototype, app.catalog, previous=name)
        saved = copy.deepcopy(app.project.data['technologies'].get(name, {}))
        saved.update(prototype=prototype, created_at=saved.get('created_at', time_ns()))
        updates[name] = saved
        changed.append(name)
    if not changed:
        return changed, skipped
    try:
        app.project.data['technologies'].update(updates)
        app.project.compile(Catalog(app.base_raw))
        app.persist()
        app.record_undo('Bulk science packs', tab, state, before)
        selection = set(tab.multi_selected)
        app.refresh_catalog()
        if tab.selected in changed:
            from editors import technology_dialog
            technology_dialog(tab, tab.selected, force=True)
        tab.multi_selected = selection
        tab.update_selection()
        tab.draw()
        return changed, skipped
    except (ValueError, OSError, KeyError):
        app.project.data = before
        raise


def science_dialog(tab):
    if not tab.multi_selected or not tab.confirm_switch():
        return
    app = tab.app
    names = set(tab.multi_selected)
    dialog = tk.Toplevel(app)
    dialog.title('Bulk edit science packs')
    dialog.geometry('650x570')
    dialog.transient(app)
    dialog.grab_set()
    ttk.Label(dialog, text=f'Science packs for {len(names)} technologies', padding=12, font=('Segoe UI', 13, 'bold')).pack(anchor='w')
    query = tk.StringVar()
    ttk.Entry(dialog, textvariable=query).pack(fill='x', padx=12)
    help_label(dialog, 'Filter science-pack IDs. Ctrl/Shift-click to select several packs. Includes your created science packs.', wraplength=600, padx=12)
    listing = tk.Listbox(dialog, selectmode='extended', exportselection=False, bg='#273240', fg='#e6edf3', selectbackground='#45566c')
    listing.pack(fill='both', expand=True, padx=12, pady=6)
    chosen, shown = set(), []
    def remember(*_):
        chosen.difference_update(shown)
        chosen.update(shown[i] for i in listing.curselection())
    def refresh(*_):
        remember()
        shown[:] = [name for name in sorted(app.catalog.raw.get('tool', {})) if all(term in name.lower() for term in query.get().lower().split())]
        listing.delete(0, 'end')
        for index, name in enumerate(shown):
            listing.insert('end', name)
            if name in chosen:
                listing.selection_set(index)
    listing.bind('<<ListboxSelect>>', remember)
    quantity = tk.StringVar(value='1')
    ttk.Label(dialog, text='Quantity for newly added packs', padding=(12, 6)).pack(anchor='w')
    ttk.Entry(dialog, textvariable=quantity, width=10).pack(anchor='w', padx=12)
    help_label(dialog, 'New packs use this amount per research unit. Existing pack quantities, research time, count and prerequisites are kept. Trigger-based research is skipped.', wraplength=610, padx=12)
    def apply(mode):
        remember()
        try:
            changed, skipped = apply_science(tab, names, chosen, mode, quantity.get())
            dialog.destroy()
            message = f'Updated {len(changed)} technologies. Ctrl+Z undoes the bulk edit.'
            if skipped:
                message += '\n\nSkipped trigger-based research:\n' + '\n'.join(skipped)
            messagebox.showinfo('Science packs updated', message, parent=tab)
        except (ValueError, OSError, KeyError) as exc:
            messagebox.showerror('Cannot update science packs', str(exc), parent=dialog)
    actions = ttk.Frame(dialog, padding=12)
    actions.pack(fill='x')
    ttk.Button(actions, text='Add selected packs', command=lambda: apply('add')).pack(side='left')
    ttk.Button(actions, text='Remove selected packs', command=lambda: apply('remove')).pack(side='left', padx=6)
    trace = query.trace_add('write', refresh)
    def cleanup(event):
        if event.widget is dialog:
            query.trace_remove('write', trace)
    dialog.bind('<Destroy>', cleanup, add='+')
    dialog.bind(sequence(app.controls['dialog_dismiss']), lambda e: dialog.destroy())
    refresh()
    return dialog
