"""Entry point. Run: python main.py

Exists so the frozen exe and running from source start the same way. cx_Freeze points at this
file; gui/app.py is still runnable on its own.
"""
from gui.app import main

if __name__ == '__main__':
    main()
