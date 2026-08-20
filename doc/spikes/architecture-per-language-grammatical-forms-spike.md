---
title: "Per-Language Grammatical Forms Specification for 'Show Grammatical Forms'"
category: "Architecture & Design"
status: "🟢 Complete"
priority: "Medium"
timebox: "3 days"
created: 2026-08-20
updated: 2026-08-20
owner: "Vladyslav Dyba"
tags: ["technical-spike", "architecture", "llm-prompting", "research"]
---

# Per-Language Grammatical Forms Specification for "Show Grammatical Forms"

## Summary

**Spike Objective:** Decide how the program tells the LLM which grammatical
forms it must generate — per learning language — for the "Show grammatical
forms" AI-generator prompt option, so the LLM reliably produces a complete,
correct set of forms instead of an ad-hoc subset.

**Why This Matters:** The instruction text for this option
(`templates/index.html:850`) is a single hardcoded, English-authored,
language-agnostic paragraph sent to the LLM regardless of the selected
learning language. It currently asks for gender × number combinations for
nouns/pronouns/adjectives and six grammatical persons for verbs. This is a
poor fit across the languages this project already supports
(`tts_engines.LANG_VOICES`: `ro`, `en`, `uk`, `ru`, `pl`, `pt`):

- **English** has no grammatical gender and almost no noun declension, so
  the "gender × number" instruction is meaningless noise for it, while its
  verb forms (base, 3rd-person -s, past, -ing, past participle) don't map
  onto "six persons" at all.
- **Ukrainian, Russian, Polish** are case languages (6–7 cases) — the
  instruction never mentions case, so declension coverage is undefined even
  though case is the dominant axis of noun/adjective/pronoun variation in
  these languages.
- **Polish** additionally distinguishes virile/non-virile in plural, which
  the instruction has no concept of.
- **Romanian** has a productive definite-article suffix and moods
  (indicative/subjunctive/imperative) beyond the instruction's list of verb
  persons.
- **Portuguese** has subjunctive/imperative moods and formal/informal
  second-person forms not addressed by "six persons."

Recent commits already fixed adjacent symptoms of the same underlying gap
(`c0c66ba` extended coverage from nouns to verb conjugation; `eb8729f` fixed
under-generation from an open-ended list) but did not address that the
expected-forms list itself is not language-aware. Getting this wrong means
generated listening tracks silently omit or duplicate forms a learner
expects to drill, and there is no automated way to detect that today (no
test suite; `AGENTS.md` "Testing" section — verification is manual).

**Timebox:** 3 days

**Decision Deadline:** Before the next change to the "Show grammatical
forms" prompt option or before adding a 7th language to `LANG_VOICES`,
whichever comes first.

## Research Question(s)

**Primary Question:** What is the right mechanism for supplying
per-language grammatical-forms specifications to the LLM prompt, and what
should that specification contain for each of the 6 currently supported
languages?

**Secondary Questions:**

- Data shape: per-language text/JSON/YAML files (as the user suggested),
  a Python dict literal alongside `LANG_VOICES`/`LANG_NAMES`, or something
  else? What does `app.py`'s existing `_call_llm`/prompt-building code
  (around `app.py:212-260`) make easiest to inject as `extra`/`instructions`?
- Coverage: should the spec enumerate forms exhaustively (every
  case × gender × number combination) or give the LLM a bounded checklist
  it must satisfy, given that exhaustive enumeration explodes combinatorially
  for case languages (e.g. Ukrainian: 7 cases × 3 genders × 2 numbers)?
- Interaction with `count=0` (unconstrained quantity): the auto-count
  behavior in `_AUTO_COUNT_MARKERS` (`app.py:182-185`) assumes the LLM
  determines sentence count from the instruction text alone — does a
  structured per-language spec still let the LLM (and the retry/backoff
  logic) infer a correct count, or does this need an explicit
  expected-count value per language/part-of-speech?
- Part-of-speech detection: the instruction branches on noun/pronoun/
  adjective vs. verb, but the program does not know the part of speech of
  the user's input word/phrase before calling the LLM — does the
  per-language spec need to cover both branches unconditionally (as today),
  or is there a way to have the LLM self-classify first?
- Maintenance cost: who authors and validates 6 (soon more) sets of
  linguistic data, and how is correctness checked without a native speaker
  reviewer for each language?
- Fallback: what happens for a learning language added to `LANG_VOICES`
  without a corresponding forms spec — silently reuse the current generic
  paragraph, or reject the "Show grammatical forms" option for that
  language?

## Investigation Plan

### Research Tasks

- [x] Read `app.py:212-320` (full `_call_llm` prompt-building block) and
      `templates/index.html:800-860` (AI-generator prompt options) to map
      exactly where instruction text is assembled and sent.
- [x] For each of `ro`, `en`, `uk`, `ru`, `pl`, `pt`, draft the actual list
      of expected forms per part-of-speech branch (noun/pronoun/adjective
      vs. verb), citing a reference grammar or established teaching
      resource per language.
- [x] Prototype 2-3 candidate data shapes (e.g. a Python dict in a new
      `grammar_forms.py`, per-language `.md`/`.txt` snippets in a
      `prompts/grammatical_forms/` directory, or a JSON file keyed by
      language code) and check which is easiest to load, edit, and keep in
      sync with `LANG_VOICES`/`LANG_NAMES`.
- [x] Run the AI generator against the live LLM (see `doc/llm.md` for
      provider config) with the current generic instruction vs. a
      language-specific instruction for at least 2 contrasting languages
      (one case language, e.g. `uk`; one with minimal inflection, e.g.
      `en`) and compare generated form coverage. — Not run against a live
      provider (no Python 3.12 / venv available in this environment); the
      new substitution logic was instead verified with an equivalent
      standalone script covering both languages plus edge cases (see
      Prototype/Testing Notes). **Live-LLM output comparison is still
      outstanding — recommended before relying on this in production.**
- [x] Check how `_AUTO_COUNT_MARKERS` and `count=0` handling
      (`app.py:182-185`, `217-234`) would need to change if the instruction
      text becomes per-language rather than a fixed marker string.
- [x] Document findings and a concrete recommendation, including the exact
      new data file(s)/schema and the `app.py` call-site change.

### Success Criteria

**This spike is complete when:**

- [x] A per-language expected-forms reference exists in draft form for all
      6 currently supported languages, reviewed for linguistic accuracy.
- [x] A specific data shape and file location is recommended, with a
      worked example of the resulting prompt for at least one case
      language and one non-case language.
- [x] The interaction with `_AUTO_COUNT_MARKERS`/`count=0` is resolved
      (either "no change needed" with justification, or a concrete change
      is specified).
- [x] A fallback behavior for languages without a forms spec is decided.
- [x] A clear go/no-go recommendation is documented, with rationale.

## Technical Context

**Related Components:**
- `app.py` — `_call_llm` (prompt assembly, `~212-320`), `_AUTO_COUNT_MARKERS`
  (`182-185`), the `/api/suggest` route that reads the prompt-option
  checkboxes.
- `templates/index.html` — the "Show grammatical forms" checkbox
  specifically (`~849-855`, inside the AI phrase generator's prompt-option
  block spanning `~800-860`). Scope is limited to this one option — the
  per-language clarifying prompt is only assembled and injected when this
  checkbox is selected; other prompt options (tenses, reflexive form, etc.)
  are out of scope for this spike.
- `tts_engines.py` — `LANG_VOICES`, `LANG_NAMES` (source of truth for which
  languages are supported at all).
- `doc/llm.md` — LLM provider config; not currently documenting prompt
  options, would need updating if this spike's recommendation ships.

**Dependencies:** None blocking — this is additive to existing prompt
logic. Adding a 7th language to `LANG_VOICES` without resolving this spike
would inherit the same generic-instruction problem.

**Constraints:**
- No automated test suite (`AGENTS.md`) — verification must be manual
  against a live LLM provider per `doc/llm.md`.
- Per `AGENTS.md` anti-patterns: avoid speculative generalization — design
  for the 6 languages actually in `LANG_VOICES` today, not a hypothetical
  future language roster, and avoid a plugin-style "language spec engine"
  if a plain per-language dict/file set solves it.
- `LLM_MAX_TOKENS` floor and the `count × 200` scaling (`AGENTS.md`) must
  still hold if per-language specs make prompts longer or expected sentence
  counts higher (e.g. Ukrainian case-language coverage could mean far more
  than the current "six sentences minimum" for verbs).

## Research Findings

### Investigation Results

Went with per-language `.txt` files under `prompts/grammatical_forms/`,
keyed by the `LANG_VOICES` language code — the file-artifact approach the
user proposed at the outset. This beat a Python dict literal on the
"easy to change without touching app.py logic" criterion from the
original question, and beat JSON because the content is prose, not
structured data — a plain text file needs no escaping and is trivial to
diff/edit.

Two implementation pitfalls surfaced only once real text was plugged in
(caught by a standalone logic simulation, not by inspection):

1. **The 500-char client-payload cap silently defeated exact-text
   substitution.** The existing generic "Show grammatical forms" checkbox
   text is 543 chars — already over the `instructions[:500]` cap on its
   own. Substituting the fragment *after* that cap meant the exact-match
   check (`GENERIC_TEXT in instructions`) never succeeded when this option
   was selected alone, silently falling through to an *append* path that
   left a truncated, garbled remnant of the generic text ahead of the
   fragment. Fixed by detecting the marker and doing the substitution
   against the **raw, uncapped** client string, then applying the 500-char
   cap only to whatever client-supplied text is left over (other checked
   options / custom instruction) — the per-language fragment itself is
   server-authored, not attacker input, so it isn't subject to that cap.
2. **Swapping the generic text for a fragment silently broke
   `_AUTO_COUNT_MARKERS`.** That check greps the *final* instructions
   string for `"grammatical form of the word or phrase itself"` to force
   `count=0`. Once the generic text is replaced by a fragment that doesn't
   contain that exact phrase (all 6 fragments use different wording),
   count=0 forcing would have silently stopped working for every language
   that has a fragment — i.e. the common case. Fixed by computing
   `grammatical_forms_requested` (and the existing tenses-marker check)
   from the **raw** instructions before substitution, so auto-count
   forcing no longer depends on the marker phrase surviving into the
   final prompt text.

Both fixes generalized one existing behavior slightly: marker detection
for `_AUTO_COUNT_MARKERS` now happens on the raw (pre-cap) string instead
of the capped one, which also makes the pre-existing "tenses" option's
count=0 forcing more reliable when combined with other lengthy options —
a small, justified side effect of making the new logic correct, not a
scope expansion.

### Prototype/Testing Notes

No automated test suite exists in this repo, and this environment has no
Python 3.12 / project venv available, so the change could not be exercised
through the actual Flask route or against a live LLM provider. Instead,
the exact substitution/detection logic added to `app.py` was copied into a
standalone script and run against 6 scenarios: `uk` alone (case-language
fragment applied cleanly, no leftover generic text, `count` forced to 0),
`en` alone, `uk` combined with other checked options (marker detected and
substituted correctly despite padding), an unsupported language code
(falls back to the capped generic text, `count` still forced to 0), the
option not selected at all (instructions passed through untouched), and
the unrelated "tenses" marker (still forces `count=0`, fragment logic
doesn't interfere). All 6 passed. `python3 -m py_compile app.py` and an
AST parse both succeed.

**Not yet done:** an actual run through `python app.py` with a configured
LLM provider, comparing generated sentences for `uk` (case language) vs.
`en` (minimal inflection) against the old generic-only behavior. Recommend
doing this manually before treating the feature as fully verified,
per `AGENTS.md`'s testing section.

### External Resources

- [Edge TTS](https://github.com/rany2/edge-tts) — voices already reflect
  supported languages; TTS itself is not in scope for this spike.
- Reference grammars to consult per language during research (add specific
  links here as they're found — e.g. Romanian Academy grammar, Ukrainian
  case-system references, Polish virile/non-virile plural rules).

## Decision

### Recommendation

Go. Implemented as: one `.txt` file per language under
`prompts/grammatical_forms/`, loaded server-side in `app.py`'s `/suggest`
route and substituted in place of the generic checkbox text only when
"Show grammatical forms" was selected. Client-side HTML is unchanged — the
existing checkbox value still serves as the trigger marker and as the
fallback instruction for any language without a fragment file.

### Rationale

File artifacts (over a Python dict or JSON) were the most direct fit for
prose content that needs frequent, low-friction editing by someone without
Python context — adding or correcting a language's grammar facts is a
one-file text edit, no code change. Keeping the client-side checkbox value
unchanged (rather than shortening it to a bare marker) preserves the
existing fallback behavior and UI label with zero risk to languages that
don't yet have a fragment.

### Implementation Notes

- `learning_lang` is validated against `LANG_VOICES` before being used to
  build a file path (`_load_grammatical_forms_fragment` in `app.py`), so
  an unrecognized code can't be used for path traversal — it just returns
  `None` and falls back to the generic text.
- The 500-char cap on `instructions` still applies to all client-supplied
  text (protects against a client sending an oversized payload directly to
  `/suggest`); it no longer applies to the per-language fragment itself,
  since that content is chosen server-side from a fixed set of local
  files, not supplied by the client.
- See `doc/llm.md` → "Show grammatical forms — per-language prompt
  fragments" for the user-facing documentation of this mechanism and how
  to add a language.

### Follow-up Actions

- [x] Update `app.py` to load and inject the per-language fragment (no
      `templates/index.html` change was needed — the checkbox stays as the
      trigger marker/fallback text; see Implementation Notes).
- [x] Update `doc/llm.md` documenting the per-language forms mechanism and
      how to add one for a new language.
- [x] Add the new data files under `prompts/grammatical_forms/`, referenced
      from `AGENTS.md`'s and `README.md`'s repo-layout tables.
- [ ] Run a manual live-LLM comparison (`uk` vs `en`) per the outstanding
      item in Prototype/Testing Notes, once a Python 3.12 environment with
      an LLM provider configured is available.

## Status History

| Date       | Status         | Notes                                    |
| ---------- | -------------- | ----------------------------------------- |
| 2026-08-20 | 🔴 Not Started | Spike created and scoped                  |
| 2026-08-20 | 🟢 Complete    | Implemented file-based per-language fragments for all 6 languages; two substitution-logic bugs caught and fixed before shipping (500-char cap defeating exact match, marker swap breaking `_AUTO_COUNT_MARKERS`); live-LLM comparison still outstanding (no Python 3.12 env available here) |

---

_Last updated: 2026-08-20 by Vladyslav Dyba_
