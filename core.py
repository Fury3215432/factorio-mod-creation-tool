"""Factorio engine integration and lossless recipe editing (standard library only)."""
import copy
import json
import math
import re
import shutil
import subprocess
import uuid
import zipfile
import hashlib
import difflib
from pathlib import Path


def read_mod(path):
    """Read a mod without extracting ZIP members to the filesystem."""
    path = Path(path)
    if path.is_dir():
        files = {p.relative_to(path).as_posix(): p.read_bytes() for p in path.rglob('*') if p.is_file()}
    else:
        with zipfile.ZipFile(path) as archive:
            infos = [n for n in archive.namelist() if n.count('/') == 1 and n.endswith('/info.json')]
            if len(infos) != 1:
                raise ValueError('The ZIP must contain one mod folder with info.json.')
            prefix = infos[0].split('/')[0] + '/'
            files = {n[len(prefix):]: archive.read(n) for n in archive.namelist() if n.startswith(prefix) and not n.endswith('/')}
    for name in files:
        if name.startswith(('/', '\\')) or '\\' in name or ':' in name or '..' in name.split('/'):
            raise ValueError('Unsafe path in mod: ' + name)
    info = json.loads(files['info.json'].decode('utf-8-sig'))
    return info, files


def loaded_mods(directory):
    result = []
    for path in sorted(Path(directory).iterdir()):
        if (path.is_dir() and (path / 'info.json').exists()) or path.suffix.lower() == '.zip':
            info, _ = read_mod(path)
            result.append((path, info))
    return result


def mod_archive_name(info):
    if not re.fullmatch(r'[a-zA-Z0-9_-]+', info['name']) or not re.fullmatch(r'\d+\.\d+\.\d+', info['version']):
        raise ValueError('Mod name or version is invalid.')
    return info['name'] + '_' + info['version'] + '.zip'


def export_mod(destination, recipe, new_name, seconds, enabled, game_root, mods_directory, target=None, mod_name=None, bundle_code=None, bundle_assets=None, change_details=None):
    """Build a complete mod ZIP, preserving a selected mod's original files."""
    code = bundle_code if bundle_code is not None else recipe.export(new_name, seconds, enabled)
    mods = loaded_mods(mods_directory)
    if target is None:
        version = json.loads((Path(game_root) / 'data/base/info.json').read_text(encoding='utf-8-sig'))['version']
        info = {'name': mod_name or ('recipe-studio-' + new_name), 'version': '1.0.0',
                'title': 'Factorio Mod Creation Tool: ' + new_name, 'author': 'FuryziN',
                'factorio_version': '.'.join(version.split('.')[:2]),
                'description': 'Custom recipes, items, technologies and machines exported by Factorio Mod Creation Tool by FuryziN.', 'dependencies': ['base']}
        files = {}
    else:
        info, files = read_mod(target)
    original_files = dict(files)
    # Depend on all loaded mods: any one of them may define a source prototype
    # or modify it at the final-fixes stage. Preserve existing version constraints.
    dependencies = info.get('dependencies', ['base'])
    if isinstance(dependencies, str):
        dependencies = [dependencies]
    dependencies = list(dependencies)
    for _, dependency in mods:
        name = dependency['name']
        if name == info['name']:
            continue
        pattern = r'^\s*(?:\(\?\)|[?!~])?\s*' + re.escape(name) + r'(?=\s|[<>=]|$)'
        matches = [d for d in dependencies if re.search(pattern, d)]
        if any(d.lstrip().startswith('!') for d in matches):
            raise ValueError('Selected mod declares an incompatibility with loaded mod ' + name)
        # Upgrade optional/no-order dependencies, keeping their constraints.
        dependencies = [re.sub(r'^\s*(?:\(\?\)|[?~])\s*', '', d) if d in matches else d for d in dependencies]
        if not matches:
            dependencies.append(name + ' >= ' + dependency['version'])
    info['dependencies'] = dependencies
    filename = mod_archive_name(info)
    if Path(destination).name != filename:
        raise ValueError('Factorio requires this ZIP filename: ' + filename)
    unique = 'recipe-studio-' + uuid.uuid4().hex
    calls = []
    original = files.get('data-final-fixes.lua')
    if original:
        files[unique + '-original.lua'] = original
        calls.append('require(' + lua(unique + '-original') + ')')
    files[unique + '.lua'] = code.encode('utf-8')
    for name, data in (bundle_assets or {}).items():
        files[name] = data
    files[unique + '.lua'] = code.replace('__RECIPE_STUDIO_MOD__', '__' + info['name'] + '__').encode('utf-8')
    calls.append('require(' + lua(unique) + ')')
    files['data-final-fixes.lua'] = ('-- Generated recipe loader\n' + '\n'.join(calls) + '\n').encode('utf-8')
    files['info.json'] = json.dumps(info, indent=2, ensure_ascii=False).encode('utf-8')
    report = None
    if mods or target:
        changes = []
        for name in sorted(set(original_files) | set(files)):
            before, after = original_files.get(name), files.get(name)
            if before == after:
                continue
            change = {'path': name, 'operation': 'added' if before is None else ('removed' if after is None else 'modified'),
                      'before_sha256': hashlib.sha256(before).hexdigest() if before is not None else None,
                      'after_sha256': hashlib.sha256(after).hexdigest() if after is not None else None}
            if name.endswith(('.lua', '.json', '.txt', '.cfg')):
                try:
                    change['diff'] = ''.join(difflib.unified_diff((before or b'').decode('utf-8-sig').splitlines(True), (after or b'').decode('utf-8-sig').splitlines(True), fromfile='original/' + name, tofile='exported/' + name))
                except UnicodeDecodeError:
                    pass
            changes.append(change)
        report = {'format': 1, 'target_mod': info['name'], 'original_mod': str(target) if target else None,
                  'baseline': 'Resolved Factorio prototypes loaded at session start (base game plus supplied mods). File changes compare against the selected original mod; a new mod has no original files.',
                  'loaded_mods': [{'name': i['name'], 'version': i['version']} for _, i in mods],
                  'prototype_changes': change_details or [], 'file_changes': changes,
                  'report_note': 'The report itself is excluded from its file diff to avoid a recursive self-diff. Unlisted original files are unchanged.'}
        report_data = json.dumps(report, indent=2, ensure_ascii=False).replace('__RECIPE_STUDIO_MOD__', '__' + info['name'] + '__').encode('utf-8')
        files['recipe-studio-changes.json'] = report_data
    root = filename[:-4]
    destination = Path(destination)
    temporary = destination.with_name(destination.name + '.' + uuid.uuid4().hex + '.tmp')
    try:
        with zipfile.ZipFile(temporary, 'w', zipfile.ZIP_DEFLATED) as archive:
            for name, data in files.items():
                archive.writestr(root + '/' + name, data)
        temporary.replace(destination)
        if report is not None:
            destination.with_name(destination.stem + '.changes.json').write_bytes(report_data)
    finally:
        temporary.unlink(missing_ok=True)
    return info


def lua(value):
    if value is None:
        return 'nil'
    if isinstance(value, bool):
        return 'true' if value else 'false'
    if isinstance(value, str):
        return '"' + ''.join(('\\%03d' % ord(c)) if ord(c) < 32 else ('\\' + c if c in '\\"' else c) for c in value) + '"'
    if isinstance(value, (int, float)):
        if not math.isfinite(value):
            raise ValueError('Non-finite number in recipe')
        return str(value)
    if isinstance(value, list):
        return '{' + ', '.join(map(lua, value)) + '}'
    return '{' + ', '.join('[' + lua(k) + '] = ' + lua(v) for k, v in value.items()) + '}'


def entries(recipe, kind):
    source = recipe.get('normal', recipe)
    values = source.get(kind, [])
    if kind == 'results' and source.get('result'):
        values = [{'name': source['result'], 'amount': source.get('result_count', 1)}]
    return [dict(v, type=v.get('type', 'item')) if isinstance(v, dict)
            else {'name': v[0], 'amount': v[1], 'type': 'item'} for v in values]


class Catalog:
    def __init__(self, raw):
        self.raw = raw
        self.items = {}
        for group, prototypes in raw.items():
            for name, proto in prototypes.items():
                if group == 'fluid' or 'stack_size' in proto:
                    self.items[(('fluid' if group == 'fluid' else 'item'), name)] = proto
        self.recipes = raw.get('recipe', {})
        self.by_product = {}
        for name, recipe in self.recipes.items():
            for product in entries(recipe, 'results'):
                self.by_product.setdefault((product['type'], product['name']), []).append(name)


class Recipe:
    def __init__(self, name, prototype):
        self.name = name
        self.original = copy.deepcopy(prototype)
        self.ingredients = entries(prototype, 'ingredients')
        self.results = entries(prototype, 'results')

    def export(self, new_name, seconds, enabled, category=None):
        if not re.fullmatch(r'[a-zA-Z0-9_-]+', new_name):
            raise ValueError('Use letters, numbers, hyphens or underscores for the recipe name.')
        seconds = float(seconds)
        if not math.isfinite(seconds) or seconds <= 0:
            raise ValueError('Crafting time must be a positive number.')
        if not self.results:
            raise ValueError('Add at least one result.')
        for group in (self.ingredients, self.results):
            keys = [(e['type'], e['name']) for e in group]
            if len(keys) != len(set(keys)):
                raise ValueError('Combine duplicate items into a single rectangle.')
            for e in group:
                for key in ('amount', 'amount_min', 'amount_max'):
                    if key in e and (not math.isfinite(float(e[key])) or float(e[key]) <= 0):
                        raise ValueError('Quantities must be positive finite numbers.')
                if e['type'] == 'item' and any(float(e[k]) != int(float(e[k])) for k in ('amount', 'amount_min', 'amount_max') if k in e):
                    raise ValueError('Item quantities must be whole numbers.')
        # Clone the live source in the target mod: preserves icons, categories,
        # machine restrictions and future Factorio properties without serializing them.
        q = lua(self.name)
        out = ['-- Generated by Factorio Mod Creation Tool by FuryziN.',
               '-- Place beside data.lua and load with: require("' + new_name + '")',
               '-- Requires the base game and any mods defining this recipe/items.',
               'local source = assert(data.raw.recipe[' + q + '], "Missing source recipe: " .. ' + q + ')',
               'local recipe = table.deepcopy(source)',
               'recipe.name = ' + lua(new_name),
               'recipe.normal = nil', 'recipe.expensive = nil',
               'recipe.result = nil', 'recipe.result_count = nil',
               'recipe.ingredients = ' + lua(self.ingredients),
               'recipe.results = ' + lua(self.results),
               'recipe.energy_required = ' + lua(seconds),
               'recipe.enabled = ' + lua(enabled),
               'recipe.main_product = ' + lua(self.results[0]['name']),
               'data:extend({recipe})', '']
        if 'normal' in self.original:
            # Lift legacy difficulty fields so crafting category and other settings survive.
            out.insert(6, 'for key, value in pairs(source.normal or {}) do recipe[key] = table.deepcopy(value) end')
        if category is not None:
            if not re.fullmatch(r'[a-zA-Z0-9_-]+', category):
                raise ValueError('Choose a valid recipe category.')
            out.insert(-2, 'recipe.category = ' + lua(category))
            out.insert(-2, 'recipe.categories = nil')
        return '\n'.join(out)


def load_game(installation, selected_mods, workspace, track_mod_content=False):
    root, workspace = Path(installation), Path(workspace)
    exe = root / 'bin' / 'x64' / 'factorio.exe'
    if not exe.exists() or not (root / 'data' / 'base' / 'info.json').exists():
        raise ValueError('Select the Factorio installation folder containing bin and data.')
    workspace.mkdir(parents=True, exist_ok=True)
    mods = workspace / 'mods'
    mods.mkdir()
    names = {'base'}
    for selected in selected_mods:
        path = Path(selected)
        sources = [path] if path.is_file() or (path / 'info.json').exists() else list(path.iterdir())
        for source in sources:
            if source.is_dir() and (source / 'info.json').exists():
                info = json.loads((source / 'info.json').read_text(encoding='utf-8-sig'))
                dest = mods / (info['name'] + '_' + info['version'])
                if not dest.exists():
                    shutil.copytree(source, dest)
            elif source.suffix.lower() == '.zip':
                with zipfile.ZipFile(source) as z:
                    infos = [n for n in z.namelist() if n.count('/') == 1 and n.endswith('/info.json')]
                    if not infos:
                        raise ValueError(f'No mod info.json in {source.name}')
                    info = json.loads(z.read(infos[0]).decode('utf-8-sig'))
                shutil.copy2(source, mods / source.name)
            else:
                continue
            names.add(info['name'])
    (mods / 'mod-list.json').write_text(json.dumps({'mods': [{'name': n, 'enabled': True} for n in sorted(names)]}), encoding='utf-8')
    config = workspace / 'config.ini'
    config.write_text('[path]\nread-data=' + (root / 'data').as_posix() + '\nwrite-data=' + workspace.as_posix() + '\n', encoding='utf-8')
    (workspace / 'script-output').mkdir()
    process = subprocess.run([str(exe), '--config', str(config), '--mod-directory', str(mods), '--dump-data'], capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=300, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    (workspace / 'loader.log').write_text(process.stdout + process.stderr, encoding='utf-8')
    dump = workspace / 'script-output' / 'data-raw-dump.json'
    if process.returncode or not dump.exists():
        raise RuntimeError('Factorio could not load the data. Include required dependency mods and close any other Factorio instances.\n\n' + (process.stdout + process.stderr)[-3500:] + '\n\nLog: ' + str(workspace / 'loader.log'))
    catalog = Catalog(json.loads(dump.read_text(encoding='utf-8')))
    if track_mod_content and selected_mods:
        baseline, _, _ = load_game(root, [], workspace / 'base-reference')
        catalog.loaded_items = {key for key, proto in catalog.items.items() if baseline.items.get(key) != proto}
        catalog.loaded_recipes = {name for name, proto in catalog.recipes.items() if baseline.recipes.get(name) != proto}
    return catalog, root, mods
