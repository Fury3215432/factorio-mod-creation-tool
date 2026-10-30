"""Resize actual entity footprints, graphics, ports and mining output offsets."""
import copy
import math


def dimensions(entity):
    box = entity.get('selection_box', [[-1.5, -1.5], [1.5, 1.5]])
    return box[1][0] - box[0][0], box[1][1] - box[0][1]


def tint_preview(image, color):
    """Tint only the in-app preview, preserving its transparent pixels."""
    if color.lower() == '#ffffff':
        return image
    rgb = [int(color[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    result = image.copy()
    for y in range(image.height()):
        for x in range(image.width()):
            if not image.transparency_get(x, y):
                pixel = image.get(x, y)
                result.put('#%02x%02x%02x' % tuple(round(pixel[i] * rgb[i]) for i in range(3)), (x, y))
    return result


def transform_graphics(value, factor, color):
    if isinstance(value, list):
        for child in value:
            transform_graphics(child, factor, color)
    elif isinstance(value, dict):
        if any(key in value for key in ('filename', 'filenames', 'stripes')) and ('width' in value or 'size' in value or 'stripes' in value):
            value['scale'] = value.get('scale', 1) * factor
            shift = value.get('shift')
            if isinstance(shift, list):
                value['shift'] = [x * factor for x in shift]
            elif isinstance(shift, dict):
                value['shift'] = {k: v * factor for k, v in shift.items()}
            if color != [1, 1, 1, 1] and not value.get('draw_as_shadow'):
                original = value.get('tint', [1, 1, 1, 1])
                if isinstance(original, dict):
                    original = [original.get(c, 1) for c in ('r', 'g', 'b', 'a')]
                value['tint'] = [original[i] * color[i] if i < len(original) else color[i] for i in range(4)]
        for child in value.values():
            if isinstance(child, (dict, list)):
                transform_graphics(child, factor, color)


def resize_entity(entity, width, height, original_width, original_height, color):
    sx, sy = width / original_width, height / original_height
    entity['selection_box'] = [[-width / 2, -height / 2], [width / 2, height / 2]]
    old_box = entity.get('collision_box', [[-original_width / 2 + .2, -original_height / 2 + .2], [original_width / 2 - .2, original_height / 2 - .2]])
    margin_x = max(.01, original_width / 2 - max(abs(old_box[0][0]), abs(old_box[1][0])))
    margin_y = max(.01, original_height / 2 - max(abs(old_box[0][1]), abs(old_box[1][1])))
    entity['collision_box'] = [[-max(.05, width / 2 - margin_x), -max(.05, height / 2 - margin_y)], [max(.05, width / 2 - margin_x), max(.05, height / 2 - margin_y)]]
    entity['tile_width'], entity['tile_height'] = width, height
    factor = min(sx, sy)
    for key in ('graphics_set', 'wet_mining_graphics_set', 'animation', 'animations', 'pictures', 'picture', 'base_picture', 'working_visualisations', 'idle_animation'):
        if key in entity:
            transform_graphics(entity[key], factor, color)
    def port(position):
        if not isinstance(position, list) or len(position) != 2:
            return position
        result = []
        for v, old_size, new_size in zip(position, (original_width, original_height), (width, height)):
            if abs(v) >= old_size / 2 - .51 and v != 0:
                result.append(math.copysign((new_size - 1) / 2, v))
            else:
                offset = .5 if int(new_size) % 2 == 0 else 0
                scaled = v * new_size / old_size
                result.append(round(scaled - offset) + offset)
        return result
    if width != original_width or height != original_height:
        def pipes(value):
            if isinstance(value, list):
                for child in value:
                    pipes(child)
            elif isinstance(value, dict):
                for connection in value.get('pipe_connections', []):
                    if 'position' in connection:
                        connection['position'] = port(connection['position'])
                    if 'positions' in connection:
                        connection['positions'] = [port(p) for p in connection['positions']]
                for key, child in value.items():
                    if key != 'pipe_connections' and isinstance(child, (dict, list)):
                        pipes(child)
        for key in ('fluid_boxes', 'input_fluid_box', 'output_fluid_box', 'fluid_box'):
            if key in entity:
                pipes(entity[key])
        if isinstance(entity.get('vector_to_place_result'), list):
            entity['vector_to_place_result'] = [entity['vector_to_place_result'][0] * sx, entity['vector_to_place_result'][1] * sy]
