"""PyTarkBuddy GUI. Run: python gui/app.py

Flat dark chrome borrowed from Tarkbot's gui/theme.py so the two look like the same toolkit.
No backdrop photo and no art here, just the palette, the condensed font and spaced caps.
"""
import ctypes
import json
import os
import sys
import tkinter as tk
from pathlib import Path
from tkinter import font as tkfont

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # ponytail: so `python gui/app.py` works
import audio  # noqa: E402
import macros  # noqa: E402
from audio import LEVELS, devices  # noqa: E402

APPDATA = Path(os.environ.get('APPDATA', Path.home()))
SETTINGS = APPDATA / 'PyTarkBuddy' / 'settings.json'
# Where settings lived when the app was called PyTarkAudio. Read once, if the new file is not
# there yet, so the rename does not cost anyone their device picks.
OLD_SETTINGS = APPDATA / 'PyTarkAudio' / 'settings.json'
# Window and taskbar icon. gui/pytarkbuddy.svg is the source: redraw the svg and re-run
# scripts/make_icon.py rather than editing the ico.
ICON = Path(__file__).parent / 'pytarkbuddy.ico'

WINDOW = (560, 660)
# Our own title bar, since the system one is gone. Darker than anything below it, so it reads
# as chrome rather than as part of the app.
TITLEBAR = 30
TITLEBAR_BG = '#0d0e0d'
CLOSE = '#8a4a4a'      # the close X, dim until hovered
CLOSE_HOT = '#d05a5a'

# Muted, matte, nothing pure white. Same values as Tarkbot's theme.
BG = '#101110'
INK = '#d8d7d2'        # primary text
INK_DIM = '#8f928f'    # labels and secondary text
INK_FAINT = '#5c5f5c'  # separators and disabled text
LINE = '#3b3d3b'       # borders and rules
PLATE = '#1d1f20'      # button and dropdown faces
PLATE_HOT = '#2b2e2f'  # under the cursor
RUNNING = '#6f8e58'
ERROR = '#944848'
STOPPED = '#6d706d'

# The meter. Bars are coloured by how loud they are, so a gunshot reads at a glance:
# quiet stays the running green, loud goes warm.
METER = 88             # canvas height
METER_TRACK = '#191b19'  # the unlit part of a bar, so it reads as a meter when silent
METER_BANDS = ('#5c7a4a', '#8f9a4e', '#b08a4a')  # calm -> warm, picked by level
FPS_MS = 33

PAD = 28
# ponytail: the list does not scroll, so it is capped at what the window can show. If anyone
# ever wants more than this many macros, that is when the page earns a scrollbar.
MAX_MACROS = 8
# Windows ships Bahnschrift, a DIN condensed and exactly the right register. The rest are
# fallbacks for a machine that does not have it.
FONT_STACK = ('Bahnschrift SemiCondensed', 'Bahnschrift', 'Segoe UI Semilight', 'Segoe UI')


def spaced(text):
    """Letter-spacing, which tk fonts do not do, faked for the headings that want it."""
    return ' '.join(text)


def font_family(root):
    """The first font in the stack this machine actually has."""
    available = {name.lower() for name in tkfont.families(root)}
    return next((n for n in FONT_STACK if n.lower() in available), 'TkDefaultFont')


def claim_taskbar_identity(app_id='pytarkbuddy'):
    """Make the taskbar show our icon instead of python.exe's.

    Windows groups taskbar buttons by AppUserModelID, and from source that id is python.exe,
    so the button shows the Python logo no matter what the window icon says.
    """
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(app_id)
    except (AttributeError, OSError):
        pass  # not Windows, or an old shell32. A wrong icon is not worth failing to open over.


def strip_titlebar(root):
    """Drop the system title bar but keep the taskbar button and alt-tab entry.

    overrideredirect takes the frame and the taskbar button with it, which would strand the
    window behind fullscreen Tarkov with no way back. Clearing WS_EX_TOOLWINDOW and setting
    WS_EX_APPWINDOW puts the button back, and the window has to be hidden and reshown for
    Windows to notice the new style at all.
    """
    GWL_EXSTYLE, WS_EX_TOOLWINDOW, WS_EX_APPWINDOW = -20, 0x00000080, 0x00040000
    root.overrideredirect(True)
    root.update_idletasks()
    user32 = ctypes.windll.user32
    hwnd = user32.GetParent(root.winfo_id()) or root.winfo_id()
    style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
    user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style & ~WS_EX_TOOLWINDOW | WS_EX_APPWINDOW)
    root.withdraw()
    root.after(10, root.deiconify)


def build_titlebar(root, font, close):
    """Our own title bar. It has to *look* draggable, not just be draggable.

    A bare header the user has to discover by accident is the same as no title bar at all, so
    this carries the three things people already read as one: the app mark on the left, the
    close on the right, and a move cursor the moment you hover it.
    """
    width = WINDOW[0]
    bar = tk.Canvas(root, width=width, height=TITLEBAR, bg=TITLEBAR_BG,
                    highlightthickness=0, bd=0, cursor='fleur')
    bar.pack()
    bar.create_line(0, TITLEBAR - 1, width, TITLEBAR - 1, fill=LINE)

    left = PAD
    if ICON.is_file():
        from PIL import Image, ImageTk

        # Held on the canvas or tk collects it and the bar comes up blank.
        bar.icon = ImageTk.PhotoImage(Image.open(ICON).resize((16, 16), Image.LANCZOS))
        bar.create_image(left, TITLEBAR // 2, image=bar.icon, anchor='w')
        left += 24
    bar.create_text(left, TITLEBAR // 2 + 1, anchor='w', text=spaced('PYTARKBUDDY'),
                    fill=INK_FAINT, font=font)

    x = bar.create_text(width - PAD, TITLEBAR // 2, text='✕', fill=CLOSE, font=font,
                        tags='close')
    # after_idle, not close() straight away: destroying the canvas from inside its own event
    # handler corrupts Tcl's heap. Let the click finish dispatching first.
    bar.tag_bind('close', '<Button-1>', lambda _: root.after_idle(close))
    # The bar's own cursor is the move one, which is wrong over a button: swap it on hover, or
    # the X reads as one more place to drag from.
    for event, colour, cursor in (('<Enter>', CLOSE_HOT, 'hand2'), ('<Leave>', CLOSE, 'fleur')):
        bar.tag_bind('close', event, lambda _, c=colour, cur=cursor: (
            bar.itemconfig(x, fill=c), bar.config(cursor=cur)))

    drag_from = {}

    def drag(event):
        # Canvas coords, so the offset is measured against the window that just moved and the
        # pointer lands back on the same pixel. Screen coords would compound the delta.
        if drag_from:
            root.geometry(f'+{root.winfo_x() + event.x - drag_from["x"]}'
                          f'+{root.winfo_y() + event.y - drag_from["y"]}')

    bar.bind('<Button-1>', lambda e: drag_from.update(x=e.x, y=e.y), add='+')
    bar.bind('<B1-Motion>', drag, add='+')
    return bar


def load():
    for path in (SETTINGS, OLD_SETTINGS):
        try:
            return json.loads(path.read_text())
        except (OSError, ValueError):  # missing, or someone hand-edited it into nonsense
            continue
    return {}


def save(**values):
    SETTINGS.parent.mkdir(parents=True, exist_ok=True)
    SETTINGS.write_text(json.dumps(values, indent=2))


def main():
    claim_taskbar_identity()
    root = tk.Tk()
    root.title('PyTarkBuddy')
    if ICON.is_file():
        root.iconbitmap(default=ICON)  # default= so dialogs inherit it, not just this window
    root.configure(bg=BG)
    root.geometry('%dx%d' % WINDOW)
    root.resizable(False, False)

    family = font_family(root)
    fonts = {'title': (family, 20), 'sub': (family, 10), 'caption': (family, 9),
             'value': (family, 10), 'status': (family, 11), 'plate': (family, 11),
             'small': (family, 9)}
    saved = load()

    build_titlebar(root, fonts['small'], lambda: close())  # packed first, so it sits on top

    def rule(parent, pady):
        tk.Frame(parent, bg=LINE, height=1).pack(fill='x', padx=PAD, pady=pady)

    tk.Label(root, text=spaced('PYTARKBUDDY'), bg=BG, fg=INK, font=fonts['title'],
             anchor='w').pack(fill='x', padx=PAD, pady=(22, 0))
    tk.Label(root, text='hear the small things.', bg=BG, fg=INK_FAINT, font=fonts['sub'],
             anchor='w').pack(fill='x', padx=PAD)

    # The tab strip, and one frame per tab. Only the selected frame is packed, so switching is
    # pack_forget and pack rather than two sets of widgets fighting over the same rows.
    strip = tk.Frame(root, bg=BG)
    strip.pack(fill='x', padx=PAD, pady=(18, 0))
    pages = {name: tk.Frame(root, bg=BG) for name in ('audio', 'macros')}
    tabs = {}

    def show(name):
        for other, page in pages.items():
            page.pack_forget()
            tabs[other].config(bg=PLATE_HOT if other == name else PLATE,
                               fg=INK if other == name else INK_DIM)
        pages[name].pack(fill='both', expand=True)

    for name, caption in (('audio', 'AUDIO'), ('macros', 'MACROS')):
        tabs[name] = tk.Button(strip, text=spaced(caption), command=lambda n=name: show(n),
                               bg=PLATE, fg=INK_DIM, activebackground=PLATE_HOT,
                               activeforeground=INK, font=fonts['plate'], bd=0, relief='flat',
                               highlightthickness=1, highlightbackground=LINE, width=11, pady=4,
                               cursor='hand2')
        tabs[name].pack(side='left', padx=(0, 8))
    rule(root, (18, 0))

    page = pages['audio']

    def dropdown(caption, values, current, command):
        """A spaced caption over a flat OptionMenu. The only real control style here."""
        tk.Label(page, text=spaced(caption), bg=BG, fg=INK_FAINT, font=fonts['caption'],
                 anchor='w').pack(fill='x', padx=PAD, pady=(16, 4))
        var = tk.StringVar(value=current)
        menu = tk.OptionMenu(page, var, *values, command=command)
        menu.config(bg=PLATE, fg=INK, activebackground=PLATE_HOT, activeforeground=INK,
                    highlightthickness=1, highlightbackground=LINE, highlightcolor=LINE,
                    bd=0, relief='flat', font=fonts['value'], anchor='w', width=1,
                    padx=8, pady=3, indicatoron=False, direction='below')
        menu['menu'].config(bg=PLATE, fg=INK, activebackground=PLATE_HOT, activeforeground=INK,
                            bd=0, relief='flat', font=fonts['value'])
        menu.pack(fill='x', padx=PAD)
        return var

    names = devices() or ['(no devices found)']

    def pick(key, default):
        return saved[key] if saved.get(key) in names else default

    eq = dropdown('EQ LEVEL', list(LEVELS),
                  saved['level'] if saved.get('level') in LEVELS else 'Medium',
                  lambda _: on_level())
    capture = dropdown('TARKOV OUTPUT  /  POINT THE GAME HERE', names,
                       pick('capture', names[0]), lambda _: remember())
    listen = dropdown('YOUR HEADPHONES  /  WHERE YOU ACTUALLY LISTEN', names,
                      pick('listen', names[-1]), lambda _: remember())

    tk.Label(page, text=spaced('LIVE SPECTRUM'), bg=BG, fg=INK_FAINT, font=fonts['caption'],
             anchor='w').pack(fill='x', padx=PAD, pady=(20, 4))
    meter = tk.Canvas(page, height=METER, bg=BG, highlightthickness=0, bd=0)
    meter.pack(fill='x', padx=PAD)
    # Rectangles are made once and moved every frame. Deleting and recreating 56 canvas items
    # 30 times a second is how you make tk flicker.
    width = WINDOW[0] - 2 * PAD
    gap = 3
    bar_w = (width - gap * (audio.BANDS - 1)) / audio.BANDS
    tracks = [meter.create_rectangle(i * (bar_w + gap), 0, i * (bar_w + gap) + bar_w, METER,
                                     fill=METER_TRACK, outline='') for i in range(audio.BANDS)]
    bars = [meter.create_rectangle(0, 0, 0, 0, fill=METER_BANDS[0], outline='')
            for _ in range(audio.BANDS)]
    del tracks  # placed once, never touched again

    def plate(parent, text, command, width=9, **pack):
        """The one button style. Everything clickable that is not a tab is one of these."""
        button = tk.Button(parent, text=spaced(text), command=command, bg=PLATE, fg=INK,
                           activebackground=PLATE_HOT, activeforeground=INK,
                           disabledforeground=INK_FAINT, font=fonts['plate'], bd=0,
                           relief='flat', highlightthickness=1, highlightbackground=LINE,
                           width=width, pady=4, cursor='hand2')
        button.pack(**(pack or {'side': 'right', 'padx': (8, 0)}))
        return button

    def indicator(parent):
        """Lamp plus words, side by side. Returns the writer that keeps the two agreeing."""
        lamp = tk.Canvas(parent, width=12, height=12, bg=BG, highlightthickness=0)
        dot = lamp.create_oval(1, 1, 11, 11, fill=STOPPED, outline='')
        lamp.pack(side='left')
        words = tk.Label(parent, text='', bg=BG, fg=STOPPED, font=fonts['status'])
        words.pack(side='left', padx=(10, 0))

        def write(text, colour):
            lamp.itemconfig(dot, fill=colour)
            words.config(text=spaced(text.upper()), fg=colour)
        return write

    rule(page, (24, 0))
    footer = tk.Frame(page, bg=BG)
    footer.pack(fill='x', padx=PAD, pady=18)
    set_status = indicator(footer)

    stop_button = plate(footer, 'STOP', lambda: stop())
    start_button = plate(footer, 'START', lambda: start())

    # ponytail: the audio thread reads this dict, never a tk widget (tkinter isn't thread-safe)
    live = {'level': eq.get(), 'streams': None,
            'macros': macros.clean(saved.get('macros')), 'engine': None, 'recording': None}

    # ---------------------------------------------------------------- macros page
    page = pages['macros']
    tk.Label(page, text=spaced('WHILE I HOLD  /  IT RUNS'), bg=BG, fg=INK_FAINT,
             font=fonts['caption'], anchor='w').pack(fill='x', padx=PAD, pady=(16, 2))
    tk.Label(page, text='a key is held until you let the trigger go, unless it says TAP.  '
                        'click a key for hold / tap, right-click it for a pause after it.',
             bg=BG, fg=INK_FAINT, font=fonts['small'], anchor='w',
             wraplength=WINDOW[0] - PAD * 2, justify='left').pack(fill='x', padx=PAD, pady=(0, 6))
    rows = tk.Frame(page, bg=BG)
    rows.pack(fill='x', padx=PAD)
    add_button = plate(page, 'ADD MACRO', lambda: add(), width=18,
                       anchor='w', padx=PAD, pady=(10, 0))
    macro_footer = tk.Frame(page, bg=BG)
    set_macro_status = None  # built at the foot of the page, below

    def draw_rows():
        """Throw the list away and redraw it. Eight rows is not worth diffing."""
        for child in rows.winfo_children():
            child.destroy()
        for i, bind in enumerate(live['macros']):
            row = tk.Frame(rows, bg=BG)
            row.pack(fill='x', pady=2)
            plate(row, macros.label(bind['trigger']) or 'SET KEY',
                  lambda n=i: record_trigger(n), width=14, side='left')
            tk.Label(row, text='  →  ', bg=BG, fg=INK_FAINT,
                     font=fonts['small']).pack(side='left')
            plate(row, '✕', lambda n=i: remove(n), width=2, side='right')
            if not bind['keys']:
                plate(row, 'SET KEYS', lambda n=i: record_keys(n), width=18, side='left')
                continue
            # Re-record lives on its own small plate now that the keys themselves are buttons.
            plate(row, '⟲', lambda n=i: record_keys(n), width=2, side='right')
            for j, key in enumerate(bind['keys']):
                # width=0 so each key takes only the room its own label needs; a run of six
                # would not fit the window at a fixed width.
                chip = plate(row, macros.step_label(key), lambda n=i, m=j: toggle_tap(n, m),
                             width=0, side='left', padx=(0, 4))
                chip.bind('<Button-3>', lambda _, n=i, m=j: cycle_wait(n, m))
        add_button.config(state='normal' if len(live['macros']) < MAX_MACROS else 'disabled')

    def add():
        live['macros'].append({'trigger': '', 'keys': []})
        draw_rows()
        remember()

    def remove(i):
        live['macros'].pop(i)
        draw_rows()
        remember()

    def edit_key(i, j, **changes):
        """Change one key of one macro. Editing while it is running would fire it under you."""
        stop_macros()
        live['macros'][i]['keys'][j].update(changes)
        draw_rows()
        remember()

    def toggle_tap(i, j):
        edit_key(i, j, tap=not live['macros'][i]['keys'][j]['tap'])

    def cycle_wait(i, j):
        current = live['macros'][i]['keys'][j]['wait']
        # next-one-up rather than an index, so a hand-edited pause that is not one of ours still
        # has somewhere to go from here.
        edit_key(i, j, wait=next((w for w in macros.WAITS if w > current), macros.WAITS[0]))

    def recording(text):
        """Editing while the listeners are up would fire the macro you are trying to change."""
        stop_macros()
        set_macro_status(text, RUNNING)

    def landed(i, keys, trigger=None):
        """Back on tk's thread. pynput's callbacks run on their own and must not touch widgets."""
        if trigger is not None:
            live['macros'][i]['trigger'] = trigger
        live['macros'][i]['keys'] = keys
        draw_rows()
        remember()
        set_macro_status('Off', STOPPED)

    def record_trigger(i):
        recording('Press the key or mouse button')
        macros.capture_one(lambda name: root.after(
            0, lambda: landed(i, live['macros'][i]['keys'], trigger=name)))

    def record_keys(i):
        recording('Type the keys, Esc when done')
        keys = []
        macros.capture_keys(lambda name: keys.append(macros.step(name)),
                            lambda: root.after(0, lambda: landed(i, keys)))

    rule(page, (24, 0))
    macro_footer.pack(fill='x', padx=PAD, pady=18)
    set_macro_status = indicator(macro_footer)
    macros_off = plate(macro_footer, 'OFF', lambda: stop_macros())
    macros_on = plate(macro_footer, 'ON', lambda: start_macros())

    def start_macros():
        live['engine'] = macros.Macros(live['macros'])
        live['engine'].start()
        if not live['engine'].listeners:  # nothing finished enough to listen for
            live['engine'] = None
            set_macro_status('Nothing bound yet', ERROR)
            return
        macros_on.config(state='disabled')
        macros_off.config(state='normal')
        set_macro_status(f'On: {len(live["engine"].binds)} bound', RUNNING)

    def stop_macros():
        if live['engine']:
            live['engine'].stop()
            live['engine'] = None
        macros_on.config(state='normal')
        macros_off.config(state='disabled')
        set_macro_status('Off', STOPPED)

    def paint():
        """Redraw the meter from the audio thread's array. The only place it is read."""
        levels = audio.spectrum()
        if not live['streams']:
            levels *= 0.8  # nothing is feeding it, so let the bars fall instead of freezing
        for i, bar in enumerate(bars):
            v = float(levels[i])
            x = i * (bar_w + gap)
            meter.coords(bar, x, METER - max(v * METER, 1.0), x + bar_w, METER)
            meter.itemconfig(bar, fill=METER_BANDS[min(int(v * len(METER_BANDS)),
                                                       len(METER_BANDS) - 1)])
        root.after(FPS_MS, paint)

    def remember():
        save(level=eq.get(), capture=capture.get(), listen=listen.get(),
             macros=live['macros'])

    def on_level():
        live['level'] = eq.get()
        remember()
        if live['streams']:
            set_status(f'Running: {live["level"]}', RUNNING)

    def start():
        if live['streams']:
            return
        try:
            live['streams'] = audio.run(capture.get(), listen.get(),
                                        level=lambda: live['level'])
        except Exception as e:  # bad pick, device busy, sample-rate mismatch
            set_status(str(e)[:52], ERROR)
            return
        start_button.config(state='disabled')
        stop_button.config(state='normal')
        on_level()

    def stop():
        if live['streams']:
            audio.stop(live['streams'])
            live['streams'] = None
        start_button.config(state='normal')
        stop_button.config(state='disabled')
        set_status('Stopped', STOPPED)

    def close():
        """The only way out now that there is no system X. Never leave streams running."""
        stop()
        stop_macros()  # the keyboard hook outlives the window if nobody takes it down
        root.destroy()

    stop()  # the initial state is the stopped state, buttons included
    stop_macros()
    draw_rows()
    show('audio')
    paint()  # runs for the life of the window, idle or not
    root.protocol('WM_DELETE_WINDOW', close)  # alt-F4 still reaches us
    strip_titlebar(root)  # last, so the window only appears once it has something to show
    root.mainloop()


if __name__ == '__main__':
    main()
