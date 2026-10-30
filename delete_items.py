"""Delete an item and every recipe containing it as one undoable change."""
import copy
import weakref
from tkinter import messagebox

from core import Catalog, Recipe, entries


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
