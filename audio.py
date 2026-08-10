"""PyTarkBuddy audio: dynamic range squasher for Tarkov.

Loud things (your gun) get pushed down, faint things (footsteps, bush rustle) get
pulled up, so both land near the same loudness. Broadband, not multiband.

No virtual cable, no VoiceMeeter. WASAPI loopback taps a playback endpoint directly:
    1. Point the game (or all of Windows) at an endpoint you don't listen on, e.g. an
       idle HDMI/monitor output or "Realtek Digital Output". Per-app routing lives in
       Settings > Sound > Volume mixer.
    2. run(capture_device="<that idle endpoint>", output_device="<your headphones>")
Capture and output must differ, or the processed audio feeds back into itself.
"""

import queue

import numpy as np
import pyaudiowpatch as pyaudio

BLOCKSIZE = 256  # 5.3 ms at 48 kHz

# threshold_db, downward ratio, upward ratio, floor_db
# A ratio of 1.0 makes the gain formula collapse to exactly unity, so "Off" is a real bypass
# and not a special case anywhere: audio passes through untouched, meter still reads it.
LEVELS = {
    "Off":        (-22.0, 1.0, 1.0, -60.0),
    "Soft":       (-20.0, 2.5, 1.4, -55.0),
    "Medium":     (-22.0, 5.0, 2.2, -60.0),
    "Aggressive": (-24.0, 12.0, 4.0, -65.0),
}

ATTACK = 0.6    # per block: duck fast when the gun goes off
RELEASE = 0.03  # per block: come back up slowly, no pumping

# Live spectrum for the GUI meter. 2048 samples is 43 ms at 48 kHz, which buys ~23 Hz of
# resolution: enough that the bottom bands aren't all the same FFT bin.
FFT_SIZE = 2048
BANDS = 28
BAND_LOW, BAND_HIGH = 40.0, 16000.0
FLOOR_DB = -72.0  # bottom of the meter
DECAY = 0.72      # per update: bars fall back rather than flicker

# ponytail: plain module global. One writer (audio callback), one reader (GUI), no lock; a
# torn read costs one frame of one bar.
_spectrum = np.zeros(BANDS, dtype=np.float32)

_pa = None


def spectrum():
    """The live meter, BANDS floats in 0..1. Written by run(), read by whoever draws it."""
    return _spectrum


def _audio():
    global _pa
    if _pa is None:
        _pa = pyaudio.PyAudio()
    return _pa


def devices():
    """Deduped playback endpoint names (the things you can capture from or play to)."""
    p = _audio()
    names = (p.get_device_info_by_index(i)["name"] for i in range(p.get_device_count()))
    return sorted(dict.fromkeys(n for n in names if f"{n} [Loopback]" in _loopbacks()))


def _loopbacks():
    return {d["name"]: d for d in _audio().get_loopback_device_info_generator()}


def _find(name, loopback=False):
    p = _audio()
    want = f"{name} [Loopback]" if loopback else name
    for i in range(p.get_device_count()):
        d = p.get_device_info_by_index(i)
        if d["name"] == want and (d["maxInputChannels"] if loopback else d["maxOutputChannels"]):
            return d
    raise ValueError(f"no device named {want!r}")


def make_processor(level="Medium", output_db=0.0):
    """Return process(block) -> block. Keeps its own smoothed-gain state.

    level may be a callable returning a level name, so it can be changed live.
    """
    get_level = level if callable(level) else (lambda: level)
    out_gain = 10.0 ** (output_db / 20.0)
    gain = 1.0

    def process(block):
        nonlocal gain
        thr, ratio, up_ratio, floor = LEVELS[get_level()]
        env_db = 20.0 * np.log10(max(float(np.max(np.abs(block))), 1e-9))
        env_db = max(env_db, floor)  # don't chase digital silence
        # one curve, both directions: pull everything toward the threshold
        r = ratio if env_db > thr else up_ratio
        target = 10.0 ** (((thr - env_db) * (1.0 - 1.0 / r)) / 20.0) * out_gain

        coef = ATTACK if target < gain else RELEASE
        new = gain + (target - gain) * coef
        # ramp across the block instead of stepping, else you hear zipper noise
        ramp = np.linspace(gain, new, len(block), dtype=np.float32)[:, None]
        gain = new
        return np.clip(block * ramp, -1.0, 1.0)

    return process


def make_analyser(rate):
    """Return analyse(block), which folds the block into _spectrum. Keeps its own history."""
    window = np.hanning(FFT_SIZE).astype(np.float32)
    history = np.zeros(FFT_SIZE, dtype=np.float32)
    freqs = np.fft.rfftfreq(FFT_SIZE, 1.0 / rate)
    edges = np.searchsorted(freqs, np.logspace(np.log10(BAND_LOW), np.log10(BAND_HIGH),
                                               BANDS + 1))
    # Below ~100 Hz the log spacing is finer than the FFT is, so several edges land on the
    # same bin. Force them apart, or those bands are empty slices and max() blows up.
    for i in range(1, len(edges)):
        edges[i] = max(edges[i], edges[i - 1] + 1)
    full_scale = FFT_SIZE / 4.0  # a full-scale sine through a Hann window lands here

    def analyse(block):
        n = len(block)
        history[:-n] = history[n:]
        history[-n:] = block.mean(axis=1)
        mag = np.abs(np.fft.rfft(history * window))
        peaks = np.array([mag[a:b].max() for a, b in zip(edges, edges[1:])])
        db = 20.0 * np.log10(np.maximum(peaks / full_scale, 1e-9))
        _spectrum[:] = np.maximum(np.clip(1.0 - db / FLOOR_DB, 0.0, 1.0), _spectrum * DECAY)

    return analyse


def run(capture_device, output_device, level="Medium", output_db=0.0):
    """Loopback-tap capture_device, squash it, play to output_device. Returns streams."""
    if capture_device == output_device:
        raise ValueError("capture and output must differ, else the audio feeds back")
    cap, out = _find(capture_device, loopback=True), _find(output_device)
    # ponytail: both endpoints must share a rate; WASAPI shared mode won't resample for us
    rate = int(cap["defaultSampleRate"])
    process = make_processor(level, output_db)
    analyse = make_analyser(rate)
    silence = np.zeros((BLOCKSIZE, 2), dtype=np.float32).tobytes()
    q = queue.Queue(maxsize=8)  # ponytail: drop on overrun, a stale block beats none

    def on_capture(data, frames, info, status):
        block = np.frombuffer(data, dtype=np.float32).reshape(-1, 2)
        out = process(block)
        analyse(out)  # after the squash, so the meter shows what you actually hear
        try:
            q.put_nowait(out.tobytes())
        except queue.Full:
            pass
        return (None, pyaudio.paContinue)

    def on_play(data, frames, info, status):
        try:
            return (q.get_nowait(), pyaudio.paContinue)
        except queue.Empty:
            return (silence, pyaudio.paContinue)

    p = _audio()
    common = dict(format=pyaudio.paFloat32, channels=2, rate=rate, frames_per_buffer=BLOCKSIZE)
    return [
        p.open(input=True, input_device_index=cap["index"],
               stream_callback=on_capture, **common),
        p.open(output=True, output_device_index=out["index"],
               stream_callback=on_play, **common),
    ]


def stop(streams):
    for s in streams:
        s.close()


def _selfcheck():
    def settled(level, amp, blocks=200):
        process = make_processor(level)
        for _ in range(blocks):
            out = process(np.full((BLOCKSIZE, 2), amp, dtype=np.float32))
        return float(np.max(np.abs(out)))

    for level in LEVELS:
        loud, quiet = settled(level, 0.9), settled(level, 0.005)
        if level == "Off":  # float32 round-trip, so exact equality is the wrong test
            assert np.isclose([loud, quiet], [0.9, 0.005], rtol=1e-6).all(), \
                "Off is not a clean bypass"
        else:
            assert loud < 0.9, f"{level}: loud not ducked"
            assert quiet > 0.005, f"{level}: quiet not lifted"
        print(f"{level:11s} loud 0.900->{loud:.3f}  quiet 0.005->{quiet:.3f}  "
              f"range {20 * np.log10(loud / quiet):5.1f} dB (was 45.1 dB)")

    assert settled("Aggressive", 0.9) < settled("Soft", 0.9)
    assert settled("Aggressive", 0.005) > settled("Soft", 0.005)

    live, block = ["Soft"], np.full((BLOCKSIZE, 2), 0.9, dtype=np.float32)
    process = make_processor(lambda: live[0])
    for _ in range(200):
        soft = process(block)
    live[0] = "Aggressive"
    for _ in range(200):
        hard = process(block)
    assert np.max(hard) < np.max(soft), "live switch did not take effect"
    print("live level switch: Soft -> Aggressive works mid-stream")

    rate, tone = 48000, 1000.0
    analyse = make_analyser(rate)
    t = np.arange(FFT_SIZE) / rate
    sine = (0.5 * np.sin(2 * np.pi * tone * t)).astype(np.float32)[:, None].repeat(2, axis=1)
    for _ in range(10):
        analyse(sine)
    peak = int(np.argmax(_spectrum))
    edges = np.logspace(np.log10(BAND_LOW), np.log10(BAND_HIGH), BANDS + 1)
    assert edges[peak] <= tone <= edges[peak + 1], f"{tone} Hz landed in band {peak}"
    assert _spectrum.max() > 0.5, "1 kHz tone barely registered"
    _spectrum[:] = 0
    print(f"spectrum: {tone:.0f} Hz peaks in band {peak} "
          f"({edges[peak]:.0f}-{edges[peak + 1]:.0f} Hz)")
    print("\ndevices:", *devices(), sep="\n  ")


if __name__ == "__main__":
    _selfcheck()
