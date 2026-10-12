# Changelog

What changed between releases, for the release notes. Newest first.

## Unreleased

- Buttons and menu items no longer end in “…”: Cut picture, Profiles, Save to a file and
  the rest read plainly, as in Onion Board. Messages that something is happening keep theirs.
- The app's font is Bahnschrift, the same as Onion Board's.
- A button's icon sits a little apart from its words, as in Onion Board (it was
  squeezed up against Watching), and Watching and Cut picture are equally bold.
- **Light themes: every button and box shows.** Buttons are a shade darker than the
  window, and boxes and drop-downs have a fill instead of white on a white card.
- The main buttons (Cut picture, Watching) get Onion Board's soft gradient and light
  top edge, with the rest of its current look.
- **Same look as Onion Board.** Buttons, boxes, chips and cards are flat with no
  outlines, headings are plain bold, the keyboard focus shows a ring, and the theme
  colours match Board's readability fixes. Trigger cards light up on hover instead of
  getting a coloured outline.
- The watching settings button in the bottom bar has a processor-chip icon instead of
  a second gear, so it doesn't look like the app's Settings.
- Light themes: the buttons and drop-downs on a trigger card have a fill again.
- Loaded inside Onion Board, Onion Watch no longer tries to start a second copy of
  itself as a stand-alone app (Board logged an error about it every time).
- The anonymous daily usage count goes by the day on your PC's clock, not every 24
  hours: using the app in the evening and again the next afternoon counts as two days
  (it used to count as one, and the second looked like a day off). Still one count a day.
- The empty trigger list keeps Hoot and his guidance inside a padded card.

## 0.9.6 (2026-10-09)

- **Roomier Triggers screen.** More space between rows, cards and the list, so it's
  easier to read at a glance.

## 0.9.5 (2026-10-09)

- **+ New trigger button.** Right by the search box: one click makes a trigger that
  watches part of the window, no picture needed (it used to hide in *Add*'s menu).
- **Roomier bottom bar.** More space between *Start watching*, *Cut picture…* and the rest.

## 0.9.4 (2026-10-08)

- **Fewer false alarms on look-alike text.** A cut-out trigger for text with a small
  mark at the end (like "READY?") no longer goes off on the same text without it
  ("READY"). The small, thin mark used to be too faint to count.

## 0.9.3 (2026-10-08)

- **Test shows it's playing.** A card's *Test* now shows in *Playing now* like a
  trigger going off, with its own stop and a working *Stop all*, and the Test button
  says *Stop* while the sound plays. Before, the bar said "Nothing playing" and only
  the board's own Stop all stopped it.
- Fewer hover tips: the ones that only repeated a button's own words are gone.
- **13 more languages**, so every Onion Board language has an Onion Watch one:
  Bahasa Melayu, Čeština, Dansk, Español (Latinoamérica), Filipino, Magyar, Norsk,
  Português (Portugal), Română, Suomi, Svenska, Ελληνικά and Български. A Bulgarian
  board no longer shows an English Triggers tab.
- **Language picker**: Settings → Appearance → Language opens a window of tiles, one
  per language in its own name, with a search (any name, English, or the code).
  *Windows' language* stays the default. The card's title is also in Windows'
  language, and the restart note is in the language picked.
- **Settings look like Onion Board's**: categories on the left (Audio, Alerts,
  Appearance, Updates and privacy, About), cards on the right, theme previews instead
  of a drop-down, and Done at the bottom.
- Inside Onion Board nothing changes: the Triggers tab follows the board's language.
- Inside Onion Board, Hoot's lines, the trigger modes, the ring options and the check
  speeds were always in English whatever the board's language (the board loads the
  add-on's files before it says which language). They follow the board now.
- Hoot's speech bubble goes onto two lines when a translation doesn't fit, instead of
  being cut off.
- Fixed: with a language other than English, pictures in an imported trigger pack
  were lost.

## 0.9.2 (2026-10-07)

- **Lighter Triggers tab**: a closed trigger card makes its editor only when it's
  first opened (about 4x quicker and 3.5x less memory per card), the Log keeps small
  pictures, and the alarm bar, Hoot and the live check rest while nothing needs
  them. Cards look the same.
- **Lighter watching**: with watching off, Onion Watch inside Onion Board no longer loads its
  maths libraries (about half a GB and 18 threads less). Watching keeps its memory
  flat over a long evening, only grabs a window or screen when one of its triggers
  is due, and is quicker on HDR screens and with colour triggers. The app closes
  its sound output after 30 s of silence, and the download is 26 MB smaller.
- One-colour text or icons (a green *READY* against a red one, say) are told apart
  by their colour, so the wrong one no longer sets a trigger off.

## 0.9.1 (2026-10-07)

- **Live chances**: each trigger card shows a small bar filled to how close it is
  to going off right now, with a mark where it fires (green once it's over). A new
  **Chances** button on the Playing now bar opens a window with every trigger's
  chance, closest first.
- Text over a moving scene (HUD text, cut-outs) is found more reliably, with fewer
  false alarms from scenery in other games.
- A card no longer keeps saying "Watching" after you stop watching.
- **14 more languages**: Italiano, Nederlands, Polski, Türkçe, Bahasa Indonesia,
  Tiếng Việt, Українська, العربية (right to left), हिन्दी, ไทย, 简体中文, 繁體中文,
  日本語 and 한국어, the same as Onion Board. Windows in Hong Kong or Macau picks
  Traditional Chinese.
- **Onion Watch in your language**: Deutsch, Español, Français, Português (Brasil)
  and Русский, besides English. Settings → Look → **Language** picks one (*Windows'
  language* by default); *Restart now* shows it. Inside Onion Board the Triggers tab
  follows the board's language.
- Windows grow to fit their text, so longer words aren't cut off.
- Settings from a newer version that this one doesn't know are kept when it saves,
  so going back a version loses nothing.
