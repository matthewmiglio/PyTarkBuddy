"""Freeze the app into a Windows onedir build and wrap it in an MSI.

    python scripts/setup_msi.py bdist_msi --target-version v0.0.0-local

Run from the repo root. The version comes off the git tag in CI, names the artifact, and is
written to the gitignored __version__ file beside the exe, which version.py reads back at runtime
so update.py can tell whether the newest release is newer than us. Nothing tracked in git holds
a version number.
"""
import re
import sys
from pathlib import Path

from cx_Freeze import Executable, setup

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

NAME = 'PyTarkBuddy'
AUTHOR = 'Matthew Miglio'
DESCRIPTION = 'Dynamic range compressor for Escape From Tarkov'
COPYRIGHT = '2026 Matthew Miglio'
UPGRADE_CODE = '{46c6e71b-3ff4-4bb9-9170-bee381f9e15a}'  # fresh GUID, never reuse another app's
ICON = ROOT / 'gui' / 'pytarkbuddy.ico'  # generated from gui/pytarkbuddy.svg by scripts/make_icon.py

try:
    _idx = sys.argv.index('--target-version')
    VERSION = sys.argv[_idx + 1]
    del sys.argv[_idx:_idx + 2]
except (ValueError, IndexError):
    VERSION = 'v0.0.0'

version_file = ROOT / '__version__'
version_file.write_text(VERSION, encoding='utf-8')

# Windows Installer only accepts a numeric a.b.c ProductVersion, so a tag like v1.2.3-rc1 has
# to be trimmed down to 1.2.3. The full tag still names the file.
_match = re.search(r'\d+(\.\d+){0,2}', VERSION)
PRODUCT_VERSION = _match.group() if _match else '0.0.0'

build_exe_options = {
    # pynput picks its platform backend with importlib.import_module('._win32', package) at
    # runtime, which a static scan cannot see, so the frozen exe shipped without it and died on
    # launch with 'this platform is not supported'. Naming the package pulls in every submodule.
    'packages': ['pynput'],
    # Optional imports cx_Freeze finds by scanning site-packages. Nothing here imports any of
    # them, and they are most of the build size if left in.
    'excludes': [
        'test', 'tests', 'setuptools', 'matplotlib',
        'IPython', 'ipykernel', 'jupyter_client', 'jupyter_core', 'jedi', 'debugpy', 'zmq',
        'gevent', 'greenlet', 'dill', 'cloudpickle', 'dns', 'defusedxml', 'lib2to3', 'curses',
    ],
    # gui/ is a namespace package and frozen modules live under lib/, so the icon has to land
    # beside its own module: app.py resolves it through Path(__file__).parent at runtime.
    'include_files': [
        (ICON, 'lib/gui/pytarkbuddy.ico'),
        (version_file, '__version__'),  # version.py reads this next to the exe when frozen
    ],
    'include_msvcr': True,
}

bdist_msi_options = {
    'upgrade_code': UPGRADE_CODE,
    'add_to_path': False,
    # cx_Freeze 8.4+ dropped bdist_msi's target_version; without these two the MSI ships as
    # v0.0.0 no matter what --target-version said.
    'product_version': PRODUCT_VERSION,
    'output_name': f'pytarkbuddy-{VERSION}-win64.msi',
    # Per-user install: all_users=False makes it ALLUSERS=2 + MSIINSTALLPERUSER=1, so it lands
    # without elevation, and update.py can then apply a newer MSI silently with msiexec /quiet.
    # cx_Freeze still defaults the dir to ProgramFiles even per-user, so LocalAppData is set by
    # hand or the install would want admin after all.
    'all_users': False,
    'initial_target_dir': rf'[LocalAppDataFolder]\{NAME}',
    'summary_data': {'author': AUTHOR, 'comments': DESCRIPTION},
}

setup(
    name=NAME,
    version=PRODUCT_VERSION,
    description=DESCRIPTION,
    executables=[Executable(
        script=ROOT / 'main.py',
        base='Win32GUI',  # no console window behind the GUI
        # Elevated, and the UAC prompt on every launch is the price. Windows drops synthetic
        # keystrokes sent from a normal process into a higher-integrity window, so an unelevated
        # build's macros fire and go nowhere while a game like Tarkov is focused. Audio needs
        # none of this; macros do.
        uac_admin=True,
        target_name='pytarkbuddy.exe',
        icon=ICON,
        shortcut_name=f'{NAME} {VERSION}',
        shortcut_dir='DesktopFolder',
        copyright=COPYRIGHT,
    )],
    options={'build_exe': build_exe_options, 'bdist_msi': bdist_msi_options},
)
