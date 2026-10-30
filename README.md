# Factorio Mod Creation Tool — by FuryziN

A Windows desktop recipe editor using Python's built-in Tkinter. Requires Python 3.10+ with Tkinter and a licensed Factorio installation supporting `--dump-data` (1.1.77+ or 2.x). No pip packages required.

## Help others discover the tool

If this app helped you make your mod, please consider mentioning **Factorio Mod Creation Tool by FuryziN** in your mod description and linking to [the tool’s website](https://fury3215432.github.io/factorio-mod-creation-tool/). This is optional, but it helps other mod creators discover the app.

Suggested credit: “Created with Factorio Mod Creation Tool by FuryziN: https://fury3215432.github.io/factorio-mod-creation-tool/”

## Open the app

Double-click **Launch Factorio Mod Creation Tool.bat**, or run `python app.py` from this folder. The app icon is bundled from the supplied assembling-machine image.

1. Browse to the Factorio installation folder containing `bin` and `data`.
2. Optionally add mod ZIPs, unpacked mods, or a folder of mods. Include dependency mods. All supplied mods are enabled; built-in optional expansions are disabled unless supplied explicitly. Mod settings use their defaults.
3. Click **Load game data**. Factorio runs in the background and exports its resolved prototypes, including mod changes. Close other Factorio instances before loading. Loading may take several minutes.
4. Click **New item/edit recipe** to open an empty browser-style flowchart tab. Right-click empty space to **Load recipe**, **Create item**, **Add new ingredient**, or **Add new result**. Load recipe searches recipe IDs directly; **Ctrl+F** also opens this picker. The selected tab is larger; use its small **×** to close it.
5. Click a rectangle to change its item or quantity, or remove it. Right-click empty canvas space to **Add new ingredient** or **Add new result**. Scroll to see large recipes. Hold **Ctrl** and scroll up/down to zoom in/out at the pointer in either flowchart. Hold the left or middle mouse button on empty space and drag to pan.
6. Set the recipe ID, crafting seconds, **Made in / recipe category**, and whether it is available from the start. Categories determine compatible producers: for example, `smelting` uses furnaces, while `crafting` uses assemblers and player crafting. A list below the fields shows the loaded producers supporting the chosen category. Machine-specific input and fluid restrictions still apply. Each input has an explanation below it.
7. After loading a recipe, the upper-right actions are **Apply edit**, which updates that recipe, and **Save as new recipe**, which asks for a unique ID and saves a separate copy of the current flowchart. After saving a copy, the tab switches to that copy; the original recipe remains unchanged, including when exporting all open tabs. In an empty/new flowchart only **Save as new recipe** appears. Existing recipes cannot be overwritten from new-recipe mode; load them to edit instead. These actions save to the project without generating Lua or a ZIP, and saved edits survive closing the tab.

   Edited recipes retain their technology unlocks. The editor shows **Unlocked by**. To make a recipe available immediately, check **Available from start** and apply the edit: all technology unlock references to that recipe are removed while other effects/research settings are preserved. Undo restores the unlocks. Otherwise export keeps the technology requirement, including for older saved edits.
8. Use **Save project as…** to save a portable project JSON, and **Open project…** to resume it. Saved edits are also automatically kept in `.studio/project.json`; the next session offers to restore them after loading the game. PNG data is embedded in the project so the original image files are not needed later. Load the same source mods when resuming.

## Export a ready-to-install mod

Click **Export mod file** in the main toolbar, outside the flowcharts. It saves pending recipe edits in open tabs and compiles **all** saved recipe, item and technology changes, including edits whose tabs have been closed. Invalid drafts block export and display the problem. Choose **Create a new mod**, or select a loaded mod to export an updated copy. A new mod includes `info.json`, all prototypes and PNG assets, and an automatic `data-final-fixes.lua` loader. An updated mod retains its identity, version, assets, and scripts, runs its existing final-fixes first, then applies the project. The original loaded files stay unchanged.

Save using the suggested ZIP filename, which Factorio requires. Copy the ZIP into your Factorio mods folder, enable the mod, and restart Factorio. When updating a mod, replace the old copy, including any unpacked duplicate.

Loaded mods become required dependencies of new mods. Updated mods also retain their existing dependencies and require the other loaded mods. Dependencies are not bundled: install them alongside the exported mod. An existing mod's optional dependency becomes required when it was loaded for this editing session. New recipe IDs with **Available from start** disabled still need a technology unlock.

When a mod is loaded or an existing mod is updated, export also writes **`<mod-name>_<version>.changes.json`** beside the ZIP and includes **`recipe-studio-changes.json`** inside it. The log contains precise before/after prototype values for recipes, items and technologies, including quantities, crafting category, research properties and automatic unlock gating. It also records added/modified files, SHA-256 hashes and full text diffs. File changes compare to the selected original mod; prototype changes compare to the resolved game data loaded at the start of the session. A new dependent mod has no original files. The report excludes its own file from the diff to avoid recursion.

## Create an ingredient item

Open **New item/edit recipe**, right-click empty space and select **Create item**. Enter the item ID, display name, description, stack size, inventory subgroup, default recipe quantity, and optionally a square PNG file (up to 4096 pixels). Leave PNG blank to use the bundled checkerboard texture supplied as the default icon. Press **Create item** at the bottom left of the dialog. This saves the item immediately, independently of the current flowchart or recipe. It is available in searches in every tab as soon as the dialog closes.

The new prototype is a normal ingredient item, with no placement or equipment behavior. Creating it does not automatically add a rectangle or crafting recipe. Use **Add new ingredient** or **Add new result** to choose it for the flowchart. The default recipe quantity is used when adding it; click the rectangle to change that quantity later. New recipes start locked by default. Assign them to a technology through Pending requirements, or explicitly enable Available from start. Item definitions, images and saved recipes are bundled by **Export mod file**.

Choose **Create item as ingredient** from the flowchart's empty-space menu to create the item and immediately add it to that flowchart at its default quantity. One **Ctrl+Z** undoes both the creation and ingredient insertion. This also supports fluid, science-pack and ore creation through the type selector.

**Bulk ingredient creation**, in the same right-click menu, opens a multiline name field and a preview of item IDs/display names. One space becomes `_` in an ID; two or more spaces separate items. New lines/tabs also separate items. For example, `copper plate  iron ore` creates `copper_plate` named `copper plate` and `iron_ore` named `iron ore`. **Apply** saves the whole batch with stack size 100, default icons and no automatic recipe rectangles. The items immediately appear in pickers, Browse creations and Pending requirements. Duplicate/invalid IDs block the batch without creating any items. One Ctrl+Z undoes the whole batch.

New recipe IDs default to the first product's ID plus `_recipe` (for example, `copper-ore_recipe`). The suggestion follows changes to the first product until you type a custom recipe ID or save/load the recipe; existing recipe IDs stay fixed.

## Browse creations and create fluids or science packs

**Create item** offers a **Creation type** selector: **item**, **fluid**, or **science pack**. Fluids use a default temperature instead of stack size and allow fractional recipe quantities. Science packs are research tools with one research use per pack; exported labs accept your new packs. Select them in the technology editor's **Science packs → Choose…** list. Create their crafting recipes separately in a recipe flowchart.

**Browse creations**, beside **Create machine**, lists your saved items, fluids, science packs and newly created machines, newest first. Search by ID, display name or type. Double-click a row or choose **Edit selected** to change its properties, icon, ID or item/fluid/science-pack type. Renaming updates saved recipes, open recipe flowcharts and saved technology science-pack references. Converting a fluid to an item requires whole-number quantities; a science pack used by saved research must remain a science pack. Existing IDs are protected from collisions. **Ctrl+Z** restores the change and affected open recipe charts.

Use **Use as ingredient** or **Use as product** to open a new recipe chart containing the selected creation. Ingredient/result pickers place your newest creations first, followed by loaded game items alphabetically. Creation order is retained in saved projects.

Item/recipe picker searches ignore letter case and treat underscores, hyphens and spaces as word separators. For example, `early_electric_motor` finds `Early_Electrical_Motor`; choosing it preserves its actual ID.

The browser also lists every saved recipe and technology, including both newly created prototypes and edits to loaded ones. The **Change** column distinguishes **Created** from **Edited**. Double-click a recipe to open its flowchart (or return to its existing tab), or a technology to select it in the technology editor. Ingredient/product actions apply to items, fluids and machines.

Select a recipe and choose **Read recipes as diagram** to open its flowchart. Ctrl/Shift-select several recipe rows to open each in a separate tab. Existing tabs are reused, preserving their unsaved edits. The same action appears when right-clicking a recipe. It works for created, edited and loaded-mod recipes.

Right-click an **Edited** item, recipe, technology or machine and select **Undo edit** to restore its original loaded definition. Open editors update to the restored values. Ctrl+Z reverses this operation and restores the saved edit and editor drafts. Newly created prototypes have no original loaded definition, so this option is shown only for edits to existing content.

When loading mods, the browser also includes their items, fluids, science packs and recipes, plus vanilla items/recipes modified by those mods. These entries show **Loaded**; the **Loaded** change filter isolates them. Loading compares the resolved mod data with a separate base-game reference so ordinary unchanged vanilla content is excluded. Double-click a loaded recipe to edit it, or use a loaded item as an ingredient/product. Loaded item properties and optional icons can be edited while keeping their original ID, type, and other prototype behavior. Saved edits replace the loaded row without duplication. **Delete selected** removes a saved edit and restores the original. **Delete from loaded mod**, also in the right-click menu, removes the prototype from the project preview and exported mod. These removals persist in project JSON, appear in change logs, and support Ctrl+Z. The source files stay unchanged until you replace them with an exported copy.

Deleting a loaded recipe also removes its technology unlock effects and module recipe restrictions. Items still used by recipes, mining products, research or other prototypes are blocked with a dependency list; remove or edit those references first. This includes generated recycling recipes. Open editors for a deleted recipe are reset so export does not recreate it; undo restores them.

Use the **Type** and **Change** filters with the search field to narrow the browser, or **Clear filters** to reset them. Right-click an item or fluid in the browser or a recipe flowchart and select **See all recipes containing this item/fluid**. This searches all loaded base-game/mod recipes with saved project edits applied. The window shows whether each recipe uses it as an ingredient, a product, or both. Search recipe IDs, filter by ingredient/product use, and double-click a result to open its flowchart. Existing open drafts are reused.

Select an item, fluid, science pack or recipe and choose **Delete selected**, press **Delete**, or use its right-click deletion action. Deletions are saved immediately and support **Ctrl+Z**. Deleting a saved edit to a loaded recipe restores the original recipe; deleting a new recipe removes it and resets its open editor so export cannot recreate it. Items still referenced by recipes/open flowcharts/research, and new recipes referenced by technologies or saved machines, cannot be deleted until those references are removed. The message lists the dependencies.

## Replace an ingredient everywhere

Right-click an item/fluid rectangle in a flowchart and select **Replace ingredient in all recipes**. Choose a replacement of the same type, review the affected recipes, then **Apply replacement**. This updates ingredients in loaded base-game/mod recipes, saved custom recipes and open flowchart drafts. Quantities, products, recipe IDs, crafting times and technology unlocks are preserved. When the replacement is already an ingredient, quantities are combined if their other settings match; incompatible settings block the entire operation. Open unsaved changes are retained. One Ctrl+Z restores the project edits and affected drafts. Export includes all recipe edits normally.

## Expand ingredient recipes in a flowchart

Right-click an ingredient rectangle and select **Show recipe** to display a recipe producing it on the same canvas. If several recipes produce it, choose one. The expanded recipe includes its ingredients, crafting time, all products and a connection to the ingredient it supplies. Repeat on expanded ingredients to build a multi-stage crafting diagram. The view zooms out to fit the recipe columns; Ctrl+wheel and dragging empty space still zoom/pan.

Use **Hide recipe** on an ingredient or expanded recipe title, or **Collapse expanded recipes** above the canvas. Expansion and collapse support Ctrl+Z and do not alter the main recipe. Circular expansions are blocked. Main recipe rectangles remain editable. Expanded branches show saved recipe definitions; click their title/craft box/rectangles or choose **Edit this recipe** to open that source's editor. Saving source edits updates the expanded graph. Loading a different main recipe clears its expansions.

## Read equations

Click **Read equations**, beside Settings, to open the equation reader. Enter one recipe per line, such as `copper plate + iron plate = metal alloy`. Use `+` between ingredients/products and `=` between the two sides. A term defaults to quantity 1; quantities can be written as `2 iron plate` or `2 * iron plate`. Multiple products are supported. Repeated ingredients are combined.

One space becomes `_` in a new item's ID: `metal alloy` creates `metal_alloy` with display name `metal alloy`. Existing IDs are reused, including readable hyphenated game names (`copper plate` resolves to `copper-plate`). Exact underscore IDs take priority. Existing fluids are recognized; fractional quantities are allowed for fluids. An ambiguous item/fluid ID can be qualified as `item:name` or `fluid:name`. Unknown names create normal items, so create a new fluid separately first if needed.

The preview shows resolved IDs, amounts, recipe IDs and which items will be created. Set crafting seconds/category for the batch, then click **Apply equations**. Recipes use `<first_product_id>_recipe`, with `_2`, `_3`, etc. for collisions; existing recipes are not overwritten. New items use stack size 100 and the default icon. Everything is saved to the project and appears in Browse creations; missing icons/recipes are tracked in Pending requirements. New recipes start locked and appear under Missing technology unlocks until assigned. **Open selected recipe** opens an applied recipe in its flowchart for further editing. Invalid equations block the entire batch without partial creation. Applying unchanged text again does not create duplicates. One **Ctrl+Z** undoes the whole batch.

## Create ores

In **Create item**, set **Creation type → ore**. This creates both a solid mineable resource and its matching inventory item. Choose a loaded solid-resource template for ground graphics and sounds, then set **Mining seconds**, **Mining yield**, **Ore color** (hex tint), and **Ore density**. The optional PNG is the inventory icon; ground graphics come from the selected template with your tint.

**Generate ore patches on Nauvis** enables natural patches and map-generation frequency/size/richness controls. **Include a starting-area patch** enables patches near spawn. New ores appear in new maps or newly generated terrain, without replacing explored terrain. Disable automatic generation for a resource you want to place through another mod or script. Standard solid-ore drills can mine it; no crafting recipe is automatically created. Ores appear in **Browse creations** with their own type filter, can be edited/deleted/undone, and their inventory items are available in recipe pickers.

## Pending requirements

**Pending requirements** appears beside **Create machine** only while something is missing. Its tab lists all custom items using the default checkerboard icon. Click a row to choose a replacement square PNG; the image is saved immediately, the item disappears from the list, and open flowcharts update. Replacing an icon supports **Ctrl+Z**, which restores the previous icon and pending entry. The pending state survives saving/opening a project. Placeholder icons are valid bundled mod assets, so they do not prevent exporting or loading the mod in Factorio.

**Export as text** saves pending item requirements to a UTF-8 `.txt` file. It includes separate lists of items needing icons and items/fluids needing recipes. The tab also links to existing missing-machine-recipe fixes. When all requirements are resolved the toolbar button disappears, while an already-open tab shows the empty state.

The tab also lists created and loaded-mod items/fluids with no recipe producing them. Select one and choose **Fix selected recipe** (or double-click) to open a new recipe with that item as its first product. The recipe ID is suggested automatically. Save the recipe to resolve the entry; undoing the save restores the requirement. Disabled recipes unlocked by technologies count as recipes. Mined resources may intentionally have no crafting recipe. **Export as text** includes both missing icons and missing item/fluid recipes, and the toolbar button stays visible while either remains.

Pending requirements are grouped into **Missing icons**, **Missing recipes**, **Unused ingredients** and **Machines** tabs. **Unused ingredients** lists created/loaded-mod items and fluids that are not consumed by any recipe; appearing only as a product does not count as use. Placeable buildings, belts, inserters, equipment, science packs and other terminal-use item types are treated as finished products automatically. In the item editor, **Mark as finished product** excludes any other item from this unused list. The flag is saved in the project, supports Ctrl+Z, and does not suppress missing-icon or missing-recipe warnings. Double-click an unused entry or choose **Edit selected item** to mark it. Text export includes unused items too.

Right-click an entry in any item/fluid requirement list and choose **See recipes containing this item/fluid** to search all loaded and saved recipes using or producing it. Machine names in the Machines group support the same menu. Results can be filtered by ingredient/product use and opened as flowcharts.

The same right-click menu offers **Delete item**/**Delete fluid** for created and loaded-mod items. Deletion runs directly from Pending requirements, with the dependency checks and Ctrl+Z support used by Browse creations. Loaded-mod deletions are also applied to exported mods. Items still referenced by recipes, open flowcharts, research or other prototypes must have those references removed first.

Choose **Delete item and recipes containing it** (or the fluid equivalent) to remove the item together with every recipe using it as an ingredient or product. This also removes deleted recipes' technology unlock effects, handles loaded-mod/recycling recipes and resets affected open flowcharts. One Ctrl+Z restores the full batch, including unsaved flowchart changes and expanded diagrams. Non-recipe dependencies, such as resource mining products or fixed machine recipes, still block the operation without partial deletion. The option is available in both Pending requirements and Browse creations.

**Missing technology unlocks** lists saved/loaded recipes that are locked from the start and have no technology unlocking them. New recipe flowcharts, saved copies, machine crafting recipes and equations default to locked. Click a missing-unlock entry to search technologies and **Add to selected technology**, or choose **Create new technology**. The latter opens the technology editor with a suggested ID and the recipe already in **Recipe unlocks**; finish its research settings and save. Assignments support Ctrl+Z and appear in text exports. Recipes explicitly available from the start do not appear in this list. Existing projects retain their previous availability settings.

Technology assignment affects only the selected recipe. Ingredient recipes do not inherit unlocks from consuming recipes. Locked ingredient recipes without an unlock remain in **Missing technology unlocks** until assigned manually. Existing saved technology assignments are preserved.

The fallback icon is bundled at `assets/default-item-icon.png` as a 64 × 64 PNG converted from the supplied texture. The original Desktop WebP file and an image-conversion program are not needed to run the app.

## Edit the technology tree

Click **Edit tech tree** to open a flowchart of loaded and saved technologies. The tree uses a top-to-bottom layout with compact technology icons, science-pack strips and connected branches. The selected technology is gold, its prerequisites are green, and its dependents are red. These colors show relationships in the editor, not research progress in a save game. A gold dot marks saved edits.

Click a card to open its editor in the **left panel**, with an icon and cost preview. The bottom technology-thumbnail gallery has been removed, leaving more space for editing. Scroll the **Research & unlocks** panel to access all fields; use **Advanced JSON** for other properties. **Save technology** commits changes and keeps the panel open; **Discard** restores the saved values. Switching cards or closing the tab asks how to handle unsaved changes. Search above the tree to focus on matching technologies and their immediate prerequisites. Ctrl + wheel zooms at the pointer, ordinary wheel scrolls, and left/middle dragging on empty space pans.

The tree only creates cards near the visible viewport. Visible icons fill in progressively so opening, panning and zooming remain responsive; off-screen icons are not decoded. Existing cards, cached images, graph layout and event handlers are reused rather than rebuilt on every interaction.

Right-click empty space and select **Create new technology**, or use **+ New technology** in the tree toolbar. Fill in the technology ID, display name, prerequisites, research count (or formula), seconds per unit, science pack quantities and recipe unlocks. The chooser buttons help select known technologies, science packs and recipes. Optionally choose a custom square PNG. Without one, a new technology uses the base automation icon.

The advanced tab exposes additional properties as JSON, including non-unlock effects, research triggers and upgrade levels. Existing properties are preserved. Trigger-based technologies can keep their trigger or switch to science-based research. **Create technology** or **Save technology** saves the change to the project and redraws the flowchart immediately. Cyclic prerequisites and unknown science packs, prerequisites or recipe unlocks are rejected. Recipes assigned to a saved technology unlock are disabled at the start when exporting.

## Bulk edit technology science packs

**Ctrl-click** technology cards to add/remove them from a selection. Selected cards have a cyan outline. **Select all shown** selects the currently filtered tree; **Clear selection** resets it. Choose **Add / remove science packs**, select one or more packs (Ctrl/Shift-click), and use **Add selected packs** or **Remove selected packs**. Created science packs are included.

Adding inserts only missing packs at the specified quantity and preserves quantities of existing packs. Removing affects only the chosen packs. Research counts/formulas, times, prerequisites, icons and unlocks are preserved. Trigger-based research is skipped and reported. If removal would leave any technology with no science packs, the entire operation is rejected. The bulk operation saves to the project and supports one-step **Ctrl+Z**.

## Create a machine

Click **Create machine**, next to **Edit tech tree**, to open an empty tab and a start window with three choices. **Choose template** shows all loaded/saved assembler, furnace, mining-drill and rocket-silo templates and creates a new machine from the selected template. **Edit machine** loads an existing machine and saves changes to that same identity. **Create variant** loads its stats into a separate new machine; give the variant its own ID. The form stays hidden until a source is selected. The existing source remains unchanged when a variant is created.

The left panel loads the source's display name, description, stack size, health, speed, energy type and usage, module slots and other stats. **All other stats (JSON)** contains the remaining entity properties, including animations, resistances, sounds and energy-source details. These can be edited alongside the basic form fields. Edit mode locks the original ID. A variant of a saved project machine keeps its current stats and assets while receiving a new ID.

**Placed width (tiles)** and **Placed height (tiles)** replace the old sprite-scale control. They change the actual entity footprint, collision and selection boxes, tile dimensions, graphics size, fluid-port positions and mining output offsets. Graphics retain their aspect ratio inside non-square footprints. Upgrade links whose collision sizes no longer match are removed so resized entities remain valid. **Machine color** accepts a hex tint or a color-picker selection; the preview and world graphics show it. Optional building PNGs are single-frame images fitted to the chosen footprint. Leave PNG fields blank to retain source animations. PNGs are embedded in saved projects and bundled into exports.

Mining-drill templates include the loaded electric and burner drills, pumpjacks and any modded drills. Their form shows **Mining speed**, **Mining radius**, **Resource drain (%)** and **Resource categories** instead of crafting-recipe controls. Source fluid connections, output behavior and remaining drill stats are preserved. The exported drill can mine matching resources, accepts power/fuel as configured, and returns its placeable item when mined.

Enter a unique machine ID and choose **Allowed recipes → Choose…** to search and select multiple loaded or saved recipes. The machine accepts exactly this list. Export assigns a separate category to each selected recipe and extends original compatible producers so they retain their existing crafting ability. A recipe may be shared by multiple custom machines without allowing their other recipes. Recipes requiring fluids are checked against the template's actual input/output pipe capacity; select a suitable template if validation reports insufficient ports.

Use **Import recipes**, beside **Choose…**, to select one or more existing assembling machines, furnaces or rocket silos. Search by machine name and select multiple rows with Ctrl/Shift, then click **Done**. Their craftable recipes are added to the current list without duplicates. Import checks their categories, fixed recipes, ingredient limits and fluid connections. The target building still needs sufficient fluid ports for the combined selection. Each recipe in the large right-hand list has a small **×** to remove it. There is no free-text recipe list field in the building form.

The building form does **not** create a crafting recipe for the machine. After saving, a warning below **Saved:** in the upper right says **Machine [name] doesn't have a crafting recipe**. Click **Fix** to open the unified recipe tab with the existing placeable machine as its result. Add ingredients and set the crafting time/category, then **Save as new recipe**. This creates an independent recipe without duplicating or replacing the machine item. The warning disappears when a saved recipe produces the machine; disabled recipes count too, so technology unlocks are supported. Exports are allowed while the warning is present. Older projects' construction costs are migrated into independent recipes automatically.

In game, electric machines need electricity and burner machines consume chemical fuel. The building can be placed, used through the normal crafting-machine interface, and mined back into its item.

Click **Save machine** to store it without exporting. In Edit mode it modifies the selected machine; in template/variant mode it adds a separate machine. Reopen a saved machine through the selector on the right. Search for its item in **Edit a recipe** to open its crafting recipe (or create one if it is missing). **Save project as…**, automatic restore, **Export mod file**, and change logs all include new and edited machines. Older projects remain compatible.

## Settings and controls

Open **Settings → Keyboard** to view and edit application shortcuts and chart controls. Defaults: **Ctrl+S** applies/saves the active tab, **Ctrl+E** exports the project, **Ctrl+T** or **Ctrl+N** opens the unified flowchart, **Ctrl+G** opens technologies, **Ctrl+M** creates a machine, **Ctrl+W** closes the active tab, **Ctrl+F** focuses search, **Ctrl+Z** undoes a change, and **Ctrl+comma** opens settings.

Undo tracks recipe loading, added/removed/changed rectangles, recipe settings, item creation, machine/technology form edits and saved project changes. Repeated typing in one field is grouped; dialog text fields have local text undo. Undoing a save restores the previous saved project and the draft from before that save. Undo history is limited to 100 actions in the current session and is cleared when opening another project. Undo does not alter ZIPs already exported.

Change keyboard combinations with values such as `Ctrl+Shift+S` or `F2`. You can also change the zoom modifier, primary and additional pan buttons, chart selection button, context-menu button, picker double-click button, confirmation key and dialog-dismiss key. Defaults use Ctrl+wheel for zoom, left/middle drag on empty space for pan, left-click for selection, right-click for context menus, Return to confirm and Escape to dismiss dialogs. Settings are saved in `.studio/settings.json` and apply to open charts immediately; picker-specific controls apply when the next picker opens. Standard Windows text editing and native file-dialog controls follow the operating system.

All ingredients and results are exported. Probability, temperature, catalyst and other entry properties survive unchanged when editing quantities. Changing an entry's item clears its old special properties. Random result ranges survive unless you enter a fixed quantity. Original icons, machine restrictions and other properties are inherited from the source at mod load time. Legacy difficulty recipes are flattened to normal difficulty when exporting.

## Images and data

Icons are read from installed game files and supplied mod ZIPs/folders. For layered icons, the first layer is shown; unsupported or missing images show a placeholder. Item searches use internal prototype names, with hyphens treated as spaces.

Each load uses a separate `.cache/session-*` directory beside the app. The app does not change your game's configuration, saves, or mod list. These cache directories hold copied mods, Factorio logs and data dumps; you can remove `.cache` when the app is closed. The app folder must be writable. Errors include the loader log location. Supplied mods run through Factorio's normal data stage.

## Verify

```powershell
python -m unittest -v
$env:FACTORIO_TEST_INSTALL = '<your Factorio installation folder>'
python -m unittest -v
```

The optional engine tests load exported ZIPs with Factorio and check recipe edits, new items and bundled icons, new and edited technologies, unlock behavior, and updated mods retaining earlier changes. Machine tests also place a new machine, craft an allowed recipe, reject an unselected recipe, and mine it back into its item in an actual Factorio save/benchmark run. The UI workflow test uses `.cache/test-catalog.json` from the original loader verification when available, otherwise it skips.

Implementation references: [Factorio command-line parameters](https://wiki.factorio.com/Command_line_parameters) and [Recipe prototype documentation](https://lua-api.factorio.com/latest/prototypes/RecipePrototype.html).
