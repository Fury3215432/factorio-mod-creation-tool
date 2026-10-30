"""Atomic replacement of an ingredient across recipes and open drafts."""
import copy
import weakref
import tkinter as tk
from tkinter import ttk, messagebox

from core import Catalog, Recipe, entries
from controls import sequence
from ui import help_label


def replace_entries(ingredients, old, new, label):
    if not any((e['type'], e['name']) == old for e in ingredients):
        return copy.deepcopy(ingredients), False
    values = copy.deepcopy(ingredients)
    merged = []
    for entry in values:
        if (entry['type'], entry['name']) == old:
            entry.update(type=new[0], name=new[1])
        previous = next((e for e in merged if (e['type'], e['name']) == (entry['type'], entry['name'])), None)
        if previous is None:
            merged.append(entry)
        elif (entry['type'], entry['name']) == new:
            settings = lambda value: {key: val for key, val in value.items() if key not in ('type', 'name', 'amount')}
            if settings(previous) != settings(entry) or 'amount' not in previous or 'amount' not in entry:
                raise ValueError(label + ' already uses the replacement with different ingredient settings. Adjust that recipe first; no changes were saved.')
            previous['amount'] += entry['amount']
        else:
            merged.append(entry)
    return merged, True


def replacement_plan(app, old, new):
    if old == new:
        raise ValueError('Choose a different replacement ingredient.')
    if old[0] != new[0]:
        raise ValueError('Replace items with items, and fluids with fluids.')
    if new not in app.catalog.items:
        raise ValueError('Choose a loaded or created ingredient.')
    plan = {}
    for name, prototype in app.catalog.recipes.items():
        ingredients, changed = replace_entries(entries(prototype, 'ingredients'), old, new, name)
        if changed:
            plan[name] = ingredients
    return plan


def apply_replacement(owner, old, new):
    app = owner.app
    plan = replacement_plan(app, old, new)
    drafts = []
    for tab in app.tabs.winfo_children():
        if hasattr(tab, 'loaded_name') and hasattr(tab, 'recipe'):
            state = tab.snapshot()
            ingredients, changed = replace_entries(state['recipe'].ingredients, old, new, 'Open flowchart: ' + state['name'])
            if changed:
                after = copy.deepcopy(state)
                after['recipe'].ingredients = ingredients
                if not tab.loaded_name and not tab.saved_key:
                    after['dirty'] = True
                elif (tab.loaded_name or tab.saved_key) in plan:
                    after['saved_key'] = tab.loaded_name or tab.saved_key
                drafts.append((tab, state, after))
    if not plan and not drafts:
        return 0, 0
    before, owner_state = copy.deepcopy(app.project.data), owner.snapshot()
    try:
        for name, ingredients in plan.items():
            saved = app.project.data['recipes'].get(name)
            source = app.base_raw.get('recipe', {}).get(name, app.catalog.recipes[name])
            recipe = app.project.recipe(name) if saved else Recipe(name, source)
            recipe.ingredients = ingredients
            proto = source.get('normal', source)
            enabled = False if app.project.recipe_unlocks(name, app.base_raw) else saved['enabled'] if saved else proto.get('enabled', True)
            app.project.save_recipe(recipe, name, saved['seconds'] if saved else proto.get('energy_required', .5), enabled,
                                    saved.get('custom', False) if saved else False,
                                    saved.get('category', proto.get('category', 'crafting')) if saved else proto.get('category', 'crafting'))
        if plan:
            app.project.compile(Catalog(app.base_raw))
            app.persist()
        app.record_undo('Replace ingredient in all recipes', owner, owner_state, before)
        app.undo_stack[-1]['related'] = [(weakref.ref(tab), state) for tab, state, _ in drafts if tab is not owner]
        app.refresh_catalog()
        for tab, _, state in drafts:
            tab.restore(state)
        return len(plan), len(drafts)
    except (ValueError, OSError, KeyError):
        app.project.data = before
        raise


def replacement_dialog(owner, old):
    app = owner.app
    dialog = tk.Toplevel(app)
    dialog.title('Replace ingredient in all recipes')
    dialog.geometry('740x510')
    dialog.transient(app)
    ttk.Label(dialog, text='Replace ingredient: ' + old[1], font=('Segoe UI', 13, 'bold'), padding=12).pack(anchor='w')
    replacement = tk.StringVar(value='Choose a replacement ingredient')
    ttk.Label(dialog, textvariable=replacement, padding=(12, 0, 12, 6)).pack(anchor='w')
    target = [None]
    plan = {}
    def selected(key):
        target[0] = key
        replacement.set('Replace with: ' + key[1])
        refresh()
    def choose():
        from app import Picker
        Picker(app, selected, kind_filter=old[0])
    ttk.Button(dialog, text='Choose replacement…', command=choose).pack(anchor='w', padx=12)
    help_label(dialog, 'Applies to ingredients in all loaded base-game/mod recipes, saved recipes and open flowcharts. Quantities and other ingredient settings are preserved. Matching existing ingredients are combined when their settings agree. Products, recipe IDs, crafting times and technology unlocks stay the same.', wraplength=700, padx=12)
    holder = ttk.Frame(dialog, padding=12)
    holder.pack(fill='both', expand=True)
    listing = ttk.Treeview(holder, columns=('recipe',), show='headings', height=7)
    listing.heading('recipe', text='Recipes to edit')
    scrollbar = ttk.Scrollbar(holder, orient='vertical', command=listing.yview)
    listing.configure(yscrollcommand=scrollbar.set)
    scrollbar.pack(side='right', fill='y')
    listing.pack(fill='both', expand=True)
    footer = ttk.Frame(dialog, padding=12)
    footer.pack(fill='x')
    status = ttk.Label(footer, wraplength=500)
    status.pack(side='left', fill='x', expand=True)
    def refresh():
        listing.delete(*listing.get_children())
        try:
            plan.clear()
            if target[0] is None:
                raise ValueError('Choose a replacement to preview the changes.')
            plan.update(replacement_plan(app, old, target[0]))
            for name in sorted(plan):
                listing.insert('', 'end', values=(name,))
            draft_count = sum(1 for tab in app.tabs.winfo_children() if hasattr(tab, 'recipe') and tab.recipe and any((e['type'], e['name']) == old for e in tab.recipe.ingredients))
            status.configure(text=f'{len(plan)} recipes and {draft_count} open flowcharts. Ctrl+Z undoes this operation.')
            apply_button.configure(state='normal' if plan or draft_count else 'disabled')
        except ValueError as exc:
            status.configure(text=str(exc))
            apply_button.configure(state='disabled')
    def apply():
        if target[0] is None:
            return
        try:
            recipes, drafts = apply_replacement(owner, old, target[0])
            dialog.destroy()
            messagebox.showinfo('Ingredient replaced', f'Updated {recipes} recipes and {drafts} open flowcharts. Ctrl+Z undoes the changes.', parent=owner)
        except (ValueError, OSError, KeyError) as exc:
            messagebox.showerror('Cannot replace ingredient', str(exc), parent=dialog)
    apply_button = ttk.Button(footer, text='Apply replacement', command=apply)
    apply_button.pack(side='right')
    dialog.bind(sequence(app.controls['dialog_dismiss']), lambda e: dialog.destroy())
    refresh()
    return dialog
