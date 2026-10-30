"""Consistent dark widgets, field explanations and browser-style tabs."""
import tkinter as tk
from tkinter import ttk

BG, CARD, TEXT = '#171c24', '#273240', '#e6edf3'

HELP = {
    'Ore template': 'Solid resource whose ground graphics and mining sounds are copied. The new ore produces its own item.',
    'Mining seconds': 'Time needed for one mining operation at mining speed 1.',
    'Mining yield': 'Whole number of ore items produced per mining operation.',
    'Ore color': 'Hex tint applied to the ground graphics and map marker, for example #bb66ff. The optional PNG is the mined item icon.',
    'Ore density': 'Average resource quantity per tile used by map generation. Higher values create richer patches.',
    'Creation type': 'Items occupy inventory slots. Fluids use pipes. Science packs are consumed by labs. Ores create a mineable map resource and its ingredient item.',
    'Default temperature': 'Temperature in degrees Celsius of this fluid when produced without a recipe temperature override.',
    'Item ID': 'Internal item or fluid name. Renaming updates your saved recipes and open flowcharts. Use letters, numbers, - or _.',
    'Display name': 'The name players will see in the game.',
    'Description': 'Tooltip text shown when players inspect this item or technology.',
    'Stack size': 'Maximum number of these items in one inventory slot.',
    'Recipe result amount': 'Default quantity when this item is first added as an ingredient or product in a recipe flowchart.',
    'Inventory subgroup': 'The group where the item appears in crafting and inventory menus.',
    'PNG file': 'Optional square item icon. Leave blank to use the checkerboard and add an entry to Pending requirements.',
    'New mod ID': 'Internal mod name and ZIP filename. Use letters, numbers, - or _.',
    'Technology ID': 'Internal technology name used by prerequisites and other mods.',
    'Prerequisites': 'Comma-separated technology IDs that must be researched first.',
    'Research count': 'Number of research units required to complete this technology.',
    'Count formula (optional)': 'Formula for research cost, such as 100*L. When set, it replaces Research count.',
    'Seconds per research unit': 'Time a lab needs to process one research unit.',
    'Science packs': 'Science consumed per research unit. Format: pack-id:amount, pack-id:amount.',
    'Recipe unlocks': 'Comma-separated recipe IDs unlocked when this research is completed.',
    'Custom icon PNG (optional)': 'Optional square technology icon. Leave blank to retain the existing icon.',
}


def help_label(parent, text, wraplength=360, **pack):
    label = ttk.Label(parent, text=text, style='Help.TLabel', wraplength=wraplength, justify='left')
    label.pack(anchor='w', **({'padx': 16, 'pady': (2, 7)} | pack))
    return label


def entry_undo(entry, variable):
    """Give dialog text fields local undo without touching the project history."""
    from controls import sequence
    app = entry._root()
    history = []
    previous = variable.get()
    restoring = False
    def changed(*_):
        nonlocal previous
        current = variable.get()
        if current != previous and not restoring:
            history.append(previous)
            del history[:-100]
        previous = current
    def undo(event=None):
        nonlocal restoring
        if history:
            restoring = True
            variable.set(history.pop())
            restoring = False
        return 'break'
    token = variable.trace_add('write', changed)
    def cleanup(event):
        if event.widget is entry:
            try:
                variable.trace_remove('write', token)
            except tk.TclError:
                pass
    entry.bind(sequence(app.controls['keys'].get('undo', 'Ctrl+Z')), undo)
    entry.bind('<Destroy>', cleanup, add='+')
    entry.undo_last_edit = undo


def scroll_form(parent):
    """Scrollable body with a fixed footer supported by the caller."""
    holder = ttk.Frame(parent)
    holder.pack(fill='both', expand=True)
    canvas = tk.Canvas(holder, bg=BG, highlightthickness=0)
    bar = ttk.Scrollbar(holder, orient='vertical', command=canvas.yview)
    canvas.configure(yscrollcommand=bar.set)
    bar.pack(side='right', fill='y')
    canvas.pack(fill='both', expand=True)
    body = ttk.Frame(canvas)
    window = canvas.create_window(0, 0, window=body, anchor='nw')
    body.bind('<Configure>', lambda e: canvas.configure(scrollregion=canvas.bbox('all')))
    canvas.bind('<Configure>', lambda e: canvas.itemconfigure(window, width=e.width))
    tag = 'FormScroll_' + str(canvas).replace('.', '_')
    canvas.bind_class(tag, '<MouseWheel>', lambda e: (canvas.yview_scroll(-1 if e.delta > 0 else 1, 'units'), 'break')[-1])
    def attach(widget):
        if tag not in widget.bindtags():
            widget.bindtags((tag,) + widget.bindtags())
        for child in widget.winfo_children():
            attach(child)
    body.after_idle(lambda: attach(body) if body.winfo_exists() else None)
    body.bind('<Configure>', lambda e: (canvas.configure(scrollregion=canvas.bbox('all')), attach(body)))
    return body


def configure_theme(app):
    # Tk Toplevels do not inherit ttk backgrounds. Set their option defaults too.
    app.option_add('*Toplevel.background', BG)
    app.option_add('*Listbox.background', CARD)
    app.option_add('*Listbox.foreground', TEXT)
    app.option_add('*Listbox.selectBackground', '#52637a')
    app.option_add('*Menu.background', CARD)
    app.option_add('*Menu.foreground', TEXT)
    app.option_add('*Menu.activeBackground', '#52637a')
    app.option_add('*Menu.activeForeground', TEXT)
    app.option_add('*Text.background', CARD)
    app.option_add('*Text.foreground', TEXT)
    app.option_add('*Text.insertBackground', TEXT)
    style = ttk.Style(app)
    style.theme_use('clam')
    style.configure('.', background=BG, foreground=TEXT, font=('Segoe UI', 10))
    style.configure('Help.TLabel', foreground='#aebccd', font=('Segoe UI', 9))
    style.configure('TButton', padding=(12, 8), background=CARD)
    style.configure('Small.TButton', padding=(3, 1))
    style.map('TButton', background=[('active', '#46576a')])
    style.configure('TEntry', fieldbackground=CARD, foreground=TEXT, insertcolor=TEXT)
    style.configure('Treeview', background=CARD, fieldbackground=CARD, foreground=TEXT, rowheight=30)
    style.configure('Treeview.Heading', background=CARD, foreground=TEXT)
    style.map('Treeview', background=[('selected', '#52637a')], foreground=[('selected', TEXT)])
    style.map('TEntry', fieldbackground=[('disabled', '#202935'), ('readonly', CARD)])
    style.configure('TCombobox', fieldbackground=CARD, foreground=TEXT, arrowcolor=TEXT)
    style.map('TCombobox', fieldbackground=[('readonly', CARD), ('disabled', '#202935')], foreground=[('readonly', TEXT), ('disabled', '#aebccd')], selectbackground=[('readonly', CARD)], selectforeground=[('readonly', TEXT)])
    style.configure('TNotebook.Tab', padding=(12, 6), background=CARD)
    style.map('TNotebook.Tab', padding=[('selected', (16, 11))], expand=[('selected', (2, 4, 2, 0))], background=[('selected', '#52637a')])


class BrowserNotebook(ttk.Notebook):
    def __init__(self, parent):
        style = ttk.Style(parent)
        self.close_images = []
        if 'Studio.close' not in style.element_names():
            for color in ('#bac7d6', '#ffffff'):
                image = tk.PhotoImage(master=parent, width=16, height=14)
                for i in range(4, 11):
                    image.put(color, to=(i, i - 1, i + 2, i + 1))
                    image.put(color, to=(i, 13 - i, i + 2, 15 - i))
                self.close_images.append(image)
            parent._tab_close_images = self.close_images
            style.element_create('Studio.close', 'image', self.close_images[0], ('active', self.close_images[1]), border=2, sticky='')
        style.layout('Browser.TNotebook.Tab', [('Notebook.tab', {'sticky': 'nswe', 'children': [('Notebook.padding', {'side': 'top', 'sticky': 'nswe', 'children': [('Notebook.label', {'side': 'left', 'sticky': ''}), ('Studio.close', {'side': 'left', 'sticky': ''})]})]})])
        super().__init__(parent, style='Browser.TNotebook')
        self.pressed = None
        self.bind('<ButtonPress-1>', self.press, add='+')
        self.bind('<ButtonRelease-1>', self.release, add='+')

    def press(self, event):
        if 'Studio.close' in self.identify(event.x, event.y):
            self.pressed = self.index('@%d,%d' % (event.x, event.y))
            return 'break'

    def release(self, event):
        try:
            if self.pressed is not None and 'Studio.close' in self.identify(event.x, event.y):
                index = self.index('@%d,%d' % (event.x, event.y))
                if index == self.pressed:
                    self.nametowidget(self.tabs()[index]).close()
        except tk.TclError:
            pass
        finally:
            self.pressed = None
