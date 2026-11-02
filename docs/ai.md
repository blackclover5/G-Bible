# AI Assistant — Specification

Status: **Phase 4 implemented.** Retrieval-grounded chat with streaming, a
provider switcher (local Ollama / LM Studio / llama.cpp, a cloud API, or one of
the three **free tiers** — Groq, Google AI Studio, OpenRouter), per-provider
keys, live model discovery with a one-click reachability test, clickable
citations, **the reader's own notes, highlights and clips as a corpus of
their own**, **Explain / Summarise / Translate** actions on a selection or a
passage, **Smart Search** (a plain-English question turned into a query for the
reader's own engine), the assistant **at the head of every topic guide** with
**questions written from the guide's own material** and a way to carry the
exchange into the chat panel, **a passage put in front of the assistant** to
ask a question about, **ranking by meaning as well as by words** wherever the
provider can embed, **conversations kept** and **the library narrowed by a
scope**, **Sermon research** (outline, illustration and exposition material,
cited, refusing to draft the sermon), and **usage metering** so a cloud bill
is never a surprise. Flatpak packaging is the last phase.

The assistant is **opt-in**. With no provider configured the app is exactly what
it was: fully usable, entirely offline, and it never makes an outbound request.

---

## Read this first

1. **The assistant retrieves; it does not remember.** Every answer is composed
   from passages already installed in the local library, and from the reader's
   own notes, highlights and clips. The language model is the reasoning
   step over a supplied corpus — it is not the corpus. This is the whole reason
   the result can be trusted where a plain chatbot cannot be.
2. **Sources are shown before the answer.** The first event on the stream
   carries the citation list, before a single token is generated, so the sources
   cannot be reconstructed after the fact to fit a reply the model already wrote.
3. **A citation opens the passage.** Every source chip opens its reference in
   the workspace, so a claim can be checked in one click. The reader's own
   material opens the note, the highlight or the clip itself.
4. **"Local" is a first-class choice, not a fallback.** A reader who chose an
   offline library can keep the whole feature offline by pointing it at Ollama,
   LM Studio or llama.cpp on `127.0.0.1`. Nothing leaves the machine in that
   mode.
5. **The model list is asked for, not guessed.** Pressing **Test** asks the
   provider which models it actually has and reports whether it answered at all.
   A preset list is a promise the software cannot keep — the reader would find
   out it was wrong only when a question failed — so the real list replaces it,
   and a stale saved model name is quietly moved to one that exists.
6. **It will not write your sermon.** Sermon research returns sourced notes and
   refuses to draft prose, because the work of preaching is the preacher's and a
   paragraph the model wrote is one they would have to check word by word. See
   *Sermon research*, below.
7. **Your own notes are yours, and are marked as such.** The reader's own
   material is retrieved, cited and opened, and the model is told to report it
   as *the reader's* — never as a commentary, never with an author's name on
   it. See *The reader's own material*, below.
8. **A passage can be put in front of the assistant.** "Ask…" on a selection,
   or the **+** button for the book you have open, makes it the first source,
   so that "what does Paul mean by this?" is answered about *this*. See *A
   passage in front of the assistant*, below.
9. **The sources are ranked by meaning as well as by words**, where the
   provider can turn text into a vector. Nothing is indexed: the vectors are
   made for the candidates of that one question and thrown away. See *Ranking
   by meaning, not just by words*, below.
10. **The conversation is kept.** It is written down as it happens, with its
    citations, titled with the reader's own question, and picked up again when
    the app is opened. It stays on this machine and is not synced. See
    *Conversations*, below.

---

## What leaves the machine

| Provider | Where the text goes | What is sent |
| --- | --- | --- |
| Ollama (local) | nowhere — `http://127.0.0.1:11434` | nothing leaves the box |
| LM Studio (local) | nowhere — `http://127.0.0.1:1234/v1` | nothing leaves the box |
| llama.cpp (local) | nowhere — `http://127.0.0.1:8080/v1` | nothing leaves the box |
| OpenAI | `api.openai.com` | the retrieved passages and the question |
| Anthropic | `api.anthropic.com` | the retrieved passages and the question |
| Groq *(free)* | `api.groq.com` | the retrieved passages and the question |
| Google AI Studio *(free)* | `generativelanguage.googleapis.com` | the retrieved passages and the question |
| OpenRouter *(free)* | the model's own provider, via `openrouter.ai` | the retrieved passages and the question |

LM Studio and llama.cpp both expose an OpenAI-compatible server, so they reuse
the `openai` adapter for free — only the port differs — and neither needs a key.
The three free tiers are OpenAI-compatible too, so they reuse the same adapter
with nothing new in the transport.

What travels is the passages *for this question* (at most `max_sources`, trimmed
to ~1,200 characters each), the recent turns of the conversation, and the
question. The library is never uploaded, and neither is a key for any other
service. The UI states the current provider's behaviour under the input box, so
the reader is never guessing.

**The reader's own material travels with it, and that is worth being explicit
about.** When *Use my own material* is on, the notes, highlights and clips
that bear on the question are sent to the provider just as the library's
passages are — they are part of the same retrieval. They are the reader's most
private writing, so this is the one thing to turn off before putting anything
that matters into a cloud provider, and the settings screen says how much of
it there is. With a **local** provider nothing leaves the machine either way,
and the "Private" badge covers both corpora.

The same is true of a topic guide's **suggested questions**: they are written
from the guide's own material, so that material goes to the provider in that
call too. It is the same material the answers are grounded in, and it is the
material the reader has already chosen to have the assistant read.

**And the question itself goes twice.** The assistant asks the model which
words to search with before it searches, so the question is sent once for that
and once for the answer. It is the reader's own question and nothing more,
and it goes to the same provider either way.

**And the same is true of the semantic re-ordering.** When the provider can
embed, the passages that bear on the question are sent to it to be turned
into vectors — the question and a few dozen candidates. That is a *second*
sending of the same passages, and it goes to the same provider, so the
privacy note above covers it: with a local provider nothing leaves the
machine, and with a cloud provider the passages for the question go there
twice rather than once.

Keys follow the codebase's existing credential rule: they live in
`api-credentials.json` (mode `0600`) **beside** the database, not inside it, so a
database carried to somebody else does not carry the reader's key with it. A key
is never rendered back into the page — the UI only ever shows whether one is set.

What the assistant *records* also never leaves the machine: the usage record is a
table in the local database (`ai_usage`), read by **Settings → AI**, and cleared
by **Forget**. No telemetry, no call home, no vendor dashboard.

---

## How it works

```
question ──► the model writes the search query ──┐
                                                  ▼
question ──► normalise ────────────────► local search ──► candidate pool ──┐
                                                                          │
question ──► own material ──────────────────────► top notes ──────────────┤
                                                                            ▼
                                                  embed + re-order by meaning
                                                                            │
                                                 ┌──────────────────────────┘
                                                 ▼
                                      numbered sources (diversity trimmed)
                                                 │
                                    ┌────────────┘
                                    ▼
                    system prompt + sources + history + question
                                    │
                                    ▼
                          provider adapter (streaming)
                                    │
                                    ▼
                   SSE: sources ─► deltas ─► done   (rendered as it arrives)
```

* **Retrieval** reuses the app's own search engine (`gbible/search.py`). The
  question is reduced to its content words (interrogatives and stop words
  dropped), because the engine implements the search query language and would
  otherwise treat "about" as a term to find.
* **The model writes the search query.** The stripped question is a poor
  search; see *The query the assistant searches with*, below.
* **The reader's own material** is retrieved separately (`gbible/mine.py`) and
  merged in afterwards. See *The reader's own material*, below.
* **The candidate pool is wide, and is re-ordered by meaning** where the
  provider can embed. See *Ranking by meaning, not just by words*, below.
* **Lookup-shaped resources are excluded** from grounding — a lexicon headword,
  an atlas caption or a concordance entry is not a passage *about* the subject.
  Bible translations are capped so they cannot fill every slot, leaving room for
  commentaries and study guides.
* **Transport** is one generator (`gbible/ai.py: stream`) over three adapters:
  `openai` (also covers any OpenAI-compatible endpoint, including LM Studio and
  llama.cpp), `anthropic`, and `ollama`. Adding a vendor that speaks one of these
  schemas is a row in `PROVIDERS`, not a branch.
* **Discovery** is one GET (`gbible/ai.py: probe`): Ollama answers `/api/tags`,
  everything else `/models`. It is deliberately an HTTP error, not a failure,
  when the server answers and refuses — "wrong key" and "not running" send the
  reader to two different places, so the reply distinguishes "reachable" from
  "ok".

---

## The query the assistant searches with

This is the half of the hybrid search that is not about ranking, and it is the
half that matters most.

**The stripped question is a poor search.** "How do I stop being anxious?"
becomes *"stop being anxious"*, and "stop" and "being" are both **more common
in the library than "anxious"** — 26,418 units against 1,081. So the two words
that say nothing about the subject dominate the ranking, and being ANDed they
destroy the recall: the passage that actually answers the question never
enters the pool at all.

The engine cannot know that a text about **worry** is a text about
**anxiety**. It matches words; it has never been told what the words mean.
**The model can**, and that is the whole of the semantic half of the hybrid:
*the model supplies the meaning, the engine does the arithmetic.*

So before searching, the assistant asks the model which words a source on the
subject would use, and the model writes them in the engine's own query
language:

| The reader asks | The model writes |
| --- | --- |
| how do I stop being anxious? | `anxious AND worry` |
| how can I overcome my fear? | `fear AND afraid AND dread` |
| how do I forgive someone who hurt me? | `forgive AND forgiveness AND pardon` |

**The plain question is still searched**, as a safety net — but only when the
model's query found too little to work with. So a model that writes a useless
query costs the reader nothing, and a good one is not diluted by the noise the
plain question brings.

Measured over five ordinary questions, asking for the passage that answers
each:

| | the answering passage is in the pool |
| --- | --- |
| the stripped question | **3 of 5** |
| the model's query | **5 of 5** |

The question is not "is it first" but "is it in the pool at all", because the
re-ordering can only choose from what the search found. With the passage in
the pool, the semantic re-ranking has something to work with; without it, the
re-ranking is rearranging the wrong eight.

**It costs one extra call per question** — a short one, whose answer is a
single line of query. It is a switch in **Settings → AI** (*Let the model
choose the search words*), and it works with **every** provider, including
Anthropic, which has no embeddings endpoint. The expansion is cached by
question, so a question asked twice is searched for once.

**Where it does not apply.** Sermon research is anchored to a *passage* — a
location, not a question — so its grounding is already precise and it does
not pay for an extra call.

## Ranking by meaning, not just by words

The search engine finds passages by their **words**. It is very good at that,
and it is very good at it because the work is arithmetic — BM25, proximity,
coverage — and arithmetic does not know that *anxious* and *worry* are the
same thing.

That is a real gap, and it is the gap semantic search closes with
semantic search. A reader asks *"how do I stop being anxious?"* and the
lexical engine finds the passages that **use the word**. The passage that
answers the question is the one that says *"do not worry about your life"* —
and no amount of stemming, proximity or coverage will find it, because the
two share nothing.

So the candidates the search engine found are **re-ordered by what they
say** as well as by what they are made of.

### Nothing is indexed

This is the part that makes it affordable, and it is deliberate.

The library holds **more than a million units**. There is no way to embed
them all, and an index of a million vectors would be a thing to keep fresh,
to store, and to move between machines. So **nothing is indexed**. The
vectors are made at the moment of the question, for the few dozen candidates
the search engine already found, and thrown away afterwards.

The cost is a handful of extra calls per question. The benefit is that there
is no index to go stale, no background job to run, and nothing new to sync.

### The three steps, in order

The order matters, and it is the opposite of what it looks like.

| Step | What happens | Why here |
| --- | --- | --- |
| **Find** | the search engine returns a wide pool of candidates | the engine recalls better than the model does, and a passage that answers the question without repeating any of its words is not in the top few |
| **Re-order** | the pool is ranked by meaning as well as by words | this is the step that moves "how do I stop being anxious?" from the passages that use the word to the passage that says "do not worry about your life" |
| **Trim** | the diversity rules are applied: two units per commentary, three translations of a verse | applying them earlier would throw away candidates the re-ordering might have put at the top |

The two scores are **normalised over the candidate set** before they are
combined. A BM25 score and a cosine similarity are not on the same scale, and
adding them raw would mean the larger one decided everything.

### Not every provider can do this

Turning text into a vector is a separate capability from answering with one,
and **not every provider has it**:

| Provider | Embeddings? |
| --- | --- |
| **Ollama** | yes — `nomic-embed-text` (pull it first) |
| **LM Studio, llama.cpp** | yes — whichever model the server has loaded |
| **OpenAI** | yes — `text-embedding-3-small` |
| **Anthropic** | **no** — there is no embeddings endpoint |
| **Groq, Google AI Studio, OpenRouter** | **no** — they proxy chat models, not embedding ones |

**A provider that cannot embed is not a worse provider.** The retrieval is
lexical, the answer is the same, and only the ordering of the sources is not
improved. Settings → AI says which case the reader is in, and the switch is
disabled rather than pretending.

The switch is on by default wherever the provider can do it, and it can be
turned off — it costs a few extra calls, and a reader on a free tier may
prefer not to spend them.

---

## A passage in front of the assistant

A question like *"what does Paul mean by this?"* is about a **place**, and the
search engine cannot find a place from those words. The passage itself has to
be supplied, or the answer is about something else.

So the reader can put a passage in front of the assistant, and it becomes
**source [1]** — the first numbered source, cited like any other, and openable
from the citation list. The prompt carries a rule with it:

> The reader has put a passage in front of them, and their question is about
> that passage. Source [1] is it. Focus your answer on it, and cite [1] when
> you say something about what it says. The other sources are context for it,
> not the subject of the question.

There are three ways to do it, and they are the same thing:

- **Ask…** on a selection — *Ask* puts the selection in front of the
  assistant and the reader asks their own question about it, which is a
  different thing from asking for an explanation of it.
- **The "+" button** — the text at the reader's current location in a book
  they have open in the workspace. The reader often wants to ask about the
  passage in front of them without having to select it and copy it.
- **The Passage** — already grounded there.

The passage belongs to the question that was asked about it: once the answer
has arrived, it is cleared, and the next question is a new one.

---

## The reader's own material

The assistant reads two corpora, and they are kept apart on purpose.

The **library** is the published material: the commentaries, lexicons, atlases
and Bible translations the reader has installed, found through the app's own
search engine. The **reader's own material** is what the reader has written
and marked: notes, journal entries, sermons, prayer lists, highlighted
passages, and the excerpts they have gathered into clips.

Before this existed, the assistant could see only the first of the two. That
meant it could not answer the question a reader is most likely to ask their own
Bible software — *what did I think about this?* — and a private note, which is
the most personal and often the most useful thing in the app, was invisible to
it.

### Why a separate module, and a separate retrieval

`gbible/mine.py` is not a new scope in the search engine, and that is
deliberate. The search engine ranks *published* material: millions of units, a
positional index, a full-text table, a query language. The reader's own
material is a different corpus answering a different question. "What does the
Bible say about faith" wants the best commentary; "what did I write about
faith" wants the reader's own words, and would be badly served by a ranking
tuned to find scholarship.

So it is retrieved on its own, with its own query handling and its own
ranking — BM25 over a few hundred documents, with the same constants the
search engine uses, so the two corpora are ranked on the same scale of "this
document answers this question".

| Kind | Where it comes from | What the reader's own words are |
| --- | --- | --- |
| **Note** | the `note` table | the body |
| **Journal, sermon, prayer** | the same table, a different `kind` | the body |
| **Highlight** | the `highlight` table | the note attached to it; the passage itself is somebody else's text, and the block says so |
| **Clip** | the `clippings` setting | the heading and the choice to gather it; the excerpt is the book's |

Notebooks are deliberately not a separate kind. A notebook is a *view* over
notes (a kind, a tag or a query), so the notes it holds are already in the
corpus and are found there. Counting them twice would answer the same question
twice.

### The question is not the same question

"What did I write in my notes about justification?" asks about *justification*.
"write", "notes" and "my" are the reader saying **where to look**, not what
they are looking for — and left in, they match any document that happens to
contain the word "note" and pull it above the one that actually discusses the
subject. So the own-material query drops the request words, and the ordinary
English function words with them. If a question is made entirely of dropped
words, they are used after all, so "what did I write?" still finds something.

### One place is found by the anchor rather than by the question

Everywhere else, the own material is found by the words of the question. There
is one exception, and it is the most important one.

A note taken on a verse is *about* that verse, whatever words it uses. A note
that says *"conditional immortality — see Morris"* shares no terms at all with
John 3:16, so a text search will never find it: the anchor is the only thing
that connects the two. So when the reader asks the assistant to **explain** a
passage, the notes and highlights **anchored to that passage** are gathered
too, by the reference rather than by the words.

This is the same distinction the sermon research draws between a passage as a
*location* and a subject as a *question*, and it is why the Passage's
**Explain** button is the one place the reader's own writing turns up
unsolicited — because that is where the reader most expects to find it.

### How the two are presented

The reader's own material is a **section of its own** in the grounding the
model reads, not a continuation of the library's:

```
Library sources for this question:

[1] Matthew Henry — Romans 8:1
    …

The reader's own material — their own notes, the passages they marked, the
excerpts they gathered. These are the reader's own words, not a published
source:

[6] my note · 19 Oct 2026 — My note on the atonement
    I read the atonement as the appeasement of divine anger, and I am not
    sure I agree with the penal substitution account of it.
```

And the system prompt carries a rule about it:

> Some sources are the reader's own material — notes, journal entries,
> highlights and clips they wrote or marked. That is the reader's own view,
> not a published source. Report it as theirs ("in your note on X you
> wrote…"), never attribute it to an author, and never present it as what a
> scholar said. Where the reader's own material and a published source differ,
> report both and say which is which.

The last sentence is the one that matters. A plain chatbot cannot tell you
that your own reading and a commentary disagree, because it has only one of
them. This can.

In the interface the citations are **marked as yours** — a dashed, accented
border rather than the plain chip of a published source — and each one opens
the thing it names: a note opens in the editor, a highlight opens the verse it
marked, a clip opens its folder. A citation that cannot be opened is a
claim the reader has to take on trust, which is the one thing the whole design
is trying to avoid.

### How much of it there is

The own material gets **a third of the source budget** when the library is
also on. That is a working number rather than a principle: enough for the
reader to see what they have written, without their own notes crowding out the
commentaries that give those notes something to answer to. The share is
reserved *before* the library is searched, so a large library cannot crowd the
own material out — and any of the share that goes unused goes back to the
library, so a reader with no notes of their own on the subject still gets a
full set of sources.

With the library turned off, the own material has the **whole** budget — "what
did I think about this?" deserves an answer built only out of what the reader
thought, and a cap on it would be a cap on the only corpus there is.

**Settings → AI** shows how much of the reader's own material there is to
cite, because a switch that says "include my own material" and then quietly
includes nothing is a lie told by omission.

### Where it is deliberately *not* used

**Sermon research** and **the two guides** keep their own corpora, and do not
draw on the reader's own material.

Sermon research is a contract about *published* sources the preacher can
check, and the reader's own notes are not that: quoting a preacher's private
note back to them as an outline point would be a strange thing to do. A
guide's corpus is the guide's own installed material, on the principle that
the reader has already decided what "grace" means to them by deciding what is
installed — and that principle is worth more than one more source.

The chat is where "what did I write" is a question that gets asked out loud,
and that is where the reader's own material belongs.

---

## Actions: explain, summarise, translate

The assistant is not only a chat box. Three actions run over a **selection** or a
**passage**, from the selection card (Explain) and its *More…* menu (all three),
and from the AI section of the Passage:

| Action | Where it appears | Grounded in the library? |
| --- | --- | --- |
| **Explain** | selection card, More…, Passage | yes — retrieves library sources, and the reader's own material, to interpret the text |
| **Summarise** | More…, Passage | **no** — the text is the only source |
| **Translate** | More…, Passage (asks the target language) | **no** — a translation blended with other verses is a different translation |

All three are the *same* call the chat uses — same provider, same adapter, same
`/api/ai/stream` SSE endpoint — differing only in the instruction prepended to
the reader's text (`gbible/ai.py: action_messages`). The result streams into the
assistant panel, so it cites like an answer does, and model output is rendered by
one set of functions (`Ai.render`, `Ai.sourceList`) wherever it appears.

Two rules are enforced in code, not by convention:

* **A grounded action is opt-in per action, and off by default.** Only `explain`
  is grounded, and only when the reader has not turned the library off. The
  builder (`action_messages`) drops any source list handed to `summarize` or
  `translate`, so a caller cannot ground a translation by mistake.
* **An action is not a conversation turn.** The streaming request sends an empty
  history for an action, so "translate this" is never bent by a question asked two
  turns earlier — even though the panel still shows those turns.

---

## Smart search: a question in, a query out

The Search view has an **Ask AI** button. Type a plain-English question
("what does the Bible say about grace"), and the model turns it into *one query
for the reader's own engine* — `faith AND grace` — which then runs and can be
edited and re-run.

This is deliberately **not** a second chat panel. The engine recalls better than
a model does, and a query the reader can see and correct is worth more than an
answer they must trust. The model is used for the one part it is good at
(knowing that "the way, the truth and the life" is about John 14); the engine
does the finding.

The reply is cleaned before use (`_clean_query`): a code fence, a `Query:` label
or a stray backtick is stripped rather than searched for literally. An unpaired
double quote is removed too — a model that wrapped a multi-term query in quotes
was describing it, and honouring the quotes would break the `AND`s it wrote.

---

## Topics

There are two guides, and they ask different questions of the same material:

| | Question | Sections |
| --- | --- | --- |
| **Topic guide** | *What is installed on this topic?* | the full article, the related verses, the glosses, the concordance, the maps, the places, the Strong's entry |
| **Topics** | *What kind of thing is this, and what does each reference work say about it?* | the name, the place, the article — **and now the same verses, glosses, concordance, maps and Strong's entry** |

They were gathering some of the same things separately, which is how a reader
ends up learning two shapes for one question. So the gathering is done **once**
now (`gbible/study.py`: `_fact_rows` and `_extra_sections`) and each guide
arranges what it gets. **Topics is the complete reference**; the topic
guide is the flatter, quicker view of the same material.

**Topics** is also the one with the **lens** — *All entries*,
*Theological*, *Counseling* — which re-ranks the article section by relevance
to that question. The topic guide has no lens, because it is not a lens-shaped
thing.

## The assistant at the head of a guide

Opening either guide puts the assistant **first**, above the articles — the
way some platforms put their AI at the head of a guide. It is one implementation
behind both doors: the same questions, the same answer, the same citations, the
same way into the chat panel. Only the corpus and the lens differ.

It is added **only when the assistant can actually answer**: a provider is
chosen, it has a key if it needs one, and there is a model. With nothing
configured the guide looks exactly as it always has, because an empty box at
the top of a study tool is worse than no box at all.

It is also **folded by default**. The answer is generated either way — the
reader asked for a topic guide, and the guide is what they get — but it is not
shouted at them; the header says how many sources are behind it, and one click
opens it. So the assistant is always used, and never in the way.

The **questions are not folded**, though. They sit outside the fold, visible
the moment the guide opens, because they are the thing that makes the section
worth opening — a topic guide that only lists what is in it is a list.

### The corpus is the guide's own material

This is the part that makes it a *topic guide* answer rather than a chat
answer. The model reads **the guide itself**:

| Source | Why it is there |
| --- | --- |
| The topical article (Torrey's, Thompson's Chain, Nave's) | what the subject *is*, in the books the reader installed |
| The related verses | what the topic is about in Scripture |
| The glosses (Easton's, Webster's) | the concise definition, and where the meanings differ |

Lookup-shaped sections — a concordance, an atlas caption, a Strong's number —
are left out, for the same reason chat grounding leaves them out: they are not
prose *about* the subject.

The reader has already decided what "grace" means to them by deciding what is
installed. The model reasons over that; it is not asked what it happens to know
about grace. That is also why the answer cites the guide's own sources, and
why a citation chip opens the article in a pane.

### The overview, and what follows it

The guide opens with an overview — *what it means, what the verses show, and
where the sources disagree or fall short* — generated as soon as the guide
opens and **cached for the session**. A topic asked once is free to ask again,
so moving between a topic and the passage it refers to does not spend the
reader's tokens twice.

Then the reader can ask follow-ups in the same box (*What are the key terms?*,
*Where do the sources disagree?*), and the exchange is kept, so "what about the
second one?" means something. Only this topic's exchange is sent — never the
reader's unrelated chat history.

The section renders through the same functions as the chat panel (`Ai.render`,
`Ai.sourceList`), and the sources appear before the answer does, so the
property that makes an answer checkable holds here too.

Closing the guide while the answer is still arriving aborts the call rather
than leaving it running in the background.

### Questions to ask

The guide offers four questions, and they are **written by the model from the
guide's own material** — the same material the answers are grounded in. That
is the point: a topic guide is assembled from what the reader happens to have
installed, so a question written for one reader's library is often about
something another reader's library does not contain. The model sees what is
there, so it can ask about *that*.

> *How does the guide's account of propitiation relate to the sacrifice in
> Leviticus 16?*
> *Do the Isaiah 53 verses support the article's reading of the suffering
> servant?*
> *Where do the two glosses differ on the meaning of "cover"?*
> *What does the chain of topics add that the article leaves out?*

The prompt asks for questions *about what is here* — a claim a source makes, a
term it uses, a tension between them — and not about the subject in general,
because "What does the Bible say about X?" is too broad to answer and the
answer would be worth less than the guide the reader already has in front of
them.

### The questions answer the lens

This is where **Topics** earns its lens, and it works exactly like this:
*"The questions suggested take account of the lens you are using to study the
topic."*

Two things carry the lens into the question:

1. **The corpus is lensed.** The Topics article section is already
   re-ranked for the lens, so the entries the model reads first are the ones
   the lens says matter.
2. **The instruction says so.** *"The reader is studying this through the
   Theological lens: what the term means for doctrine. Ask about that."*

So the theological lens asks about doctrine and the counseling lens about
people, and the **overview** answers the same question: the same term gives a
different overview through each lens.

### The questions carry an answer

The topic guide shows the questions **and a suggested answer** beside each one,
so a reader can see the shape of the answer before deciding to open it. Here
the model writes a **one-line answer** under each question, and clicking the
question gives the full answer with its citations.

The format is a numbered question with the answer on the line under it. It
matters that a half-broken reply still gives the reader something to click,
so **a question with no answer under it is kept**: the question is the point,
and the answer is a convenience.

**The questions are a call of their own**, and a small one: four short lines.
A reader should not have to wait for an overview to finish before they can
see what they might ask about. The generic questions are shown first, so the
row is never a blank space while the model thinks, and they are what is left
if the model cannot be reached at all.

**The parser is what makes this safe.** A model asked for questions will
sometimes answer instead, in statements; those are dropped, because a guide
that offers the generic questions is better than one that offers a paragraph
of prose as a question. Code fences, quotes, `**1.**` and "Here are the
questions:" are all stripped rather than trusted.

Clicking a question answers it in place, in the guide, with the same
grounding and the same citation chips as everything else.

**The questions go quiet while a call is running.** A reader who clicks one
while the overview is still arriving would otherwise get nothing at all, and
no sign that anything had gone wrong, so the row dims and stops taking clicks
until the answer has landed.

### Ask a follow-up question

The last button in the row is **Ask a follow-up question…**, and it is the way
out of the guide and into the conversation: it opens the assistant panel with
the guide's exchange **already in it**, sources and all, so the reader carries
on from the question they were pursuing rather than starting again.

This is what makes the topic guide and the chat panel one thing rather than
two. Before this, a reader who read an answer in the guide and wanted to go
deeper had to retype the question, and the answer they had just read was
gone.

The overview is asked with an instruction the *model* was given — *give me an
overview of this topic from the sources* — and not one the reader typed. In
the chat panel that instruction would read as something the reader had just
said, so it is shown as what it is: **Overview of atonement**.

---

## Conversations: kept, and scoped

Two things the assistant panel needed and did not have: somewhere to put a
conversation that has been had, and a way to say *only read this part of my
library*.

### The conversation is kept

The exchange used to live in one array in the browser, which meant two things
a reader notices at once: it was gone when the app was closed, and there was
no way back to a question asked last week. A question is worth keeping for
both reasons — the question asked on Sunday is usually the question being
asked again on Wednesday, and the answer that settled it is not something to
have to re-derive.

So the exchange is written down, and the reader can pick it up again.

* **It is written as it happens.** The answer is on screen whether or not the
  save succeeds; a failure to save is not worth interrupting the reader for.
* **The whole exchange is written each time**, not appended to. A question the
  reader edited and asked again replaces the attempt rather than sitting
  beside it — a conversation that remembers an abandoned attempt is a
  conversation that lies about what was asked.
* **The citations are kept with the answer.** They matter as much as the
  words: a conversation whose answers cannot be traced back to the passages
  they came from is a record of a claim, and the whole design of the
  assistant is that a claim can be checked.
* **The title is the reader's own question**, shortened. A title written by
  the software is a title that means the same thing for every conversation:
  *New chat* is not a title, it is a shrug.
* **Opening the app picks the conversation back up.** The panel shows the last
  exchange rather than starting blank.
* **New chat starts a new one** and leaves the old one in the list, because
  the reader may want it back. **Recent** lists them with *Open*, *Rename*
  and *Delete*.

**It is a local record.** A conversation is a transcript of what the reader
asked and what was said back, and it is **not synced**: a reader who does not
want one of their conversations on another machine should not have one there.
It stays in the database beside the app, and it is the reader's to erase.

### The scope: which part of the library may be read

The assistant can be restricted to a part of the library: everything, a
collection, a kind of resource, or a single book. The same idea here.
The library is a great deal of material, and a reader asking about one
commentary does not want the answer drawn from two hundred atlases.

The picker offers **everything installed**, each **kind of resource** that is
actually present (*Commentary (16)*, *Bible (29)*…), and each **collection**.
Only the kinds that are installed are offered: a scope of "commentaries" on a
library with no commentaries is a dead end in a picker, and a list of dead
ends is a list nobody reads.

**A scope is stored as the reader's intent** — "the commentary collection" —
and not as the list of resources it resolves to. A resolved list goes stale
the moment the reader adds a book to a collection, and a scope that quietly
stops including the book it was named for is worse than no scope at all.

**A scope that names nothing reads nothing.** A collection with nothing in it
is not the whole library, and answering from the whole library would answer a
question the reader deliberately narrowed — which is the one thing the scope
exists to prevent.

The scope applies to the chat and to the **Explain** action, which grounds in
the library. It does not apply to the **topic guide**, whose corpus is the
guide's own material by design, nor to the reader's own material, which is
already on a switch of its own.

---

## Sermon research: notes, not a manuscript

The Sermon Editor has a **Research** card with three buttons. Each sends the
passage the preacher named, plus what the library says about it, and returns
**short sourced notes** — never prose:

| Kind | What comes back | Where it goes |
| --- | --- | --- |
| **Outline ideas** | three to six short headings, each with the source(s) it rests on | *Add to points* |
| **Illustrations** | stories, worked examples, quotations or background a source actually contains, each naming what it illustrates | *Add to illustrations* |
| **Exposition notes** | observations to notice before preaching: structure, repeated words, key terms, setting, cross-references worth following | *Add to points* |

The corpus is the passage *as a location*, not a search of a reference string
(`sermon_sources`): its text, the commentary on it, its cross-references, the
people and places it names, and — the raw material an outline is actually made
of — the installed sermon works' own points, which the Sermons tool already
extracts. Search only comes in when the preacher names a **subject**, because
that is a question rather than a location.

**It refuses to ghost-write.** That is a rule in the system prompt of all three
kinds (`_SERMON_RULE`), not a hope: no introduction, no conclusion, no preaching
paragraphs, no prayers, no illustration retold in the model's own words. The
reason is practical as well as ethical — the work of preaching is the preacher's,
and a paragraph the model wrote is one they would have to check word by word,
which is slower than writing it.

Two things follow from that in the UI:

* The result renders through the same `Ai.render` and `Ai.sourceList` the chat
  panel uses, so model output still has **one renderer**; the research box is a
  second *home*, not a second interpretation.
* **Add to points / Add to illustrations** only takes *list-shaped* lines — a
  heading or a bullet, never a paragraph — so a model that ignored the "short
  headings" instruction cannot smuggle a sermon in through the button. The
  research and its citations stay on screen after the click: the citation numbers
  are the point of having run it.

The research box is separate from the Passage's AI buttons and from the
chat panel on purpose: points belong next to the fields they are added to, and
the reader reviews what arrives before it becomes theirs.

---

## Usage: what the calls have been

**Settings → AI** ends with a **Usage — last 30 days** card. It is there because
the alternative is finding out from the provider's billing page, where the reader
has to work out which of the calls on it were theirs.

* Every call is written down as it happens (`record_usage`): provider, model,
  what it was for (`chat`, `action:explain`, `sermon:outline`, `smart-search`…),
  the token counts, and whether it completed.
* The counts are the ones the **provider itself reported**, read out of the
  stream as it arrives — `include_usage` on OpenAI-shaped servers, the
  `message_start`/`message_delta` events on Anthropic, the final `done` line on
  Ollama. Nothing is estimated. A provider that reports nothing logs none, and
  the call is still counted, because "three calls, tokens unknown" is truer than
  no record at all.
* A call that **failed** after being sent, or that the reader stopped part way,
  is recorded as incomplete — that is exactly the row wanted when a bill does not
  match an impression of what was used.
* Costs are estimated from an approximate, clearly-labelled list-price table
  (`_PRICES`, USD per million tokens), matched by **longest prefix** so a
  `gpt-4o-mini` call is not billed as `gpt-4o`. An unpriced *cloud* model makes
  the total a floor, shown as `≥ $x`; an unpriced **local** model is simply free,
  and does not.
* **Local calls are recorded too**, at zero cost. "Free and stays free" is the
  claim that makes the local option worth choosing, and it should be visible
  rather than asserted.
* **Forget** clears the record. It stays on the machine and is never sent
  anywhere, but the numbers are the reader's to erase.

One implementation note: the token counts for a streamed OpenAI call come from
`stream_options.include_usage`, which is an OpenAI extension. A local server that
speaks the shape but not the option answers **400**, so `stream` drops the flag
and retries once, remembering the provider (`_NO_USAGE`). Metering is worth one
retry; it is not worth a broken answer.

---

## Free tiers: an AI that costs nothing

Three providers have a standing free allowance and need no card. They are wired
as ordinary rows in `PROVIDERS` — all three speak the OpenAI schema, so the
transport is unchanged — and they carry a `free` flag that the settings screen
shows as a **Free tier** badge.

| Provider | Base URL | Free allowance | Needs a key to list models? |
| --- | --- | --- | --- |
| **Groq** | `https://api.groq.com/openai/v1` | ~30 req/min, ~1,000/day, per organisation | yes |
| **Google AI Studio** | `https://generativelanguage.googleapis.com/v1beta/openai` | per project; ~1,500 requests a day on the Flash models | yes |
| **OpenRouter** | `https://openrouter.ai/api/v1` | ~20 req/min, ~50/day (1,000/day after a one-off $10) | **no** |

**"Free" is not "private", and the UI never lets the two be confused.** A free
tier is a cloud provider like any other: the passages for your question and the
question itself are sent to somebody else's machine. The badge is a different
colour from the green "Private" one for exactly that reason, and the note under
the input box says *"Free tier: no charge for the calls, but this is still the
cloud."* Google's free tier may also use what you send to improve their
products, which the provider's note says.

Each provider's conditions are stated in the app rather than left for the reader
to go and find, because "free" without its limits is a promise the software
cannot keep.

### The one that needs code: OpenRouter's free-model filter

OpenRouter aggregates other people's models behind one key and answers `/models`
with **several hundred** of them, at every price from free upwards. A reader who
pressed **Test** expecting a free tier and got 470 models — most of them
chargeable — would be badly served, so its listing is filtered.

The filter (`_free_to_use`) answers three questions, and all three must be yes:

* **Is it free?** The `pricing` object must be zero. The `:free` suffix on the
  id is used only as a fallback for entries that carry no pricing at all,
  because a model that claims free and carries a price is the one case that
  must never get through.
* **Does it answer in text?** OpenRouter also lists audio and image models at
  zero, and a chat request to one of those fails. The output modality must be
  text alone.
* **Does it need the suffix to qualify?** No — `openrouter/free`, the router
  that picks a free model for you, has no `:free` suffix and is the single most
  useful entry on the list, so it is included on the strength of its own zero
  price.

The number of models the filter removed is **reported**, not dropped silently: a
list that quietly lost 452 entries would look like the provider only had 18.
It reads *"18 models offered. (452 others hidden — this provider is filtered to
the free ones)."*

OpenRouter publishes its model list without a key, so **Test** works before the
reader signs up — the list is the advertisement. It is also the one provider
here with no preset model list, because its free roster rotates: a preset would
be a promise the software cannot keep.

### What a free call costs

The usage card prices a free model as **$0.00, known** rather than as an unknown,
because "this call cost nothing" and "this call's cost is not known" are
different statements and only the second is a gap. Two rules decide it:

* A `:free` model (or `openrouter/free`) is free — that is the provider's own
  promise, not an inference.
* A model in a free-*tier* provider's free list is treated as free. The app
  cannot see whether the reader has enabled billing on that account, so the
  usage card says so: *"Free tier assumed for Groq: a free-tier provider
  charges for the same model on a paid account, so check the bill if you have
  enabled one."*

---

## Adding a provider

One entry in `PROVIDERS` (`gbible/ai.py`):

```python
Provider("groq", "Groq", "openai",            # openai-compatible
         "https://api.groq.com/openai/v1", False, True, "Groq API key",
         models=["llama-3.3-70b-versatile"])
```

`adapter` names the wire format, `local` is the only distinction the reader
makes ("does my text leave this machine"), and `base_url` is where the call
goes. `models` is a *fallback* list; if the provider can be listed it will be,
and an empty list means "ask with Test". Nothing else changes: the settings
screen, the key field, the Test button, the chat panel and all three actions are
driven from this list — and a selftest fails if a row's adapter has no transport,
so a provider cannot be added that only fails when a question is asked.

The optional arguments are for the cases that are not the common one:

| Argument | For |
| --- | --- |
| `free=True` | a provider with a standing free allowance — shows the badge and states its conditions in `free_note` |
| `free_filter=fn` | a provider that lists other people's models and must be narrowed to the free ones; the predicate takes one model object |
| `list_without_key=True` | a provider that publishes its model list without a key, so **Test** works before the reader signs up |

---

## Files

| Piece | Where |
| --- | --- |
| Providers, grounding, transport, discovery, actions, smart search, the two guides and their questions, scope, embeddings and the semantic re-order, sermon research, usage, settings | `gbible/ai.py` |
| The reader's own material: notes, highlights, clips, and their retrieval | `gbible/mine.py` |
| The conversations the reader has had, and the Markdown export | `gbible/aichat.py` |
| Which words of a source carried a claim | `gbible/ai.py` (`fragments`, `_fragment`, `_sentences`) |
| JSON endpoints + SSE stream | `gbible/server/app.py` (`ai/*`, `/api/ai/stream`) |
| Chat panel, actions, scope picker, recent conversations, the passage you are reading, settings screen, usage card | `gbible/web/ai.js`, `#v-ai`, `#v-aisettings` |
| Selection-card actions | `gbible/web/tools.js` (`SelCard`) |
| Passage AI section | `gbible/web/app.js` (`Study.openPassage`) |
| Smart Search button | `gbible/web/workspace.js` (`Search.smart`), `#s-smart` |
| Topics AI section, its questions, and the follow-up bridge | `gbible/web/app.js` (`Study.openTopic`, `Study.openFact`, `Study.guideAi`), `#st-sec-ai` |
| What the two guides share: the topic entries and the verses, glosses, concordance, maps and Strong's | `gbible/study.py` (`_fact_rows`, `_extra_sections`) |
| Sermon research buttons | `gbible/web/tools.js` (`SermonBuilder`), `#sb-research` |
| Keys | `api-credentials.json`, ids `ai-<provider>` (`gbible/api/registry.py`) |
| Choice of provider/model | `setting` table, key `ai` |
| Usage record | `ai_usage` table (`gbible/db.py` schema), one row per call |
| Conversations | `ai_chat` and `ai_chat_turn` tables (`gbible/db.py` schema) |
| Discovered models | not stored — re-asked per session, so a list can never go stale |

---

## Later phase

* **Phase 5** — Flatpak packaging. The assistant needs `--share=network`;
  settings and the database move under `~/.var/app/<appid>/data`, and local
  models are never bundled — Ollama runs outside the sandbox.

## Which words of a source carried the claim

Some platforms highlight the *exact words* a claim was drawn from: hovering a
footnote shows the passage with the fragment the answer leaned on marked. Here
a citation chip does the same.

**It is computed, not asked.** The model cites a source, not a place inside
it, so the words that carried the claim are somewhere in the passage and
nowhere marked. They are found by comparing the two texts: the sentence of
the answer around the `[n]` marker, and the sentences of the source, and the
source sentence that shares the most content words with the answer sentence
is the fragment.

The obvious alternative — asking the model to quote the words it relied on
inside the citation — was deliberately **not** taken. It would change the
citation grammar the model has to follow, make the answer noisier to read, and
put the app in the position of trusting a model's quotation. The whole
citation design is there so that a claim can be checked against the passage
rather than taken on trust; asking the model to reproduce the passage weakens
exactly that. So the two texts are compared instead, and the reader is shown
the result.

**It is an approximation.** The model may be paraphrasing rather than
quoting, and then the closest sentence is the closest, not the exact one. A
claim that shares no words with its source has no fragment, and the chip
falls back to showing the whole passage. Some platforms' fragment is exact
because their retrieval chose a precise location; this one is a comparison of two
texts, and it says so.

## Asking again

Every question in the conversation has a **pencil** beside it. Opening it
turns the question into an editor, and asking again **replaces** the exchange
from that question onward — it does not add to it. The reader is left with
one exchange and not two versions of it.

The scope in the header applies to the new question, so narrowing what the
assistant reads and asking again are one action rather than two.

## A conversation is a file

**Export** writes the conversation to a Markdown file, with each answer's
sources as text beneath it, so the document can be checked on a machine that
does not have the books.

It is a file and **not a link**, and that is the whole argument. A link would
put the conversation in a URL, where it is copied into browser history and the
URL bar and wherever a link is pasted — and a conversation is the reader's own
writing, their questions and often what they are wrestling with. A file the
reader attaches to a message themselves is a share they chose. Every other
decision about a conversation has been "this stays on this machine": it is not
synced, the usage record is not synced, and the keys live in a `0600` file
beside the database.
