# Search

Search covers installed resources and supports several specialized modes. The search box offers query help and a **Browse** builder when you do not want to construct a query manually.

## Search modes

| Mode | Searches |
|---|---|
| All | Combined supported sources across the library |
| Bible | Bible translations, with translation and passage filters |
| Books | Installed reference books, with collection and resource-type filters |
| Morph | Tagged Hebrew and Greek forms, lemmas, and morphology |
| Topics | Indexed people, places, subjects, and related references |
| Media | Images and visual resources, with source and license filters |
| Documents | Your notes, sermons, prayers, journal, and study documents |
| Maps | Biblical places, with place-type filters |

Available filters vary by mode. Results can be sorted by relevance, passage, or resource. Search queries and saved searches can be revisited later.

## Query examples

```text
faith AND lord
"exact phrase"
strongs:G2316
lemma:ἀγαπάω
~pryaer
```

Use AND to require terms and quotes to find an exact phrase. The search interface includes a query builder and inline explanations for syntax. You can limit Bible search to one or more translations and a passage range.

In the Topics view, each reference-work entry has a **Summarise** button: it sends just that entry's text to your configured AI provider and shows the summary in the assistant pane. It is labelled as sending text off the computer; with a local provider nothing leaves it.

A leading `~` searches the closest correct spelling from your library's own vocabulary instead of the typo: `~pryaer` searches for `prayer`. The substitution is reported in the search warnings. Quoted text is never rewritten.

## Morphology

Morph search requires resources with original-language tagging. Select a tagged resource and optionally restrict the passage. The interface accepts a lemma and morphology form (for example `λογος@V-PAI-3S`); choose a form from the UI where possible because morphology codes depend on the tagging scheme.

In the main Search box, `morph:` matches by **grammatical feature** rather than by tag spelling, so one query works across the Hebrew and Greek tagging schemes:

```text
morph:robinson:V-PPM-2S                       an exact tag
morph:"pos=verb tense=aorist voice=active"    features, any scheme
morph:"person=third not:conjugation=qal"      'not:' excludes a feature
```

Available features: `pos`, `gender`, `number`, `case`, `state`, `tense`, `voice`, `mood`, `person`, `conjugation`, `participle`, `degree`, `scheme`, `pos_particle`. Short values are accepted (`person=3`, `number=s`, `gender=m`). A bare tag fragment such as `morph:HNcms` is decoded to its features and matched across schemes; a value that decodes to nothing falls back to a literal tag-fragment match and says so in the search warnings.

## Clause roles

If a **CoNLL-U treebank** is installed, search can ask which word played which part in a sentence:

```text
subject:Jesus object:Peter
subject:Peter NOT object:Jesus
verb:love
role:Jesus
```

Roles are `subject`, `object`, `indirect_object`, `oblique` and `verb`, decoded from Universal Dependencies relations at import time. Both the surface form and the lemma are indexed, and accents and case are folded. `role:` searches every role at once. A treebank is optional — without one these queries return no hits rather than guessing. See [[Importing Bible Modules]] for how to install one.

Third-person pronouns are resolved locally and conservatively: a pronoun is attributed to a name only when **exactly one** name in the last few sentences has compatible person, gender and number. Two compatible names mean no resolution at all. When a name's own features are missing, a nearby article or determiner can supply the gender. Inferred hits are marked with the pronoun they came from (for example `subject:jesus ← He`) in the result and in the Analysis view's **Resolution** column. The **Inferred** button in the search options turns these inferred matches on or off — turn it off to see only explicit words. Nothing is sent to a model or a server for this; a name that is not in the treebank cannot be recovered.

## Results

Open a result in the Workspace to read it in context. Use surrounding context where available. Bible and reference modules may divide or label units differently; check the source module when comparing results.

## Smart Search

The **Ask AI** button turns a plain-language question into a library query when an AI provider is configured. It is optional and sends the question to the provider you selected; see [[AI Assistant]]. Without configuration, use ordinary search and its Browse builder.

## If results are missing

- Confirm the resource is installed and appears in **Library → My library**.
- Some resources need indexing after a source update; see [[Troubleshooting]].
- Morphology searches need tagged text, not merely a Greek or Hebrew font.
- Search covers your local installed library; the Store catalogue itself is not a searchable Bible corpus.
