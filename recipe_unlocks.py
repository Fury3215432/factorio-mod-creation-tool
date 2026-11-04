"""Resolve recipes that are locked without a technology unlock."""
import copy
import re
from time import time_ns
import weakref
import tkinter as tk
from tkinter import ttk, messagebox

from core import Catalog, Recipe, entries
from controls import sequence, BUTTONS
from ui import help_label, entry_undo


def recipe_names(value):
    return list(dict.fromkeys([value] if isinstance(value, str) else value))


class IngredientChoiceCancelled(Exception):
    pass


def choose_ingredient_recipe(owner, key, recipes):
    app = owner.app
    dialog = tk.Toplevel(app)
    dialog.title('Choose ingredient recipe')
    dialog.transient(app)
    dialog.geometry('680x440')
    ttk.Label(dialog, text='Recipe for ' + key[1], font=('Segoe UI', 13, 'bold'), padding=12).pack(anchor='w')
    help_label(dialog, 'This ingredient has multiple eligible crafting recipes. Choose the one to unlock with this technology. Cancelling keeps the technology unlock list unchanged.', wraplength=640, padx=12)
    listing = tk.Listbox(dialog, exportselection=False, bg='#273240', fg='#e6edf3', selectbackground='#45566c')
    listing.pack(fill='both', expand=True, padx=12, pady=8)
    for name in recipes:
        listing.insert('end', name)
    listing.selection_set(0)
    details = tk.StringVar()
    ttk.Label(dialog, textvariable=details, wraplength=640, padding=12).pack(anchor='w')
    def describe(*_):
        if listing.curselection():
            recipe = app.catalog.recipes[recipes[listing.curselection()[0]]]
            def describe_side(side):
                return ' + '.join(str(e.get('amount', '?')) + ' × ' + e['name'] for e in entries(recipe, side))
            details.set(describe_side('ingredients') + ' → ' + describe_side('results'))
    listing.bind('<<ListboxSelect>>', describe)
    selected = []
    def choose(*_):
        if listing.curselection():
            selected.append(recipes[listing.curselection()[0]])
            dialog.destroy()
    footer = ttk.Frame(dialog, padding=12)
    footer.pack(fill='x')
    ttk.Button(footer, text='Use selected recipe', command=choose).pack(side='right')
    ttk.Button(footer, text='Cancel', command=dialog.destroy).pack(side='left')
    listing.bind('<Double-Button-1>', choose)
    listing.bind(sequence(app.controls['picker_accept']), choose)
    dialog.bind(sequence(app.controls['dialog_dismiss']), lambda e: dialog.destroy())
    describe()
    dialog.grab_set()
    dialog.wait_window()
    if not selected:
        raise IngredientChoiceCancelled()
    return selected[0]


def include_ingredient_recipes(app, recipes, technology=None, prerequisites=None, chooser=None, allowed_ingredients=None):
    names = recipe_names(recipes)
    selected = set(names)
    previous = set()
    pending = list(prerequisites) if prerequisites is not None else [technology] if technology else []
    if technology and prerequisites is not None:
        previous.add(technology)
    while pending:
        name = pending.pop()
        if name in previous:
            continue
        previous.add(name)
        pending.extend(app.catalog.raw.get('technology', {}).get(name, {}).get('prerequisites', []))
    mined = {(entry['type'], entry['name']) for resource in app.catalog.raw.get('resource', {}).values()
             for entry in entries(resource.get('minable', {}), 'results')}
    for name in list(names):
        if name not in app.catalog.recipes:
            raise ValueError('Recipe is no longer loaded: ' + name)
        for ingredient in entries(app.catalog.recipes[name], 'ingredients'):
            key = ingredient['type'], ingredient['name']
            if key in mined or allowed_ingredients is not None and key not in allowed_ingredients:
                continue
            choices = []
            already_available = False
            for candidate in app.catalog.by_product.get(key, []):
                proto = app.catalog.recipes[candidate].get('normal', app.catalog.recipes[candidate])
                if proto.get('category') == 'recycling' or candidate.endswith('-recycling'):
                    continue
                unlocks = set(app.project.recipe_unlocks(candidate, app.catalog.raw))
                if proto.get('enabled', True) or unlocks.intersection(previous):
                    already_available = True
                    break
                choices.append((bool(proto.get('hidden')), candidate != key[1], candidate))
            if already_available or not choices:
                continue
            candidates = [choice[-1] for choice in sorted(choices)]
            child = chooser(key, candidates) if chooser is not None and len(candidates) > 1 else candidates[0]
            if child is None:
                raise IngredientChoiceCancelled()
            if child not in candidates:
                raise ValueError('Choose one of the eligible recipes for ' + key[1])
            if child not in selected:
                names.append(child)
                selected.add(child)
    return names


def necessary_ingredient_recipes(app, recipes, technology=None, prerequisites=None, chooser=None):
    """Add direct inputs, then only deeper inputs exclusively used in this scope."""
    choices = {}
    def choose_once(key, candidates):
        if key not in choices:
            choices[key] = chooser(key, candidates)
        return choices[key]
    select = choose_once if chooser is not None else None
    names = include_ingredient_recipes(app, recipes, technology, prerequisites, select)
    consumers = {}
    for name, recipe in app.catalog.recipes.items():
        source = recipe.get('normal', recipe)
        if source.get('category') == 'recycling' or name.endswith('-recycling'):
            continue
        for ingredient in entries(recipe, 'ingredients'):
            consumers.setdefault((ingredient['type'], ingredient['name']), set()).add(name)
    selected = set(names)
    while True:
        added = []
        for name in list(names):
            eligible = {(entry['type'], entry['name']) for entry in entries(app.catalog.recipes[name], 'ingredients')
                        if consumers.get((entry['type'], entry['name']), set()) <= selected}
            for child in include_ingredient_recipes(app, [name], technology, prerequisites, select, eligible)[1:]:
                if child in selected:
                    continue
                products = {(entry['type'], entry['name']) for entry in entries(app.catalog.recipes[child], 'results')}
                if products.intersection(eligible):
                    selected.add(child)
                    added.append(child)
        if not added:
            return names
        names.extend(added)


def assign_unlock(owner, recipe_name, technology):
    app = owner.app
    names = recipe_names(recipe_name)
    if not names or any(name not in app.catalog.recipes for name in names) or technology not in app.catalog.raw.get('technology', {}):
        raise ValueError('Choose a currently loaded recipe and technology.')
    before = copy.deepcopy(app.project.data)
    try:
        saved = copy.deepcopy(app.project.data['technologies'].get(technology, {}))
        prototype = copy.deepcopy(app.catalog.raw['technology'][technology])
        effects = prototype.setdefault('effects', [])
        for name in names:
            if not any(e.get('type') == 'unlock-recipe' and e.get('recipe') == name for e in effects):
                effects.append({'type': 'unlock-recipe', 'recipe': name})
        saved.update(prototype=prototype, created_at=saved.get('created_at', time_ns()))
        app.project.data['technologies'][technology] = saved
        for name in names:
            if name in app.project.data['recipes']:
                app.project.data['recipes'][name]['enabled'] = False
            else:
                proto = app.catalog.recipes[name]
                recipe = Recipe(name, proto)
                settings = proto.get('normal', proto)
                if settings.get('enabled', True):
                    app.project.save_recipe(recipe, name, settings.get('energy_required', .5), False)
        app.project.compile(Catalog(app.base_raw))
        app.persist()
        app.record_undo('Assign recipe technology' if len(names) == 1 else 'Assign technology to %d recipes' % len(names), owner, owner.snapshot(), before)
        related = []
        for widget in app.tabs.winfo_children():
            if hasattr(widget, 'loaded_name') and (widget.loaded_name in names or widget.saved_key in names):
                related.append((weakref.ref(widget), widget.snapshot()))
                widget.tracking = False
                widget.enabled.set(False)
                widget.availability_override = False
                widget.tracking = True
                widget.last_state = widget.snapshot()
            if getattr(widget, 'selected', None) == technology and hasattr(widget, 'editor_vars'):
                related.append((weakref.ref(widget), widget.snapshot()))
                widget.editor_tracking = False
                variable = widget.editor_vars['unlocks']
                shown = [name.strip() for name in variable.get().split(',') if name.strip()]
                expected = [e['recipe'] for e in app.project.data['technologies'][technology]['prototype'].get('effects', []) if e.get('type') == 'unlock-recipe']
                variable.set(', '.join(shown + [name for name in expected if name not in shown]))
                widget.editor_tracking = True
                widget.last_editor_state = widget.snapshot()
        app.undo_stack[-1]['related'] = related
        app.refresh_catalog()
        return True
    except (ValueError, OSError, KeyError):
        app.project.data = before
        raise


def unlock_from_start(owner, recipes):
    app = owner.app
    names = recipe_names(recipes)
    if not names or any(name not in app.catalog.recipes for name in names):
        raise ValueError('Choose currently loaded recipes.')
    before = copy.deepcopy(app.project.data)
    related = [(weakref.ref(widget), widget.snapshot()) for widget in app.tabs.winfo_children()
               if hasattr(widget, 'loaded_name') or hasattr(widget, 'editor_vars')]
    try:
        for name in names:
            app.project.remove_recipe_unlocks(name, app.base_raw)
            if name in app.project.data['recipes']:
                app.project.data['recipes'][name]['enabled'] = True
            else:
                proto = app.base_raw.get('recipe', {}).get(name, app.catalog.recipes[name])
                settings = proto.get('normal', proto)
                app.project.save_recipe(Recipe(name, proto), name, settings.get('energy_required', .5), True, category=settings.get('category', 'crafting'))
        app.project.compile(Catalog(app.base_raw))
        app.persist()
    except (ValueError, OSError, KeyError):
        app.project.data = before
        raise
    app.record_undo('Unlock recipes from start', owner, owner.snapshot(), before)
    app.undo_stack[-1]['related'] = related
    for reference, _ in related:
        widget = reference()
        if hasattr(widget, 'loaded_name') and (widget.loaded_name in names or widget.saved_key in names):
            widget.tracking = False
            widget.enabled.set(True)
            widget.availability_override = True
            widget.tracking = True
            widget.last_state = widget.snapshot()
        elif hasattr(widget, 'editor_vars') and 'unlocks' in widget.editor_vars:
            widget.editor_tracking = False
            variable = widget.editor_vars['unlocks']
            variable.set(', '.join(n.strip() for n in variable.get().split(',') if n.strip() and n.strip() not in names))
            widget.editor_tracking = True
            widget.last_editor_state = widget.snapshot()
    app.refresh_catalog()
    return True


def remove_doubled_unlock(owner, technology, recipe):
    app = owner.app
    if not any(row['technology'] == technology and row['recipe'] == recipe
               for row in app.project.doubled_technology_unlocks(app.catalog)):
        return False
    before = copy.deepcopy(app.project.data)
    related = [(weakref.ref(widget), widget.snapshot()) for widget in app.tabs.winfo_children()
               if hasattr(widget, 'editor_vars') and getattr(widget, 'selected', None) == technology]
    try:
        record = copy.deepcopy(app.project.data['technologies'].get(technology, {}))
        proto = copy.deepcopy(app.catalog.raw['technology'][technology])
        proto['effects'] = [effect for effect in proto.get('effects', [])
                            if not (effect.get('type') == 'unlock-recipe' and effect.get('recipe') == recipe)]
        record.update(prototype=proto, created_at=record.get('created_at', time_ns()))
        app.project.data['technologies'][technology] = record
        app.project.compile(Catalog(app.base_raw))
        app.persist()
    except (ValueError, OSError, KeyError):
        app.project.data = before
        raise
    app.record_undo('Remove doubled technology unlock', owner, owner.snapshot(), before)
    app.undo_stack[-1]['related'] = related
    for reference, _ in related:
        widget = reference()
        widget.editor_tracking = False
        variable = widget.editor_vars['unlocks']
        variable.set(', '.join(name.strip() for name in variable.get().split(',') if name.strip() and name.strip() != recipe))
        widget.editor_tracking = True
        widget.last_editor_state = widget.snapshot()
    app.refresh_catalog()
    return True


def create_shared_prerequisite(owner, recipes, prototype, icon=None, icon_path=''):
    app = owner.app
    names = recipe_names(recipes)
    from project import identifier
    name = identifier(prototype['name'])
    if not names or any(n not in app.catalog.recipes for n in names):
        raise ValueError('Select currently loaded recipes.')
    if name in app.catalog.raw.get('technology', {}):
        raise ValueError('That technology ID already exists.')
    targets = {technology for recipe in names for technology in app.project.recipe_unlocks(recipe, app.catalog.raw)}
    if any(len(app.project.recipe_unlocks(recipe, app.catalog.raw)) < 2 for recipe in names):
        raise ValueError('Every selected recipe must still be unlocked by at least two technologies.')
    before = copy.deepcopy(app.project.data)
    related = [(weakref.ref(widget), widget.snapshot()) for widget in app.tabs.winfo_children()
               if hasattr(widget, 'editor_vars') or hasattr(widget, 'loaded_name')]
    try:
        proto = copy.deepcopy(prototype)
        proto.update(type='technology', effects=[{'type': 'unlock-recipe', 'recipe': recipe} for recipe in names])
        app.project.data['technologies'][name] = {'prototype': proto, 'icon': icon, 'icon_path': icon_path, 'created_at': time_ns()}
        for target in targets:
            record = copy.deepcopy(app.project.data['technologies'].get(target, {}))
            parent = copy.deepcopy(app.catalog.raw['technology'][target])
            parent['effects'] = [effect for effect in parent.get('effects', []) if not (effect.get('type') == 'unlock-recipe' and effect.get('recipe') in names)]
            parent['prerequisites'] = list(dict.fromkeys(parent.get('prerequisites', []) + [name]))
            record.update(prototype=parent, created_at=record.get('created_at', time_ns()))
            app.project.data['technologies'][target] = record
        for recipe in names:
            if recipe in app.project.data['recipes']:
                app.project.data['recipes'][recipe]['enabled'] = False
            else:
                source = app.base_raw.get('recipe', {}).get(recipe, app.catalog.recipes[recipe])
                settings = source.get('normal', source)
                app.project.save_recipe(Recipe(recipe, source), recipe, settings.get('energy_required', .5), False, category=settings.get('category', 'crafting'))
        app.project.compile(Catalog(app.base_raw))
        app.persist()
    except (ValueError, OSError, KeyError):
        app.project.data = before
        raise
    app.record_undo('Create shared prerequisite technology', owner, owner.snapshot(), before)
    app.undo_stack[-1]['related'] = related
    for reference, _ in related:
        widget = reference()
        if hasattr(widget, 'editor_vars') and getattr(widget, 'selected', None) in targets:
            widget.editor_tracking = False
            variable = widget.editor_vars['unlocks']
            variable.set(', '.join(n.strip() for n in variable.get().split(',') if n.strip() and n.strip() not in names))
            variable = widget.editor_vars['prerequisites']
            variable.set(', '.join(dict.fromkeys([n.strip() for n in variable.get().split(',') if n.strip()] + [name])))
            widget.editor_tracking = True
            widget.last_editor_state = widget.snapshot()
        elif hasattr(widget, 'loaded_name') and (widget.loaded_name in names or widget.saved_key in names):
            widget.tracking = False
            widget.enabled.set(False)
            widget.availability_override = False
            widget.tracking = True
            widget.last_state = widget.snapshot()
    app.refresh_catalog()
    return True


def new_technology(owner, recipe_name):
    names = recipe_names(recipe_name)
    if not names:
        return False
    if any(name not in owner.app.catalog.recipes for name in names):
        raise ValueError('Technology unlocks require recipe IDs, not item IDs.')
    recipe_name = names[0]
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
    tree.editor_vars['unlocks'].set(', '.join(names))
    tree.dirty = True
    return tree


def unlock_dialog(owner, recipe_name):
    app = owner.app
    names = recipe_names(recipe_name)
    if not names or any(name not in app.catalog.recipes for name in names):
        return
    dialog = tk.Toplevel(app)
    dialog.title('Assign recipe to a technology')
    dialog.geometry('700x630')
    dialog.transient(app)
    ttk.Label(dialog, text='Unlock recipe: ' + names[0] if len(names) == 1 else 'Unlock %d selected recipes' % len(names), padding=12, font=('Segoe UI', 13, 'bold')).pack(anchor='w')
    query = tk.StringVar()
    entry = ttk.Entry(dialog, textvariable=query)
    entry.pack(fill='x', padx=12)
    entry_undo(entry, query)
    help_label(dialog, 'Search technology IDs. All selected recipes are assigned together; ingredient recipes are included only when Add ingredient recipes is checked. Create new technology opens its editor with the selected recipes already in Recipe unlocks; finish its settings and save.', wraplength=620, padx=12)
    add_ingredients = tk.BooleanVar(value=False)
    ttk.Checkbutton(dialog, text='Add ingredient recipes', variable=add_ingredients).pack(anchor='w', padx=12, pady=4)
    help_label(dialog, 'Optional: also assign recipes for direct ingredients only. Skip ingredients available from the start or unlocked by the selected technology or any prerequisite technology. Deeper ingredient chains are not included. Mined resources and recycling are skipped.', wraplength=620, padx=12)
    def selected_recipes(technology=None):
        return include_ingredient_recipes(app, names, technology, chooser=lambda key, choices: choose_ingredient_recipe(owner, key, choices)) if add_ingredients.get() else names
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
                assign_unlock(owner, selected_recipes(matches[listing.curselection()[0]]), matches[listing.curselection()[0]])
                dialog.destroy()
            except IngredientChoiceCancelled:
                return
            except (ValueError, OSError, KeyError) as exc:
                messagebox.showerror('Cannot assign technology', str(exc), parent=dialog)
    def create():
        try:
            if new_technology(owner, selected_recipes()):
                dialog.destroy()
        except IngredientChoiceCancelled:
            return
        except (ValueError, OSError, KeyError) as exc:
            messagebox.showerror('Cannot create technology', str(exc), parent=dialog)
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
