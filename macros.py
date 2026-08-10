"""Key macros: one trigger key or mouse button fires a run of keystrokes.

Sits beside audio.py for the same reason it does: this is the logic, gui/app.py is the face.

The trigger is never swallowed. Right mouse still aims and the macro rides along on top of it,
which is what you want in a game and also half the code of a suppressing hook.
"""
import threading
import time

from pynput import keyboard, mouse

# Games read the hardware queue, and a press and release in the same millisecond can fall
# between two polls and never register. This is the knob to turn if a game misses the odd key.
HOLD = 0.03

_kb = keyboard.Controller()


def key_name(key):
    """A pynput key as the string we store and show: 'a', 'f1', 'shift'."""
    if isinstance(key, keyboard.KeyCode) and key.char:
        return key.char
    return key.name if isinstance(key, keyboard.Key) else str(key)


def to_key(name):
    """The stored string back into something the controller can press."""
    return keyboard.Key.__members__.get(name) or keyboard.KeyCode.from_char(name)


def label(name):
    """The stored string as it reads in the GUI."""
    if not name:
        return ''
    if name.startswith('mouse_'):
        # Short, because spaced caps eat width fast and 'RIGHT MOUSE' does not fit the plate.
        side = name[6:]
        return {'left': 'L', 'right': 'R', 'middle': 'M'}.get(side, side.upper()) + '-MOUSE'
    return name.upper()


def clean(binds):
    """Keep only the rows that are actually shaped like a macro.

    settings.json is a plain file a person can open and edit, so anything from it is guessed
    at rather than trusted.
    """
    out = []
    for bind in binds if isinstance(binds, list) else []:
        if not isinstance(bind, dict):
            continue
        trigger, keys = bind.get('trigger'), bind.get('keys')
        if isinstance(trigger, str) and isinstance(keys, list):
            out.append({'trigger': trigger,
                        'keys': [k for k in keys if isinstance(k, str) and k]})
    return out


def send(names):
    """Press and release each key in turn."""
    for name in names:
        key = to_key(name)
        _kb.press(key)
        time.sleep(HOLD)
        _kb.release(key)
        time.sleep(HOLD)


class Macros:
    """The listeners, running until stop(). Callbacks arrive on pynput's threads, never tk's."""

    def __init__(self, binds):
        self.binds = {b['trigger']: b['keys'] for b in clean(binds) if b['trigger'] and b['keys']}
        self.listeners = []
        self.firing = False

    def _fire(self, trigger):
        keys = self.binds.get(trigger)
        if not keys or self.firing:
            return
        # Sent from a worker, not from here: a keyboard trigger's own output comes straight back
        # through this same hook, so `firing` has to still be up when it does, and a low-level
        # hook that blocks for the length of a macro is one Windows quietly unhooks.
        self.firing = True
        threading.Thread(target=self._send, args=(keys,), daemon=True).start()

    def _send(self, keys):
        try:
            send(keys)
            time.sleep(HOLD)  # slack, so the last injected key lands while we still ignore it
        finally:
            self.firing = False

    def start(self):
        if self.listeners or not self.binds:
            return
        self.listeners = [keyboard.Listener(on_press=lambda k: self._fire(key_name(k))),
                          mouse.Listener(on_click=self._click)]
        for listener in self.listeners:
            listener.start()

    def _click(self, x, y, button, pressed):
        # Named rather than a lambda because returning False from a mouse callback stops the
        # listener, and `pressed and self._fire(...)` does exactly that on every release.
        if pressed:
            self._fire('mouse_' + button.name)

    def stop(self):
        for listener in self.listeners:
            listener.stop()
        self.listeners = []


def capture_one(done):
    """Grab the next key or mouse press, hand its name to done(), then stop listening."""
    listeners = []

    def finish(name):
        for listener in listeners:
            listener.stop()
        done(name)

    listeners += [keyboard.Listener(on_press=lambda k: finish(key_name(k))),
                  mouse.Listener(on_click=lambda x, y, b, p: finish('mouse_' + b.name) if p else None)]
    for listener in listeners:
        listener.start()
    return listeners


def capture_keys(on_key, done):
    """Collect keys until Esc. Esc itself cannot be recorded; it is the way out."""
    def press(key):
        if key == keyboard.Key.esc:
            done()
            return False
        on_key(key_name(key))

    listener = keyboard.Listener(on_press=press)
    listener.start()
    return listener


def _self_check():
    assert key_name(keyboard.KeyCode.from_char('[')) == '['
    assert key_name(keyboard.Key.f1) == 'f1'
    assert to_key('f1') is keyboard.Key.f1
    assert to_key('[') == keyboard.KeyCode.from_char('[')
    assert label('mouse_right') == 'R-MOUSE'
    assert label('mouse_x2') == 'X2-MOUSE'
    assert clean([{'trigger': 'mouse_right', 'keys': ['[', ']', 7]}, 'junk', {'keys': []}]) == \
        [{'trigger': 'mouse_right', 'keys': ['[', ']']}]
    # A row missing either half is carried in the file but must never reach the listeners.
    assert Macros([{'trigger': 'a', 'keys': []}, {'trigger': '', 'keys': ['b']}]).binds == {}
    print('ok')


if __name__ == '__main__':
    _self_check()
