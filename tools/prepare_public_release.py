"""Build a whitelist-only public source tree and a portable app download."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import struct
import zipfile

ROOT = Path(__file__).resolve().parent.parent
MODULES = ('app.py', 'bulk_items.py', 'bulk_science.py', 'controls.py', 'core.py', 'creations_ui.py',
           'delete_items.py', 'editors.py', 'equations.py', 'flow.py', 'installation.py', 'machine_geometry.py',
           'machine_model.py', 'machine_ui.py', 'ore_model.py', 'pending_ui.py', 'project.py', 'recipe_graph.py',
           'recipe_unlocks.py', 'replace_ingredient.py', 'technology.py', 'ui.py')
DOCUMENTS = ('README.md', 'SECURITY.md', 'THIRD_PARTY_NOTICES.md')
LAUNCHERS = ('Launch Factorio Mod Creation Tool.bat',)
PRIVATE_PARTS = {'.cache', '.studio', '__pycache__', 'output', '.env', '.venv', 'venv', 'node_modules'}
TEXT_SUFFIXES = {'.py', '.md', '.bat', '.html', '.css', '.json', '.ps1', '.yml', '.yaml'}


def clean_png(data):
    if not data.startswith(b'\x89PNG\r\n\x1a\n'):
        raise ValueError('Expected a PNG asset.')
    result = bytearray(data[:8])
    offset = 8
    while offset < len(data):
        size = struct.unpack('>I', data[offset:offset + 4])[0]
        kind = data[offset + 4:offset + 8]
        chunk = data[offset:offset + size + 12]
        if len(chunk) != size + 12:
            raise ValueError('Invalid PNG chunk.')
        if kind in (b'IHDR', b'PLTE', b'tRNS', b'IDAT', b'IEND'):
            result.extend(chunk)
        offset += size + 12
        if kind == b'IEND':
            break
    return bytes(result)


def audit(folder):
    issues = []
    patterns = [re.compile(r'(?<![A-Za-z0-9])[A-Z]:[\\/]', re.I),
                re.compile(r'/(?:Users|home)/[^/\s]+/', re.I),
                re.compile(r'gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}'),
                re.compile(r'AKIA[A-Z0-9]{16}|-----BEGIN [A-Z ]*PRIVATE KEY-----'),
                re.compile(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b')]
    username = os.environ.get('USERNAME', '')
    for path in folder.rglob('*'):
        if not path.is_file() or '.git' in path.relative_to(folder).parts:
            continue
        relative = path.relative_to(folder)
        if set(relative.parts) & PRIVATE_PARTS or path.name == 'repair_mod.py':
            issues.append(str(relative) + ': excluded local content')
        if path.suffix in TEXT_SUFFIXES or path.name in ('.gitignore', 'CODEOWNERS'):
            text = path.read_text(encoding='utf-8')
            for number, line in enumerate(text.splitlines(), 1):
                line = line.replace('noreply@users.noreply.github.com', '')
                if any(pattern.search(line) for pattern in patterns) or (path.name != 'CODEOWNERS' and len(username) >= 3 and re.search(r'\b' + re.escape(username) + r'\b', line, re.I)):
                    issues.append(f'{relative}:{number}: potential private information (value withheld)')
        elif path.suffix == '.png':
            if clean_png(path.read_bytes()) != path.read_bytes():
                issues.append(str(relative) + ': unexpected image metadata')
    if issues:
        raise ValueError('\n'.join(issues))
    return len([p for p in folder.rglob('*') if p.is_file() and '.git' not in p.relative_to(folder).parts])


def verify(folder):
    count = audit(folder)
    manifest = json.loads((folder / 'PUBLIC_MANIFEST.json').read_text(encoding='utf-8-sig'))
    actual = {str(p.relative_to(folder)).replace('\\', '/') for p in folder.rglob('*')
              if p.is_file() and '.git' not in p.relative_to(folder).parts and p.name != 'PUBLIC_MANIFEST.json'}
    if actual != set(manifest):
        raise ValueError('The public directory contains missing or unexpected files. Rebuild a fresh clean copy.')
    for name, expected in manifest.items():
        path = folder / name
        if folder.resolve() not in path.resolve().parents or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise ValueError('A public file changed after preparation: ' + name)
    return count


def prepare(destination):
    destination = destination.resolve()
    publish_root = (ROOT / 'publish').resolve()
    if destination == publish_root or publish_root not in destination.parents:
        raise ValueError('Choose a new subdirectory inside the workspace publish directory.')
    if destination.exists() and any(destination.iterdir()):
        raise ValueError('Destination must be empty. Existing files are never removed.')
    destination.mkdir(parents=True, exist_ok=True)
    names = list(MODULES + DOCUMENTS + LAUNCHERS) + ['.gitignore', '.github/CONTRIBUTING.md']
    names += [p.name for p in ROOT.glob('test_*.py')]
    names += ['tools/prepare_public_release.py', 'tools/publish_github.ps1']
    names += ['docs/index.html', 'docs/style.css', 'docs/.nojekyll']
    for name in names:
        source = ROOT / name
        if not source.is_file():
            raise ValueError('Missing allowed source file: ' + name)
        target = destination / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(source.read_bytes())
    for name in ('app-icon.png', 'default-item-icon.png'):
        target = destination / 'assets' / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(clean_png((ROOT / 'assets' / name).read_bytes()))
    web_icon = destination / 'docs/assets/app-icon.png'
    web_icon.parent.mkdir(parents=True, exist_ok=True)
    web_icon.write_bytes((destination / 'assets/app-icon.png').read_bytes())
    download = destination / 'docs/downloads/factorio-mod-creation-tool.zip'
    download.parent.mkdir(parents=True, exist_ok=True)
    release_files = list(MODULES + DOCUMENTS + LAUNCHERS) + ['assets/app-icon.png', 'assets/default-item-icon.png']
    with zipfile.ZipFile(download, 'w', zipfile.ZIP_DEFLATED) as archive:
        for name in release_files:
            entry = zipfile.ZipInfo('factorio-mod-creation-tool/' + name, date_time=(2020, 1, 1, 0, 0, 0))
            entry.compress_type = zipfile.ZIP_DEFLATED
            entry.external_attr = 0o644 << 16
            archive.writestr(entry, (destination / name).read_bytes())
    count = audit(destination)
    manifest = {str(p.relative_to(destination)).replace('\\', '/'): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in sorted(destination.rglob('*')) if p.is_file()}
    (destination / 'PUBLIC_MANIFEST.json').write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
    print(f'Prepared {count + 1} public files. Privacy scan passed. Local project/cache/mod files were not copied.')
    print('Public source: ' + str(destination))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--destination', type=Path, default=ROOT / 'publish/factorio-mod-creation-tool')
    parser.add_argument('--verify', type=Path)
    args = parser.parse_args()
    if args.verify:
        print(f'Privacy and manifest verification passed for {verify(args.verify.resolve())} files.')
    else:
        prepare(args.destination)
