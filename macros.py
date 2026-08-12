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

# The pauses the GUI cycles through for "wait this long after this key". Not free text: a box
# to type seconds into is a way to sit on 30s by accident with the trigger still down.
WAITS = (0.0, 0.05, 0.1, 0.25, 0.5, 1.0)

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


def step(entry):
    """One step of a macro: a key, whether it is held or tapped, the pause after it.

    A bare string is the old shape, from before there was anything to say but the key, and it
    means held with no pause. Anything that is not a key at all comes back as None.
    """
    if isinstance(entry, str):
        entry = {'key': entry}
    if not isinstance(entry, dict) or not isinstance(entry.get('key'), str) or not entry['key']:
        return None
    wait = entry.get('wait')
    return {'key': entry['key'], 'tap': bool(entry.get('tap')),
            # Clamped, not just checked: a hand-edited 60 in the file is a macro that looks hung.
            'wait': min(float(wait), max(WAITS)) if isinstance(wait, (int, float)) and wait > 0
                    else 0.0}


def step_label(entry):
    """One step as it reads on its plate: the key, TAP if it is tapped, the pause after it."""
    return (label(entry['key']) + (' TAP' if entry['tap'] else '')
            + (' +%gs' % entry['wait'] if entry['wait'] else ''))


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
                        'keys': [s for s in map(step, keys) if s]})
    return out


class Macros:
    """The listeners, running until stop(). Callbacks arrive on pynput's threads, never tk's.

    Each key in a macro is either held or tapped. A held key goes down with the trigger and comes
    back up when the trigger does, so right mouse bound to a held `[` means `[` is down for
    exactly as long as right mouse is. A tapped key goes down and straight back up on the way
    through, and a key can carry a pause after it, so q -> shift, e, wait, f is one macro.
    """

    def __init__(self, binds):
        self.binds = {b['trigger']: b['keys'] for b in clean(binds) if b['trigger'] and b['keys']}
        self.listeners = []
        self.held = {}  # trigger -> the keys currently down for it
        self.lock = threading.Lock()  # ponytail: one lock, so a fast tap cannot release before it presses

    def _press(self, trigger):
        keys = self.binds.get(trigger)
        # `held` doubles as the loop guard. A keyboard trigger's own output comes straight back
        # through this hook, and so does the auto-repeat of a key being held down; both find the
        # trigger already recorded as down and stop here.
        if not keys or trigger in self.held:
            return
        self.held[trigger] = keys
        # From a worker, not from here: Windows quietly unhooks a low-level hook that blocks, and
        # pressing a run of keys with a hold between them takes long enough to qualify.
        threading.Thread(target=self._push, args=(keys, False), daemon=True).start()

    def _let_go(self, trigger):
        keys = self.held.pop(trigger, None)
        if keys:
            threading.Thread(target=self._push, args=(keys, True), daemon=True).start()

    def _push(self, keys, up):
        """Press the keys, or release them last-down-first-up. The lock keeps the two in order."""
        with self.lock:
            for entry in reversed(keys) if up else keys:
                # A tapped key was already let go on the way down, so the release pass skips it.
                # Its pause belongs to the way down too, or letting the trigger go would sit
                # there waiting on a key that is not even down.
                if up and entry['tap']:
                    continue
                key = to_key(entry['key'])
                if up:
                    _kb.release(key)
                    time.sleep(HOLD)
                    continue
                _kb.press(key)
                time.sleep(HOLD)
                if entry['tap']:
                    _kb.release(key)
                    time.sleep(HOLD)
                time.sleep(entry['wait'])

    def start(self):
        if self.listeners or not self.binds:
            return
        self.listeners = [keyboard.Listener(on_press=lambda k: self._press(key_name(k)),
                                            on_release=lambda k: self._let_go(key_name(k))),
                          mouse.Listener(on_click=self._click)]
        for listener in self.listeners:
            listener.start()

    def _click(self, x, y, button, pressed):
        # Named rather than a lambda because returning False from a mouse callback stops the
        # listener, and `pressed and self._press(...)` does exactly that on every release.
        name = 'mouse_' + button.name
        self._press(name) if pressed else self._let_go(name)

    def stop(self):
        for listener in self.listeners:
            listener.stop()
        self.listeners = []
        # Whatever is down when the hooks come off would stay down forever, with nothing left
        # listening for the release. A stuck key in a raid is the worst thing this can do.
        for trigger in list(self.held):
            self._let_go(trigger)


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


class _Recorder:
    """Stands in for the controller, so the check can read what would have been sent."""

    def __init__(self):
        self.log = []

    def press(self, key):
        self.log.append('+' + str(getattr(key, 'char', None) or key))

    def release(self, key):
        self.log.append('-' + str(getattr(key, 'char', None) or key))


def _self_check():
    global _kb

    assert key_name(keyboard.KeyCode.from_char('[')) == '['
    assert key_name(keyboard.Key.f1) == 'f1'
    assert to_key('f1') is keyboard.Key.f1
    assert to_key('[') == keyboard.KeyCode.from_char('[')
    assert label('mouse_right') == 'R-MOUSE'
    assert label('mouse_x2') == 'X2-MOUSE'
    # A bare string is the old shape and still means held, with no pause.
    assert step('[') == {'key': '[', 'tap': False, 'wait': 0.0}
    assert step({'key': 'f', 'tap': 1, 'wait': 0.1}) == {'key': 'f', 'tap': True, 'wait': 0.1}
    assert step({'key': 'f', 'wait': 60})['wait'] == max(WAITS), 'a hand-edited pause ran wild'
    assert step({'key': 'f', 'wait': 'soon'})['wait'] == 0.0
    assert step(7) is None and step({'key': ''}) is None
    assert step_label({'key': 'e', 'tap': True, 'wait': 0.1}) == 'E TAP +0.1s'
    assert clean([{'trigger': 'mouse_right', 'keys': ['[', {'key': ']', 'tap': True}, 7]},
                  'junk', {'keys': []}]) == \
        [{'trigger': 'mouse_right', 'keys': [{'key': '[', 'tap': False, 'wait': 0.0},
                                             {'key': ']', 'tap': True, 'wait': 0.0}]}]
    # A row missing either half is carried in the file but must never reach the listeners.
    assert Macros([{'trigger': 'a', 'keys': []}, {'trigger': '', 'keys': ['b']}]).binds == {}

    _kb = recorder = _Recorder()  # nothing below reaches a real keyboard
    try:
        m = Macros([{'trigger': 'mouse_right', 'keys': ['[', ']']}])

        m._press('mouse_right')
        assert list(m.held) == ['mouse_right'], 'the trigger is not recorded as down'
        m._press('mouse_right')  # auto-repeat, and a macro that sends its own trigger
        assert list(m.held) == ['mouse_right'], 'a second press stacked on the first'
        m._let_go('mouse_right')
        m._let_go('mouse_right')  # a stray release must be a no-op, not a second round of ups
        assert m.held == {}
        time.sleep(HOLD * 8)  # the workers do the sending
        assert recorder.log == ['+[', '+]', '-]', '-['], recorder.log

        # Taking the hooks off has to let go of anything still down, or the key stays stuck.
        recorder.log.clear()
        m._press('mouse_right')
        m.stop()
        time.sleep(HOLD * 8)
        assert recorder.log == ['+[', '+]', '-]', '-['], recorder.log
        assert m.held == {}

        # Hold one, tap the other: the tapped key is done on the way down and must not come
        # back up a second time when the trigger is let go.
        recorder.log.clear()
        m = Macros([{'trigger': 'q', 'keys': ['[', {'key': ']', 'tap': True, 'wait': 0.1}]}])
        m._press('q')
        m._let_go('q')
        time.sleep(0.1 + HOLD * 10)
        assert recorder.log == ['+[', '+]', '-]', '-['], recorder.log
    finally:
        _kb = keyboard.Controller()
    print('ok')


if __name__ == '__main__':
    _self_check()
