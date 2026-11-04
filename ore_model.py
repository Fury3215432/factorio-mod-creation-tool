"""Solid ore resources and their map-generation controls."""
import base64
from pathlib import Path
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
    source = item.get('ore_template')
    if source and source not in templates(raw):
        raise ValueError('Missing original ore template: ' + source)
    color = item.get('ore_color', '#ffffff')
    if not re.fullmatch(r'#[0-9a-fA-F]{6}', color):
        raise ValueError('Ore color must be a hex color, such as #bb66ff.')
    tint = dict(zip(('r', 'g', 'b'), [int(color[i:i + 2], 16) / 255 for i in (1, 3, 5)]))
    proto = copy.deepcopy(raw['resource'][source]) if source else {
        'type': 'resource', 'flags': ['placeable-neutral'],
        'collision_box': [[-.1, -.1], [.1, .1]], 'selection_box': [[-.5, -.5], [.5, .5]]}
    for field in ('icons', 'autoplace', 'factoriopedia_simulation', 'infinite', 'minimum', 'normal', 'infinite_depletion_amount'):
        proto.pop(field, None)
    proto.update(name=name, localised_name=item['title'], localised_description=item.get('description', ''),
                 icon=icon['icon'], icon_size=icon['icon_size'], category='basic-solid',
                 minable={'mining_time': positive(item.get('mining_time', 1), 'Mining seconds'),
                          'results': [{'type': 'item', 'name': name, 'amount': positive(item.get('mining_amount', 1), 'Mining yield', True)}]},
                 map_color=tint, mining_visualisation_tint=tint)
    if not source or item.get('ore_graphics'):
        asset = item.get('ore_graphics') or item.get('icon')
        if not asset:
            from project import default_icon_asset
            asset = default_icon_asset()
        full_width, full_height = asset.get('width', asset.get('size')), asset.get('height', asset.get('size'))
        counts = item.get('ore_stage_counts', [0])
        if not counts or any(not isinstance(n, int) or n < 0 for n in counts) or counts != sorted(set(counts), reverse=True):
            raise ValueError('Ore stage amounts must be unique, descending whole numbers, ending with 0.')
        if counts[-1] != 0:
            raise ValueError('The final ore stage amount must be 0.')
        variations = positive(item.get('ore_variations', 1), 'Ore variations', True)
        stages = len(counts)
        width = positive(item.get('ore_frame_width') or full_width / stages, 'Ore frame width', True)
        height = positive(item.get('ore_frame_height') or full_height / variations, 'Ore frame height', True)
        if width * stages > full_width or height * variations > full_height:
            raise ValueError('Ore frames do not fit the graphics PNG: depletion stages run across columns and variations down rows.')
        scale = positive(item.get('ore_graphics_scale', 1), 'Ore graphics scale')
        proto['stage_counts'] = counts
        proto['stages'] = {'sheet': {'filename': '__RECIPE_STUDIO_MOD__/graphics/ores/' + name + '.png',
                          'width': width, 'height': height, 'frame_count': stages, 'variation_count': variations, 'scale': 32 / width * scale}}
    transform_graphics(proto['stages'], 1, list(tint.values()) + [1])
    volume = float(item.get('ore_sound_volume', .7))
    if not 0 <= volume <= 1:
        raise ValueError('Ore sound volume must be between 0 and 1.')
    for sound in ('mining', 'mined', 'walking'):
        asset = item.get('ore_' + sound + '_sound')
        if asset:
            proto[sound + '_sound'] = {'filename': '__RECIPE_STUDIO_MOD__/sound/ores/' + name + '-' + sound + asset['extension'], 'volume': volume}

    positive(item.get('ore_density', 10), 'Ore density')
    return proto


def sound_asset(path):
    path = Path(path)
    data = path.read_bytes()
    extension = path.suffix.lower()
    if len(data) > 20 * 1024 * 1024 or not ((extension == '.ogg' and data.startswith(b'OggS')) or
        (extension == '.wav' and data.startswith(b'RIFF') and data[8:12] == b'WAVE')):
        raise ValueError('Choose an OGG or WAV audio file, up to 20 MB.')
    return {'data': base64.b64encode(data).decode('ascii'), 'extension': extension}


def resource_assets(name, item):
    result = {}
    if not item.get('ore_template') or item.get('ore_graphics'):
        from project import default_icon_asset
        asset = item.get('ore_graphics') or item.get('icon') or default_icon_asset()
        result['graphics/ores/' + name + '.png'] = base64.b64decode(asset['data'], validate=True)
    for sound in ('mining', 'mined', 'walking'):
        asset = item.get('ore_' + sound + '_sound')
        if asset:
            if asset['extension'] not in ('.ogg', '.wav'):
                raise ValueError('Unsupported ore sound format.')
            result['sound/ores/' + name + '-' + sound + asset['extension']] = base64.b64decode(asset['data'], validate=True)
    return result


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
