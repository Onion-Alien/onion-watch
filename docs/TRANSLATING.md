# Translating Onion Watch

Onion Watch's text is English in the code, wrapped for translation, the same way as
Onion Board's (so the Triggers tab reads like the rest of the board):

```python
from onionwatch.i18n import _, ngettext

QPushButton(_("Add a picture"))
self.undo_bar.show_for(_("Deleted “{name}”", name=t.name), undo)
ngettext("{n} trigger", "{n} triggers", n)
```

- `_()` takes a plain string (never an f-string or `+`): put the changing parts in
  `{placeholders}` and pass them as keyword arguments, so a translation can move them.
- `ngettext(singular, plural, n)` for text with a number in it; `{n}` is filled in.
- Whole sentences, not pieces glued together: "Screen 2 isn't plugged in…" and "the
  window…" / "the screen…" are separate texts, because other languages change the
  words around them.
- Don't wrap log messages, settings keys, the update / usage JSON or file names.
- Don't use `_` as a throwaway name (`path, _ = …`) in a function that calls `_()`:
  write `path, __ = …`. Where a module needs `_` for throwaways (the engine,
  `screenwatch.py`), call `i18n._("…")` instead. `scripts/i18n_extract.py` and the
  tests catch both.

## The catalogs

`onionwatch/lang/<code>.json`, inside the package so they travel in the Onion Board
add-on zip and the built app:

```json
{
  "_meta": {"name": "Deutsch"},
  "Add a picture": "Bild hinzufügen",
  "Deleted “{name}”": "„{name}“ gelöscht",
  "{n} trigger": ["{n} Trigger", "{n} Trigger"]
}
```

- The key is the English exactly as in the code. An empty or missing translation shows
  the English.
- Plural entries are a list of forms in the order of the language's rule
  (`onionwatch/i18n.py` → `PLURALS`): English, German, Spanish: one, other; French and
  Portuguese (Brazil): 0–1, other; Russian: one, few, many.
- Keep the app's tone: short, plain, friendly words. Keep `{placeholders}`, `<b>…</b>`,
  `&amp;` and line breaks as they are. Use the same words Onion Board uses for shared
  things (sound, trigger, hotkey, Settings, headphones).

`python scripts/i18n_extract.py` lists, per language, what's missing and what's no
longer used; `--update` adds the missing texts (empty) to every catalog and drops the
unused ones; `--check` exits 1 if anything is off. The tests also check that every
catalog is complete and keeps the placeholders.

A new language: copy a catalog to `<code>.json` (a Windows language code: `it`,
`pl`, `zh-CN`…), set `_meta.name` to the language's own name, translate, and add its
plural rule to `PLURALS` if it isn't one / other.

## Which language

- The app: Settings → Look → **Language**. *Windows' language* (the default) uses
  Windows' display language when there's a catalog for it, else English. A change
  shows after a restart (*Restart now*). Saved as `language` in `config.json`.
- Inside Onion Board: the board's language (its host's optional `language()`), else
  Windows'.
- `ONIONWATCH_LANG=de` (or `xx`) overrides both, for checking a translation from
  source.

## Checking the layout

The pseudo-language `xx` (`ONIONWATCH_LANG=xx`) shows every wrapped text as
`[Šéttîñĝš~~~]`: about 40 % longer, like German or Russian. In a screenshot, text
without brackets isn't wrapped yet and a missing `]` means the label cuts it off.
`i18n.unwrapped_texts(widget)` lists the unwrapped ones for a test. Dialogs grow to
fit their text (`ui/fit.py`), so check labels and buttons that can't wrap.
