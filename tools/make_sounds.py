"""Generate the game sounds (small .wav files, no external downloads).

    python tools/make_sounds.py            # only what is missing
    python tools/make_sounds.py --force    # regenerate everything

Sounds are plain waveforms written with the standard `wave` module, so this
works everywhere Python does. They land in `assets/sounds/`; a resource pack may
override them by shipping its own `sounds/` folder.

Every sound is short (0.1-0.6 s) and quiet - they are meant as feedback for
chopping, hitting, building, eating and so on.
"""

import argparse
import math
import os
import struct
import sys
import wave
from pathlib import Path

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

ROOT = Path(__file__).resolve().parent.parent
RATE = 22050


def envelope(i, total, attack=0.01, release=0.25):
    """Simple attack/release envelope so nothing clicks."""
    position = i / max(1, total - 1)
    if position < attack:
        return position / attack
    if position > 1 - release:
        return max(0.0, (1 - position) / release)
    return 1.0


def tone(frequency, duration, volume=0.4, harmonics=(1.0, 0.4, 0.2), noise=0.0,
         sweep=0.0):
    """One note: a few harmonics plus optional noise and a frequency sweep."""
    total = int(RATE * duration)
    frames = []
    for i in range(total):
        t = i / RATE
        freq = frequency * (1 + sweep * (i / total))
        value = sum(amplitude * math.sin(2 * math.pi * freq * h * t)
                    for h, amplitude in enumerate(harmonics, start=1))
        if noise:
            value += noise * (random_value(i) - 0.5) * 2
        frames.append(value * envelope(i, total) * volume)
    return frames


def random_value(i):
    """Deterministic pseudo noise (so regenerating gives the same file)."""
    x = math.sin(i * 12.9898) * 43758.5453
    return x - math.floor(x)


def hit_noise(duration=0.12, volume=0.5, low=0.85):
    total = int(RATE * duration)
    frames = []
    previous = 0.0
    for i in range(total):
        noise = random_value(i) - 0.5
        previous = previous * low + noise * (1 - low)     # low-pass
        frames.append(previous * envelope(i, total, 0.005, 0.5) * volume * 3)
    return frames


def mix(*tracks):
    length = max(len(track) for track in tracks)
    out = []
    for i in range(length):
        value = sum(track[i] for track in tracks if i < len(track))
        out.append(max(-1.0, min(1.0, value)))
    return out


def write_wav(path: Path, frames):
    with wave.open(str(path), "w") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(RATE)
        handle.writeframes(b"".join(struct.pack("<h", int(max(-1, min(1, f)) * 32000))
                                    for f in frames))


# ------------------------------------------------------------------ the sounds
def snd_chop():
    return mix(hit_noise(0.10, 0.5, 0.8), tone(180, 0.10, 0.25, (1.0, 0.5), sweep=-0.4))


def snd_mine():
    return mix(hit_noise(0.09, 0.45, 0.6), tone(420, 0.09, 0.3, (1.0, 0.6, 0.3),
                                                sweep=-0.3))


def snd_hit():
    return mix(hit_noise(0.14, 0.6, 0.5), tone(120, 0.16, 0.35, (1.0, 0.7), sweep=-0.5))


def snd_hurt():
    return tone(300, 0.22, 0.4, (1.0, 0.6, 0.4), sweep=-0.6)


def snd_shot():
    return mix(hit_noise(0.09, 0.7, 0.3), tone(900, 0.08, 0.3, (1.0, 0.3), sweep=-0.8))


def snd_bow():
    return mix(tone(700, 0.12, 0.25, (1.0, 0.2), sweep=-0.7), hit_noise(0.05, 0.3, 0.9))


def snd_craft():
    return mix(tone(520, 0.09, 0.25), tone(780, 0.09, 0.2), tone(1040, 0.12, 0.18))


def snd_build():
    return mix(tone(220, 0.14, 0.3, (1.0, 0.5)), hit_noise(0.08, 0.35, 0.7))


def snd_break():
    return mix(hit_noise(0.35, 0.6, 0.55), tone(90, 0.35, 0.3, (1.0, 0.8, 0.5),
                                                sweep=-0.5))


def snd_eat():
    return mix(hit_noise(0.10, 0.25, 0.9), tone(150, 0.10, 0.2, sweep=-0.3))


def snd_step():
    return hit_noise(0.07, 0.25, 0.75)


def snd_pickup():
    return mix(tone(880, 0.07, 0.22), tone(1320, 0.09, 0.18))


def snd_task():
    return mix(tone(660, 0.12, 0.22), tone(880, 0.12, 0.2), tone(1180, 0.18, 0.18))


def snd_death():
    return tone(200, 0.5, 0.35, (1.0, 0.6, 0.4), sweep=-0.75)


def snd_night():
    return tone(140, 0.6, 0.25, (1.0, 0.5), sweep=-0.2)


def snd_rain():
    return hit_noise(0.6, 0.18, 0.95)


# ---------------------------------------------------------------- music (b13)
#
# Simple built-in tracks: a slow chord progression, a soft bass and a faint
# noise bed. They are not songs, but they make the world feel alive, and a
# resource pack may replace them with real music (see README, «Своя музыка»).

def _note(frequency, duration, volume=0.3):
    """A softer note for music: fewer harmonics, long release."""
    return tone(frequency, duration, volume=volume, harmonics=(1.0, 0.25, 0.08),
                sweep=0.0)


def _chord(frequencies, duration, volume=0.16):
    frames = None
    for freq in frequencies:
        part = _note(freq, duration, volume)
        frames = part if frames is None else [a + b for a, b in zip(frames, part)]
    return frames


def _pad(frames, seconds, volume=0.05):
    """Add a quiet wind/sea noise bed under a piece."""
    total = int(RATE * seconds)
    bed = [volume * (random_value(i) - 0.5) * 2 for i in range(total)]
    if len(bed) < len(frames):
        bed += [0.0] * (len(frames) - len(bed))
    return [a + b for a, b in zip(frames, bed[:len(frames)])]


def track_calm():
    """Day music: a calm four-chord loop (Am - F - C - G), 12 seconds."""
    progression = [(220.0, 261.6, 329.6), (174.6, 220.0, 261.6),
                   (261.6, 329.6, 392.0), (196.0, 246.9, 293.7)]
    frames = []
    for chord in progression:
        frames += _chord(chord, 2.5)
        frames += _note(chord[0] / 2, 2.5, 0.10)          # bass under the chord
    return _pad(frames, 10.0, 0.035)


def track_night():
    """Night music: lower, slower, a little mysterious (Dm - Bb - Gm - A)."""
    progression = [(146.8, 174.6, 220.0), (116.5, 146.8, 174.6),
                   (98.0, 116.5, 146.8), (110.0, 138.6, 164.8)]
    frames = []
    for chord in progression:
        frames += _chord(chord, 3.0, 0.14)
        frames += _note(chord[0] / 2, 3.0, 0.09)
    return _pad(frames, 12.0, 0.03)


MUSIC = {
    "day_calm": track_calm,        # plays during the day
    "night_calm": track_night,     # plays after sunset
}

SOUNDS = {
    "chop": snd_chop,
    "mine": snd_mine,
    "hit": snd_hit,
    "hurt": snd_hurt,
    "shot": snd_shot,
    "bow": snd_bow,
    "craft": snd_craft,
    "build": snd_build,
    "break": snd_break,
    "eat": snd_eat,
    "step": snd_step,
    "pickup": snd_pickup,
    "task": snd_task,
    "death": snd_death,
    "night": snd_night,
    "rain": snd_rain,
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true", help="regenerate existing files")
    parser.add_argument("--list", action="store_true")
    args = parser.parse_args()

    target_dir = ROOT / "assets" / "sounds"
    target_dir.mkdir(parents=True, exist_ok=True)
    missing = [n for n in SOUNDS if not (target_dir / f"{n}.wav").exists()]
    if args.list:
        print("missing:", ", ".join(sorted(missing)) or "nothing")
        return 0

    created = []
    for name, maker in sorted(SOUNDS.items()):
        path = target_dir / f"{name}.wav"
        if path.exists() and not args.force:
            continue
        write_wav(path, maker())
        created.append(name)

    music_dir = ROOT / "assets" / "music"
    music_dir.mkdir(parents=True, exist_ok=True)
    made_music = []
    for name, maker in sorted(MUSIC.items()):
        path = music_dir / f"{name}.wav"
        if path.exists() and not args.force:
            continue
        write_wav(path, maker())
        made_music.append(name)

    print(f"created {len(created)} sound(s): {', '.join(created)}" if created
          else "nothing to do - every sound already exists (use --force)")
    print(f"created {len(made_music)} music track(s): {', '.join(made_music)}"
          if made_music else "music: nothing to do (use --force to regenerate)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
