RU
Civilization Survival Game — сборка b13 «Всё сразу»
Игра про то, как из одного дерева вырастает страна. Вы высаживаетесь в мире,
где есть биомы и времена года, рубите лес, охотитесь, ставите костёр, строите
первый верстак — а через час у вас город с ратушей, налогами и стеной. Кто-то
рядом делает то же самое, и рано или поздно вы либо союзники, либо соседи по
осаде.

Это релизная сборка: сразу всё, что планировалось к 1.0 — живой мир, музыка,
обучение и удобства.

Что нового в b13

Шесть биомов. Луга, лес, пустыня, снежная тундра, болото и пещеры. В лесу
деревья, в пещерах руда, на лугах овцы, в тундре волки. Болото и тундра
замедляют ходьбу (0.8 и 0.85), пустыня чуть ускоряет.
Сезоны. Весна → лето → осень → зима, каждый сезон — несколько игровых
дней. Весной лес отрастает, осенью всюду грибы и ягоды, зимой земля мёрзлая:
всё растёт медленнее, все ходят медленнее, дождь меняется на туман, идёт снег.
Музыка. Спокойная дневная и ночная тема, отдельная музыка в пещере и в
бою. Громкость и выключатель — в настройках, свои треки кладутся в
assets/music/ или в ресурс-пак.
Первые шаги. Цепочка из десяти целей для новичка: оглядеться, дерево,
инструмент, камень, верстак, костёр, еда, факел, город, первая зима.
Прогресс сохраняется, F1 — справка из четырёх страниц.
Удобства. Любую клавишу можно переназначить (занятую игра не отбирает
молча: скажет, кто занял, и предложит поменять местами). Точки на карте
(P), сортировка инвентаря (O), каналы чата: /g всем, /l рядом,
/c стране, /w имя одному.
Внешний вид и жесты. N — цвет одежды (13 цветов), головной убор, плащ
за спиной, след — и шесть готовых наборов (путешественник, знать, фермер,
моряк, праздник, воин). X — жесты: помахать, танец, сесть, спать, указать,
хлопать, честь, смех. Цвет одежды красит имя над головой. Настоящие искры и
дым у костров, листья осенью, брызги в воде и след за игроком можно выключить
в настройках. Косметика ничего не даёт по игре — только вид.
Что было раньше

b12 — сервер и клиент разными сборками, установщик для Windows, каналы
обновлений с откатом.
b11 — можно заходить в воду (плывёшь медленно), мосты, живой человечек.
b10 — города и страны, роли и права, налоги и казна, осады и захват,
победа (все города или чудо света), эпохи: медицина и электричество.
b9 — реки и озёра, пещеры, рыбалка и готовка, погода, стаи волков и
пещерные медведи, дипломатия, рынок.
b8 — голод, инструменты, животные, погода, города, машины, задания, звуки.
Как играть

Один игрок запускает сервер: python run_server.py — он печатает адрес
(192.168.1.5:5555), его надо отдать друзьям.
Остальные запускают клиент: python run_client.py, вводят адрес, входят под
аккаунтом или гостем.
На Windows проще всего установить Civilization-Setup-b13.exe — Python не
нужен, будет ярлык и удаление как у обычной программы.
Технические подробности

Python 3.10+ и pygame 2 (клиент). Сервер pygame не требует вообще: он
ставится отдельным архивом и работает на любом VPS.
До 24 игроков, LAN или интернет при проброшенном порту.
Три языка интерфейса: English / Polski / Русский.
Мир 100×100 тайлов, три эпохи технологий, 60 предметов, ~40 построек.
Сейв мира каждую минуту, аккаунты с PBKDF2-хешами паролей.
EN
Civilization Survival Game — build b13 "All at Once"
A game about a country growing out of a single tree. You land in a world with
biomes and seasons, chop wood, hunt, light a campfire, build your first
workbench — and an hour later you have a city with a town centre, taxes and a
wall. Somebody next to you is doing the same, and sooner or later you are either
allies or neighbours in a siege.

This is the release build: everything planned for 1.0 in one go — a living
world, music, onboarding and quality-of-life.

New in b13

Six biomes. Meadow, forest, desert, snowy tundra, swamp and caves. Trees
in the forest, ore in caves, sheep on meadows, wolves in the tundra. Swamps
and tundra slow you down (0.8 / 0.85), sand is a bit quicker.
Seasons. Spring → summer → autumn → winter, a few game days each. Spring
grows the woods back, autumn fills the world with mushrooms and berries,
winter freezes the ground: everything grows slower, everybody walks slower,
rain turns to fog and snow falls.
Music. A calm day theme and a night theme, separate music in caves and in
a fight. Volume and the on/off switch are in the settings; your own tracks go
into assets/music/ or a resource pack.
First steps. A chain of ten small goals (look around, wood, a tool, stone,
a workbench, a campfire, food, a torch, a city, your first winter) with saved
progress, and an F1 help window with four pages.
Comfort. Every key can be rebound (a taken key is never stolen silently -
the game tells you who has it and offers to swap). Waypoints on the map (P),
inventory sorting (O), chat channels: /g everybody, /l nearby, /c your
country, /w <name> one person.
Looks and emotes. N opens your appearance: 13 clothes colours, headwear,
something on your back and a trail, plus six ready-made outfits. X opens the
emotes (wave, dance, sit, sleep, point, clap, salute, laugh) - everybody
nearby sees them. Your clothes colour also paints your name. Sparks at
campfires, autumn leaves, water splashes and your own trail can be switched
off in the settings. Cosmetics change nothing in the game - only the look.
How to play

One player hosts: python run_server.py prints an address to share
(192.168.1.5:5555).
Everybody else runs python run_client.py, types the address and joins as a
guest or with an account.
On Windows the easiest way is Civilization-Setup-b13.exe — no Python needed,
with a shortcut and a normal uninstaller.
Technical

Python 3.10+ and pygame 2 for the client. The server needs no pygame at all
and ships as its own archive, so it runs on any VPS.
Up to 24 players, LAN or the internet with a forwarded port.
Three interface languages: English / Polski / Русский.
100×100 tile world, three tech epochs, 60 items, ~40 buildings.
World saved every minute, accounts with PBKDF2-hashed passwords.
