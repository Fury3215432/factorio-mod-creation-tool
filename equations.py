"""Read simple crafting equations without executing input as code."""
import copy
from difflib import SequenceMatcher
import re
from time import time_ns
import tkinter as tk
from tkinter import ttk, messagebox

from core import Catalog, Recipe
from controls import sequence, BUTTONS
from project import identifier, positive, default_icon_asset
from ui import help_label, entry_undo


def existing_equation_item(known, term, force=None):
    """Resolve exactly as equation parsing does, including readable game IDs."""
    name = term.replace(' ', '_')
    candidates = [name, name.lower()]
    if ' ' in term:
        candidates += [term.replace(' ', '-'), term.lower().replace(' ', '-')]
    for candidate in dict.fromkeys(candidates):
        matches = [(kind, candidate) for kind in ('item', 'fluid')
                   if (kind, candidate) in known and (not force or kind == force)]
        if len(matches) > 1:
            raise ValueError('Ambiguous item/fluid name: ' + term + '. Use item: or fluid: before its name.')
        if matches:
            return matches[0]
    return None


def equation_options(line, seconds, category, categories):
    """Read optional per-line metadata without treating it as recipe terms."""
    equation, *options = line.split(';')
    if not options:
        parts = equation.split('=')
        if not 2 <= len(parts) <= 4:
            raise ValueError('Use ingredients = products = seconds = category (last two fields are optional).')
        equation = '='.join(parts[:2])
        if len(parts) >= 3 and parts[2].strip():
            seconds = positive(parts[2].strip(), 'Crafting seconds')
        if len(parts) == 4 and parts[3].strip():
            category = parts[3].strip()
    seen = set()
    for option in options:
        match = re.fullmatch(r'\s*(time|seconds|category)\s*=\s*(.*?)\s*', option, re.I)
        if not match:
            raise ValueError('Use ; time=3 and/or ; category=smelting after an equation.')
        key, value = match.groups()
        key = 'time' if key.lower() in ('time', 'seconds') else 'category'
        if key in seen:
            raise ValueError('Specify each equation option only once: ' + key)
        seen.add(key)
        if key == 'time':
            seconds = positive(value, 'Crafting seconds')
        else:
            category = value
    if category not in categories:
        raise ValueError('Choose a loaded recipe category: ' + category)
    return equation, seconds, category


ROOT_TOKEN = re.compile(r'(?<![\w-])ROOT(?![\w-])')
SCOPE_TOKEN = re.compile(r'(?<![\w-])SCOPE(?![\w-])')


def equation_root(left):
    """Use the first ingredient's name, without its quantity or type prefix."""
    first = next(equation_terms(left), None)
    if first is None or ROOT_TOKEN.search(left) or SCOPE_TOKEN.search(left):
        raise ValueError('ROOT and SCOPE need a named first ingredient and can only be used in products.')
    return first[2].replace('_', ' ').replace('-', ' ')


def expanded_equation_lines(text):
    """Resolve SCOPE locally and ROOT through first-ingredient producer links."""
    rows = {}
    for number, line in enumerate(text.splitlines(), 1):
        parts = line.split(';', 1)[0].split('=')
        if len(parts) < 2:
            continue
        left, right = parts[:2]
        try:
            scope = equation_root(left)
        except ValueError:
            continue
        rows[number] = {'scope': scope, 'root': scope, 'left': left, 'right': SCOPE_TOKEN.sub(lambda _: scope, right)}
    normalize = lambda name: re.sub(r'[-_\s]+', ' ', name.casefold()).strip()
    for _ in range(len(rows) + 1):
        producers = {}
        for number, row in rows.items():
            right = ROOT_TOKEN.sub(lambda _: row['root'], row['right'])
            for _, _, name, force in equation_terms(right):
                producers.setdefault(normalize(name), []).append(number)
        def origin(number, visiting):
            if number in visiting:
                raise ValueError('ROOT cannot be resolved through a circular crafting chain.')
            row = rows[number]
            parents = [n for n in producers.get(normalize(row['scope']), []) if n != number]
            if not parents:
                return row['scope']
            names = {origin(parent, visiting | {number}) for parent in parents}
            if len({normalize(name) for name in names}) != 1:
                raise ValueError('ROOT has multiple possible chain origins for ' + row['scope'] + '.')
            return sorted(names)[0]
        changed = False
        for number, row in rows.items():
            if not ROOT_TOKEN.search(row['right']):
                continue
            try:
                root = origin(number, set())
                row.pop('error', None)
            except ValueError as exc:
                row['error'] = str(exc)
                continue
            if root != row['root']:
                row['root'] = root
                changed = True
        if not changed:
            break
    else:
        for row in rows.values():
            if ROOT_TOKEN.search(row['right']):
                row['error'] = 'ROOT could not resolve a stable crafting chain.'
    for row in rows.values():
        row['expanded'] = ROOT_TOKEN.sub(lambda _: row['root'], row['right'])
    return rows


def equation_terms(text, expand_roots=False):
    """Yield name spans, excluding quantities, type prefixes and metadata."""
    offset = 0
    expanded = expanded_equation_lines(text) if expand_roots else {}
    for number, line in enumerate(text.splitlines(keepends=True), 1):
        equation = '='.join(line.split(';', 1)[0].split('=')[:2])
        row = expanded.get(number)
        equal = equation.find('=')
        for match in re.finditer(r'[^+=]+', equation):
            raw = match.group()
            start = match.start() + len(raw) - len(raw.lstrip())
            term = raw.strip()
            quantity = re.match(r'^(\d+(?:\.\d+)?)\s*(?:\*\s*|\s+)', term)
            if quantity:
                start += quantity.end()
                term = term[quantity.end():]
            force = None
            prefix = re.match(r'^(item|fluid):\s*', term)
            if prefix:
                force = prefix[1]
                start += prefix.end()
                term = term[prefix.end():]
            if term:
                end = offset + start + len(term)
                if row is not None and not row.get('error') and start > equal:
                    term = SCOPE_TOKEN.sub(lambda _: row['scope'], term)
                    term = ROOT_TOKEN.sub(lambda _: row['root'], term)
                yield offset + start, end, term, force
        offset += len(line)


def item_suggestions(catalog, text, limit=3):
    """Suggest close existing IDs/names; never replace or create anything."""
    normalize = lambda name: re.sub(r'[-_\s]+', ' ', name.casefold()).strip()
    candidates = []
    for (kind, name), proto in catalog.items.items():
        aliases = {normalize(name)}
        title = proto.get('localised_name')
        if isinstance(title, str):
            aliases.add(normalize(title))
        candidates.append((kind, name, aliases))
    suggestions, seen = [], set()
    for start, end, term, force in equation_terms(text, expand_roots=True):
        query = normalize(term)
        if not query or (query, force) in seen:
            continue
        seen.add((query, force))
        # Match the parser's exact readable-ID rules before suggesting typos.
        ids = {term.replace(' ', '_'), term.lower().replace(' ', '_')}
        if ' ' in term:
            ids.update((term.replace(' ', '-'), term.lower().replace(' ', '-')))
        if any(name in ids and (not force or kind == force) for kind, name, _ in candidates):
            continue
        ranked = []
        for kind, name, aliases in candidates:
            if force and kind != force:
                continue
            score = max(SequenceMatcher(None, query, alias).ratio() for alias in aliases)
            if score >= .76:
                ranked.append((score, kind, name))
        for score, kind, name in sorted(ranked, key=lambda row: (-row[0], row[2], row[1]))[:limit]:
            suggestions.append({'term': term, 'force': force, 'kind': kind, 'name': name,
                                'score': score})
    return suggestions


def plan_equations(app, text, seconds='1', category='crafting'):
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
            key = existing_equation_item(known, term, force)
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
    expanded = expanded_equation_lines(text)
    for line_number, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            continue
        try:
            line, recipe_seconds, recipe_category = equation_options(line, seconds, category, app.catalog.raw.get('recipe-category', {'crafting': {}}))
            if line.count('=') != 1:
                raise ValueError('Use exactly one = between ingredients and products.')
            left, right = line.split('=')
            if ROOT_TOKEN.search(left) or SCOPE_TOKEN.search(left):
                raise ValueError('ROOT and SCOPE can only be used in products; name the first ingredient explicitly.')
            if ROOT_TOKEN.search(right) or SCOPE_TOKEN.search(right):
                row = expanded.get(line_number)
                if row is None:
                    raise ValueError('ROOT and SCOPE need a named first ingredient.')
                if row.get('error'):
                    raise ValueError(row['error'])
                right = row['expanded']
            ingredients, results = side(left), side(right)
            signature = repr((ingredients, results, recipe_seconds, recipe_category))
            if signature in seen:
                raise ValueError('This equation appears more than once.')
            seen.add(signature)
            base_name = results[0]['name'] + '_recipe'
            name, index = base_name, 2
            while name in reserved:
                name, index = base_name + '_' + str(index), index + 1
            reserved.add(name)
            proto = {'type': 'recipe', 'name': name, 'ingredients': ingredients, 'results': results}
            Recipe(name, proto).export(name, recipe_seconds, True, recipe_category)
            recipes.append({'name': name, 'prototype': proto, 'seconds': recipe_seconds, 'category': recipe_category, 'line': line_number})
        except ValueError as exc:
            raise ValueError(f'Line {line_number}: {exc}') from exc
    if not recipes:
        raise ValueError('Enter at least one equation, with one equation per line.')
    return {'items': new_items, 'recipes': recipes}


def describe_equation(row):
    def describe(side):
        return ' + '.join((f"{entry['amount']:g} " if entry['amount'] != 1 else '') +
                          entry['name'].replace('_', ' ').replace('-', ' ')
                          for entry in row['prototype'][side])
    return f"{describe('ingredients')} = {describe('results')} = {row['seconds']:g} = {row['category']}"


def equation_line_checks(app, text, seconds, category, readings=None):
    """Validate each nonblank line, including duplicate recipes in this batch."""
    checks, seen = {}, set()
    expanded = expanded_equation_lines(text)
    for number, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            continue
        try:
            equation, line_seconds, line_category = equation_options(line, seconds, category, app.catalog.raw.get('recipe-category', {'crafting': {}}))
            expansion = expanded.get(number)
            if expansion and expansion.get('error'):
                raise ValueError(expansion['error'])
            if expansion:
                equation = expansion['left'] + '=' + expansion['expanded']
            row = plan_equations(app, equation, line_seconds, line_category)['recipes'][0]
            signature = repr((row['prototype']['ingredients'], row['prototype']['results'], row['seconds'], row['category']))
            if signature in seen:
                raise ValueError('This equation appears more than once.')
            seen.add(signature)
            checks[number] = None
            if readings is not None:
                readings[number] = describe_equation(row)
        except ValueError as exc:
            checks[number] = str(exc)
    return checks


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
        tab.last_plan = copy.deepcopy(plan)
        tab.applied_input = tab.current_input()
        tab.saved_input = tab.current_input()
        tab.dirty = False
        app.project.data['equations_draft'] = tab.draft_data()
        app.persist()
        app.record_undo('Read equations', tab, state, before)
        app.refresh_catalog()
    except (ValueError, OSError, KeyError):
        app.project.data = before
        tab.restore(state)
        raise


def equation_chains(plan, selected=()):
    """Expand batch recipes by exact item/fluid IDs, avoiding dependency cycles."""
    rows = {row['name']: row for row in plan['recipes']}
    producers = {}
    consumed = set()
    for row in rows.values():
        for product in row['prototype']['results']:
            producers.setdefault((product['type'], product['name']), []).append(row['name'])
        consumed.update((entry['type'], entry['name']) for entry in row['prototype']['ingredients'])
    preferred = [name for name in selected if name in rows]
    if not preferred:
        preferred = [name for name, row in rows.items()
                     if any((e['type'], e['name']) not in consumed for e in row['prototype']['results'])]
    covered = set()
    graphs = []

    def build(root):
        expanded = {}
        def visit(name, path, ancestors):
            covered.add(name)
            for index, ingredient in enumerate(rows[name]['prototype']['ingredients']):
                key = ingredient['type'], ingredient['name']
                child = next((n for n in producers.get(key, []) if n not in ancestors), None)
                if child is not None:
                    child_path = path + (index,)
                    expanded[child_path] = {'name': child, 'key': key}
                    visit(child, child_path, ancestors | {child})
        visit(root, (), {root})
        graphs.append((root, expanded))
    for name in preferred:
        build(name)
    # Include disconnected chains, alternate recipes, and cyclic components.
    if not selected:
        for name in rows:
            if name not in covered:
                build(name)
    return graphs


class EquationsTab(ttk.Frame):
    def __init__(self, app):
        super().__init__(app.tabs)
        self.app, self.dirty = app, False
        self.last_plan, self.applied_input = None, None
        self.saved_input = ('', '1', 'crafting')
        self.preview_job = None
        self.icon_job = None
        self.input_icons = []
        self.line_markers = []
        self.line_check_input = None
        self.line_checks = {}
        self.line_readings = {}
        ttk.Label(self, text='Read equations', font=('Segoe UI', 16, 'bold'), padding=12).pack(anchor='w')
        input_box = ttk.Frame(self)
        input_box.pack(fill='x', padx=12)
        self.text = tk.Text(input_box, height=6, wrap='none', undo=True, spacing1=20, spacing3=3, padx=24,
                            bg='#273240', fg='#e6edf3', insertbackground='#e6edf3')
        input_vertical = ttk.Scrollbar(input_box, orient='vertical', command=self.text.yview)
        input_vertical.pack(side='right', fill='y')
        input_horizontal = ttk.Scrollbar(input_box, orient='horizontal', command=self.text.xview)
        input_horizontal.pack(side='bottom', fill='x')
        self.text.pack(fill='x', expand=True)
        def scrolled(scrollbar, first, last):
            scrollbar.set(first, last)
            self.schedule_input_icons()
        self.text.configure(yscrollcommand=lambda a, b: scrolled(input_vertical, a, b),
                            xscrollcommand=lambda a, b: scrolled(input_horizontal, a, b))
        self.text.bind('<Configure>', lambda e: self.schedule_input_icons())
        help_label(self, 'Existing items and fluids show their icons above their names as you type. Unknown names have no icon and will create new items when applied.', wraplength=1100, padx=12)
        help_label(self, 'A green ✓ after an equation means it is valid, followed by how it is interpreted. Click the green reading to see the full text. It does not mean the recipe has been saved.', wraplength=1100, padx=12)
        help_label(self, 'One recipe per line: copper plate + iron plate = metal alloy\nOne space becomes _ in a new item ID. Use + between terms and = before products. Optional quantities: 2 copper plate + iron plate = 3 metal alloy. Existing items/fluids are reused; missing names create normal items.', wraplength=1100, padx=12)
        help_label(self, 'SCOPE = this recipe’s first ingredient; ROOT = the original first ingredient at the start of its chain in these equations. Example: copper ore = crushed SCOPE, then crushed copper ore = concentrated ROOT produces concentrated copper ore. Both keywords are uppercase and used in product names.', wraplength=1100, padx=12)
        help_label(self, 'Readable names also match existing hyphenated game IDs (copper plate → copper-plate). New items use default icons and appear in Suggested actions. Existing recipes are kept; name collisions receive _2, _3, etc.', wraplength=1100, padx=12)
        bar = ttk.Frame(self, padding=12)
        bar.pack(fill='x')
        self.seconds = tk.StringVar(value='1')
        ttk.Label(bar, text='Crafting seconds').pack(side='left')
        entry = ttk.Entry(bar, textvariable=self.seconds, width=8)
        entry.pack(side='left', padx=8)
        entry_undo(entry, self.seconds)
        self.category = tk.StringVar(value='crafting')
        ttk.Label(bar, text='Recipe category').pack(side='left')
        ttk.Combobox(bar, textvariable=self.category, state='readonly', values=sorted(c for c in app.catalog.raw.get('recipe-category', {'crafting': {}}) if not c.startswith('recipe-studio-only-')), width=24).pack(side='left', padx=8)
        self.apply_button = ttk.Button(bar, text='Apply equations', command=self.apply_changes)
        self.apply_button.pack(side='right')
        self.diagram_button = ttk.Button(bar, text='Show as diagram', command=self.show_diagram)
        self.diagram_button.pack(side='right', padx=6)
        self.open_button = ttk.Button(bar, text='Open selected recipe', command=self.open_selected)
        self.open_button.pack(side='right', padx=6)
        help_label(self, 'Format: ingredients = products = seconds = category. Example: copper ore = crushed SCOPE = 3 = crushing_crusher (create that category first). Omit the last fields to use batch defaults; leave time empty to specify only category. Time is seconds per craft; category determines compatible machines.', wraplength=1100, padx=12)
        help_label(self, 'Show as diagram saves this batch and opens final-product recipes with their ingredient chains expanded. Select rows to choose the roots; with no selection, every chain is shown, including disconnected chains in separate tabs.', wraplength=1100, padx=12)
        suggestions = ttk.LabelFrame(self, text='Suggest items', padding=8)
        suggestions.pack(fill='x', padx=12, pady=4)
        self.suggest_enabled = tk.BooleanVar(value=True)
        ttk.Checkbutton(suggestions, text='Suggest existing items with similar names', variable=self.suggest_enabled,
                        command=self.refresh_suggestions).pack(anchor='w')
        help_label(suggestions, 'Possible spelling matches, such as iron pate → iron-plate. Select a suggestion and use it to replace that name everywhere in these equations. Nothing is replaced automatically; ignore suggestions to create new items.', wraplength=1100)
        suggestion_body = ttk.Frame(suggestions)
        suggestion_body.pack(fill='x')
        self.suggestions = ttk.Treeview(suggestion_body, columns=('typed', 'existing', 'kind'), show='headings', height=3)
        for name, label in [('typed', 'Name in equations'), ('existing', 'Suggested existing ID'), ('kind', 'Type')]:
            self.suggestions.heading(name, text=label)
        self.suggestions.pack(side='left', fill='x', expand=True)
        suggestion_scroll = ttk.Scrollbar(suggestion_body, orient='vertical', command=self.suggestions.yview)
        suggestion_scroll.pack(side='left', fill='y')
        self.suggestions.configure(yscrollcommand=suggestion_scroll.set)
        self.use_suggestion_button = ttk.Button(suggestion_body, text='Use selected suggestion', command=self.use_suggestion)
        self.use_suggestion_button.pack(side='right', padx=8)
        self.suggestions.bind('<Double-Button-1>', lambda e: self.use_suggestion())
        self.suggestions.bind('<<TreeviewSelect>>', lambda e: self.use_suggestion_button.configure(state='normal' if self.suggestions.selection() else 'disabled'))
        holder = ttk.Frame(self, padding=12)
        holder.pack(fill='both', expand=True)
        self.preview = ttk.Treeview(holder, columns=('recipe', 'ingredients', 'products', 'seconds', 'category'), show='headings')
        for name, title in [('recipe', 'Recipe ID'), ('ingredients', 'Ingredients (quantity × ID)'), ('products', 'Products (quantity × ID)'), ('seconds', 'Crafting seconds'), ('category', 'Category')]:
            self.preview.heading(name, text=title)
            self.preview.column(name, width=220 if name in ('recipe', 'ingredients', 'products') else 110)
        scrollbar = ttk.Scrollbar(holder, orient='vertical', command=self.preview.yview)
        self.preview.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side='right', fill='y')
        self.preview.pack(fill='both', expand=True)
        self.preview.bind('<Double-Button-1>', lambda e: self.open_selected())
        self.preview.bind('<Button-%d>' % BUTTONS[app.controls['context_button']], self.recipe_context)
        self.status = ttk.Label(self, padding=12, wraplength=1100)
        self.status.pack(anchor='w')
        self.text.bind('<<Modified>>', self.modified)
        self.text.bind(sequence(app.controls['keys']['undo']), self.undo_text)
        self.traces = [(v, v.trace_add('write', lambda *_: self.changed())) for v in (self.seconds, self.category)]
        draft = app.project.data.get('equations_draft')
        if draft:
            self.restore({'input': draft['input'], 'saved_input': draft['input'], 'dirty': False,
                          'last_plan': draft.get('last_plan'), 'applied_input': draft.get('applied_input')})
            self.suggest_enabled.set(draft.get('suggest_enabled', True))
        self.refresh()

    def refresh_suggestions(self):
        self.suggestions.delete(*self.suggestions.get_children())
        self.suggestion_rows = {}
        if self.suggest_enabled.get():
            for index, row in enumerate(item_suggestions(self.app.catalog, self.text.get('1.0', 'end-1c'))):
                key = str(index)
                self.suggestion_rows[key] = row
                self.suggestions.insert('', 'end', iid=key, values=(row['term'], row['name'], row['kind']))
        self.use_suggestion_button.configure(state='disabled')

    def schedule_input_icons(self):
        if self.icon_job is None:
            self.icon_job = self.after_idle(self.refresh_input_icons)

    def refresh_input_icons(self):
        """Overlay icons in line spacing, keeping equation text and undo untouched."""
        if self.icon_job is not None:
            self.after_cancel(self.icon_job)
            self.icon_job = None
        for label in self.input_icons:
            label.destroy()
        self.input_icons = []
        self.refresh_line_markers()
        for start, end, term, force in equation_terms(self.text.get('1.0', 'end-1c'), expand_roots=True):
            try:
                key = existing_equation_item(self.app.catalog.items, term, force)
            except ValueError:
                continue
            if key is None:
                continue
            index = f'1.0+{start}c'
            box = self.text.bbox(index)
            if box is None:
                continue
            x, y, _, _ = box
            if y < 18 or x < 0:
                continue
            icon = self.app.icon(key, size=16)
            if not icon:
                continue
            label = tk.Label(self.text, image=icon, bg='#273240', borderwidth=0, highlightthickness=0)
            label.image = icon
            label.item_key = key
            label.place(x=x, y=y-18, width=16, height=16)
            def focus(event, position=index):
                self.text.mark_set('insert', position)
                self.text.focus_set()
            label.bind('<Button-1>', focus)
            label.bind('<Button-%d>' % BUTTONS[self.app.controls['context_button']], lambda event, item=key: self.item_context(event, item))
            self.input_icons.append(label)

    def item_context(self, event, key):
        from creations_ui import edit_item
        if hasattr(self, 'item_context_menu'):
            self.item_context_menu.destroy()
        self.item_context_menu = tk.Menu(self, tearoff=False)
        self.item_context_menu.add_command(label='Edit item' if key[0] == 'item' else 'Edit fluid', command=lambda: edit_item(self, key))
        from creations_ui import rename_item
        self.item_context_menu.add_command(label='Rename item' if key[0] == 'item' else 'Rename fluid', command=lambda: rename_item(self, key))
        from creations_ui import open_item_recipe
        self.item_context_menu.add_command(label='Open recipe', command=lambda: open_item_recipe(self.app, key))
        if key[0] == 'item':
            from creations_ui import convert_to_machine
            self.item_context_menu.add_command(label='Convert to machine', command=lambda: convert_to_machine(self, key))
        from creations_ui import open_all_recipes_containing
        self.item_context_menu.add_command(label='Open all recipes containing this item' if key[0] == 'item' else 'Open all recipes containing this fluid',
                                           command=lambda: open_all_recipes_containing(self.app, key))
        self.item_context_menu.tk_popup(event.x_root, event.y_root)

    def refresh_line_markers(self):
        for label in self.line_markers:
            label.destroy()
        self.line_markers = []
        current = self.current_input()
        cache_key = (current, id(self.app.catalog))
        if cache_key != self.line_check_input:
            self.line_readings = {}
            self.line_checks = equation_line_checks(self.app, *current, readings=self.line_readings)
            self.line_check_input = cache_key
        for number, error in self.line_checks.items():
            if error is not None:
                continue
            box = self.text.bbox(f'{number}.end')
            if box is None:
                continue
            x, y, _, height = box
            if x < 0 or x + 22 > self.text.winfo_width():
                continue
            reading = self.line_readings[number]
            label = tk.Label(self.text, text='✓ ' + reading, fg='#74d680', bg='#273240', anchor='w',
                             font=('Segoe UI', 10), borderwidth=0, highlightthickness=0, cursor='hand2')
            label.line_number = number
            label.reading = reading
            label.place(x=x+4, y=y, height=height)
            def show_reading(event, value=reading):
                dialog = tk.Toplevel(self.app)
                dialog.title('Interpreted equation')
                dialog.transient(self.app)
                ttk.Label(dialog, text=value, wraplength=800, padding=16).pack(fill='both', expand=True)
                ttk.Button(dialog, text='Close', command=dialog.destroy).pack(pady=12)
            label.bind('<Button-1>', show_reading)
            self.line_markers.append(label)

    def use_suggestion(self):
        selected = self.suggestions.selection()
        row = self.suggestion_rows.get(selected[0]) if selected else None
        if not row:
            return
        text = self.text.get('1.0', 'end-1c')
        spans = [(start, end) for start, end, term, force in equation_terms(text, expand_roots=True)
                 if term == row['term'] and force == row['force']]
        self.text.edit_separator()
        # Include the type explicitly, so item/fluid ID collisions stay unambiguous.
        replacement = ('' if row['force'] else row['kind'] + ':') + row['name']
        previous_autoseparators = self.text.cget('autoseparators')
        self.text.configure(autoseparators=False)
        try:
            for start, end in reversed(spans):
                self.text.delete(f'1.0+{start}c', f'1.0+{end}c')
                self.text.insert(f'1.0+{start}c', replacement)
        finally:
            self.text.configure(autoseparators=previous_autoseparators)
            self.text.edit_separator()
        self.text.edit_modified(False)
        self.changed()
        self.refresh()

    def recipe_context(self, event):
        row = self.preview.identify_row(event.y)
        if not row:
            return
        self.preview.selection_set(row)
        from creations_ui import rename_recipe
        if hasattr(self, 'context_menu'):
            self.context_menu.destroy()
        self.context_menu = tk.Menu(self, tearoff=False)
        def rename():
            if self.apply_changes():
                rename_recipe(self, row)
        self.context_menu.add_command(label='Rename recipe', command=rename)
        self.context_menu.tk_popup(event.x_root, event.y_root)

    def current_input(self):
        return self.text.get('1.0', 'end-1c'), self.seconds.get(), self.category.get()

    def snapshot(self):
        return {'input': self.current_input(), 'saved_input': self.saved_input, 'dirty': self.dirty, 'last_plan': copy.deepcopy(self.last_plan), 'applied_input': self.applied_input}

    def restore(self, state):
        self.text.delete('1.0', 'end')
        self.text.insert('1.0', state['input'][0])
        self.text.edit_modified(False)
        self.seconds.set(state['input'][1])
        self.category.set(state['input'][2])
        self.last_plan = copy.deepcopy(state['last_plan'])
        self.applied_input = tuple(state['applied_input']) if state['applied_input'] is not None else None
        self.saved_input = tuple(state.get('saved_input', ('', '1', 'crafting')))
        self.dirty = state['dirty']
        self.refresh()

    def modified(self, event):
        if self.text.edit_modified():
            self.text.edit_modified(False)
            self.changed()

    def changed(self):
        self.dirty = self.current_input() != self.saved_input
        if self.preview_job is not None:
            self.after_cancel(self.preview_job)
        self.preview_job = self.after(200, self.refresh)

    def refresh(self):
        if self.preview_job is not None:
            self.after_cancel(self.preview_job)
            self.preview_job = None
        self.refresh_suggestions()
        self.schedule_input_icons()
        selected = self.preview.selection()
        self.preview.delete(*self.preview.get_children())
        try:
            applied = self.current_input() == self.applied_input and self.last_plan is not None
            plan = self.last_plan if applied else plan_equations(self.app, *self.current_input())
            for row in plan['recipes']:
                describe = lambda side: ' + '.join(f"{entry['amount']:g} × {entry['name']}" for entry in row['prototype'][side])
                self.preview.insert('', 'end', iid=row['name'], values=(row['name'], describe('ingredients'), describe('results'), f"{row['seconds']:g}", row['category']))
            if selected and self.preview.exists(selected[0]):
                self.preview.selection_set(selected[0])
            self.status.configure(text=(f"Saved {len(plan['recipes'])} recipes and {len(plan['items'])} new items. Ctrl+Z undoes this batch." if applied else f"Ready: {len(plan['recipes'])} recipes. New items: " + (', '.join(plan['items']) or 'none')))
            self.apply_button.configure(state='disabled' if applied else 'normal')
            self.open_button.configure(state='normal' if applied else 'disabled')
            self.diagram_button.configure(state='normal')
        except ValueError as exc:
            self.status.configure(text=str(exc))
            self.apply_button.configure(state='disabled')
            self.open_button.configure(state='disabled')
            self.diagram_button.configure(state='disabled')

    def save_changes(self, quiet=False):
        """Save the editor document, including invalid/incomplete equations."""
        before = copy.deepcopy(self.app.project.data)
        try:
            self.app.project.data['equations_draft'] = self.draft_data()
            self.app.persist()
        except (OSError, ValueError) as exc:
            self.app.project.data = before
            messagebox.showerror('Cannot save equations text', str(exc), parent=self)
            return False
        self.saved_input = self.current_input()
        self.dirty = False
        return True

    def draft_data(self):
        return {'input': list(self.current_input()), 'last_plan': copy.deepcopy(self.last_plan),
                'applied_input': list(self.applied_input) if self.applied_input is not None else None,
                'suggest_enabled': self.suggest_enabled.get()}

    def apply_changes(self):
        if self.current_input() == self.applied_input or not self.text.get('1.0', 'end-1c').strip():
            return True
        try:
            apply_equations(self, plan_equations(self.app, *self.current_input()))
            return True
        except (ValueError, OSError, KeyError) as exc:
            messagebox.showerror('Cannot read equations', str(exc), parent=self)
            return False

    def show_diagram(self):
        selected = self.preview.selection()
        if not self.text.get('1.0', 'end-1c').strip() or not self.apply_changes():
            return []
        tabs = []
        for name, expanded in equation_chains(self.last_plan, selected):
            if name not in self.app.catalog.recipes:
                continue
            tab = self.app.new_tab()
            tab.load(name)
            tab.expanded_recipes = expanded
            tab.draw()
            if expanded:
                tab.zoom = min(1, max(.25, (max(800, tab.canvas.winfo_width()) - 30) / tab.graph_width))
                tab.draw()
            tab.canvas.xview_moveto(0)
            tab.canvas.yview_moveto(0)
            tab.last_state = tab.snapshot()
            tabs.append(tab)
        if tabs:
            self.app.tabs.select(tabs[0])
        return tabs

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
            answer = messagebox.askyesnocancel('Close equations', 'Save this tab’s text and settings before closing? This will not import the equations.', parent=self)
            if answer is None or answer and not self.save_changes():
                return
        self.destroy()

    def destroy(self):
        if self.icon_job is not None:
            self.after_cancel(self.icon_job)
        if self.preview_job is not None:
            self.after_cancel(self.preview_job)
        for variable, trace in self.traces:
            variable.trace_remove('write', trace)
        super().destroy()
