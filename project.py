"""Portable, saved edits and multi-prototype mod compilation."""
import base64
import copy
import json
import math
import re
import struct
import time
from functools import lru_cache
from pathlib import Path

from core import Recipe, export_mod, lua


def identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r'[a-zA-Z0-9_-]+', value):
        raise ValueError('IDs must contain letters, numbers, hyphens or underscores.')
    return value


def positive(value, label, integer=False):
    number = float(value)
    if not math.isfinite(number) or number <= 0 or (integer and not number.is_integer()):
        raise ValueError(label + ' must be a positive ' + ('whole number.' if integer else 'number.'))
    return int(number) if integer else number


def png_asset(path):
    data = Path(path).read_bytes()
    return encode_png(data)


@lru_cache(maxsize=1)
def default_icon_asset():
    """The bundled checkerboard, independent of the original desktop file."""
    return png_asset(Path(__file__).resolve().parent / 'assets' / 'default-item-icon.png')


def uses_default_icon(item):
    return bool(item.get('icon_is_default')) or not item.get('icon') or item['icon'].get('data') == default_icon_asset()['data']


def is_finished_product(item, prototype=None):
    if 'finished_product' in item:
        return bool(item['finished_product'])
    proto = prototype or item.get('original', {})
    return bool(proto.get('place_result') or proto.get('place_as_tile') or proto.get('placed_as_equipment_result')
                or proto.get('type') in ('ammo', 'gun', 'armor', 'capsule', 'repair-tool', 'tool', 'module')
                or item.get('kind') == 'science pack')


def encode_png(data):
    if len(data) < 24 or data[:8] != b'\x89PNG\r\n\x1a\n':
        raise ValueError('Choose a valid PNG image.')
    width, height = struct.unpack('>II', data[16:24])
    if width != height or width < 1 or width > 4096:
        raise ValueError('Icons must be square PNG images, up to 4096 × 4096 pixels.')
    return {'data': base64.b64encode(data).decode('ascii'), 'size': width}


class Project:
    def __init__(self, data=None):
        self.data = copy.deepcopy(data or {'format': 1, 'recipes': {}, 'items': {}, 'technologies': {}})
        if self.data.get('format') != 1 or any(not isinstance(self.data.get(k), dict) for k in ('recipes', 'items', 'technologies')):
            raise ValueError('Unsupported or invalid Recipe Studio project.')
        self.data.setdefault('machines', {})
        self.data.setdefault('deleted', {})
        if not isinstance(self.data['deleted'], dict) or any(not isinstance(names, dict) for names in self.data['deleted'].values()):
            raise ValueError('Invalid deleted prototypes in project.')
        if not isinstance(self.data['machines'], dict):
            raise ValueError('Invalid machines in project.')
        for item in self.data['items'].values():
            if not item.get('icon') and item.get('operation') != 'edit':
                item['icon'] = copy.deepcopy(default_icon_asset())
                item['icon_is_default'] = True
        # Preserve construction recipes from projects saved by older versions,
        # but keep them as normal independent recipe edits from now on.
        for name, machine in self.data['machines'].items():
            if machine.get('ingredients') and name not in self.data['recipes']:
                proto = {'type': 'recipe', 'name': name, 'ingredients': machine['ingredients'], 'results': [{'type': 'item', 'name': name, 'amount': 1}]}
                self.save_recipe(Recipe(name, proto), name, machine.get('build_time', 2), machine.get('enabled', True), custom=True)
            for key in ('ingredients', 'build_time', 'enabled'):
                machine.pop(key, None)

    @classmethod
    def open(cls, path):
        return cls(json.loads(Path(path).read_text(encoding='utf-8')))

    def save(self, path):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(path.name + '.tmp')
        temporary.write_text(json.dumps(self.data, indent=2, ensure_ascii=False, allow_nan=False), encoding='utf-8')
        temporary.replace(path)

    def save_recipe(self, recipe, name, seconds, enabled, custom=False, category=None):
        recipe.export(name, seconds, enabled, category)
        self.data.get('deleted', {}).get('recipe', {}).pop(name, None)
        created_at = self.data['recipes'].get(name, {}).get('created_at', time.time_ns())
        self.data['recipes'][name] = {'source': recipe.name, 'original': copy.deepcopy(recipe.original),
                                     'created_at': created_at,
                                     'ingredients': copy.deepcopy(recipe.ingredients), 'results': copy.deepcopy(recipe.results),
                                     'seconds': float(seconds), 'enabled': bool(enabled), 'custom': custom,
                                     'category': category or recipe.original.get('normal', recipe.original).get('category', 'crafting')}

    def recipe(self, name):
        saved = self.data['recipes'][name]
        recipe = Recipe(saved['source'], saved['original'])
        recipe.ingredients, recipe.results = copy.deepcopy(saved['ingredients']), copy.deepcopy(saved['results'])
        return recipe

    def recipe_unlocks(self, name, base):
        technologies = dict(base.get('technology', {}))
        technologies.update({n: t['prototype'] for n, t in self.data['technologies'].items()})
        return sorted(n for n, proto in technologies.items()
                      if any(e.get('type') == 'unlock-recipe' and e.get('recipe') == name for e in proto.get('effects', [])))

    def remove_recipe_unlocks(self, name, base):
        affected = self.recipe_unlocks(name, base)
        for technology in affected:
            saved = copy.deepcopy(self.data['technologies'].get(technology, {}))
            proto = copy.deepcopy(saved.get('prototype') or base.get('technology', {}).get(technology, {}))
            proto['effects'] = [e for e in proto.get('effects', []) if not (e.get('type') == 'unlock-recipe' and e.get('recipe') == name)]
            saved.update(prototype=proto, created_at=saved.get('created_at', time.time_ns()))
            self.data['technologies'][technology] = saved
        return affected

    def recipes_missing_unlocks(self, catalog, loaded_recipes=()):
        names = set(loaded_recipes) | set(self.data['recipes'])
        for name, item in self.data['items'].items():
            names.update(catalog.by_product.get(('fluid' if item.get('kind') == 'fluid' else 'item', name), []))
        result = []
        for name in sorted(names):
            if name not in catalog.recipes:
                continue
            proto = catalog.recipes[name].get('normal', catalog.recipes[name])
            if proto.get('hidden') and name not in self.data['recipes']:
                continue
            if not proto.get('enabled', True) and not self.recipe_unlocks(name, catalog.raw):
                result.append(name)
        return result

    def item_prototype(self, name):
        item = self.data['items'][name]
        kind = item.get('kind', 'item')
        proto = {'type': 'tool' if kind == 'science pack' else 'item' if kind == 'ore' else kind, 'name': name, 'localised_name': item['title'],
                'localised_description': item.get('description', ''),
                'subgroup': item['subgroup'], 'order': 'z[' + name + ']',
                'icon': '__RECIPE_STUDIO_MOD__/graphics/items/' + name + '.png', 'icon_size': item['icon']['size'] if item.get('icon') else 64}
        if proto['type'] == 'fluid':
            proto.update(default_temperature=item.get('default_temperature', 25),
                         base_color=item.get('base_color', {'r': 0.5, 'g': 0.5, 'b': 0.5}),
                         flow_color=item.get('flow_color', {'r': 0.8, 'g': 0.8, 'b': 0.8}))
        else:
            proto['stack_size'] = item['stack_size']
            if kind == 'science pack':
                proto.update(durability=1,
                             durability_description_key='description.science-pack-remaining-amount-key',
                             durability_description_value='description.science-pack-remaining-amount-value')
        if item.get('operation') == 'edit':
            original = copy.deepcopy(item['original'])
            proto['type'] = original['type']
            if not item.get('icon'):
                proto.pop('icon', None)
                proto.pop('icon_size', None)
            else:
                original.pop('icons', None)
            original.update(proto)
            proto = original
        return proto

    def creations(self, include_edits=False):
        """Saved creations, newest first; insertion order supports older projects."""
        rows = [(item.get('kind', 'item'), name, item) for name, item in self.data['items'].items()]
        rows.extend(('machine', name, machine) for name, machine in self.data['machines'].items()
                    if machine.get('operation') != 'edit')
        if include_edits:
            rows.extend(('machine', name, machine) for name, machine in self.data['machines'].items() if machine.get('operation') == 'edit')
            rows.extend(('recipe', name, recipe) for name, recipe in self.data['recipes'].items())
            rows.extend(('technology', name, tech) for name, tech in self.data['technologies'].items())
        return sorted(reversed(rows), key=lambda row: row[2].get('created_at', 0), reverse=True)

    def update_creation(self, previous, draft, catalog):
        """Rename/convert a saved creation and its saved recipe references."""
        name = identifier(draft['name'])
        old = self.data['items'][previous]
        old_key = ('fluid' if old.get('kind') == 'fluid' else 'item', previous)
        new_key = ('fluid' if draft.get('kind') == 'fluid' else 'item', name)
        if name != previous and (name in self.data['items'] or any(n == name for _, n in catalog.items)):
            raise ValueError('That ID already exists. Choose a unique ID.')
        if new_key != old_key and new_key in catalog.items and name not in self.data['items']:
            raise ValueError('That ID and type already exist in the loaded game.')
        replacement = {}
        for key, value in self.data['items'].items():
            replacement[name if key == previous else key] = draft if key == previous else value
        self.data['items'] = replacement
        for recipe in self.data['recipes'].values():
            for entry in recipe['ingredients'] + recipe['results']:
                if (entry['type'], entry['name']) == old_key:
                    entry.update(type=new_key[0], name=new_key[1])
                    if new_key[0] == 'item':
                        for field in ('temperature', 'minimum_temperature', 'maximum_temperature', 'fluidbox_index'):
                            entry.pop(field, None)
        if name != previous:
            for tech in self.data['technologies'].values():
                for ingredient in tech['prototype'].get('unit', {}).get('ingredients', []):
                    if isinstance(ingredient, dict):
                        if ingredient['name'] == previous:
                            ingredient['name'] = name
                    elif ingredient[0] == previous:
                        ingredient[0] = name
        return old_key, new_key

    def items_missing_icons(self):
        return sorted(name for name, item in self.data['items'].items() if uses_default_icon(item) and not (item.get('operation') == 'edit' and not item.get('icon')))

    def items_missing_recipes(self, catalog, loaded_items=()):
        from machine_model import placed_item_name
        keys = set(loaded_items) | {('fluid' if item.get('kind') == 'fluid' else 'item', name) for name, item in self.data['items'].items()}
        keys.difference_update(('item', placed_item_name(name, machine)) for name, machine in self.data['machines'].items())
        return sorted(key for key in keys if key in catalog.items and not catalog.by_product.get(key))

    def items_unused(self, catalog, loaded_items=()):
        from core import entries
        from machine_model import placed_item_name
        keys = set(loaded_items) | {('fluid' if item.get('kind') == 'fluid' else 'item', name) for name, item in self.data['items'].items()}
        keys.difference_update(('item', placed_item_name(name, machine)) for name, machine in self.data['machines'].items())
        used = {(e['type'], e['name']) for proto in catalog.recipes.values() for e in entries(proto, 'ingredients')}
        return sorted(key for key in keys if key in catalog.items and key not in used
                      and not is_finished_product(self.data['items'].get(key[1], {}), catalog.items[key]))

    def editable_item(self, key, catalog):
        if key[1] in self.data['items']:
            return copy.deepcopy(self.data['items'][key[1]])
        proto = catalog.items[key]
        kind = 'fluid' if key[0] == 'fluid' else 'science pack' if proto.get('type') == 'tool' else 'item'
        title = proto.get('localised_name')
        description = proto.get('localised_description', '')
        record = {'name': key[1], 'title': title if isinstance(title, str) else key[1].replace('-', ' ').title(),
                  'description': description if isinstance(description, str) else '', 'kind': kind, 'operation': 'edit',
                  'original': copy.deepcopy(proto), 'stack_size': proto.get('stack_size', 100),
                  'subgroup': proto.get('subgroup', 'intermediate-product'), 'icon': None, 'icon_path': '', 'default_amount': 1,
                  'default_temperature': proto.get('default_temperature', 25)}
        record.update({field: proto[field] for field in ('base_color', 'flow_color') if field in proto})
        return record

    def merged_raw(self, base, include_machines=True):
        raw = copy.deepcopy(base)
        for name in self.data['items']:
            proto = self.item_prototype(name)
            raw.setdefault(proto['type'], {})[name] = proto
            item = self.data['items'][name]
            if item.get('kind') == 'ore':
                from ore_model import resource, apply
                apply(raw, name, item, resource(name, item, base, proto))
        for lab in raw.get('lab', {}).values():
            lab['inputs'] = [n for n in lab.get('inputs', []) if n in raw.get('tool', {})]
            lab['inputs'].extend(n for n, item in self.data['items'].items()
                                 if item.get('kind') == 'science pack' and item.get('operation') != 'edit' and n not in lab['inputs'])
        for name, saved in self.data['recipes'].items():
            proto = copy.deepcopy(saved['original'])
            for field in ('normal', 'expensive', 'result', 'result_count'):
                proto.pop(field, None)
            proto.update(type='recipe', name=name, ingredients=saved['ingredients'], results=saved['results'], energy_required=saved['seconds'], enabled=False if self.recipe_unlocks(name, base) else saved['enabled'])
            proto['category'] = saved.get('category', proto.get('category', 'crafting'))
            proto.pop('categories', None)
            if saved['results']:
                proto['main_product'] = saved['results'][0]['name']
            raw.setdefault('recipe', {})[name] = proto
        for name, tech in self.data['technologies'].items():
            raw.setdefault('technology', {})[name] = copy.deepcopy(tech['prototype'])
        if include_machines and self.data['machines']:
            from machine_model import apply_machines
            apply_machines(raw, self.data['machines'])
        for tech in self.data['technologies'].values():
            for effect in tech['prototype'].get('effects', []):
                if effect.get('type') == 'unlock-recipe' and effect.get('recipe') in raw.get('recipe', {}):
                    raw['recipe'][effect['recipe']]['enabled'] = False
        self.apply_deletions(raw)
        return raw

    def apply_deletions(self, raw):
        deleted_recipes = self.data.get('deleted', {}).get('recipe', {})
        for group, names in self.data.get('deleted', {}).items():
            for name in names:
                raw.get(group, {}).pop(name, None)
        for tech in raw.get('technology', {}).values():
            if 'effects' in tech:
                tech['effects'] = [effect for effect in tech['effects'] if not (effect.get('type') == 'unlock-recipe' and effect.get('recipe') in deleted_recipes)]
        for module in raw.get('module', {}).values():
            for field in ('limitation', 'limitation_blacklist'):
                if field in module:
                    module[field] = [name for name in module[field] if name not in deleted_recipes]
        for lab in raw.get('lab', {}).values():
            if 'inputs' in lab:
                lab['inputs'] = [name for name in lab['inputs'] if name not in self.data.get('deleted', {}).get('tool', {})]

    def validate_technology(self, prototype, catalog, previous=None):
        name = identifier(prototype['name'])
        if previous and name != previous:
            raise ValueError('Technology IDs cannot be renamed. Create a new technology instead.')
        known = set(catalog.raw.get('technology', {})) | set(self.data['technologies']) | {name}
        prerequisites = prototype.get('prerequisites', [])
        if not isinstance(prerequisites, list) or any(p not in known for p in prerequisites):
            raise ValueError('Every prerequisite must name a loaded or saved technology.')
        if name in prerequisites or len(prerequisites) != len(set(prerequisites)):
            raise ValueError('Prerequisites must be unique and cannot include the technology itself.')
        graph = {n: p.get('prerequisites', []) for n, p in catalog.raw.get('technology', {}).items()}
        graph.update({n: t['prototype'].get('prerequisites', []) for n, t in self.data['technologies'].items()})
        graph[name] = prerequisites
        visiting, done = set(), set()
        def visit(node):
            if node in visiting:
                raise ValueError('Technology prerequisites create a cycle.')
            if node in done:
                return
            visiting.add(node)
            for parent in graph.get(node, []):
                visit(parent)
            visiting.remove(node)
            done.add(node)
        visit(name)
        if not prototype.get('research_trigger'):
            unit = prototype.get('unit', {})
            if not unit.get('count_formula'):
                positive(unit.get('count', 0), 'Research count', True)
            positive(unit.get('time', 0), 'Research time')
            if not unit.get('ingredients'):
                raise ValueError('Choose at least one science pack.')
            packs = []
            for ingredient in unit['ingredients']:
                pack, amount = (ingredient['name'], ingredient['amount']) if isinstance(ingredient, dict) else ingredient
                if pack not in catalog.raw.get('tool', {}):
                    raise ValueError('Unknown science pack: ' + str(pack))
                positive(amount, 'Science pack quantity', True)
                packs.append(pack)
            if len(packs) != len(set(packs)):
                raise ValueError('Science packs must be unique.')
        recipes = set(catalog.recipes) | set(self.data['recipes'])
        for effect in prototype.get('effects', []):
            if effect.get('type') == 'unlock-recipe' and effect.get('recipe') not in recipes:
                raise ValueError('Unknown recipe unlock: ' + str(effect.get('recipe')))

    def compile(self, catalog):
        code, assets = [], {}
        for name, item in self.data['items'].items():
            identifier(name)
            kind = item.get('kind', 'item')
            if kind not in ('item', 'fluid', 'science pack', 'ore'):
                raise ValueError('Creation type must be item, fluid, science pack or ore.')
            exists = ('fluid' if kind == 'fluid' else 'item', name) in catalog.items
            if item.get('operation') == 'edit':
                if not exists or item.get('original', {}).get('type') not in catalog.raw or name not in catalog.raw[item['original']['type']]:
                    raise ValueError('Missing original item. Load its source mod: ' + name)
            elif exists:
                raise ValueError('New item already exists in the loaded game: ' + name)
            if kind != 'fluid':
                positive(item['stack_size'], 'Stack size', True)
            elif not math.isfinite(float(item.get('default_temperature', 25))):
                raise ValueError('Default temperature must be a finite number.')
            if item['subgroup'] not in catalog.raw.get('item-subgroup', {}):
                raise ValueError('Unknown item subgroup: ' + item['subgroup'])
            if item.get('icon'):
                data = base64.b64decode(item['icon']['data'], validate=True)
                encode_png(data)
                assets['graphics/items/' + name + '.png'] = data
            code.append('data:extend({' + lua(self.item_prototype(name)) + '})')
            if kind == 'ore':
                from ore_model import resource, compile_resource
                code.append(compile_resource(name, item, resource(name, item, catalog.raw, self.item_prototype(name))))
        from machine_model import placed_item_name
        known_items = set(catalog.items) | {('fluid' if i.get('kind') == 'fluid' else 'item', n) for n, i in self.data['items'].items()} | {('item', placed_item_name(n, m)) for n, m in self.data['machines'].items()}
        for group, names in self.data.get('deleted', {}).items():
            if group != 'recipe':
                known_items.difference_update(('fluid' if group == 'fluid' else 'item', name) for name in names)
        if self.data['items']:
            # Keep labs compatible when a custom pack is renamed or converted.
            code.append('for _, lab in pairs(data.raw.lab or {}) do\n'
                        '  local inputs = {}\n'
                        '  for _, name in pairs(lab.inputs or {}) do if data.raw.tool[name] then inputs[#inputs + 1] = name end end\n'
                        '  lab.inputs = inputs\nend')
            for name, item in self.data['items'].items():
                if item.get('kind') == 'science pack' and item.get('operation') != 'edit':
                    code.append('for _, lab in pairs(data.raw.lab or {}) do\n'
                                '  local found = false\n'
                                '  for _, name in pairs(lab.inputs) do if name == ' + lua(name) + ' then found = true end end\n'
                                '  if not found then table.insert(lab.inputs, ' + lua(name) + ') end\nend')
        # Every recipe gets its own scope, so locals do not leak between edits.
        for name, saved in self.data['recipes'].items():
            recipe = self.recipe(name)
            enabled = False if self.recipe_unlocks(name, catalog.raw) else saved['enabled']
            category = saved.get('category', recipe.original.get('normal', recipe.original).get('category', 'crafting'))
            recipe.export(name, saved['seconds'], enabled, category)
            if catalog.raw.get('recipe-category') and category not in catalog.raw['recipe-category']:
                raise ValueError('Unknown recipe category: ' + category)
            for entry in recipe.ingredients + recipe.results:
                if (entry['type'], entry['name']) not in known_items:
                    raise ValueError('Unknown recipe item: ' + entry['name'])
            if saved.get('custom'):
                if name in catalog.recipes:
                    raise ValueError('New recipe ID already exists: ' + name)
                proto = {'type': 'recipe', 'name': name, 'category': category, 'ingredients': recipe.ingredients,
                         'results': recipe.results, 'enabled': enabled, 'energy_required': saved['seconds']}
                if recipe.results:
                    proto['main_product'] = recipe.results[0]['name']
                code.append('data:extend({' + lua(proto) + '})')
            else:
                if recipe.name not in catalog.recipes:
                    raise ValueError('Missing source recipe. Load the original mods: ' + recipe.name)
                code.append('do\n' + recipe.export(name, saved['seconds'], enabled, category) + '\nend')
        if self.data['machines']:
            from machine_model import compile_machines
            machine_code, machine_assets = compile_machines(self, catalog)
            code.append(machine_code)
            assets.update(machine_assets)
        merged = type(catalog)(self.merged_raw(catalog.raw))
        for name, tech in self.data['technologies'].items():
            proto = copy.deepcopy(tech['prototype'])
            if 'effects' in proto:
                proto['effects'] = [e for e in proto['effects'] if not (e.get('type') == 'unlock-recipe' and e.get('recipe') in self.data.get('deleted', {}).get('recipe', {}))]
            self.validate_technology(proto, merged, previous=name)
            for effect in proto.get('effects', []):
                if effect.get('type') == 'unlock-recipe':
                    code.append('data.raw.recipe[' + lua(effect['recipe']) + '].enabled = false')
            if tech.get('icon'):
                data = base64.b64decode(tech['icon']['data'], validate=True)
                encode_png(data)
                assets['graphics/technologies/' + name + '.png'] = data
                proto.pop('icons', None)
                proto['icon'] = '__RECIPE_STUDIO_MOD__/graphics/technologies/' + name + '.png'
                proto['icon_size'] = tech['icon']['size']
            code.append('data:extend({' + lua(proto) + '})')
        if any(self.data.get('deleted', {}).values()):
            deleted = self.data['deleted']
            code.append('do\nlocal deleted = ' + lua(deleted) + '\n'
                        'for kind, names in pairs(deleted) do for name in pairs(names) do if data.raw[kind] then data.raw[kind][name] = nil end end end\n'
                        'for _, tech in pairs(data.raw.technology or {}) do\n'
                        '  if tech.effects then local effects = {}; for _, effect in pairs(tech.effects) do\n'
                        '    if not (effect.type == "unlock-recipe" and (deleted.recipe or {})[effect.recipe]) then effects[#effects+1] = effect end\n'
                        '  end; tech.effects = effects end\nend\n'
                        'for _, module in pairs(data.raw.module or {}) do for _, field in pairs({"limitation", "limitation_blacklist"}) do\n'
                        '  if module[field] then local names = {}; for _, name in pairs(module[field]) do if not (deleted.recipe or {})[name] then names[#names+1] = name end end; module[field] = names end\n'
                        'end end\n'
                        'for _, lab in pairs(data.raw.lab or {}) do local inputs = {}; for _, name in pairs(lab.inputs or {}) do\n'
                        '  if not (deleted.tool or {})[name] then inputs[#inputs+1] = name end\n'
                        'end; lab.inputs = inputs end\nend')
        if not code:
            raise ValueError('Save at least one recipe, item, technology or machine first.')
        return '\n\n'.join(code), assets

    def export(self, destination, catalog, game_root, mods_directory, target=None, mod_name='recipe-studio-project'):
        code, assets = self.compile(catalog)
        return export_mod(destination, None, 'project', 1, True, game_root, mods_directory,
                          target=target, mod_name=mod_name, bundle_code=code, bundle_assets=assets, change_details=self.changes(catalog))

    def changes(self, catalog):
        """Exact before/after values for every edited prototype property."""
        from machine_model import placed_item_name
        result = []
        merged = self.merged_raw(catalog.raw)
        def diff(before, after, path=''):
            output = []
            if isinstance(before, dict) and isinstance(after, dict):
                for key in sorted(set(before) | set(after)):
                    pointer = path + '/' + key.replace('~', '~0').replace('/', '~1')
                    if key not in before or key not in after:
                        output.append({'path': pointer, 'before_present': key in before, 'after_present': key in after, 'before': before.get(key), 'after': after.get(key)})
                    else:
                        output.extend(diff(before[key], after[key], pointer))
            elif before != after:
                output.append({'path': path, 'before': before, 'after': after})
            return output
        for group, names in self.data.get('deleted', {}).items():
            for name in names:
                result.append({'type': group, 'name': name, 'operation': 'deleted', 'changes': diff(catalog.raw.get(group, {}).get(name), None)})
        for group, names in [('item', self.data['items']), ('recipe', self.data['recipes']), ('technology', self.data['technologies'])]:
            for name in names:
                prototype_group = self.item_prototype(name)['type'] if group == 'item' else group
                before = copy.deepcopy(catalog.raw.get(prototype_group, {}).get(name))
                after = copy.deepcopy(merged[prototype_group][name])
                if group == 'recipe' and before:
                    source = before.get('normal', before)
                    recipe = Recipe(name, before)
                    before.update(ingredients=recipe.ingredients, results=recipe.results, energy_required=source.get('energy_required', 0.5), enabled=source.get('enabled', True), category=source.get('category', 'crafting'))
                if group == 'technology' and self.data['technologies'][name].get('icon'):
                    after.pop('icons', None)
                    after['icon'] = '__RECIPE_STUDIO_MOD__/graphics/technologies/' + name + '.png'
                    after['icon_size'] = self.data['technologies'][name]['icon']['size']
                if group == 'recipe' and any(e.get('type') == 'unlock-recipe' and e.get('recipe') == name for t in self.data['technologies'].values() for e in t['prototype'].get('effects', [])):
                    after['enabled'] = False
                result.append({'type': prototype_group, 'name': name, 'operation': 'added' if before is None else 'modified', 'changes': diff(before, after)})
                if group == 'item' and self.data['items'][name].get('kind') == 'ore':
                    for extra_group in ('resource', 'autoplace-control'):
                        if name in merged.get(extra_group, {}):
                            original = catalog.raw.get(extra_group, {}).get(name)
                            result.append({'type': extra_group, 'name': name, 'operation': 'added' if original is None else 'modified',
                                           'changes': diff(original, merged[extra_group][name])})
        if any(item.get('kind') == 'ore' for item in self.data['items'].values()):
            for name, planet in merged.get('planet', {}).items():
                original = catalog.raw.get('planet', {}).get(name, {})
                changes = diff(original, planet)
                if changes:
                    result.append({'type': 'planet', 'name': name, 'operation': 'modified', 'changes': changes})
        for name, lab in merged.get('lab', {}).items():
            before = catalog.raw.get('lab', {}).get(name, {})
            changes = diff(before, lab)
            if changes:
                result.append({'type': 'lab', 'name': name, 'operation': 'modified', 'changes': changes})
        # Technology unlocks can gate a loaded recipe even in imported projects
        # where the recipe does not have its own saved edit record.
        gated = {e['recipe'] for t in self.data['technologies'].values() for e in t['prototype'].get('effects', []) if e.get('type') == 'unlock-recipe'}
        for name in sorted(gated - set(self.data['recipes']) - set(self.data['machines']) - set(self.data.get('deleted', {}).get('recipe', {}))):
            before = catalog.recipes.get(name, {}).get('enabled', True)
            if before:
                result.append({'type': 'recipe', 'name': name, 'operation': 'modified', 'changes': [{'path': '/enabled', 'before': before, 'after': False}]})
        if self.data.get('deleted', {}).get('recipe'):
            for group in ('technology', 'module'):
                for name, after in merged.get(group, {}).items():
                    if group == 'technology' and name in self.data['technologies']:
                        continue
                    original = catalog.raw.get(group, {}).get(name)
                    changes = diff(original, after)
                    if changes:
                        result.append({'type': group, 'name': name, 'operation': 'modified', 'changes': changes})
        if self.data['machines']:
            from machine_model import machine_kind
            for name, machine in self.data['machines'].items():
                item_name = placed_item_name(name, machine)
                for kind, prototype_name in ((machine_kind(machine), name), ('item', item_name)):
                    before = catalog.raw.get(kind, {}).get(prototype_name)
                    result.append({'type': kind, 'name': prototype_name, 'operation': 'added' if before is None else 'modified', 'changes': diff(before, merged[kind][prototype_name])})
            # Include the recipe categories and producer compatibility additions.
            for kind in ('recipe-category', 'recipe', 'assembling-machine', 'furnace', 'mining-drill', 'character', 'rocket-silo'):
                for name, after in merged.get(kind, {}).items():
                    if name in self.data['machines'] or (kind == 'recipe' and name in self.data['recipes']):
                        continue
                    before = catalog.raw.get(kind, {}).get(name)
                    changes = diff(before, after)
                    if changes:
                        result.append({'type': kind, 'name': name, 'operation': 'added' if before is None else 'modified', 'changes': changes})
        return result

    def missing_machine_recipes(self, catalog):
        from core import entries
        from machine_model import placed_item_name
        produced = {p['name'] for name, recipe in catalog.recipes.items() if name not in self.data['recipes'] and name not in self.data.get('deleted', {}).get('recipe', {}) for p in entries(recipe, 'results') if p['type'] == 'item'}
        produced.update(p['name'] for recipe in self.data['recipes'].values() for p in recipe['results'] if p['type'] == 'item')
        return [name for name in sorted(self.data['machines']) if placed_item_name(name, self.data['machines'][name]) not in produced]
