"""Tiny sound player and the music box (b13).

Sounds live in the active resource pack (`sounds/*.wav`) and fall back to the
built-in `assets/sounds/`. Music works the same way (`music/*.ogg`), but it is
streamed by `pygame.mixer.music`, so a long track costs almost no memory.

Everything is optional: if pygame has no audio device (headless test runs, a
server box), `Audio.available` is False and every call is a no-op, so the game
never crashes because of sound. The same is true for music.
"""

import pygame

SOUND_NAMES = ("chop", "mine", "hit", "hurt", "shot", "bow", "craft", "build",
               "break", "eat", "step", "pickup", "task", "death", "night", "rain")

# What a file of yours may be called: .wav is what the game ships, but pygame
# loads .ogg and .mp3 just as well, so a "normal" sound file can be dropped in
# without converting anything.
SOUND_EXTENSIONS = (".wav", ".ogg", ".mp3")

# Music: the file name says when it should play (b13). A track called
# `night_*.ogg` is played after sunset, `battle_*.ogg` while somebody fights
# nearby, everything else is day music. A resource pack may add its own tracks.
MUSIC_MOODS = ("day", "night", "calm", "battle", "cave")
MUSIC_EXTENSIONS = (".ogg", ".mp3", ".wav")

# how loud each sound is compared to the master volume
DEFAULT_VOLUMES = {
    "step": 0.35, "chop": 0.7, "mine": 0.7, "hit": 0.8, "hurt": 0.8, "shot": 0.9,
    "bow": 0.7, "craft": 0.7, "build": 0.7, "break": 0.9, "eat": 0.6,
    "pickup": 0.6, "task": 0.8, "death": 0.9, "night": 0.5, "rain": 0.4,
}


class Audio:
    def __init__(self, resources=None, volume: float = 0.7, enabled: bool = True,
                 music_enabled: bool = True, music_volume: float = 0.45):
        self.volume = max(0.0, min(1.0, float(volume)))
        self.enabled = bool(enabled)
        self.music_enabled = bool(music_enabled)
        self.music_volume = max(0.0, min(1.0, float(music_volume)))
        self.sounds = {}
        self.music = {}                   # mood -> [paths]
        self.music_mood = ""
        self.music_track = ""
        self.available = False
        self.resources = resources
        self._mixer_ready = False
        try:
            if pygame.mixer.get_init() is None:
                pygame.mixer.init(frequency=22050, size=-16, channels=1, buffer=512)
            self._mixer_ready = True
        except pygame.error:
            self._mixer_ready = False
        self.reload(resources)
        self.load_music(resources)

    # ------------------------------------------------------------------ loading
    def reload(self, resources=None):
        if resources is not None:
            self.resources = resources
        self.sounds = {}
        if not self._mixer_ready:
            self.available = False
            return
        for name in SOUND_NAMES:
            path = self._find(name)
            if path is None:
                continue
            try:
                self.sounds[name] = pygame.mixer.Sound(str(path))
            except (pygame.error, OSError):
                continue
        self.available = bool(self.sounds)

    def _find(self, name: str):
        """Resource pack first, built-in sounds second.

        b11: this used to look for `<pack>.path`, which no pack object ever had,
        so custom sounds in a resource pack were silently ignored. A pack may
        keep its sounds in `sounds/` (or right next to pack.json).
        """
        if self.resources is not None:
            pack = getattr(self.resources, "pack", None)
            directory = getattr(pack, "directory", None)
            if directory is not None:
                for folder in (directory / "sounds", directory):
                    for extension in SOUND_EXTENSIONS:
                        candidate = folder / f"{name}{extension}"
                        if candidate.is_file():
                            return candidate
        from client.resources import project_root
        folder = project_root() / "assets" / "sounds"
        for extension in SOUND_EXTENSIONS:
            candidate = folder / f"{name}{extension}"
            if candidate.is_file():
                return candidate
        return None

    # -------------------------------------------------------------------- music
    def music_candidates(self, resources=None) -> dict:
        """Which music files exist: {mood: [paths]} (pack first, assets second)."""
        resources = resources if resources is not None else self.resources
        folders = []
        if resources is not None:
            pack = getattr(resources, "pack", None)
            directory = getattr(pack, "directory", None)
            if directory is not None:
                folders.extend([directory / "music", directory])
        from client.resources import project_root
        folders.append(project_root() / "assets" / "music")
        found = {mood: [] for mood in MUSIC_MOODS}
        for folder in folders:
            if not folder.is_dir():
                continue
            for path in sorted(folder.iterdir()):
                if path.suffix.lower() not in MUSIC_EXTENSIONS:
                    continue
                mood = "calm"
                for candidate in MUSIC_MOODS:
                    if path.stem.lower().startswith(candidate):
                        mood = candidate
                        break
                if path not in found[mood]:
                    found[mood].append(path)
        return found

    def load_music(self, resources=None):
        if resources is not None:
            self.resources = resources
        self.music = self.music_candidates(resources)
        self.music_mood = ""
        self.music_track = ""

    def play_music(self, mood: str = "day", track: str = ""):
        """Start (or switch to) a mood. Called from the game loop every second.

        The music keeps playing while the mood stays the same, so this is safe
        to call often. `track` picks a concrete file name (used by the menu).
        """
        if not (self._mixer_ready and self.music_enabled):
            return
        if track:
            paths = [path for group in self.music.values() for path in group
                     if path.stem == track]
            if not paths:
                return
            chosen = paths[0]
            if self.music_track == track:
                return
            self.music_track = track
        else:
            if mood == self.music_mood:
                return
            paths = self.music.get(mood) or []
            if not paths:
                # no track for this mood: fall back to calm music, then to
                # anything the player happens to have (b13)
                for fallback in ("calm", "day", "night", "cave", "battle"):
                    if self.music.get(fallback):
                        paths = self.music[fallback]
                        break
            if not paths:
                self.music_mood = mood
                return
            chosen = paths[0]
            self.music_mood = mood
            self.music_track = chosen.stem
        try:
            pygame.mixer.music.load(str(chosen))
            pygame.mixer.music.set_volume(self.music_volume * self.volume)
            pygame.mixer.music.play(-1)          # loop forever
        except (pygame.error, OSError):
            pass

    def stop_music(self):
        try:
            pygame.mixer.music.stop()
        except pygame.error:
            pass
        self.music_mood = ""
        self.music_track = ""

    def set_music_volume(self, volume: float):
        """Applied at once: `music_volume` scales with the master volume."""
        self.music_volume = max(0.0, min(1.0, float(volume)))
        try:
            pygame.mixer.music.set_volume(self.music_volume * self.volume)
        except pygame.error:
            pass

    def set_music_enabled(self, enabled: bool):
        self.music_enabled = bool(enabled)
        if not self.music_enabled:
            self.stop_music()

    # ------------------------------------------------------------------ playing
    def play(self, name: str, volume: float = 1.0):
        if not self.enabled or not self.available:
            return
        sound = self.sounds.get(name)
        if sound is None:
            return
        level = self.volume * volume * DEFAULT_VOLUMES.get(name, 0.7)
        if level <= 0.01:
            return
        try:
            sound.set_volume(min(1.0, level))
            sound.play()
        except pygame.error:
            pass

    def set_volume(self, volume: float):
        self.volume = max(0.0, min(1.0, float(volume)))
        try:
            pygame.mixer.music.set_volume(self.music_volume * self.volume)
        except pygame.error:
            pass

    def stop_all(self):
        if self.available:
            pygame.mixer.stop()
