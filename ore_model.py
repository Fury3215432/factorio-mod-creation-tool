"""Solid ore resources and their map-generation controls."""
import copy
import re

from core import entries, lua
from project import identifier, positive
from machine_geometry import transform_graphics


def templates(raw):
    return sorted(name for name, proto in raw.get('resource', {}).items()
                  if not proto.get('infinite') and proto.get('stages')
                  and any(e['type'] == 'item' for e in entries(proto.get('minable', {}), 'results')))


def resource(name, item, raw, icon):
    identifier(name)
    if name in raw.get('resource', {}):
        raise ValueError('That resource ID already exists in the loaded game.')
    source = item.get('ore_template', 'iron-ore')
    if source not in templates(raw):
        raise ValueError('Choose a loaded solid ore template.')
    color = item.get('ore_color', '#ffffff')
    if not re.fullmatch(r'#[0-9a-fA-F]{6}', color):
        raise ValueError('Ore color must be a hex color, such as #bb66ff.')
    tint = dict(zip(('r', 'g', 'b'), [int(color[i:i + 2], 16) / 255 for i in (1, 3, 5)]))
    proto = copy.deepcopy(raw['resource'][source])
    for field in ('icons', 'autoplace', 'factoriopedia_simulation', 'infinite', 'minimum', 'normal', 'infinite_depletion_amount'):
        proto.pop(field, None)
    proto.update(name=name, localised_name=item['title'], localised_description=item.get('description', ''),
                 icon=icon['icon'], icon_size=icon['icon_size'], category='basic-solid',
                 minable={'mining_time': positive(item.get('mining_time', 1), 'Mining seconds'),
                          'results': [{'type': 'item', 'name': name, 'amount': positive(item.get('mining_amount', 1), 'Mining yield', True)}]},
                 map_color=tint, mining_visualisation_tint=tint)
    transform_graphics(proto['stages'], 1, list(tint.values()) + [1])
    positive(item.get('ore_density', 10), 'Ore density')
    return proto


def control(name, item):
    return {'type': 'autoplace-control', 'name': name, 'localised_name': item['title'], 'category': 'resource', 'richness': True, 'order': 'z[' + name + ']'}


def apply(raw, name, item, prototype):
    raw.setdefault('resource', {})[name] = prototype
    if item.get('ore_autoplace', True):
        raw.setdefault('autoplace-control', {})[name] = control(name, item)
        planet = raw.get('planet', {}).get('nauvis')
        if planet:
            settings = planet.setdefault('map_gen_settings', {})
            settings.setdefault('autoplace_controls', {})[name] = {}
            settings.setdefault('autoplace_settings', {}).setdefault('entity', {}).setdefault('settings', {})[name] = {}


def compile_resource(name, item, prototype):
    lines = ['do', 'local ore = ' + lua(prototype)]
    if item.get('ore_autoplace', True):
        parameters = {'name': name, 'order': 'b', 'base_density': item.get('ore_density', 10),
                      'has_starting_area_placement': bool(item.get('ore_starting_area', True)),
                      'regular_rq_factor_multiplier': 1.1, 'starting_rq_factor_multiplier': 1.5}
        lines += ['data:extend({' + lua(control(name, item)) + '})',
                  'local resource_autoplace = require("resource-autoplace")',
                  'resource_autoplace.initialize_patch_set(' + lua(name) + ', ' + lua(parameters['has_starting_area_placement']) + ')',
                  'ore.autoplace = resource_autoplace.resource_autoplace_settings(' + lua(parameters) + ')',
                  'local nauvis = data.raw.planet and data.raw.planet.nauvis',
                  'if nauvis then',
                  '  local settings = nauvis.map_gen_settings or {}; nauvis.map_gen_settings = settings',
                  '  settings.autoplace_controls = settings.autoplace_controls or {}',
                  '  settings.autoplace_controls[' + lua(name) + '] = {}',
                  '  settings.autoplace_settings = settings.autoplace_settings or {}',
                  '  settings.autoplace_settings.entity = settings.autoplace_settings.entity or {}',
                  '  settings.autoplace_settings.entity.settings = settings.autoplace_settings.entity.settings or {}',
                  '  settings.autoplace_settings.entity.settings[' + lua(name) + '] = {}', 'end']
    lines += ['data:extend({ore})', 'end']
    return '\n'.join(lines)
