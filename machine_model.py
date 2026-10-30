"""Placeable crafting machines built from valid game templates."""
import base64
import copy
import re
import struct
from pathlib import Path

from core import entries, lua
from machine_geometry import dimensions, resize_entity

MACHINE_TYPES = ('assembling-machine', 'furnace', 'mining-drill', 'rocket-silo')
CONTROLLED = {'name', 'type', 'localised_name', 'localised_description', 'max_health', 'crafting_speed', 'mining_speed',
              'energy_usage', 'module_slots', 'module_specification', 'crafting_categories', 'resource_categories',
              'resource_searching_radius', 'resource_drain_rate_percent', 'selection_box', 'collision_box', 'tile_width', 'tile_height',
              'icon', 'icons', 'icon_size', 'minable', 'placeable_by'}


def machine_kind(machine):
    return machine.get('entity_type', 'assembling-machine')


def placed_item_name(name, machine):
    return (machine.get('item_name') or name) if machine.get('operation') == 'edit' else name


def source_config(kind, name, catalog):
    """Populate the form from every stat of the selected source entity."""
    source = catalog.raw[kind][name]
    item_name, item = next(((n, p) for (t, n), p in catalog.items.items() if t == 'item' and p.get('place_result') == name), (name, {}))
    width, height = dimensions(source)
    energy = source.get('energy_source', {})
    return {'template': name, 'entity_type': kind, 'operation': 'create', 'title': source.get('localised_name') if isinstance(source.get('localised_name'), str) else name.replace('-', ' ').title(),
            'description': source.get('localised_description') if isinstance(source.get('localised_description'), str) else '',
            'stack_size': item.get('stack_size', 50), 'health': source.get('max_health', 100),
            'speed': source.get('mining_speed' if kind == 'mining-drill' else 'crafting_speed', 1),
            'power': source.get('energy_usage', '150kW'), 'energy_type': energy.get('type', 'electric'),
            'module_slots': source.get('module_slots', source.get('module_specification', {}).get('module_slots', 0)),
            'width': max(1, round(width)), 'height': max(1, round(height)), 'color': '#ffffff',
            'mining_radius': source.get('resource_searching_radius', 2.49), 'resource_categories': source.get('resource_categories', ['basic-solid']),
            'resource_drain': source.get('resource_drain_rate_percent', 100), 'recipes': importable_recipes(catalog, [(kind, name)]) if kind != 'mining-drill' else [],
            'advanced': {k: copy.deepcopy(v) for k, v in source.items() if k not in CONTROLLED},
            'item_name': item_name, 'icon': None, 'sprite': None, 'icon_path': '', 'sprite_path': ''}


def sprite_asset(path):
    from project import positive
    data = Path(path).read_bytes()
    if len(data) < 24 or data[:8] != b'\x89PNG\r\n\x1a\n':
        raise ValueError('The building sprite must be a PNG.')
    width, height = struct.unpack('>II', data[16:24])
    if not (1 <= width <= 4096 and 1 <= height <= 4096):
        raise ValueError('Building PNG dimensions must be between 1 and 4096 pixels.')
    return {'data': base64.b64encode(data).decode('ascii'), 'width': width, 'height': height}


def recipe_category(name):
    return 'recipe-studio-only-' + name


def validate_machine(name, machine, catalog, project):
    from project import identifier, positive
    identifier(name)
    editing = machine.get('operation') == 'edit'
    kind = machine_kind(machine)
    if editing and (name != machine['template'] or name not in catalog.raw.get(kind, {})):
        raise ValueError('Edit mode must keep the selected machine’s original ID.')
    if not editing and (('item', name) in catalog.items or ('fluid', name) in catalog.items or name in project.data['items']):
        raise ValueError('Machine ID already belongs to a loaded or custom item: ' + name)
    if not editing and name in catalog.recipes:
        raise ValueError('Machine ID already belongs to a recipe: ' + name)
    if not editing and any(name in group for group in catalog.raw.values()):
        raise ValueError('That prototype ID already exists. Choose a unique machine ID.')
    source = catalog.raw.get(kind, {}).get(machine['template'])
    if source is None:
        raise ValueError('Choose a loaded machine or mining-drill template.')
    if not isinstance(machine.get('advanced', {}), dict) or any(k in CONTROLLED for k in machine.get('advanced', {})):
        raise ValueError('Advanced stats must be a JSON object; identity and basic stats belong in their form fields.')
    for key in ('width', 'height'):
        size = positive(machine.get(key, round(dimensions(source)[0 if key == 'width' else 1])), 'Placed ' + key, True)
        if size > 64:
            raise ValueError('Placed dimensions cannot exceed 64 tiles.')
    if not re.fullmatch(r'#[0-9a-fA-F]{6}', machine.get('color', '#ffffff')):
        raise ValueError('Color must be a hex color, such as #77bbff.')
    for key in ('stack_size', 'health'):
        positive(machine[key], key.replace('_', ' ').title(), True)
    positive(machine['speed'], 'Crafting speed')
    if machine['energy_type'] not in ('electric', 'burner', source.get('energy_source', {}).get('type')):
        raise ValueError('Choose electric, burner, or the template’s original energy source.')
    power = re.fullmatch(r'([0-9]+(?:\.[0-9]+)?)([kMGT]?W)', machine['power'])
    if not power or float(power[1]) <= 0:
        raise ValueError('Power must be positive, for example 150kW or 1MW.')
    positive(power[1], 'Power usage')
    slots = machine.get('module_slots', 0)
    if int(slots) != slots or not 0 <= slots <= 64:
        raise ValueError('Module slots must be a whole number from 0 to 64.')
    if kind == 'mining-drill':
        categories = machine.get('resource_categories', source.get('resource_categories', []))
        if not categories or any(c not in catalog.raw.get('resource-category', {}) for c in categories):
            raise ValueError('Select valid resource categories for the mining drill.')
        positive(machine.get('mining_radius', source.get('resource_searching_radius', 1)), 'Mining radius')
        drain = float(machine.get('resource_drain', 100))
        if not 0 <= drain <= 100 or not drain.is_integer():
            raise ValueError('Resource drain must be a whole number between 0 and 100 percent.')
        return
    merged = project.merged_raw(catalog.raw, include_machines=False)
    recipes = merged.get('recipe', {})
    selected = machine.get('recipes', [])
    if not selected or len(selected) != len(set(selected)):
        raise ValueError('Select at least one recipe; do not repeat recipes.')
    boxes = source.get('fluid_boxes', [])
    if not isinstance(boxes, list):
        boxes = [v for v in boxes.values() if isinstance(v, dict) and 'production_type' in v]
    # Verify real pipe capacity, so selected recipes can actually run.
    for recipe_name in selected:
        if recipe_name not in recipes:
            raise ValueError('Unknown allowed recipe: ' + recipe_name)
        recipe = recipes[recipe_name]
        pool = list(boxes)
        for side, direction in [('ingredients', 'input'), ('results', 'output')]:
            fluids = [e for e in entries(recipe, side) if e['type'] == 'fluid']
            available = [box for box in pool if box.get('production_type', 'input-output') in (direction, 'input-output')]
            for fluid in sorted(fluids, key=lambda f: sum(not b.get('filter') or b['filter'] == f['name'] for b in available)):
                index = next((i for i, b in enumerate(available) if not b.get('filter') or b['filter'] == fluid['name']), None)
                if index is None:
                    raise ValueError(f"Template {machine['template']} has insufficient {direction} fluid ports for {recipe_name}. Choose a compatible template.")
                pool.remove(available.pop(index))


def prototypes(name, machine, raw):
    kind = machine_kind(machine)
    original = raw[kind][machine['template']]
    entity = copy.deepcopy(original)
    if 'advanced' in machine:
        for key in list(entity):
            if key not in CONTROLLED and key not in machine['advanced']:
                entity.pop(key)
        entity.update(copy.deepcopy(machine['advanced']))
    remove = ['placeable_by', 'icons', 'icon', 'icon_size']
    if machine.get('operation') != 'edit':
        remove += ['next_upgrade', 'fast_replaceable_group', 'fixed_recipe']
    for key in remove:
        entity.pop(key, None)
    icon = {k: copy.deepcopy(original[k]) for k in ('icon', 'icons', 'icon_size') if k in original}
    if machine.get('icon'):
        icon = {'icon': '__RECIPE_STUDIO_MOD__/graphics/machines/' + name + '-icon.png', 'icon_size': machine['icon']['size']}
    entity.update(icon)
    item_name = placed_item_name(name, machine)
    minable = copy.deepcopy(original.get('minable') or {})
    minable.pop('results', None)
    minable.update(mining_time=minable.get('mining_time', .2), result=item_name)
    entity.update(name=name, type=kind, localised_name=machine['title'], localised_description=machine.get('description', ''),
                  minable=minable, placeable_by={'item': item_name, 'count': 1},
                  flags=entity.get('flags', ['placeable-neutral', 'placeable-player', 'player-creation']), max_health=machine['health'],
                  energy_usage=machine['power'])
    if kind == 'mining-drill':
        entity.update(mining_speed=machine['speed'], resource_categories=machine.get('resource_categories', original.get('resource_categories', ['basic-solid'])), resource_searching_radius=machine.get('mining_radius', original.get('resource_searching_radius', 1)))
        if 'resource_drain_rate_percent' in original or machine.get('resource_drain', 100) != 100:
            entity['resource_drain_rate_percent'] = machine.get('resource_drain', 100)
    else:
        entity.update(crafting_speed=machine['speed'], crafting_categories=[recipe_category(n) for n in machine['recipes']])
        if kind == 'assembling-machine':
            entity['ingredient_count'] = 255
    if entity.get('energy_source', {}).get('type') != machine['energy_type']:
        entity['energy_source'] = {'type': 'electric', 'usage_priority': 'secondary-input'} if machine['energy_type'] == 'electric' else {'type': 'burner', 'fuel_categories': ['chemical'], 'fuel_inventory_size': 1, 'burnt_inventory_size': 1, 'effectivity': 1}
    if 'module_specification' in entity:
        entity['module_specification']['module_slots'] = machine.get('module_slots', 0)
    else:
        entity['module_slots'] = machine.get('module_slots', 0)
    width, height = dimensions(original)
    color = machine.get('color', '#ffffff')
    rgba = [int(color[i:i+2], 16) / 255 for i in (1, 3, 5)] + [1]
    resize_entity(entity, machine.get('width', round(width)), machine.get('height', round(height)), width, height, rgba)
    if machine.get('sprite'):
        asset = machine['sprite']
        animation = {'filename': '__RECIPE_STUDIO_MOD__/graphics/machines/' + name + '-building.png', 'width': asset['width'], 'height': asset['height'], 'frame_count': 1, 'scale': min(machine.get('width', width) * 32 / asset['width'], machine.get('height', height) * 32 / asset['height']), 'tint': rgba}
        if 'graphics_set' in entity:
            entity['graphics_set'] = {'animation': animation}
        else:
            entity['animation'] = animation
            entity.pop('working_visualisations', None)
    item = copy.deepcopy(raw.get('item', {}).get(item_name, {})) if machine.get('operation') == 'edit' else {}
    item.update({'type': item.get('type', 'item'), 'name': item_name, 'localised_name': machine['title'], 'localised_description': machine.get('description', ''),
            'subgroup': 'production-machine', 'order': 'z[' + name + ']', 'stack_size': machine['stack_size'], 'place_result': name, **icon}
    )
    return entity, item


def apply_machines(raw, machines):
    templates = dict(raw)
    templates.update(copy.deepcopy({kind: raw.get(kind, {}) for kind in MACHINE_TYPES}))
    templates['item'] = copy.deepcopy(raw.get('item', {}))
    for name, machine in machines.items():
        entity, item = prototypes(name, machine, templates)
        raw.setdefault('item', {})[item['name']] = item
        raw.setdefault(machine_kind(machine), {})[name] = entity
    for kind in MACHINE_TYPES:
        for entity in raw.get(kind, {}).values():
            target = raw.get(kind, {}).get(entity.get('next_upgrade'))
            if target and entity.get('collision_box') != target.get('collision_box'):
                entity.pop('next_upgrade', None)
    for recipe_name in sorted({r for m in machines.values() for r in m['recipes']}):
        recipe = raw.get('recipe', {}).get(recipe_name)
        if recipe is None:
            continue
        old_category = recipe.get('category', 'crafting')
        category = recipe_category(recipe_name)
        raw.setdefault('recipe-category', {})[category] = {'type': 'recipe-category', 'name': category}
        recipe['category'] = category
        for kind in ('assembling-machine', 'furnace', 'character', 'rocket-silo'):
            for name, entity in raw.get(kind, {}).items():
                if name not in machines and old_category in entity.get('crafting_categories', []):
                    if category not in entity['crafting_categories']:
                        entity['crafting_categories'].append(category)


def compile_machines(project, catalog):
    assets, code = {}, []
    machines = project.data['machines']
    raw = project.merged_raw(catalog.raw, include_machines=False)
    snapshots = ['do', 'local studio_templates = {}']
    for kind, template in sorted({(machine_kind(m), m['template']) for m in machines.values()}):
        snapshots.append('studio_templates[' + lua(kind + '/' + template) + '] = table.deepcopy(assert(data.raw[' + lua(kind) + '][' + lua(template) + ']))')
    for name, machine in machines.items():
        validate_machine(name, machine, catalog, project)
        entity, item = prototypes(name, machine, raw)
        # Clone the engine's actual template at mod load time, rather than
        # serializing its graphics, sounds and circuit connector definitions.
        source = raw[machine_kind(machine)][machine['template']]
        overrides = {k: v for k, v in entity.items() if k not in source or v != source[k]}
        lines = ['do', 'local entity = table.deepcopy(studio_templates[' + lua(machine_kind(machine) + '/' + machine['template']) + '])']
        for key in (set(source) - set(entity)) | {'placeable_by', 'icons', 'icon', 'icon_size'}:
            lines.append('entity[' + lua(key) + '] = nil')
        # Icon fields are re-applied even when unchanged from the source.
        overrides.update({k: entity[k] for k in ('icon', 'icons', 'icon_size') if k in entity})
        overrides.update({k: entity[k] for k in ('placeable_by',) if k in entity})
        for key, value in overrides.items():
            lines.append('entity[' + lua(key) + '] = ' + lua(value))
        lines += ['data:extend({entity, ' + lua(item) + '})', 'end']
        code.append('\n'.join(lines))
        for key, suffix in [('icon', '-icon.png'), ('sprite', '-building.png')]:
            if machine.get(key):
                assets['graphics/machines/' + name + suffix] = base64.b64decode(machine[key]['data'], validate=True)
    # One category per recipe gives each new machine exactly its selected list.
    # Extend original producers so their existing recipes remain craftable.
    custom_names = {name: True for name in machines}
    code.append('''do
local function equal_box(a,b)
  if not a or not b then return a == b end
  for i=1,2 do
    if (a[i].x or a[i][1]) ~= (b[i].x or b[i][1]) or (a[i].y or a[i][2]) ~= (b[i].y or b[i][2]) then return false end
  end
  return true
end
for _, kind in ipairs({"assembling-machine","furnace","mining-drill","rocket-silo"}) do
  for _, entity in pairs(data.raw[kind] or {}) do
    local target = entity.next_upgrade and data.raw[kind][entity.next_upgrade]
    if target and not equal_box(entity.collision_box, target.collision_box) then entity.next_upgrade = nil end
  end
end
end''')
    for name in sorted({r for m in machines.values() for r in m['recipes']}):
        category = recipe_category(name)
        code.append('\n'.join(['do', 'local recipe = assert(data.raw.recipe[' + lua(name) + '])',
                               'local old = recipe.category or "crafting"',
                               'local category = ' + lua(category),
                               'data:extend({{type="recipe-category", name=category}})',
                               'local custom = ' + lua(custom_names),
                               'for _, kind in ipairs({"assembling-machine", "furnace", "character", "rocket-silo"}) do',
                               '  for entity_name, entity in pairs(data.raw[kind] or {}) do',
                               '    if not custom[entity_name] then',
                               '      local compatible = false',
                               '      for _, value in pairs(entity.crafting_categories or {}) do if value == old then compatible = true end end',
                               '      if compatible then',
                               '        local found = false',
                               '        for _, value in pairs(entity.crafting_categories) do if value == category then found = true end end',
                               '        if not found then table.insert(entity.crafting_categories, category) end',
                               '      end', '    end', '  end', 'end', 'recipe.category = category', 'end']))
    return '\n'.join(snapshots) + '\n' + '\n\n'.join(code) + '\nend', assets


def importable_recipes(catalog, selected_machines):
    """Union the actual category/fixed-recipe capabilities of loaded producers."""
    result = set()
    for kind, name in selected_machines:
        producer = catalog.raw.get(kind, {}).get(name)
        if producer is None:
            raise ValueError('Unknown machine: ' + name)
        fixed = producer.get('fixed_recipe')
        if fixed:
            if fixed in catalog.recipes:
                result.add(fixed)
            continue
        categories = set(producer.get('crafting_categories', []))
        for recipe_name, recipe in catalog.recipes.items():
            source = recipe.get('normal', recipe)
            recipe_categories = recipe.get('categories', [source.get('category', recipe.get('category', 'crafting'))])
            if not categories.intersection(recipe_categories):
                continue
            if len(entries(recipe, 'ingredients')) > producer.get('ingredient_count', 255):
                continue
            if kind == 'furnace' and sum(e['type'] == 'item' for e in entries(recipe, 'ingredients')) > producer.get('source_inventory_size', 1):
                continue
            # Reuse the same real pipe/filter checks as machine validation.
            boxes = producer.get('fluid_boxes', [])
            boxes = list(boxes) if isinstance(boxes, list) else [v for v in boxes.values() if isinstance(v, dict)]
            compatible = True
            for side, direction in [('ingredients', 'input'), ('results', 'output')]:
                fluids = [e for e in entries(recipe, side) if e['type'] == 'fluid']
                for fluid in fluids:
                    index = next((i for i, b in enumerate(boxes) if b.get('production_type', 'input-output') in (direction, 'input-output') and (not b.get('filter') or b['filter'] == fluid['name'])), None)
                    if index is None:
                        compatible = False
                        break
                    boxes.pop(index)
                if not compatible:
                    break
            if compatible:
                result.add(recipe_name)
    return sorted(result)
