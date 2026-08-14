# Doc style

The documentation standard for repos managed through `cfq`. Plugin-level, not per-skill, because
both `pfq` and `ifq` need it. A repo overrides it by adding its own `docs/STYLE.md` — if that file
exists, it wins over this one.

## Files

One file per topic, `kebab-case.md`. The same relative path and the same filename in every
language tree.

## Page structure

- H1 = topic
- Purpose in one or two sentences
- "Prerequisites" only if there are any
- Sections as H2
- At least one runnable example
- "See also" at the end

## Formatting

- Wrap at 100 characters
- Code blocks always carry a language tag
- Exactly one H1 per file
- Links are relative and stay within the same language tree

## Translations

Same outline, same heading order, same examples. Only the prose is translated — code blocks,
identifiers, filenames and commands stay in `codeLanguage`.

## What `docLevel` requires

- `minimal` — `README` only, no `docs/` tree
- `standard` — `docs/` with the entry-level topics: setup, usage, configuration
- `full` — additionally a reference page per module/script and an architecture overview
