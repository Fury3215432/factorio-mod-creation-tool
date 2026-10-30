"""Lay out several dependency recipes on one navigable canvas."""
import tkinter.font as tkfont

from core import Recipe
from flow import select_event

BG, CARD, TEXT, GOLD = '#171c24', '#273240', '#e6edf3', '#e9aa52'


def draw_recipes(tab):
    app, canvas = tab.app, tab.canvas
    active = {}

    def build(recipe, path, name, ancestors):
        children, slots = {}, []
        for index, entry in enumerate(recipe.ingredients):
            child_path = path + (index,)
            saved = tab.expanded_recipes.get(child_path)
            if saved and tuple(saved['key']) == (entry['type'], entry['name']) and saved['name'] in app.catalog.recipes and saved['name'] not in ancestors:
                child_name = saved['name']
                child_recipe = app.project.recipe(child_name) if child_name in app.project.data['recipes'] else Recipe(child_name, app.catalog.recipes[child_name])
                if not any((e['type'], e['name']) == (entry['type'], entry['name']) for e in child_recipe.results):
                    slots.append(120)
                    continue
                child = build(child_recipe, child_path, child_name, ancestors | {child_name})
                children[index] = child
                active[child_path] = saved
            slots.append(max(120, children[index]['height'] if index in children else 120))
        body = max(sum(slots), len(recipe.results) * 120, 260)
        return dict(recipe=recipe, path=path, name=name, children=children, slots=slots, height=body + 100, body=body)

    root_name = tab.loaded_name or tab.name.get()
    root = build(tab.recipe, (), root_name, {root_name})
    tab.expanded_recipes = active
    max_depth = max((len(path) for path in active), default=0)
    width, height = (max_depth + 1) * 1040, max(460, root['height'])
    tab.graph_width = width
    canvas.delete('all')
    tab.flow_images = []
    tab.graph_nodes = {}
    links = []

    def node(value, side, index, path, x, cy):
        tag = f'{side}_{index}' if not path else 'branch:' + '.'.join(map(str, path)) + f':{side}:{index}'
        tab.graph_nodes[tag] = dict(path=path, side=side, index=index, value=value)
        canvas.create_rectangle(x, cy - 44, x + 260, cy + 44, fill=CARD, outline='#4b6075', width=2, tags=tag)
        picture = app.icon((value['type'], value['name']), size=48 * tab.zoom)
        if picture:
            tab.flow_images.append(picture)
            canvas.create_image(x + 40, cy, image=picture, tags=tag)
        else:
            canvas.create_text(x + 40, cy, text='◈', fill=GOLD, font=('Segoe UI', 28), tags=tag)
        canvas.create_text(x + 78, cy - 19, text=value['name'].replace('-', ' '), width=175, anchor='w', fill=TEXT, font=('Segoe UI', 10, 'bold'), tags=tag)
        amount = value.get('amount', f"{value.get('amount_min', '?')}–{value.get('amount_max', '?')}")
        probability = f" · {value['probability']:g} chance" if 'probability' in value else ''
        canvas.create_text(x + 78, cy + 18, text=f'× {amount}{probability}', anchor='w', fill=GOLD, font=('Segoe UI', 11), tags=tag)
        if not path:
            canvas.tag_bind(tag, select_event(tab), lambda e, s=side, i=index: tab.edit(s, i))
        else:
            canvas.tag_bind(tag, select_event(tab), lambda e, p=path: tab.edit_expanded_recipe(p))
        return x, cy, x + 260

    def draw(group, y):
        recipe, path = group['recipe'], group['path']
        x = (max_depth - len(path)) * 1040
        cy = y + 80 + group['body'] / 2
        color = GOLD if not path else '#7cc6db'
        title_tag = 'recipe-title:' + '.'.join(map(str, path))
        tab.graph_nodes[title_tag] = dict(path=path, side=None)
        canvas.create_text(x + 520, y + 23, text=('MAIN RECIPE · ' if not path else 'RECIPE · ') + group['name'], fill=color, font=('Segoe UI', 12, 'bold'), tags=title_tag)
        canvas.create_text(x + 190, y + 55, text='INGREDIENTS', fill=color, font=('Segoe UI', 11, 'bold'))
        canvas.create_text(x + 820, y + 55, text='PRODUCTS', fill=color, font=('Segoe UI', 11, 'bold'))
        craft_tag = 'craft:' + '.'.join(map(str, path))
        tab.graph_nodes[craft_tag] = dict(path=path, side=None)
        canvas.create_rectangle(x + 444, cy - 42, x + 596, cy + 42, fill='#364352', outline=color, width=2, tags=craft_tag)
        source = recipe.original.get('normal', recipe.original)
        seconds = tab.seconds.get() if not path else app.project.data['recipes'].get(group['name'], {}).get('seconds', source.get('energy_required', .5))
        canvas.create_text(x + 520, cy, text='CRAFT\n' + str(seconds) + ' seconds', fill=TEXT, font=('Segoe UI', 12), justify='center', tags=craft_tag)
        if path:
            for tag in (craft_tag, title_tag):
                canvas.tag_bind(tag, select_event(tab), lambda e, p=path: tab.edit_expanded_recipe(p))
        start = y + 80 + (group['body'] - sum(group['slots'])) / 2
        for index, (entry, slot) in enumerate(zip(recipe.ingredients, group['slots'])):
            iy = start + slot / 2
            node(entry, 'ingredients', index, path, x + 60, iy)
            canvas.create_line(x + 320, iy, x + 390, iy, x + 390, cy, x + 444, cy, fill='#687b91', width=2, arrow='last')
            if index in group['children']:
                child = group['children'][index]
                child_products = draw(child, start + (slot - child['height']) / 2)
                matching = child_products.get((entry['type'], entry['name']))
                if matching:
                    links.append((matching[2], matching[1], x + 60, iy))
            start += slot
        products = {}
        for index, entry in enumerate(recipe.results):
            ry = cy + (index - (len(recipe.results) - 1) / 2) * 120
            coords = node(entry, 'results', index, path, x + 690, ry)
            products[(entry['type'], entry['name'])] = coords
            canvas.create_line(x + 596, cy, x + 640, cy, x + 640, ry, x + 690, ry, fill=color, width=2, arrow='last')
        return products

    draw(root, 0)
    for x1, y1, x2, y2 in links:
        canvas.create_line(x1, y1, (x1 + x2) / 2, y1, (x1 + x2) / 2, y2, x2, y2, fill='#7cc6db', width=3, arrow='last', tags='recipe-link')
    canvas.tag_lower('recipe-link')
    canvas.scale('all', 0, 0, tab.zoom, tab.zoom)
    for item in canvas.find_all():
        if canvas.type(item) == 'text':
            font = tkfont.Font(font=canvas.itemcget(item, 'font'))
            canvas.itemconfigure(item, font=(font.actual('family'), max(5, round(font.actual('size') * tab.zoom)), font.actual('weight')))
            wrap = float(canvas.itemcget(item, 'width'))
            if wrap:
                canvas.itemconfigure(item, width=wrap * tab.zoom)
    canvas.configure(scrollregion=(0, 0, width * tab.zoom, height * tab.zoom))
