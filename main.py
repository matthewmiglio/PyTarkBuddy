"""Entry point. Run: python main.py

Exists so the frozen exe and running from source start the same way. cx_Freeze points at this
file; gui/app.py is still runnable on its own.

The update gate goes first: an installed build that finds a newer release hands off to the
updater window and exits without ever opening the main window. From source it is a no-op.
"""
from gui.app import main
from update import boot_gate

if __name__ == '__main__':
    if not boot_gate():
        main()
