# Changelog

What changed between releases, for the release notes. Newest first.

## Unreleased

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
