"""Factorio-style technology tiles and an in-tab editor sidebar."""
import tkinter as tk
from collections import defaultdict, deque
from tkinter import messagebox, ttk

from flow import bind_navigation, prototype_image, zoom_at, select_event
from ui import help_label
from controls import MODIFIERS

BG, TEXT, GOLD = '#292a27', '#e7e1d4', '#e9c577'


class TechTab(ttk.Frame):
    def __init__(self, app):
        super().__init__(app.tabs)
        self.app = app
        self.dirty = False
        self.zoom = 0.85
        self.positions = {}
        self.selected = None
        self.multi_selected = set()
        self.editor_frame = None
        self.editor_save = None
        self.query = tk.StringVar()
        self.images = []
        self.rendered_nodes = {}
        self.rendered_edges = {}
        self.render_serial = 0
        self.render_job = None
        self.initial_job = None
        self.scene_zoom = None
        self.region = None
        self.node_click_binding = None
        self.layout_key = None
        self.icon_tasks = deque()
        self.image_job = None
        self.relation_key = object()
        self.relation_sets = (set(), set())
        bar = ttk.Frame(self, padding=10)
        bar.pack(fill='x')
        ttk.Label(bar, text='TECHNOLOGY TREE', foreground=GOLD, font=('Segoe UI', 11, 'bold')).pack(side='left', padx=(0, 16))
        search = ttk.Frame(bar)
        search.pack(side='left')
        self.tree_search_entry = ttk.Entry(search, textvariable=self.query, width=23)
        self.tree_search_entry.pack(fill='x')
        help_label(search, 'Filters tree names and prerequisites.', wraplength=200, padx=0)
        ttk.Button(bar, text='Search', command=lambda: self.refresh(reset_view=True)).pack(side='left', padx=4)
        ttk.Button(bar, text='Show all', command=self.show_all).pack(side='left')
        ttk.Button(bar, text='+ New technology', command=lambda: self.edit()).pack(side='left', padx=4)
        ttk.Button(bar, text='−', width=2, command=lambda: self.set_zoom(1 / 1.15)).pack(side='left', padx=(12, 0))
        self.zoom_label = tk.StringVar()
        ttk.Label(bar, textvariable=self.zoom_label, width=6, anchor='center').pack(side='left')
        ttk.Button(bar, text='+', width=2, command=lambda: self.set_zoom(1.15)).pack(side='left')
        bulk_bar = ttk.Frame(self, padding=(10, 0, 10, 6))
        bulk_bar.pack(fill='x')
        ttk.Button(bulk_bar, text='Select all shown', command=self.select_all_shown).pack(side='left')
        ttk.Button(bulk_bar, text='Clear selection', command=self.clear_selection).pack(side='left', padx=6)
        self.bulk_button = ttk.Button(bulk_bar, text='Add / remove science packs', command=self.bulk_science_dialog)
        self.bulk_button.pack(side='left')
        self.selection_text = tk.StringVar(value='0 selected · Ctrl-click technologies to select several')
        ttk.Label(bulk_bar, textvariable=self.selection_text).pack(side='left', padx=12)
        split = tk.PanedWindow(self, orient='horizontal', sashwidth=6, bg='#151613', borderwidth=0)
        split.pack(fill='both', expand=True)
        self.sidebar = ttk.Frame(split, width=430)
        split.add(self.sidebar, minsize=340, width=430, stretch='never')
        self.editor_host = ttk.Frame(self.sidebar)
        ttk.Label(self.editor_host, text='Select a technology', font=('Segoe UI', 16, 'bold'), padding=16).pack(anchor='w')
        ttk.Label(self.editor_host, text='Select a technology in the tree.\nResearch settings and properties open here.', padding=16).pack(anchor='w')
        self.editor_host.pack(fill='both', expand=True)
        holder = ttk.Frame(split)
        split.add(holder, minsize=300, stretch='always')
        legend = ttk.Frame(holder, padding=(12, 6))
        legend.pack(fill='x')
        for label, color in [('Prerequisites', '#66be77'), ('Selected', GOLD), ('Dependents', '#df7770'), ('Other', '#aaa892')]:
            ttk.Label(legend, text='■ ' + label, foreground=color).pack(side='left', padx=(0, 16))
        self.canvas = tk.Canvas(holder, bg='#343426', highlightthickness=0)
        ybar = ttk.Scrollbar(holder, orient='vertical', command=self.canvas.yview)
        xbar = ttk.Scrollbar(holder, orient='horizontal', command=self.canvas.xview)
        def scrolled(bar, first, last):
            bar.set(first, last)
            self.view_changed()
        self.canvas.configure(xscrollcommand=lambda a, b: scrolled(xbar, a, b), yscrollcommand=lambda a, b: scrolled(ybar, a, b))
        ybar.pack(side='right', fill='y')
        xbar.pack(side='bottom', fill='x')
        self.canvas.pack(fill='both', expand=True)
        self.canvas.bind('<Button-3>', self.context)
        self.canvas.bind('<Configure>', lambda e: self.view_changed())
        self.canvas.tag_bind('technology-node', '<Enter>', self.node_hover)
        bind_navigation(self, self.draw)
        self.count = tk.StringVar()
        ttk.Label(self, textvariable=self.count, padding=(12, 5)).pack(anchor='w')
        ttk.Label(self, text='Drag empty space to pan · See Settings → Keyboard for shortcuts and mouse controls', padding=(12, 0, 12, 8)).pack(anchor='w')
        self.refresh()
        if 'automation' in self.technologies:
            self.initial_job = self.after_idle(self.select_initial)

    def select_initial(self):
        self.initial_job = None
        if self.editor_frame is None:
            self.edit('automation')

    def view_changed(self):
        if self.render_job is None:
            self.render_job = self.after(16, self.draw)

    def node_name(self):
        return next((tag[5:] for tag in self.canvas.gettags('current') if tag.startswith('tech:')), None)

    def node_hover(self, event):
        name = self.node_name()
        if name:
            self.count.set(name + ' · click to edit in the left panel')

    def node_click(self, event):
        name = self.node_name()
        if name:
            if event.state & MODIFIERS.get(self.app.controls.get('multi_select_modifier', 'Ctrl'), 4):
                self.multi_selected.symmetric_difference_update({name})
                self.update_selection()
                self.draw()
            else:
                self.edit(name)

    def update_selection(self):
        modifier = self.app.controls.get('multi_select_modifier', 'Ctrl')
        self.selection_text.set(f'{len(self.multi_selected)} selected · {modifier}-click to add/remove technologies')
        self.bulk_button.configure(state='normal' if self.multi_selected else 'disabled')

    def select_all_shown(self):
        self.multi_selected = set(self.positions)
        self.update_selection()
        self.draw()

    def clear_selection(self):
        self.multi_selected.clear()
        self.update_selection()
        self.draw()

    def bulk_science_dialog(self):
        from bulk_science import science_dialog
        return science_dialog(self)

    def destroy(self):
        for job in (self.render_job, self.initial_job, self.image_job):
            if job is not None:
                self.after_cancel(job)
        self.render_job = self.initial_job = self.image_job = None
        super().destroy()

    def queue_icon(self, item, loader, references, owner, placeholder=None):
        self.icon_tasks.append((item, loader, references, placeholder, owner))
        if self.image_job is None:
            self.image_job = self.after(1, self.load_next_icon)

    def load_next_icon(self):
        self.image_job = None
        # Decode at most one icon per event-loop turn. Keep input and paint
        # events responsive even when modded technology PNGs are expensive.
        while self.icon_tasks:
            item, loader, references, placeholder, (name, serial) = self.icon_tasks.popleft()
            node = self.rendered_nodes.get(name)
            if node is None or node[2] != serial:
                continue
            image = loader()
            if image:
                references.append(image)
                self.canvas.itemconfigure(item, image=image)
                if placeholder:
                    self.canvas.delete(placeholder)
            break
        if self.icon_tasks:
            self.image_job = self.after(1, self.load_next_icon)

    def close(self):
        if self.confirm_switch():
            self.destroy()

    def confirm_switch(self):
        if not self.dirty:
            return True
        answer = messagebox.askyesnocancel('Unsaved technology', 'Save your technology changes before switching?', parent=self)
        if answer is None:
            return False
        return self.save_changes() if answer else True

    def save_changes(self, quiet=False):
        return bool(self.editor_save()) if self.editor_save else True

    def snapshot(self):
        return {'selected': self.selected, 'values': {k: v.get() for k, v in self.editor_vars.items()},
                'json': self.editor_text.get('1.0', 'end-1c'), 'dirty': self.dirty, 'multi_selected': set(self.multi_selected)}

    def restore(self, state):
        from editors import technology_dialog
        technology_dialog(self, state['selected'], force=True)
        self.editor_tracking = False
        for key, value in state['values'].items():
            self.editor_vars[key].set(value)
        self.editor_text.delete('1.0', 'end')
        self.editor_text.insert('1.0', state['json'])
        self.editor_text.edit_modified(False)
        self.dirty = state['dirty']
        self.multi_selected = set(state.get('multi_selected', []))
        self.update_selection()
        self.draw()
        self.editor_tracking = True
        self.last_editor_state = self.snapshot()

    def context(self, event):
        if self.canvas.find_withtag('current'):
            return
        menu = tk.Menu(self, tearoff=False)
        menu.add_command(label='Create new technology', command=lambda: self.edit())
        menu.tk_popup(event.x_root, event.y_root)

    def show_all(self):
        self.query.set('')
        self.refresh(reset_view=True)

    def set_zoom(self, factor, x=None, y=None):
        zoom_at(self, factor, self.draw, x, y)

    def prepare_zoom(self):
        self.region = (0, 0, self.world_width * self.zoom, self.world_height * self.zoom)
        self.canvas.configure(scrollregion=self.region)

    def refresh(self, reset_view=False):
        old_technologies = getattr(self, 'technologies', None)
        self.technologies = self.app.catalog.raw.get('technology', {})
        self.multi_selected.intersection_update(self.technologies)
        self.update_selection()
        techs = self.technologies
        query = self.query.get().lower().strip()
        key = (query, tuple((name, tuple(t.get('prerequisites', []))) for name, t in techs.items()))
        if self.layout_key == key:
            if old_technologies is not techs:
                self.invalidate_scene()
                self.draw()
            if reset_view:
                self.focus_node(self.selected if self.selected in self.positions else next(iter(self.positions), None))
            return
        self.layout_key = key
        self.invalidate_scene()
        self.relation_key = object()
        visible = {n for n, t in techs.items() if not query or query in n.lower() or query in str(t.get('localised_name', '')).lower()}
        for name in list(visible):
            visible.update(p for p in techs[name].get('prerequisites', []) if p in techs)
        indegree = {n: 0 for n in techs}
        self.dependents = defaultdict(list)
        for name, t in techs.items():
            for parent in t.get('prerequisites', []):
                if parent in techs:
                    indegree[name] += 1
                    self.dependents[parent].append(name)
        ready = deque(sorted(n for n in techs if not indegree[n]))
        levels = defaultdict(int)
        while ready:
            name = ready.popleft()
            for child in self.dependents[name]:
                levels[child] = max(levels[child], levels[name] + 1)
                indegree[child] -= 1
                if not indegree[child]:
                    ready.append(child)
        groups = defaultdict(list)
        for name in visible:
            groups[levels[name]].append(name)
        max_columns = max((len(g) for g in groups.values()), default=6)
        self.world_width = max(850, max_columns * 150 + 80)
        self.positions = {}
        # Average parent positions put related branches near one another.
        for rank, level in enumerate(sorted(groups)):
            def parent_center(name):
                parents = [self.positions[p][0] for p in techs[name].get('prerequisites', []) if p in self.positions]
                return sum(parents) / len(parents) if parents else self.world_width / 2
            names = sorted(groups[level], key=lambda n: (parent_center(n), n))
            left = (self.world_width - len(names) * 150) / 2
            for column, name in enumerate(names):
                self.positions[name] = (left + column * 150 + 10, 30 + rank * 200)
        self.world_height = max(600, len(groups) * 200 + 100)
        self.rows = defaultdict(list)
        for name, (x, y) in self.positions.items():
            self.rows[int(y // 200)].append((name, x, y))
        self.edges = []
        for name, (x, y) in self.positions.items():
            for parent in techs[name].get('prerequisites', []):
                if parent in self.positions:
                    px, py = self.positions[parent]
                    self.edges.append((parent, name, px + 58, py + 128, x + 58, y))
        self.draw()
        if reset_view:
            if self.selected in self.positions:
                self.focus_node(self.selected)
            elif self.positions:
                self.focus_node(next(iter(self.positions)))

    def relations(self):
        if self.relation_key == self.selected:
            return self.relation_sets
        ancestors, descendants = set(), set()
        def walk(start, seen, neighbors):
            pending = list(neighbors(start))
            while pending:
                name = pending.pop()
                if name in seen or name == start:
                    continue
                seen.add(name)
                pending.extend(neighbors(name))
        if self.selected:
            walk(self.selected, ancestors, lambda n: self.technologies.get(n, {}).get('prerequisites', []))
            walk(self.selected, descendants, lambda n: self.dependents.get(n, []))
        self.relation_key = self.selected
        self.relation_sets = (ancestors, descendants)
        return self.relation_sets

    def node_colors(self, name, ancestors, descendants):
        if name in self.multi_selected and len(self.multi_selected) > 1:
            return '#3c788d', '#86d5e9', '#244d61'
        if name == self.selected:
            return '#b5a069', '#e7d29b', '#75602c'
        if name in ancestors:
            return '#478759', '#79bd8b', '#234b2e'
        if name in descendants:
            return '#a6554e', '#d8877b', '#61322e'
        return '#73745b', '#a4a58b', '#464834'

    def tech_image(self, name, size, cached_only=False):
        asset = self.app.project.data['technologies'].get(name, {}).get('icon')
        return prototype_image(self.app, self.technologies[name], size, asset, cached_only=cached_only)

    def invalidate_scene(self):
        self.canvas.delete('all')
        self.rendered_nodes.clear()
        self.rendered_edges.clear()
        self.images = []
        self.icon_tasks.clear()
        if self.image_job is not None:
            self.after_cancel(self.image_job)
            self.image_job = None

    def viewport(self):
        c, z = self.canvas, self.zoom
        width, height = c.winfo_width(), c.winfo_height()
        width = width if width > 1 else 800
        height = height if height > 1 else 550
        margin = 140
        return (c.canvasx(0) / z - margin, c.canvasy(0) / z - margin,
                c.canvasx(width) / z + margin, c.canvasy(height) / z + margin)

    def draw(self):
        if self.render_job is not None:
            self.after_cancel(self.render_job)
            self.render_job = None
        c, z = self.canvas, self.zoom
        if self.scene_zoom != z:
            self.invalidate_scene()
            self.scene_zoom = z
        region = (0, 0, self.world_width * z, self.world_height * z)
        if self.region != region:
            c.configure(scrollregion=region)
            self.region = region
        event = select_event(self)
        if self.node_click_binding is None or self.node_click_binding[0] != event:
            if self.node_click_binding:
                c.tag_unbind('technology-node', *self.node_click_binding)
            self.node_click_binding = (event, c.tag_bind('technology-node', event, self.node_click))
        ancestors, descendants = self.relations()
        left, top, right, bottom = self.viewport()
        visible = {}
        for row in range(max(0, int((top - 180) // 200)), int(bottom // 200) + 1):
            for name, x, y in self.rows.get(row, []):
                if x <= right and x + 136 >= left and y <= bottom and y + 180 >= top:
                    visible[name] = (x, y)
        for name in self.rendered_nodes.keys() - visible.keys():
            c.delete('tech:' + name)
            del self.rendered_nodes[name]
        # Top-to-bottom orthogonal branches, like the in-game tree.
        visible_edges = set()
        for parent, name, x0, y0, x1, y1 in self.edges:
            if max(x0, x1) < left or min(x0, x1) > right or max(y0, y1) < top or min(y0, y1) > bottom:
                continue
            key = (parent, name)
            visible_edges.add(key)
            selected_branch = (parent in ancestors and (name in ancestors or name == self.selected)) or (parent == self.selected and name in descendants)
            color = GOLD if selected_branch else '#aaa68d'
            if key not in self.rendered_edges:
                middle = (y0 + y1) / 2
                item = c.create_line(x0 * z, y0 * z, x0 * z, middle * z, x1 * z, middle * z, x1 * z, y1 * z, fill=color, width=max(1, 1.4 * z), tags='connector')
                c.tag_lower(item)
                self.rendered_edges[key] = (item, color)
            elif self.rendered_edges[key][1] != color:
                item = self.rendered_edges[key][0]
                c.itemconfigure(item, fill=color)
                self.rendered_edges[key] = (item, color)
        for key in self.rendered_edges.keys() - visible_edges:
            c.delete(self.rendered_edges.pop(key)[0])
        for name, (x, y) in visible.items():
            t = self.technologies[name]
            tag = 'tech:' + name
            fill, light, dark = self.node_colors(name, ancestors, descendants)
            selected = name == self.selected or name in self.multi_selected
            signature = (id(t), fill, name == self.selected, name in self.app.project.data['technologies'], selected)
            if name in self.rendered_nodes and self.rendered_nodes[name][0] == signature:
                continue
            c.delete(tag)
            node_images = []
            self.render_serial += 1
            owner = (name, self.render_serial)
            inset = -7 if name == self.selected else 0
            x0, y0, x1, y1 = x + inset, y + inset, x + 116 - inset, y + 128 - inset
            c.create_rectangle(x0 * z, y0 * z, x1 * z, y1 * z, fill=fill, outline='#86d5e9' if name in self.multi_selected else GOLD if name == self.selected else '#1b1c17', width=3 if selected else 2, tags=tag)
            c.create_line(x0 * z, y1 * z, x0 * z, y0 * z, x1 * z, y0 * z, fill=light, width=max(1, 2 * z), tags=tag)
            c.create_rectangle(x0 * z, (y + 105) * z, x1 * z, y1 * z, fill=dark, outline='', tags=tag)
            image = self.tech_image(name, 91 * z, cached_only=True)
            if image:
                node_images.append(image)
                c.create_image((x + 58) * z, (y + 52) * z, image=image, tags=tag)
            else:
                placeholder = c.create_text((x + 58) * z, (y + 50) * z, text=name[:2].upper(), fill=TEXT, font=('Segoe UI', max(7, int(24 * z)), 'bold'), tags=tag)
                item = c.create_image((x + 58) * z, (y + 52) * z, tags=tag)
                self.queue_icon(item, lambda n=name, size=91 * z: self.tech_image(n, size), node_images, owner, placeholder)
            for i, entry in enumerate(t.get('unit', {}).get('ingredients', [])[:7]):
                pack = entry['name'] if isinstance(entry, dict) else entry[0]
                image = self.app.icon(('item', pack), size=14 * z, cached_only=True)
                if image:
                    node_images.append(image)
                    c.create_image((x + 10 + i * 15) * z, (y + 116) * z, image=image, tags=tag)
                else:
                    item = c.create_image((x + 10 + i * 15) * z, (y + 116) * z, tags=tag)
                    self.queue_icon(item, lambda p=pack, size=14 * z: self.app.icon(('item', p), size=size), node_images, owner)
            if t.get('research_trigger'):
                c.create_text((x + 58) * z, (y + 116) * z, text='TRIGGER', fill=TEXT, font=('Segoe UI', max(5, int(7 * z))), tags=tag)
            if name in self.app.project.data['technologies']:
                c.create_text((x + 106) * z, (y + 10) * z, text='●', fill='#ffe2a1', font=('Segoe UI', max(6, int(9 * z))), tags=tag)
            label = t.get('localised_name')
            label = label if isinstance(label, str) else name.replace('-', ' ').title()
            label = label[:38] + ('…' if len(label) > 38 else '')
            c.create_text((x + 58) * z, (y + 142) * z, text=label, fill=TEXT, width=max(50, 136 * z), anchor='n', font=('Segoe UI', max(5, round(9 * z))), tags=tag)
            c.addtag_withtag('technology-node', tag)
            self.rendered_nodes[name] = (signature, node_images, owner[1])
        # Discard abandoned loads during fast drags instead of growing a backlog.
        self.icon_tasks = deque(task for task in self.icon_tasks if task[4][0] in self.rendered_nodes and self.rendered_nodes[task[4][0]][2] == task[4][1])
        self.zoom_label.set(f'{round(z * 100)}%')
        self.count.set(f'{len(self.positions)} / {len(self.technologies)} technologies · gold dot = saved edit · colors show relationships, not in-game research progress')

    def focus_node(self, name):
        if name not in self.positions:
            return
        x, y = self.positions[name]
        c, z = self.canvas, self.zoom
        c.xview_moveto(((x + 58) * z - c.winfo_width() / 2) / (self.world_width * z))
        c.yview_moveto(((y + 64) * z - c.winfo_height() / 3) / (self.world_height * z))
        self.draw()

    def edit(self, name=None):
        if name is not None and name == self.selected and self.editor_frame is not None:
            self.multi_selected = {name}
            self.update_selection()
            self.focus_node(name)
            return
        from editors import technology_dialog
        technology_dialog(self, name)
        if name is not None and self.selected == name:
            self.multi_selected = {name}
            self.update_selection()
            self.draw()
