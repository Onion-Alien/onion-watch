# Everything Onion Watch does

The full list. The [README](../README.md) has the short version.

- **Watches a window, not just a screen.** Windows are captured on their own, so
  a game is still watched while other windows cover it. It can't see a
  **minimized** window, because Windows stops drawing those.
- **Handles several accounts at once.** A trigger watches one window, several
  windows and screens, or **every copy of a game** (also copies started later), and
  the alert says which one it was. Two copies of the same game are told apart by
  the order they were started, so "copy 2" stays your second account's window.
- **More than "it shows up".** A trigger can go off when its picture **appears**,
  when it **goes away** (a buff running out, a fishing bobber), when anything
  **changes** in an area (a new chat line), when nothing has **moved for a while**
  (a stuck or disconnected game), or when a **bar runs low**: point it at a health
  bar, check its colour, and pick the level.
- **Only part of a window.** Drag the area to look in, so other things on screen
  can't set it off (it follows the window when it's resized).
- **Cut from window…** grabs the watched window (even from behind other
  windows) so you can drag a box around the thing to watch for. The **Add** menu
  next to it makes one from a picture file, from a picture you copied with
  Win+Shift+S, or without a picture.
- **Ring until you're back.** An alarm keeps playing until you are: until the
  game moves (it waits for the screen to settle first, so a fade-in doesn't count),
  until you switch to the game, until the thing is gone, until you touch the mouse
  or keyboard, or only until you click Stop. Stop, the tray icon and the Windows
  notification always stop it. Otherwise a sound plays once each time the thing
  appears.
- **What went off** (More → What went off…) lists the latest alerts, each with the
  window as it was checked and a box round what set it off: for "what woke me up?"
  and for setting the numbers. Kept only until the app closes.
- **Built-in alert sounds** (Chime, Ping, Ready, Bell, Alarm), or any sound file of
  yours. Sounds play on the speakers or headphones you pick in Settings.
- Per trigger:
  - several pictures (any of them counts) and several sounds (at random, in
    turn, or all at once);
  - a wait before playing, and a cooldown before it can play again;
  - how long it must last before it counts, so a flicker doesn't set it off;
  - how close a match must be, with the live match shown next to it;
  - staying quiet while the window it went off in is the one you're playing.
- **Categories and profiles for a big library.** Keep hundreds of triggers (up to
  500) in categories of your own and switch a whole category on or off in one
  click; a trigger that's off costs nothing. A **profile** is a set of categories:
  pick one by hand, or set Profile to **Automatic** and a profile turns on while a
  program you tie it to (any `something.exe`, picked from the open windows or
  typed) has a window open or is in front. The list shows how many triggers and
  pictures are on, and says so when that's more than your computer checks often.
- **Duplicate** a trigger, and **save triggers to a file** (pictures and all, each
  in its category; or just one category) to move them to another PC or share them;
  sounds go by name.
- **Search large libraries.** Click **Search** or press **Ctrl+F** to find triggers
  by name, category, game window or sound. Search all categories, choose one in
  **Search in**, or use a category's **Search** button. Folded categories are
  searched too. **Clear filters** restores the list; **Escape** closes search.
  Filtering never switches triggers off or changes which ones are watched.
- **Nothing is lost to a misclick.** Deleting a trigger asks first, and a deleted
  trigger stays in **Recently deleted** for 30 days, pictures and all, so it can be
  brought back.
- **Keeps watching from the tray** when you close the window.
- The same themes as [Onion Board](https://github.com/Onion-Alien/onion-board),
  plus its own teal **Hoot** theme. Onion Watch started as Onion Board's Triggers
  tab.

## How it works

Each check copies the watched window's inside with `PrintWindow`
(`PW_RENDERFULLCONTENT`). For a screen it uses Desktop Duplication, falling back
to GDI. The copy is shrunk to a few hundred pixels and turned grey. Each picture
is then found with normalised cross-correlation (an FFT), so a match scores the
same however bright the game is. Transparent parts of a picture are left out. A
place that matches in grey also has its colours compared with the picture's, so
a red potion isn't taken for a blue one. A place about to go off at the picture's
own size is also compared strip by strip on the full-size pixels (a window's whole
copy; for a screen, just that small box, copied when it's needed), so text one
character apart ("WAVE 7" for "WAVE 1") doesn't set
it off. Text with something added at the end ("READY?" for "READY") still does.

With **Any size** (on by default) a picture is found even when the game shows it
bigger or smaller than when it was cut: cut in fullscreen and played in a window,
at another resolution, or with another UI scale. Each picture remembers the size
of the window it was cut from, so a resized game is matched at once; other sizes
are searched for a couple at a time and kept once found.

**Characters and creatures** work best cut out with a transparent background (a
PNG with the scenery erased): then only the model counts, so it's found over any
background, in daylight or at night, nearer or further away. A plain rectangle cut
around a model brings its scenery with it and is mostly found only where it was
cut. While you cut, the window keeps being looked at (a screen, for a moment after): if
the scene behind the thing moves meanwhile, that scenery is left out of the picture for
you when it works better (with smooth or dark scenery next to it that barely changed),
and a piece that may be missed or go off by mistake is said
straight away. Picture matching can't follow a model that turns or changes pose, or is mostly
hidden: add a picture of each pose to the same trigger (it holds up to 100).

Watching keeps to about 1 % of your processor so games keep their frame rate. On
a slow computer, or with a lot of pictures, it looks less often than the "Check
every" setting rather than use more. The ⚙ on the Triggers bar lets it use more
(2 % or 5 %, or no limit at all) when you'd rather have dozens of pictures noticed
straight away, and shows how often each trigger is being checked. As a guide, measured
on a 16-thread processor with 50 pictures on across 10 game windows ("any size" on), the
1 % setting checks each of them about every half second and really uses about 0.6 % of
the processor (a trigger with an Area costs far less). Fewer pictures are checked more
often, so switch off the categories you don't need now; the list warns when checks are
spaced out past half a second.

"Max detection", under the same ⚙, drops the limit and searches much harder for
pictures shown bigger or smaller than they were cut: always, or only while you're not
in the game (none of the watched windows in front, and no fullscreen window over a
watched screen), going back to your share the moment you are. In the same 10-window
test on an 8-thread processor it noticed things about three times sooner (0.3 s instead
of 0.9 s) and, with all 50 harder cases shown at once, found one more of them, for about
5 % of the processor instead of 0.6 %.

A trigger fires once each time its picture appears, then waits for it to go away
before it can fire again. A window that isn't open yet is looked for every two
seconds, and one that closes is picked up again when it reopens.

If a game's window comes out black (some exclusive-fullscreen games and some
anti-cheat do this), set the trigger to watch the **screen** the game is on
instead.
