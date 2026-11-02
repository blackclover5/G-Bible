# Attributions

**Almost no study material is included in this repository.** Everything below is
downloaded at run time by the user, from the repositories listed in the Store.
Each item keeps its own licence, which is recorded against it in the Library
and reproduced verbatim in Library → *Attribution*.

The one exception is a single 52 KB file of **section headings** — no prose —
which is committed, because an outline browser with nothing in it is not a
feature. It is listed under
[Bundled data](#bundled-data-the-one-exception) below.

This file lists the material the reference library was developed and tested
against, and the repositories the Store draws from.

---

## Material used to develop and test the application

| Work | Repository | Author / source | Licence | Attribution required |
|---|---|---|---|---|
| World English Bible Classic | eBible.org | Public Domain (eBible.org) | **Public Domain** | No — but "World English Bible" is eBible.org's trademark; do not call a modified text the WEB |
| American Standard Version 1901 | eBible.org | Public Domain | **Public Domain** | No |
| Barnes' New Testament Notes | CrossWire SWORD | Albert Barnes, 1832 | **Public Domain** | No |
| Condensed Biblical Cyclopedia | CrossWire SWORD | John McClintock & James Strong | **Public Domain** | No |
| Jonathan Bagster, *Daily Light on the Daily Path* | CrossWire SWORD | 1813–1872 | **Public Domain** | No |
| Strong's Exhaustive Concordance | Wikisource | James Strong, 1890 | **Public Domain** | No |
| *A Book of Jewish Thoughts* | Project Gutenberg #57218 | Public Domain | **Public Domain** | No |
| *A critical and exegetical commentary on the Gospel of St. John* | Project Gutenberg #77363 | H. H. H. (ed.), 1872 | **Public Domain** | No |
| Berean Standard Bible | eBible.org | BSB Publishing, LLC | **Public Domain** | No |
| Textus Receptus (Stephanus 1550) | midvash/bible-data | — | **Public Domain** | No |
| SBL Greek New Testament | Open Scriptures | Holmes, 2010, ed. | **CC BY 4.0** | **Yes** — "SBL Greek New Testament, ed. Michael W. Holmes, 2010. CC BY 4.0" |
| Exodus route map (Ortelius, 1624) and others | Wikimedia Commons | Abraham Ortelius and other public-domain cartographers | **Public Domain** | No |
| Bible place coordinates (334 places) | OpenBible.info / BiblePlaces.com | BiblePlaces.com contributors | **CC BY 4.0** | **Yes** — "Bible place data from BiblePlaces.com via OpenBible.info, CC BY 4.0" |
| OpenStreetMap tiles shown in the map pane | openstreetmap.org | © OpenStreetMap contributors | **ODbL** | **Yes** — "© OpenStreetMap contributors". Tiles are fetched at display time; none are bundled. |

Map tiles are the one component that is *not* installed locally: the map pane
embeds OpenStreetMap, which requires visible attribution, and the app shows it
under the map. Place coordinates — the data the app actually indexes — are
installed and attributed locally.

---

## Bundled data (the one exception)

| What | Where it came from | Author | Licence | Attribution |
|---|---|---|---|---|
| `gbible/data/outlines.json.gz` — the section headings of all 66 books, 1,192 chapters, 2,025 headings; no commentary prose, no word glosses, no verse notes (52 KB gzipped) | Christian Classics Ethereal Library, which distributes Jamieson–Fausset–Brown as an EPUB | Robert Jamieson, A. R. Fausset and David Brown, *Commentary Critical and Explanatory on the Whole Bible*, 1871 | **Public Domain** — out of copyright in every jurisdiction (published 1871; CrossWire records the same work as `DistributionLicense=Public Domain`) | Not required. The app prints the basis rather than just the source: *"Jamieson, Fausset and Brown, Critical and Explanatory Commentary on the Whole Bible (1871). Public domain: out of copyright in every jurisdiction. Only the authors' own section headings are used here — no commentary prose from any edition."* |

Regenerate or re-audit it with:

```
python3 tools/build_outlines.py --check    # what is bundled, and any gap
python3 tools/build_outlines.py           # download CCEL's EPUB and rebuild
python3 tools/license_audit.py            # and check the committed file too
```

**On the licence.** CCEL's electronic edition of this work carries a
"Copyright 2010 Christian Classics Ethereal Library (CCEL)" notice in its front
matter (`jfb.about.html`). That covers CCEL's own editorial additions and
packaging, not the 1871 text, and the build drops the front matter entirely —
the committed file contains nothing but the 1871 chapter headings. The
attribution above names the source, because where a file came from is worth
knowing, but leads with the basis, because what makes it usable is the date and
not the provenance.

**And it is checked, not just asserted.** `tools/license_audit.py` audits the
installed modules against the licence and date gates, and it audits this file
too — which it did not used to do, leaving the only third-party-derived material
in the repository outside the tool written to enforce exactly that. It now
verifies that the file records its provenance, that its licence claim survives
the same date gate as a catalogue entry, that every entry carries only the
fields a heading may have (`title`, `ref`, `sub`), that the headings stay
heading-scale, and that nothing in the content references the source library or
anyone else's words. That last scan runs over the content only, never over the
metadata: the attribution is *supposed* to name CCEL and to record that CCEL
claims copyright over some of its contents, and a check that flagged its own
provenance note would be one that had to be turned off.

The audit fails if prose is added to an entry, if front matter appears in a
heading, if the headings grow past four times their real size, if the licence or
year claim is removed, or if the year is changed to something still in
copyright.

Nothing else derived from a copyrighted work is committed. The Store
catalogues in `gbible/store/data/*.json` are metadata only — title, author,
licence, URL — never any of the works themselves.

## Store repositories

| Repository | What it offers | Licence policy applied |
|---|---|---|
| **eBible.org** | 111 public-domain USFM and SWORD modules in 41 languages | Only modules whose own licence reads "public domain" are listed. The ~1,180 Wycliffe / TW / restricted modules are excluded. |
| **CrossWire Bible Society** | 232 public-domain SWORD modules: 145 bibles, 28 commentaries, 24 books, 10 devotionals, 8 factbooks, 8 lexicons, 7 dictionaries | Only `DistributionLicense = Public Domain`, plus the two whose About text grants unrestricted use. CC-BY-SA (`Robinson`, `MLStrong`), CC-BY-ND and "Copyrighted" (`NETnotesfree`) are excluded. |
| **Wikisource** | 8 public-domain works: Matthew Henry, Clarke, Strong's Concordance, Easton, BDB, Jewish Encyclopedia, Catholic Encyclopedia, Gesenius | All works are out of copyright. Pages marked `{{incomplete}}` are flagged in the catalogue. |
| **Open Scriptures** | Open Scriptures Hebrew Bible (morphology) and SBLGNT | CC BY 4.0; attribution is recorded automatically. |
| **Project Gutenberg** | 130 hand-checked public-domain books and devotionals | Public domain in the United States. |
| **Wikimedia Commons** | 19 maps and illustrations | Public Domain (12), CC0 (5), CC BY 2.5 (1), CC BY 4.0 (1). CC BY-SA images are excluded. |
| **OpenBible Geography** | 334 geocoded Bible places, plus KML overlays | CC BY 4.0. |
| **Midvash open data** | 32 public-domain Bible texts in 22 languages, as whole-Bible JSON, per-book JSON, or indexed SQLite | Public domain per version, declared in each `metadata.json`. Provenance in the upstream `SOURCES.md`. |
| Hebrew Leningrad Codex 26.0 | Open Bibles (`heb-leningrad.usfx.xml`) | tanach.us | **Free to view and copy without restriction** | **Yes, requested** — "Westminster Leningrad Codex, version 26.0" (the licensor asks for a citation; it is not a restriction) |
| Reina-Valera 1909, and 33 other translations | Open Bibles | various | **Public Domain** per the repository's own table | No |
| La Biblia en Español Sencillo | Open Bibles | AudioBiblia.org / Irma Flores, 2018 | **CC BY 4.0** | **Yes** — name AudioBiblia.org / Irma Flores |
| Palabra de Dios para ti; Versión Biblia Libre | Open Bibles | ABL; J. Gallagher & S. Barrios de Ávila | **CC BY-SA 4.0** | **Yes** — name the source, and share adaptations under the same licence |
| **Open Bibles** (`seven1m/open-bibles`) | 39 USFX and OSIS texts | Public Domain and CC BY 4.0 from the repository's own table, plus the two CC BY-SA 4.0 texts, which the gate permits with attribution. The 9 Zefania-XML files are **not** offered — that format is not read yet. |
| **CCEL Fathers** (`ccel.org/fathers`) | 288 works of the Fathers: Schaff's *Ante-Nicene Fathers* and *Nicene and Post-Nicene Fathers*, offered one work at a time — Irenaeus, Justin Martyr, Athanasius, Augustine, Chrysostom, Jerome, the conciliar canons | Public domain, read from the file: every volume's ThML head states `<DC.Rights>Public Domain</DC.Rights>` and `firstPublished` 1867–1887, and `taxonomy.redistributable` is run on those values rather than on anything asserted here. **No** attribution required by the licence, but the installed module records where the text came from: *"Text from the Christian Classics Ethereal Library (CCEL), ccel.org, hosted on the campus of Calvin University."* |
| **Latin Fathers** (`thelatinlibrary.com/christian.html`) | 200 patristic works in Latin: Ambrose, Augustine, Jerome, Tertullian, Isidore, Leo the Great, Prudentius, Cassiodorus and others, offered one work (or one book) at a time | Public domain. Text scraped from The Latin Library, which hosts out-of-copyright Latin texts. Original-language, not translated. Attribution recorded in the installed module. |
| **Greek Fathers** (deferred) | *Not yet available.* Target: Chrysostom, Basil, Gregory Nazianzen, Gregory of Nyssa, Athanasius, Cyril of Alexandria, Origen, Clement of Alexandria, via Perseus (CTS URNs). Blocked on Perseus stability and URN research. | Public domain (ancient texts). Requires a TEI-XML reader and a curated URN list. Tracked as a follow-up. |
| **Philo of Alexandria** (deferred) | *Not available as a store module.* Yonge's 1854–1890 translation is public domain, but no clean, complete, downloadable module exists in a format this app reads (SWORD/USFM/EPUB/plain text). Scanned volumes are on the Internet Archive (`worksofphilojuda01yonguoft` and siblings, OCR-derived EPUB/PDF) and the text is readable online at earlychristianwritings.com. A user who obtains the text can bring it in through **Modules → This computer → Import a file…** (EPUB or plain text). | Public domain. Blocked on a clean source, not on code. |
| **Edersheim, *The Life and Times of Jesus the Messiah*** (deferred) | *Not available as a store module.* Public domain (1883), but only as scanned volumes on the Internet Archive (`lifetimesofjesus01eder` and siblings, OCR-derived). No clean EPUB/SWORD module. Importable manually via **Modules → This computer → Import a file…** once obtained. | Public domain. Blocked on a clean source, not on code. |
| **Coptic / Syriac Fathers** (deferred) | *Not available as open data.* Only the Horner Coptic NT and the Peshitta exist (already in the store as Bibles); patristic works in those languages have no free digital source. | Blocked on resources, not code. |
| **This computer** | Files you already have | Whatever the file declares; shown in the module's licence field. |

---

## Sources deliberately excluded

| Source | Reason |
|---|---|
| CCEL's **own material** (ccel.org) | "may be used for personal, educational, or non-profit purposes. **Contact us for permission to republish.**" That covers the site design (Harry Plantinga, © 1993-2020), the ThML software, and the blurbs CCEL's staff write today — none of which is installed or bundled. The **texts** are a different question and are handled separately: the Fathers' own writings in Schaff's 1867–1887 editions are public domain, each volume says so in its own `<DC.Rights>`, and they are offered by the **CCEL Fathers** repository. Nothing CCEL wrote is installed with them. |
| eBible.org Wycliffe / TW / UnsortedBible.in modules | Copyrighted; non-commercial or restricted sharing. |
| Door43 / unbound (git.door43.org) | Repository content is CC BY-SA 4.0; share-alike complicates bundling into a MIT-licensed project. |
| BibleHub lexica | Per-work licence, frequently unrestricted. |
| Lexham | Proprietary. |
| `Robinson.zip`, `MLStrong.zip` (CrossWire) | CC BY-SA 4.0. |
| `NETnotesfree.zip` (CrossWire) | Copyrighted. |
| **Thayer's Greek Lexicon** (CrossWire `Thayer`) | Removed by CrossWire over copyright concerns ("Due copyright problems the Thayer is no longer available"). Not legally redistributable by this app. |
| **Liddell–Scott (Middle Liddell)** (CrossWire `MLStrong`) | CC BY-SA 4.0 — excluded by the share-alike gate. The Strong's-keyed abridgement is the only form CrossWire ever offered. |
| `bible_databases` (scrollmapper) | Bundles NIV, ESV and NASB, which are not redistributable. Listed in **API Settings** with that warning; never used as a source. |
| `jburson/bible-data` | Also called "BibleData", and it carries the usual markup DSL — but it bundles ESV, NIV, NASB, NKJV and CSB. Listed in **API Settings** so the name resolves; not offered as a source. The other project called BibleData, `midvash/bible-data`, *is* public domain and **is** an install source. |
| Westminster Leningrad Codex | Present in `midvash/bible-data`, but declared `wlc-license` rather than public domain, so that one version is left out of the Store. |
| OpenBible.info Topical Bible and cross-references | openbible.info's own work is CC BY 4.0, but these two features are built on the English Standard Version, which is still in copyright. May be read, never bundled. The geocoding data — the part the Store installs — is unaffected. |
| `thiagobodruk/bible` | Same problem: bundles NIV, ESV, NASB. |
| Some commercial platforms | Proprietary. Their *public documentation* was used as the design reference for the pane, link-set and search models — documentation, not code or content. |
| STEP Bible data (desktop app) | Free for non-commercial use; redistribution restricted. Read locally if you have it, never bundled. |
| STEPBible-Data (GitHub) | CC BY 4.0 — freely redistributable, with attribution to "STEP Bible" (www.STEPBible.org). Listed in **API Settings** as `stepbible-data` and installed via the **STEPBible-Data** Store repository. Distinct from the desktop app above. |
| MACULA (Clear Bible) | CC BY 4.0 by Biblica/Clear Bible (syntax trees, morphology, word senses, semantic frames). The Louw-Nida (@ln/@domain) fields are included "used with permission" from MARBLE — treat that subset as permission-dependent. Listed in **API Settings**. |
| Gnosis, Bolly, API.Bible, Bible Gateway, BibleCloud, getbible, scrip.app, Midvash | Listed in **API Settings** as read-only lookups. The app does not redistribute what they return, and the Store does not offer them as sources. |

---

## Design references (documentation, not code)

The workspace, link-set and search models follow the *published behaviour* of
some commercial platforms, from their own support documentation and Sean
Boisen's "BibleTech 2011 — Using the Bible Knowledgebase for Information
Integration". Those platforms are proprietary; none of their code or content is
used here. The practical consequences of that research are recorded in
`README.md` — chiefly that link sets work only between resources with
overlapping milestone types, and
that a pane stores a milestone cursor rather than a scroll offset.

Module format behaviour was established by reading the modules themselves:
`OPEN_BIBLE_MODULE_FORMATS_SPEC.md` records the SWORD `.bzs` / `.bzv` / `.bzz`
byte layouts, the USFM and OSIS constructs, the e-Sword `.mod` and `.bblx`
schemas, and which of the above are verified versus assumed.

---

## Read-aloud voice

The one thing outside the standard library, and it is installed rather than
bundled: nothing here is redistributed by this repository.

| Work | Where from | Author / source | Licence | Attribution required |
|---|---|---|---|---|
| Kitten TTS Nano v0.8 — model weights | `KittenML/kitten-tts-nano-0.8-fp32` on the Hugging Face hub | Kitten ML | **Apache-2.0** | No — retain the notice if you redistribute the weights |
| Kitten TTS — inference code | `pip install kittentts` | Kitten ML | **Apache-2.0** | No |
| ONNX Runtime — inference engine | `pip install onnxruntime` | Microsoft | **MIT** | No |
| StyleTTS 2 — the architecture Kitten TTS is built on | cited by Kitten ML | Yuxuan Wang et al. | **MIT** | No |

Apache-2.0 covers commercial use, so this voice can ship inside something you
give away or sell. See [Read aloud](README.md#read-aloud) for how it is
installed.

---

## English dependency parser

Also installed rather than bundled, and also optional: nothing here is
redistributed by this repository. It is what answers "where is this word the
*object of a verb*", and what supplies parts of speech for an English verse in
the sentence diagram.

| Work | Where from | Author / source | Licence | Attribution required |
|---|---|---|---|---|
| spaCy — parsing library | `pip install spacy` | Explosion AI | **MIT** | No |
| `en_core_web_sm` v3.8.0 — English pipeline | `python3 -m spacy download en_core_web_sm` | Explosion AI | **MIT** | No — confirmed from the installed package's own metadata |
| OntoNotes — the annotated corpus the parser was trained on | cited by the model | Linguistic Data Consortium, via Explosion AI | Not redistributed here | No — only the trained weights are installed |

The model is statistical and trained on news, fiction and non-fiction rather
than on scripture, so it is very reliable on ordinary English and will
occasionally be wrong on a long or archaic sentence. Every result therefore
names the verb that governs the match, so it can be checked rather than trusted,
and the panel says the roles are from a parser.

Without it, the two relations that need a parse are not offered at all rather
than answered from punctuation, and the diagram falls back to what it can know.
See [Clause search](README.md#clause-search-and-the-sentence-diagram).

---

## The MIT licence covers the software only

See [LICENSE](LICENSE). Study material keeps its own licence and is never
redistributed by this project.

The one exception is the 52 KB of public-domain outline headings described
above, which is in the repository because the feature is worth more with it
than without it, and whose source and licence are recorded in the file itself
and shown in the app beside every outline it draws.
