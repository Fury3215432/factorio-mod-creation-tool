import tkinter as tk
from tkinter import ttk
import unittest

from ui import BrowserNotebook, configure_theme, help_label, update_pro_mode


class ProMode(unittest.TestCase):
    def test_each_tab_independent_and_dynamic_help_restored_in_order(self):
        root = tk.Tk(); root.withdraw(); self.addCleanup(root.destroy)
        configure_theme(root)
        book = BrowserNotebook(root); book.pack(fill='both', expand=True)
        tab = ttk.Frame(book)
        first = help_label(tab, 'First tip')
        control = ttk.Entry(tab); control.pack()
        last = help_label(tab, 'Last tip')
        data = ttk.Label(tab, text='Actual data'); data.pack()
        book.add(tab, text='Example')
        other = ttk.Frame(book); other_tip = help_label(other, 'Other tip'); book.add(other, text='Other')
        original = tab.pack_slaves()
        tab.pro_mode.set(True); update_pro_mode(tab)
        self.assertFalse(first.winfo_manager()); self.assertFalse(last.winfo_manager())
        self.assertEqual(control.winfo_manager(), 'pack'); self.assertEqual(data.winfo_manager(), 'pack')
        self.assertEqual(other_tip.winfo_manager(), 'pack'); self.assertFalse(other.pro_mode.get())
        dynamic = help_label(tab, 'Created while pro is enabled')
        next_control = ttk.Entry(tab); next_control.pack()
        self.assertFalse(dynamic.winfo_manager())
        tab.pro_mode.set(False); update_pro_mode(tab)
        self.assertEqual(tab.pack_slaves(), original + [dynamic, next_control])
        tab.pro_mode.set(True); update_pro_mode(tab)
        tab.pro_mode.set(False); update_pro_mode(tab)
        self.assertEqual(tab.pack_slaves(), original + [dynamic, next_control])

