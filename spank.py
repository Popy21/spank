#!/usr/bin/env python3
"""
SPANK - Plays audio when your Mac detects real movement/vibration.
After the audio, loops an ultrasonic pain tone until Touch ID / password.
Forces volume to max — cannot be turned down.
"""

import argparse
import subprocess
import signal
import time
import sys
import os
import threading

import numpy as np
import sounddevice as sd

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
for ext in ("mp3", "aiff", "wav", "m4a"):
    _candidate = os.path.join(SCRIPT_DIR, "sounds", f"spank.{ext}")
    if os.path.exists(_candidate):
        DEFAULT_SOUND = _candidate
        break
else:
    DEFAULT_SOUND = os.path.join(SCRIPT_DIR, "sounds", "spank.mp3")

SAMPLERATE = 44100
LOWPASS_HZ = 300

triggered = False
ultrasonic_active = False
ultrasonic_phase = 0
baseline_rms = 0.0
baseline_max = 0.0
calibration_count = 0
CALIBRATION_FRAMES = 100
volume_enforcer_active = False
lock_armed_event = threading.Event()


# --- VOLUME ENFORCER: forces volume to 100% every 0.3s ---
def volume_enforcer():
    while volume_enforcer_active:
        subprocess.run(["osascript", "-e", "set volume output volume 100"], capture_output=True)
        time.sleep(0.3)


# --- TOUCH ID / PASSWORD AUTH ---
def authenticate():
    """Prompt for Touch ID or password. Returns True if authenticated."""
    result = subprocess.run(
        ["osascript", "-e",
         'tell application "System Events" to display dialog '
         '"SPANK: Authenticate to stop" '
         'default answer "" with hidden answer '
         'with title "SPANK Lock" '
         'giving up after 0'],
        capture_output=True
    )
    # Use LocalAuthentication via Swift snippet for Touch ID
    auth_script = '''
    import Foundation
    import LocalAuthentication
    let context = LAContext()
    let semaphore = DispatchSemaphore(value: 0)
    var success = false
    context.evaluatePolicy(.deviceOwnerAuthentication,
        localizedReason: "Authenticate to stop SPANK") { result, error in
        success = result
        semaphore.signal()
    }
    semaphore.wait()
    exit(success ? 0 : 1)
    '''
    proc = subprocess.run(
        ["swift", "-e", auth_script],
        capture_output=True, timeout=60
    )
    return proc.returncode == 0


# --- BLOCK CTRL+C: require auth instead ---
def block_sigint(signum, frame):
    """Intercept Ctrl+C — require Touch ID / password to stop."""
    print("\n  LOCKED! Authenticate to stop...", flush=True)
    threading.Thread(target=_auth_gate, daemon=True).start()


def _auth_gate():
    global ultrasonic_active, volume_enforcer_active
    if authenticate():
        ultrasonic_active = False
        volume_enforcer_active = False
        print("\n  Authenticated. Stopping.", flush=True)
        os._exit(0)
    else:
        print("  Auth failed. SPANK continues.", flush=True)


# --- AUDIO ---
def generate_ultrasonic_chunk(frames):
    global ultrasonic_phase
    t = (np.arange(frames) + ultrasonic_phase) / SAMPLERATE
    ultrasonic_phase += frames

    tone = np.zeros(frames, dtype=np.float32)
    for f in [2800, 3200, 3500, 4000]:
        tone += np.sin(2 * np.pi * f * t)
    for f in [7500, 14000, 15500, 17000]:
        tone += np.sin(2 * np.pi * f * t) * 0.8
    tone += np.sin(2 * np.pi * 3000 * t) + np.sin(2 * np.pi * 3007 * t)
    tone += np.sin(2 * np.pi * 15000 * t) + np.sin(2 * np.pi * 15013 * t)

    peak = np.max(np.abs(tone))
    if peak > 0:
        tone /= peak
    return tone.reshape(-1, 1)


def ultrasonic_callback(outdata, frames, time_info, status):
    if ultrasonic_active:
        outdata[:] = generate_ultrasonic_chunk(frames)
    else:
        outdata[:] = 0


def lowpass(data, cutoff, fs):
    fft = np.fft.rfft(data.flatten())
    freqs = np.fft.rfftfreq(len(data), 1.0 / fs)
    fft[freqs > cutoff] = 0
    return np.fft.irfft(fft, len(data))


def set_volume_max():
    subprocess.run(["osascript", "-e", "set volume output volume 100"], capture_output=True)


SOUND2 = os.path.join(SCRIPT_DIR, "sounds", "spank2.m4a")


def play_sound_then_ultrasonic(path):
    global ultrasonic_active, volume_enforcer_active
    set_volume_max()

    # Start volume enforcer (keeps volume at max)
    volume_enforcer_active = True
    threading.Thread(target=volume_enforcer, daemon=True).start()

    subprocess.run(["afplay", path], capture_output=True)
    ultrasonic_active = True
    print("  ULTRASONIC ON", flush=True)
    print("  VOLUME LOCKED AT MAX", flush=True)
    print("  Ctrl+C = Touch ID / password required to stop\n", flush=True)
    # Signal handler is set from main thread via lock_armed flag
    lock_armed_event.set()

    # 4 seconds later, loop spank2 on top of ultrasonic
    if os.path.exists(SOUND2):
        time.sleep(4)
        print("  SPANK 2 LOOP ON", flush=True)
        while ultrasonic_active:
            proc = subprocess.Popen(["afplay", SOUND2], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            proc.wait()


def make_callback(cooldown, sound_path, sensitivity):
    def callback(indata, frames, time_info, status):
        global triggered, baseline_rms, baseline_max, calibration_count

        if triggered:
            return

        filtered = lowpass(indata, LOWPASS_HZ, SAMPLERATE)
        rms = float(np.sqrt(np.mean(np.array(filtered) ** 2)))

        if calibration_count < CALIBRATION_FRAMES:
            baseline_rms = (baseline_rms * calibration_count + rms) / (calibration_count + 1)
            if rms > baseline_max:
                baseline_max = rms
            calibration_count += 1
            if calibration_count == CALIBRATION_FRAMES:
                print(f"  Baseline: mean={baseline_rms:.6f}, max={baseline_max:.6f}", flush=True)
                print(f"  Trigger requires: >{baseline_max * sensitivity:.5f} (ambient_max x {sensitivity})", flush=True)
                print(f"  Ready! Tap desk or move Mac.\n", flush=True)
            return

        threshold = baseline_max * sensitivity
        if rms > threshold:
            triggered = True
            spike = rms / max(baseline_rms, 1e-8)
            print(f"  SPANK! (rms: {rms:.5f}, spike: {spike:.1f}x, threshold: {threshold:.5f})", flush=True)
            threading.Thread(target=play_sound_then_ultrasonic, args=(sound_path,), daemon=True).start()

    return callback


def main():
    parser = argparse.ArgumentParser(description="Vibration detector -> audio + ultrasonic (auth to stop)")
    parser.add_argument("-s", "--sound", default=DEFAULT_SOUND, help="Path to audio file")
    parser.add_argument("-x", "--sensitivity", type=float, default=1.5,
                        help="Multiplier over ambient max to trigger (default: 1.5)")
    parser.add_argument("-c", "--cooldown", type=float, default=2.0, help="Seconds between triggers")
    parser.add_argument("--list-devices", action="store_true", help="List audio input devices")
    parser.add_argument("-d", "--device", type=int, default=None, help="Input device index")
    args = parser.parse_args()

    if args.list_devices:
        print(sd.query_devices())
        return

    if not os.path.exists(args.sound):
        print(f"Audio file not found: {args.sound}")
        sys.exit(1)

    print("SPANK motion detector")
    print(f"  Sound:       {args.sound}")
    print(f"  Sensitivity: {args.sensitivity}x ambient max")
    print(f"  Filter:      <{LOWPASS_HZ}Hz (vibrations only)")
    print(f"  Mode:        audio -> ultrasonic loop")
    print(f"  Lock:        Touch ID / password to stop")
    print(f"  Calibrating (2s, don't move)...\n")

    cb = make_callback(args.cooldown, args.sound, args.sensitivity)

    try:
        out_stream = sd.OutputStream(
            callback=ultrasonic_callback, channels=1,
            samplerate=SAMPLERATE, dtype='float32'
        )
        out_stream.start()

        with sd.InputStream(callback=cb, channels=1, samplerate=SAMPLERATE, device=args.device):
            while True:
                # Once triggered, install signal handler from main thread
                if lock_armed_event.is_set():
                    signal.signal(signal.SIGINT, block_sigint)
                    lock_armed_event.clear()
                time.sleep(0.1)
    except KeyboardInterrupt:
        # Before trigger: normal exit. After trigger: auth required (handled by signal handler)
        if not triggered:
            out_stream.stop()
            out_stream.close()
            print("\nStopped.")
        else:
            block_sigint(None, None)
            while True:
                time.sleep(1)
    except sd.PortAudioError as e:
        print(f"Audio error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
