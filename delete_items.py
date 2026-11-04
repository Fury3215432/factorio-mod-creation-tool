"""Delete an item and every recipe containing it as one undoable change."""
import copy
import weakref
from tkinter import messagebox

from core import Catalog, Recipe, entries


def delete_technology(owner, name, confirm=True):
    """Delete the prototype, rather than merely discarding its saved edit."""
    app = owner.app
    technologies = app.catalog.raw.get('technology', {})
    if name not in technologies:
        return False
    dependents = sorted(n for n, proto in technologies.items() if name in proto.get('prerequisites', []))
    if dependents:
        messagebox.showerror('Cannot delete technology',
                             'Remove this technology from these prerequisites first:\n\n' + '\n'.join(dependents), parent=owner)
        return False
    if confirm and not messagebox.askyesno('Delete technology',
            f'Delete {name} from the project and exported mod?\n\nIts recipe unlocks will be removed. Recipes are kept; they may need another technology to unlock them. Ctrl+Z restores the deletion.', parent=owner):
        return False
    before = copy.deepcopy(app.project.data)
    state = owner.snapshot()
    editors = [(tab, tab.snapshot()) for tab in app.tabs.winfo_children()
               if hasattr(tab, 'editor_vars') and getattr(tab, 'selected', None) == name]
    try:
        app.project.data['technologies'].pop(name, None)
        app.project.data.setdefault('deleted', {}).setdefault('technology', {})[name] = True
        app.project.compile(Catalog(app.base_raw))
        app.persist()
    except (ValueError, OSError, KeyError) as exc:
        app.project.data = before
        messagebox.showerror('Cannot delete technology', str(exc), parent=owner)
        return False
    app.record_undo('Delete technology: ' + name, owner, state, before)
    app.undo_stack[-1]['related'] = [(weakref.ref(tab), prior) for tab, prior in editors if tab is not owner]
    # Reset deleted editors before refreshing the tree or its icons.
    from editors import technology_dialog
    for tab, _ in editors:
        technology_dialog(tab, None, force=True)
    app.refresh_catalog()
    return True


def delete_with_recipes(owner, key):
    app = owner.app
    if key not in app.catalog.items:
        return False
    from creations_ui import CreationsTab
    data = app.project.editable_item(key, app.catalog)
    row = data['kind'], key[1], data
    loaded = key in app.loaded_items or data.get('operation') == 'edit'
    if not (CreationsTab.can_delete_from_mod(owner, row) if loaded else CreationsTab.can_delete(owner, row)):
        return False
    affected = {name for name, proto in app.catalog.recipes.items()
                if any((e['type'], e['name']) == key for e in entries(proto, 'ingredients') + entries(proto, 'results'))}
    blockers = ['Machine: ' + name for name, machine in app.project.data['machines'].items() if affected.intersection(machine.get('recipes', []))]
    blockers.extend(group + ': ' + name + ' (fixed recipe)' for group, prototypes in app.catalog.raw.items()
                    for name, proto in prototypes.items() if proto.get('fixed_recipe') in affected)
    if blockers:
        messagebox.showerror('Cannot delete item and recipes', 'Remove the affected recipes from these machines first:\n\n' + '\n'.join(sorted(set(blockers))), parent=owner)
        return False
    before = copy.deepcopy(app.project.data)
    owner_state = owner.snapshot()
    charts = [(tab, tab.snapshot()) for tab in app.tabs.winfo_children() if hasattr(tab, 'loaded_name') and hasattr(tab, 'recipe')]
    undo_count = len(app.undo_stack)

    def rollback():
        app.project.data = before
        app.undo_stack[undo_count:] = []
        app.refresh_catalog()
        for tab, state in charts:
            if tab.winfo_exists():
                tab.restore(state)

    try:
        for name in affected:
            app.project.data['recipes'].pop(name, None)
            app.project.data.setdefault('deleted', {}).setdefault('recipe', {})[name] = True
        app.catalog = Catalog(app.project.merged_raw(app.base_raw))
        for tab, state in charts:
            if state['loaded_name'] in affected or state['saved_key'] in affected or any((e['type'], e['name']) == key for e in state['recipe'].ingredients + state['recipe'].results):
                tab.restore(dict(state, recipe=Recipe('new-recipe', {'ingredients': [], 'results': []}), name='new-recipe',
                                 loaded_name=None, saved_key=None, result_machine=None, item_draft=None, is_custom=True,
                                 dirty=False, auto_name=True, enabled=False, availability_override=False, expanded_recipes={}))
        success = CreationsTab.delete_from_mod(owner, row=row) if loaded else CreationsTab.delete_selected(owner, row=row)
        if not success:
            rollback()
            return False
        entry = app.undo_stack[-1]
        entry['label'] = 'Delete item and recipes'
        entry['project'] = before
        entry['state'] = owner_state
        entry['related'] = [(weakref.ref(tab), state) for tab, state in charts]
        owner.set_deletion_status(f'Deleted {key[1]} and {len(affected)} recipes. Ctrl+Z restores the whole operation.')
        return True
    except (ValueError, OSError, KeyError) as exc:
        rollback()
        messagebox.showerror('Cannot delete item and recipes', str(exc), parent=owner)
        return False


def delete_recipe(owner, name):
    """Remove a resolved recipe and its unlocks, preserving charts for undo."""
    app = owner.app
    if name not in app.catalog.recipes:
        return False
    assigned = [n for n, machine in app.project.data['machines'].items() if name in machine.get('recipes', [])]
    blockers = [group + ': ' + n + ' (fixed recipe)' for group, prototypes in app.catalog.raw.items()
                for n, proto in prototypes.items() if proto.get('fixed_recipe') == name]
    if blockers:
        messagebox.showerror('Cannot delete recipe', 'Remove this recipe from these machines first:\n\n' + '\n'.join(sorted(set(blockers))), parent=owner)
        return False
    if assigned and not messagebox.askyesno('Delete recipe and machine assignments',
            f'Delete {name} and remove it from these machines?\n\n'+ '\n'.join(sorted(assigned)) +
            '\n\nThe machines are kept. Ctrl+Z restores the recipe and assignments together.', parent=owner):
        return False
    before = copy.deepcopy(app.project.data)
    state = owner.snapshot()
    charts = [(tab, tab.snapshot()) for tab in app.tabs.winfo_children()
              if hasattr(tab, 'loaded_name') and hasattr(tab, 'recipe')]
    machine_editors = [(tab, tab.snapshot()) for tab in app.tabs.winfo_children()
                       if hasattr(tab, 'selected_recipes') and
                       (getattr(tab, 'saved_name', None) in assigned or name in tab.selected_recipes())]
    try:
        for machine in assigned:
            record=app.project.data['machines'][machine]
            record['recipes']=[recipe for recipe in record.get('recipes',[]) if recipe != name]
        app.project.data['recipes'].pop(name, None)
        app.project.data.setdefault('deleted', {}).setdefault('recipe', {})[name] = True
        app.project.compile(Catalog(app.base_raw))
        app.persist()
    except (ValueError, OSError, KeyError) as exc:
        app.project.data = before
        messagebox.showerror('Cannot delete recipe', str(exc), parent=owner)
        return False
    app.record_undo('Delete recipe: ' + name, owner, state, before)
    app.undo_stack[-1]['related'] = [(weakref.ref(tab), prior) for tab, prior in charts + machine_editors]
    for tab, prior in machine_editors:
        tab.ready=False
        tab.vars['recipes'].set(', '.join(r for r in tab.selected_recipes() if r != name))
        tab.ready=True
        tab.last_state=tab.snapshot()
    for tab, prior in charts:
        if prior['loaded_name'] == name or prior['saved_key'] == name:
            tab.restore(dict(prior, recipe=Recipe('new-recipe', {'ingredients': [], 'results': []}), name='new-recipe',
                             loaded_name=None, saved_key=None, result_machine=None, item_draft=None, is_custom=True,
                             dirty=False, auto_name=True, enabled=False, availability_override=False, expanded_recipes={}))
    app.refresh_catalog()
    return True


def bulk_delete_with_recipes(owner, keys):
    """Validate and remove a whole batch with one compile, save and redraw."""
    app = owner.app
    keys = set(keys)
    if not keys:
        return False
    before = copy.deepcopy(app.project.data)
    history = list(app.undo_stack)
    charts = [(tab, tab.snapshot()) for tab in app.tabs.winfo_children()
              if hasattr(tab, 'loaded_name') and hasattr(tab, 'recipe')]
    affected = {name for name, proto in app.catalog.recipes.items()
                if any((e['type'], e['name']) in keys for e in entries(proto, 'ingredients') + entries(proto, 'results'))}
    try:
        removed_prototypes = set()
        for key in keys:
            if key not in app.catalog.items:
                raise ValueError('Item is no longer loaded: ' + key[1])
            item = app.project.data['items'].get(key[1], {})
            if not item and key not in app.loaded_items:
                raise ValueError('Only project creations and loaded-mod items can be deleted here: ' + key[1])
            removed_prototypes.add((app.catalog.items[key]['type'], key[1]))
        blockers = ['Machine: ' + name for name, machine in app.project.data['machines'].items()
                    if affected.intersection(machine.get('recipes', []))]
        item_names = {name for kind, name in keys if kind == 'item'}
        fluid_names = {name for kind, name in keys if kind == 'fluid'}
        def fluid_reference(value):
            if isinstance(value, dict):
                if any(value.get(field) in fluid_names for field in ('filter', 'fluid', 'input_fluid_filter', 'output_fluid_filter', 'required_fluid') if isinstance(value.get(field), str)):
                    return True
                return any(fluid_reference(v) for v in value.values() if isinstance(v, (dict, list)))
            return any(fluid_reference(v) for v in value) if isinstance(value, list) else False
        for group, prototypes in app.catalog.raw.items():
            if group == 'recipe':
                continue
            for name, proto in prototypes.items():
                if (group, name) in removed_prototypes:
                    continue
                if group == 'resource' and ('item', name) in keys and app.project.data['items'].get(name, {}).get('kind') == 'ore':
                    continue
                if proto.get('fixed_recipe') in affected:
                    blockers.append(group + ': ' + name + ' (fixed recipe)')
                references = {e['name'] for e in entries(proto.get('minable', {}), 'results') if e['type'] == 'item'}
                references.update(e.get('item') for e in proto.get('loot', []) if isinstance(e, dict))
                references.update(proto.get(field) for field in ('burnt_result', 'spoil_result'))
                references.update(e.get('name') for e in proto.get('rocket_launch_products', []) if isinstance(e, dict))
                if group == 'technology':
                    references.update(e.get('name') if isinstance(e, dict) else e[0] for e in proto.get('unit', {}).get('ingredients', []))
                if item_names.intersection(references) or fluid_names and fluid_reference(proto):
                    blockers.append(group + ': ' + name)
        if blockers:
            raise ValueError('Remove these references first; nothing was deleted:\n\n' + '\n'.join(sorted(set(blockers))))
        for name in affected:
            app.project.data['recipes'].pop(name, None)
            app.project.data['deleted'].setdefault('recipe', {})[name] = True
        for prototype_type, name in removed_prototypes:
            app.project.data['items'].pop(name, None)
            if name in app.base_raw.get(prototype_type, {}):
                app.project.data['deleted'].setdefault(prototype_type, {})[name] = True
        if any(app.project.data[group] for group in ('items', 'recipes', 'technologies', 'machines', 'categories')) or any(app.project.data['deleted'].values()):
            app.project.compile(Catalog(app.base_raw))
        app.persist()
    except (ValueError, OSError, KeyError, TypeError) as exc:
        app.project.data = before
        app.undo_stack = history
        # Restore the saved state if persistence failed after updating one file.
        try:
            app.persist()
        except OSError:
            pass
        messagebox.showerror('Cannot delete selected items and recipes', str(exc), parent=owner)
        return False
    app.record_undo('Delete selected items and recipes', owner, owner.snapshot(), before)
    app.undo_stack[-1]['related'] = [(weakref.ref(tab), prior) for tab, prior in charts]
    # Reset affected drafts before the single catalog/UI refresh so their draw
    # callbacks never attempt to display items that have just been removed.
    app.catalog = Catalog(app.project.merged_raw(app.base_raw))
    for tab, prior in charts:
        if prior['loaded_name'] in affected or prior['saved_key'] in affected or any((e['type'], e['name']) in keys for e in prior['recipe'].ingredients + prior['recipe'].results):
            tab.restore(dict(prior, recipe=Recipe('new-recipe', {'ingredients': [], 'results': []}), name='new-recipe',
                             loaded_name=None, saved_key=None, result_machine=None, item_draft=None, is_custom=True,
                             dirty=False, auto_name=True, enabled=False, availability_override=False, expanded_recipes={}))
    app.refresh_catalog()
    owner.set_deletion_status(f'Deleted {len(keys)} items/fluids and {len(affected)} recipes. Ctrl+Z restores the entire batch.')
    return True
