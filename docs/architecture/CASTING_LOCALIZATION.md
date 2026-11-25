# Localized Casting descriptions

Casting identity is language-independent. Localized descriptive text is stored
in `casting_translations`, keyed by the stable `casting_id` and language.

Supported catalog languages:

- `ru` — Russian (default/fallback)
- `en` — English
- `ja` — Japanese

The legacy `castings.description` column remains for compatibility during the
transition. Its contents are not copied automatically because the language may
be unknown and previously corrupted text must not be propagated.

The catalog Release detail endpoint accepts `?language=ru|en|ja` and returns:

- `casting.description`: selected translation, falling back to Russian;
- `casting.description_language`: language code actually returned, or null;
- `casting.descriptions`: all available translations for that Casting.

Missing translations remain missing. The API does not machine-translate or
invent text. One Casting remains one entity across all languages; translations
never create additional Castings or Releases.
