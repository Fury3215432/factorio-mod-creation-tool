"""Find common Factorio installations without embedding a developer's path."""
import os
from pathlib import Path


def find_installation():
    candidates = [Path(value) for name in ('FACTORIO_INSTALL', 'FACTORIO_TEST_INSTALL') if (value := os.environ.get(name))]
    for name in ('ProgramFiles(x86)', 'ProgramFiles'):
        if value := os.environ.get(name):
            candidates.append(Path(value) / 'Steam' / 'steamapps' / 'common' / 'Factorio')
            candidates.append(Path(value) / 'Factorio')
    if os.name == 'nt':
        for letter in 'CDEFGHIJKLMNOPQRSTUVWXYZ':
            candidates.append(Path(letter + ':/') / 'SteamLibrary' / 'steamapps' / 'common' / 'Factorio')
    for candidate in candidates:
        if (candidate / 'bin' / 'x64' / 'factorio.exe').is_file() and (candidate / 'data' / 'base' / 'info.json').is_file():
            return candidate
    return None
