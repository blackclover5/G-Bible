/* Web research, reduced to the one thing the reader sees: a yes/no question.
 *
 * The sites are built into G-Bible; the reader does not pick them or their
 * pages.  Consent lives only in the server process, so it is forgotten when
 * the app shuts down.  Everything after "Yes" -- choosing the relevant sites,
 * searching them, reading the best page -- happens here without further prompts.
 */
const WebResearch = {
  async shouldSearch(question) {
    if (aiOff()) return false;
    try {
      const r = await post('ai/web-check', { question: question || '' });
      return !!(r && r.ok && r.need);
    } catch (e) { return false; }
  },

  /* Ask for each question. A yes authorizes only the plan gathered immediately
   * afterward; the next question returns to the installed library by default. */
  async ask() {
    return new Promise((resolve) => {
      modal('Use the internet?',
        '<div style="line-height:1.6">This question may be answered better '
        + 'with information from the web. G-Bible will search a small list of '
        + 'trusted Bible study websites, read the most relevant pages, '
        + 'and follow up with a narrower search if the first pass finds little. '
        + 'It combines what it finds with the books you have installed.</div>'
        + '<div class="tiny muted" style="margin-top:10px">'
        + 'Your question is sent to a search engine and those websites. '
        + 'A yes applies to this question only. Choose no and the answer uses '
        + 'only your installed books and notes.</div>',
        [
          { label: 'No — use my library', fn: () => resolve(false) },
          { label: 'Yes — use the internet', cls: 'btn primary', fn: () => {
            post('webresearch/consent', { allow: true }).then(() => resolve(true));
          } },
        ]);
    });
  },

  /* Everything after consent: pick sites, find the best pages, read them.
   * A short notice covers the wait: the research happens before the answer
   * appears, so without it the assistant looks frozen on a slower connection.
   */
  async gather(question) {
    toast('Searching the approved study sites…');
    const p = await post('webresearch/plan', { query: question || '' });
    if (!p.ok) { toast(p.error || 'Could not prepare web research.', 'warn'); return null; }
    const r = await post('webresearch/run', { token: p.token });
    if (!r.ok) { toast(r.error || 'No web page could be read.', 'warn'); return null; }
    return { token: r.token, results: r.results || [], sites: p.sites || [] };
  },
};
