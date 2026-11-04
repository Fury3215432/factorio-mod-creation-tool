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
    'PNG file': 'Optional square item icon. Leave blank to use the checkerboard and add an entry to Suggested actions.',
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
    label.is_instruction = True
    ancestor = parent
    while ancestor is not None:
        if hasattr(ancestor, 'pro_mode'):
            if ancestor.pro_mode.get():
                set_instruction_visible(label, False)
            break
        ancestor = getattr(ancestor, 'master', None)
    return label


def set_instruction_visible(widget, visible):
    if not visible and widget.winfo_manager() == 'pack':
        options = widget.pack_info()
        siblings = widget.master.pack_slaves()
        index = siblings.index(widget)
        following = siblings[index + 1] if index + 1 < len(siblings) else None
        widget.instruction_layout = options, following
        widget.pack_forget()
    elif visible and hasattr(widget, 'instruction_layout'):
        options, following = widget.instruction_layout
        options = dict(options)
        if following is None or not following.winfo_exists() or following.winfo_manager() != 'pack':
            siblings = widget.master.winfo_children()
            following = next((child for child in siblings[siblings.index(widget)+1:] if child.winfo_manager() == 'pack'), None)
        if following is not None and following.winfo_exists() and following.winfo_manager() == 'pack':
            options['before'] = following
        widget.pack(**options)
        del widget.instruction_layout


def update_pro_mode(tab):
    def visit(parent):
        # Restore later siblings first so original pack order is preserved.
        for child in reversed(parent.winfo_children()):
            if getattr(child, 'is_instruction', False):
                set_instruction_visible(child, not tab.pro_mode.get())
            visit(child)
    visit(tab)


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
    style.configure('TSpinbox', fieldbackground=CARD, foreground=TEXT,
                    insertcolor=TEXT, arrowcolor=TEXT, background=CARD,
                    selectbackground='#52637a', selectforeground=TEXT)
    style.map('TSpinbox',
              fieldbackground=[('disabled', '#202935'), ('readonly', CARD), ('!disabled', CARD)],
              foreground=[('disabled', '#aebccd'), ('!disabled', TEXT)],
              arrowcolor=[('disabled', '#aebccd'), ('!disabled', TEXT)])
    style.configure('Treeview', background=CARD, fieldbackground=CARD, foreground=TEXT, rowheight=30)
    style.configure('Treeview.Heading', background=CARD, foreground=TEXT)
    style.map('Treeview', background=[('selected', '#52637a')], foreground=[('selected', TEXT)])
    style.map('TEntry', fieldbackground=[('disabled', '#202935'), ('readonly', CARD)])
    style.configure('TCombobox', fieldbackground=CARD, foreground=TEXT, arrowcolor=TEXT)
    style.map('TCombobox', fieldbackground=[('readonly', CARD), ('disabled', '#202935')], foreground=[('readonly', TEXT), ('disabled', '#aebccd')], selectbackground=[('readonly', CARD)], selectforeground=[('readonly', TEXT)])
    style.configure('TNotebook.Tab', padding=(12, 6), background=CARD)
    style.map('TNotebook.Tab', padding=[('selected', (16, 11))], expand=[('selected', (2, 4, 2, 0))], background=[('selected', '#52637a')])


class BrowserNotebook(ttk.Notebook):
    def add(self, child, **options):
        if not hasattr(child, 'pro_mode'):
            child.pro_mode = tk.BooleanVar(master=child, value=False)
            header = ttk.Frame(child)
            siblings = child.pack_slaves()
            header.pack(fill='x', padx=12, pady=(4, 0), **({'before': siblings[0]} if siblings else {}))
            ttk.Checkbutton(header, text="I'm a pro", variable=child.pro_mode,
                            command=lambda: update_pro_mode(child)).pack(side='right')
        return super().add(child, **options)

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
        def instruction_mapped(event):
            widget = event.widget
            if not getattr(widget, 'is_instruction', False):
                return
            ancestor = getattr(widget, 'master', None)
            while ancestor is not None:
                if hasattr(ancestor, 'pro_mode'):
                    if ancestor.pro_mode.get():
                        set_instruction_visible(widget, False)
                    break
                ancestor = getattr(ancestor, 'master', None)
        self.bind_all('<Map>', instruction_mapped, add='+')

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


def accept_file_drops(widget, callback):
    """Queue Explorer drops without subclassing Tk's native window procedure."""
    import sys
    if sys.platform != 'win32':
        return None
    import ctypes
    from ctypes import wintypes
    from collections import deque
    shell = ctypes.WinDLL('shell32', use_last_error=True)
    user = ctypes.WinDLL('user32', use_last_error=True)
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    result_type = ctypes.c_ssize_t
    handler_type = ctypes.WINFUNCTYPE(result_type, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)
    user.SetWindowsHookExW.argtypes = [ctypes.c_int, handler_type, wintypes.HINSTANCE, wintypes.DWORD]
    user.SetWindowsHookExW.restype = wintypes.HANDLE
    user.CallNextHookEx.argtypes = [wintypes.HANDLE, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM]
    user.CallNextHookEx.restype = result_type
    user.UnhookWindowsHookEx.argtypes = [wintypes.HANDLE]
    kernel.GetCurrentThreadId.restype = wintypes.DWORD
    shell.DragAcceptFiles.argtypes = [wintypes.HWND, wintypes.BOOL]
    shell.DragQueryFileW.argtypes = [wintypes.HANDLE, wintypes.UINT, wintypes.LPWSTR, wintypes.UINT]
    shell.DragQueryFileW.restype = wintypes.UINT
    shell.DragQueryPoint.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.POINT)]
    shell.DragFinish.argtypes = [wintypes.HANDLE]
    hwnd = widget.winfo_id()
    pending = deque()
    active = True
    timer = None

    @handler_type
    def handler(code, wparam, lparam):
        # Never call Tk from a native callback: Tcl may already be processing
        # an event with its Python thread state released.
        if code >= 0 and wparam == 1:  # PM_REMOVE
            message = ctypes.cast(lparam, ctypes.POINTER(wintypes.MSG)).contents
            if message.hWnd == hwnd and message.message == 0x0233:
                drop = message.wParam
                try:
                    point = wintypes.POINT()
                    shell.DragQueryPoint(drop, ctypes.byref(point))
                    paths = []
                    for index in range(shell.DragQueryFileW(drop, 0xFFFFFFFF, None, 0)):
                        length = shell.DragQueryFileW(drop, index, None, 0)
                        buffer = ctypes.create_unicode_buffer(length + 1)
                        shell.DragQueryFileW(drop, index, buffer, length + 1)
                        paths.append(buffer.value)
                    pending.append((paths, point.x, point.y))
                except Exception as exc:
                    pending.append(exc)
                finally:
                    shell.DragFinish(drop)
                    message.message = 0  # WM_NULL: do not let Tk process this drop.
                    message.wParam = message.lParam = 0
        return user.CallNextHookEx(None, code, wparam, lparam)

    hook = user.SetWindowsHookExW(3, handler, None, kernel.GetCurrentThreadId())  # WH_GETMESSAGE
    if not hook:
        raise ctypes.WinError(ctypes.get_last_error())
    shell.DragAcceptFiles(hwnd, True)
    widget._file_drop_handler = handler

    def poll():
        nonlocal timer
        timer = None
        if not active:
            return
        try:
            while pending and active:
                event = pending.popleft()
                if isinstance(event, Exception):
                    widget._root().report_callback_exception(type(event), event, event.__traceback__)
                else:
                    callback(*event)
        finally:
            if active:
                timer = widget.after(50, poll)

    def cleanup(event):
        nonlocal active
        if event.widget is widget and active:
            active = False
            if timer is not None:
                widget.after_cancel(timer)
            shell.DragAcceptFiles(hwnd, False)
            user.UnhookWindowsHookEx(hook)
            pending.clear()
    widget.bind('<Destroy>', cleanup, add='+')
    timer = widget.after(50, poll)
    return handler
