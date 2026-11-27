# Web research in the AI Assistant

The assistant normally answers from the books you have installed. If a question
would be better answered with the internet, it asks:

> **Use the internet?** — *No — use my library* / *Yes — use the internet*

Choose **Yes** and it searches a small, built-in list of Bible study sites,
reads the most relevant pages, and follows up with a narrower search if the
first pass found little. It combines what it finds with your library and writes
one answer. **Websites used** are listed after the answer, with a link to each
page actually read. At most six pages and fourteen requests are used for one
question, and requests are spaced out. Bible Gateway asks for a 15-second crawl
delay in its `robots.txt`, so the app keeps to that pause for that site.

There are no web buttons, no site list to manage, and no URLs to approve. The
sites are chosen for you:

| Site | Best for |
| --- | --- |
| Answers in Genesis | creation, Genesis, the Flood, fossils, apologetics |
| Got Questions | direct answers to Bible and doctrine questions |
| The Gospel Coalition | articles on Jesus, the gospel, the church and Christian living |
| Bible Gateway | Bible dictionary and topical entries: word meanings, Hebrew and Greek terms, concordance subjects |
| Bible Odyssey | scholarly articles on the Hebrew Bible, New Testament, archaeology and history |
| STEP Bible | original-language word studies, meanings and parallel passages |
| Bible Project | readable articles on biblical themes, books, and word studies (not its videos) |

The assistant judges which sites fit the question — a creation question goes to
Answers in Genesis, a question about ancient Near Eastern history to Bible
Odyssey — and reads the best matching page from each. The list is deliberately
short and fixed; a site is added only when it permits this kind of access and
publishes a public sitemap or stable article URLs.

## Permission applies to one question

The dialog appears for each question that could benefit from outside research.
Saying **Yes** authorizes one search plan for that question; later questions
return to the installed library by default and ask again if web research may
help. The permission is held in memory only while that one plan is created and
is never written to the database or a file. Saying **No** answers with your
installed library alone.

## What is enforced

- Discovery uses each site's own public sitemap, cached for a day in memory.
  Article URLs are ranked against the words in the question, so a question
  about Friday or Wednesday finds the Good Friday article instead of a generic
  page. The site's own URL patterns and search pages are fallbacks. A thin
  first pass gets one follow-up with the question's distinctive words, against
  the same approved sites only. A fetched page is included only if its title,
  URL and text match the question topic; count questions also require a count
  in the page. Weak matches are discarded. Only links on the site being read
  are followed; nothing else on the internet is read. Pages showing a bot challenge or
  "human verification" are discarded.
- Distinctive words matter more than common ones: "Friday" outranks "Jesus",
  which appears in hundreds of article titles.
- The model is told to use an outside page only when it directly answers the
  exact question. A nearby topic is not enough, and it must say when the
  supplied sources do not answer the question.
- HTTPS only, exact host matching, no credentials in the URL, no redirects.
- Every address DNS returns must be public, and the connection is pinned to
  that verified address, so a second DNS answer cannot redirect it internally.
- The search engine's own text never reaches the model — only pages from the
  built-in sites do.
- Fetched text is labelled in the prompt as untrusted data, never instructions.
  The assistant is told to weigh it against your library and report disagreement.
- Pages are capped in size and stripped of scripts, styles and forms before
  they reach the model.

Respect each site's terms of use; reading a page does not grant a right to
republish it.
