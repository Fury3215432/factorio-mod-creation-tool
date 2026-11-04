import json,tempfile
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from tkinter import ttk
from core import Catalog
from project import Project
from recipe_unlocks import necessary_ingredient_recipes
from app import App
from installation import find_installation

class NecessaryIngredients(unittest.TestCase):
    def test_exclusive_deep_dependencies_and_previous_unlocks(self):
        def recipe(product, ingredients, enabled=False):
            return {'type':'recipe','name':product+'_recipe','enabled':enabled,
                    'ingredients':[{'type':'item','name':name,'amount':1} for name in ingredients],
                    'results':[{'type':'item','name':product,'amount':1}]}
        rows=[recipe('final',['part']),recipe('part',['private','shared','free','prior']),
              recipe('private',['leaf']),recipe('leaf',['raw']),recipe('shared',['raw']),
              recipe('unrelated',['shared']),recipe('free',['raw'],True),recipe('prior',['raw'])]
        raw={'recipe':{r['name']:r for r in rows},'technology':{
            'earlier':{'effects':[{'type':'unlock-recipe','recipe':'prior_recipe'}]},
            'middle':{'prerequisites':['earlier']},'target':{'prerequisites':['middle']}}}
        app=SimpleNamespace(catalog=Catalog(raw),project=Project())
        expected=['final_recipe','part_recipe','private_recipe','leaf_recipe']
        self.assertEqual(necessary_ingredient_recipes(app,['final_recipe'],'target'),expected)
        # The editor's unsaved prerequisites are respected for a new technology.
        self.assertEqual(necessary_ingredient_recipes(app,['final_recipe'],None,['middle']),expected)
        self.assertFalse(app.project.data['recipes'])
        # Multiple eligible producers are chosen explicitly, not silently.
        alternative=recipe('private',['raw'])
        alternative['name']='private-alternative'
        raw['recipe']['private-alternative']=alternative
        app.catalog=Catalog(raw)
        prompts=[]
        def choose(key,candidates):
            prompts.append(key)
            return 'private-alternative' if key==('item','private') else candidates[0]
        chosen=necessary_ingredient_recipes(app,['final_recipe'],'target',chooser=choose)
        self.assertIn('private-alternative',chosen)
        self.assertNotIn('private_recipe',chosen)
        self.assertNotIn('leaf_recipe',chosen)
        self.assertEqual(prompts,[('item','private')])
        from recipe_unlocks import IngredientChoiceCancelled
        with self.assertRaises(IngredientChoiceCancelled):
            necessary_ingredient_recipes(app,['final_recipe'],'target',chooser=lambda key,choices:None)
        raw['recipe'].pop('private-alternative')

        raw['recipe']['leaf_recipe']['ingredients']=[{'type':'item','name':'private','amount':1}]
        app.catalog=Catalog(raw)
        actual=necessary_ingredient_recipes(app,['final_recipe'],'target')
        self.assertEqual(len(actual),len(set(actual)))
        self.assertNotIn('shared_recipe',actual)
        self.assertNotIn('prior_recipe',actual)
        self.assertNotIn('free_recipe',actual)

    @unittest.skipUnless(Path('.cache/test-catalog.json').exists(),'Requires catalog')
    def test_editor_button_and_undo(self):
        work=Path(tempfile.mkdtemp(dir=Path('.cache').resolve()))
        with patch('tkinter.messagebox.askyesno',return_value=False),patch('tkinter.messagebox.showerror') as errors:
            app=App();app.withdraw();self.addCleanup(app.destroy)
            app.autosave_path=work/'project.json'
            app.catalog=Catalog(json.loads(Path('.cache/test-catalog.json').read_text(encoding='utf-8')))
            app.root_path=find_installation() or Path('unconfigured-factorio-installation')
            app.mods_path=work/'mods';app.mods_path.mkdir()
            app.setup_frame.destroy();app.workspace()
            equations=app.equations_tab()
            equations.text.insert('1.0','iron plate = exclusive leaf\nexclusive leaf = exclusive part\nexclusive part = exclusive final')
            self.assertTrue(equations.apply_changes())
            tree=app.tech_tab();tree.edit('automation-2')
            tree.editor_vars['unlocks'].set('exclusive_final_recipe')
            def descendants(widget):
                for child in widget.winfo_children():
                    yield child
                    yield from descendants(child)
            button=next(w for w in descendants(tree) if isinstance(w,ttk.Button) and w.cget('text')=='Add necessary ingredients')
            count=len(app.undo_stack)
            button.invoke()
            self.assertEqual(tree.editor_vars['unlocks'].get(),'exclusive_final_recipe, exclusive_part_recipe, exclusive_leaf_recipe')
            self.assertEqual(len(app.undo_stack),count+1)
            self.assertTrue(app.undo())
            self.assertEqual(tree.editor_vars['unlocks'].get(),'exclusive_final_recipe')
            button=next(w for w in descendants(tree) if isinstance(w,ttk.Button) and w.cget('text')=='Add necessary ingredients')
            button.invoke();self.assertTrue(tree.save_changes())
            self.assertIn('automation-2',app.project.recipe_unlocks('exclusive_leaf_recipe',app.base_raw))
            self.assertFalse(errors.called,errors.call_args_list)
            import tkinter as tk
            from recipe_unlocks import choose_ingredient_recipe, IngredientChoiceCancelled
            def choose_second():
                dialog=next(w for w in app.winfo_children() if isinstance(w,tk.Toplevel) and w.title()=='Choose ingredient recipe')
                listing=next(w for w in descendants(dialog) if isinstance(w,tk.Listbox))
                listing.selection_clear(0,'end');listing.selection_set(1)
                next(w for w in descendants(dialog) if isinstance(w,ttk.Button) and w.cget('text')=='Use selected recipe').invoke()
            app.after(20,choose_second)
            self.assertEqual(choose_ingredient_recipe(tree,('item','iron-plate'),['iron-plate','copper-plate']),'copper-plate')
            def cancel():
                dialog=next(w for w in app.winfo_children() if isinstance(w,tk.Toplevel) and w.title()=='Choose ingredient recipe')
                dialog.destroy()
            app.after(20,cancel)
            with self.assertRaises(IngredientChoiceCancelled):
                choose_ingredient_recipe(tree,('item','iron-plate'),['iron-plate','copper-plate'])

