"""Web research: session consent, built-in sites, and the fetch guards.

No test touches the network.  What is protected here is the part that has to be
right when a page is hostile: consent is session-only, only built-in hosts are
followed, and outside text is one-use.
"""

import os
import shutil
import time
import tempfile
import unittest


def _scratch_home(test_case):
    home = tempfile.mkdtemp(prefix="gbible-web-test-")
    test_case.addCleanup(shutil.rmtree, home, True)
    old = os.environ.get("GBIBLE_HOME")
    os.environ["GBIBLE_HOME"] = home

    def _restore():
        if old is None:
            os.environ.pop("GBIBLE_HOME", None)
        else:
            os.environ["GBIBLE_HOME"] = old

    test_case.addCleanup(_restore)
    return home


class WebResearchTests(unittest.TestCase):
    def setUp(self):
        _scratch_home(self)
        from gbible import webresearch as wr
        self.wr = wr
        wr.set_consent(False)
        wr._INDEX.clear()

    def test_built_in_sites_are_exactly_the_seven_named(self):
        hosts = {s["host"] for s in self.wr.sites_view()}
        self.assertEqual(hosts, {"answersingenesis.org", "www.gotquestions.org",
                                 "www.thegospelcoalition.org",
                                 "www.biblegateway.com",
                                 "www.bibleodyssey.org", "www.stepbible.org",
                                 "bibleproject.com"})

    def test_relevance_ranks_the_right_site_first(self):
        chosen = self.wr._choose_sites("How was the earth created in Genesis?")
        self.assertEqual(chosen[0]["host"], "answersingenesis.org")
        jesus = self.wr._choose_sites("Who is Jesus?")
        self.assertEqual(jesus[0]["host"], "www.gotquestions.org")

    def test_consent_is_session_only_and_defaults_to_no(self):
        self.assertFalse(self.wr.consent_allowed())
        self.assertTrue(self.wr.set_consent(True))
        self.assertTrue(self.wr.consent_allowed())
        # Nothing is persisted: a fresh read of the setting table has no flag.
        from gbible import db
        self.assertIsNone(db.get_setting("webresearch-consent"))

    def test_plan_requires_consent(self):
        self.assertFalse(self.wr.plan("who is Jesus")["ok"])
        self.wr.set_consent(True)
        p = self.wr.plan("who is Jesus")
        self.assertTrue(p["ok"])
        self.assertTrue(p["sites"])

    def test_plan_token_is_one_use(self):
        self.wr.set_consent(True)
        p = self.wr.plan("creation")
        self.assertEqual(self.wr.take_plan(p["token"])["query"], "creation")
        with self.assertRaises(ValueError):
            self.wr.take_plan(p["token"])

    def test_only_exact_https_hosts_pass(self):
        allowed = {"good.example"}
        self.assertEqual(self.wr.safe_url("https://good.example/a", allowed)[0],
                         "https://good.example/a")
        for bad in ("http://good.example/", "https://evil.example/",
                    "https://good.example.evil.test/",
                    "https://user@good.example/", "https://good.example:8443/"):
            self.assertIsNone(self.wr.safe_url(bad, allowed)[0], bad)

    def test_pinned_connection_checks_tls_against_the_host_name(self):
        conn = self.wr._PinnedHTTPS("www.example.org", "93.184.216.34", timeout=1)
        seen = {}

        class Ctx:
            def wrap_socket(self, sock, server_hostname=None):
                seen["host"] = server_hostname
                return "wrapped"

        conn._context = Ctx()
        original = self.wr.socket.create_connection
        self.wr.socket.create_connection = lambda addr, timeout, source: object()
        self.addCleanup(setattr, self.wr.socket, "create_connection", original)
        conn.connect()
        self.assertEqual(seen["host"], "www.example.org")
        self.assertEqual(conn.sock, "wrapped")

    def test_private_host_is_not_public(self):
        self.assertEqual(self.wr._public_ips("localhost"), [])
        self.assertEqual(self.wr._public_ips("127.0.0.1"), [])

    def test_site_search_links_are_filtered_to_that_host(self):
        page = (b'<a href="https://answersingenesis.org/creation/earth">Creation of the Earth</a>'
                b'<a href="https://evil.example/page">Bad</a>')
        links = self.wr._site_links(page, "answersingenesis.org")
        self.assertEqual(links, ["https://answersingenesis.org/creation/earth"])

    def test_sitemap_index_finds_articles_not_index_pages(self):
        site = next(s for s in self.wr.SITES if s["id"] == "gq")
        xml = ("<urlset>"
               "<url><loc>https://www.gotquestions.org/who-is-Jesus.html</loc></url>"
               "<url><loc>https://www.gotquestions.org/Good-Friday.html</loc></url>"
               "<url><loc>https://www.gotquestions.org/search.html</loc></url>"
               "<url><loc>https://www.gotquestions.org/content_Jesus.html</loc></url>"
               "</urlset>").encode()
        original = self.wr._get_raw
        self.wr._get_raw = lambda url, allowed, max_bytes=0: (xml, "")
        self.addCleanup(setattr, self.wr, "_get_raw", original)
        urls = self.wr._load_index(site)
        self.assertIn("https://www.gotquestions.org/who-is-Jesus.html", urls)
        self.assertIn("https://www.gotquestions.org/Good-Friday.html", urls)
        self.assertNotIn("https://www.gotquestions.org/search.html", urls)
        self.assertNotIn("https://www.gotquestions.org/content_Jesus.html", urls)

    def test_index_ranking_finds_crucifixion_pages(self):
        site = next(s for s in self.wr.SITES if s["id"] == "gq")
        urls = [
            "https://www.gotquestions.org/who-is-Jesus.html",
            "https://www.gotquestions.org/what-year-did-Jesus-die.html",
            "https://www.gotquestions.org/Good-Friday.html",
            "https://www.gotquestions.org/crucifixion.html",
            "https://www.gotquestions.org/tattoos-sin.html",
        ]
        self.wr._INDEX[site["id"]] = (time.time(), urls)
        ranked = self.wr._rank_index(
            site, "Did Jesus die Friday or Wednesday?")
        self.assertIn("https://www.gotquestions.org/Good-Friday.html", ranked)
        self.assertIn("https://www.gotquestions.org/crucifixion.html", ranked)
        self.assertNotIn("https://www.gotquestions.org/tattoos-sin.html", ranked)

    def test_specific_topic_beats_generic_word(self):
        # Both words of "what does the Bible say about love" appear in a
        # topical sitemap, but the broad "Bible" entry must not outrank the
        # specific "Love" one just because it comes first alphabetically.
        site = next(s for s in self.wr.SITES if s["id"] == "bg")
        urls = [
            "https://www.biblegateway.com/topical/Bible/Nave",
            "https://www.biblegateway.com/topical/Love/Nave",
        ]
        self.wr._INDEX[site["id"]] = (time.time(), urls)
        ranked = self.wr._rank_index(site, "What does the Bible say about love?")
        self.assertEqual(ranked[0],
                         "https://www.biblegateway.com/topical/Love/Nave")

    def test_url_patterns_are_built_from_the_question(self):
        site = next(s for s in self.wr.SITES if s["id"] == "gq")
        urls = self.wr._candidates(site, "Who is Jesus?")
        self.assertIn("https://www.gotquestions.org/who-is-jesus.html", urls)

    def test_bible_odyssey_article_pattern_and_sitemap(self):
        site = next(s for s in self.wr.SITES if s["id"] == "bo")
        self.assertEqual(site["host"], "www.bibleodyssey.org")
        urls = self.wr._candidates(site, "Who wrote the Bible?")
        self.assertIn("https://www.bibleodyssey.org/articles/who-wrote-the-bible/", urls)
        self.assertTrue(site["sitemap"].endswith("/article-sitemap.xml"))

    def test_step_bible_query_string_articles_are_indexed_and_ranked(self):
        site = next(s for s in self.wr.SITES if s["id"] == "step")
        xml = ("<urlset><url><loc>"
               "https://www.stepbible.org/?q=version=NIV@version=ESV@meanings=Jacob"
               "</loc></url></urlset>").encode()
        original = self.wr._get_raw
        self.wr._get_raw = lambda url, allowed, max_bytes=0: (xml, "")
        self.addCleanup(setattr, self.wr, "_get_raw", original)
        self.wr._INDEX.pop(site["id"], None)
        urls = self.wr._load_index(site)
        self.assertIn(
            "https://www.stepbible.org/?q=version=NIV@version=ESV@meanings=Jacob",
            urls)
        ranked = self.wr._rank_index(site, "Who was Jacob?")
        self.assertIn(
            "https://www.stepbible.org/?q=version=NIV@version=ESV@meanings=Jacob",
            ranked)
        urls = self.wr._candidates(site, "What does Jacob mean?")
        self.assertIn("https://www.stepbible.org/?q=meanings=what-does-jacob-mean",
                      urls)

    def test_bible_project_article_pattern_and_index(self):
        site = next(s for s in self.wr.SITES if s["id"] == "bp")
        self.assertEqual(site["host"], "bibleproject.com")
        xml = ("<urlset>"
               "<url><loc>https://bibleproject.com/articles/what-is-the-sermon-on-the-mount/</loc></url>"
               "<url><loc>https://bibleproject.com/videos/the-sermon-on-the-mount/</loc></url>"
               "</urlset>").encode()
        original = self.wr._get_raw
        self.wr._get_raw = lambda url, allowed, max_bytes=0: (xml, "")
        self.addCleanup(setattr, self.wr, "_get_raw", original)
        self.wr._INDEX.pop(site["id"], None)
        urls = self.wr._candidates(site, "What is the Sermon on the Mount?")
        self.assertIn(
            "https://bibleproject.com/articles/what-is-the-sermon-on-the-mount/",
            urls)
        urls = self.wr._load_index(site)
        self.assertIn(
            "https://bibleproject.com/articles/what-is-the-sermon-on-the-mount/",
            urls)
        # Video pages are not prose sources; the reader already has those.
        self.assertNotIn(
            "https://bibleproject.com/videos/the-sermon-on-the-mount/", urls)

    def test_new_sites_are_ranked_for_their_own_topics(self):
        # A scholarly question should pull Bible Odyssey in; a word-study
        # question should pull STEP Bible in.  Neither displaces the original
        # sites for the questions those were chosen to answer.
        scholarly = self.wr._choose_sites(
            "What does archaeology tell us about the Hebrew Bible?")
        self.assertIn("www.bibleodyssey.org", [s["host"] for s in scholarly])
        words = self.wr._choose_sites("What does this Greek word mean?")
        self.assertIn("www.stepbible.org", [s["host"] for s in words])
        themed = self.wr._choose_sites(
            "What is the Sermon on the Mount about?")
        self.assertIn("bibleproject.com", [s["host"] for s in themed])
        self.assertEqual(
            self.wr._choose_sites("Who is Jesus?")[0]["host"],
            "www.gotquestions.org")

    def test_run_returns_a_page_and_a_one_use_token(self):
        self.wr.set_consent(True)
        p = self.wr.plan("creation of the earth")
        article = ("<html><head><title>Creation</title></head><body>"
                   + "<p>" + ("God created the earth. " * 30) + "</p>"
                   + "</body></html>").encode()
        original = self.wr._get_raw
        self.wr._get_raw = lambda url, allowed, max_bytes=0: (article, "")
        self.addCleanup(setattr, self.wr, "_get_raw", original)
        r = self.wr.run(p["token"])
        self.assertTrue(r["ok"])
        self.assertEqual(r["results"][0]["host"], "answersingenesis.org")
        self.assertEqual(r["results"][0]["title"], "Creation")
        src = self.wr.as_sources(self.wr.take_results(r["token"]))
        self.assertTrue(src[0]["external"])
        self.assertEqual(self.wr.take_results(r["token"]), [])

    def test_thin_first_pass_gets_one_bounded_follow_up(self):
        from unittest.mock import patch
        self.wr.set_consent(True)
        p = self.wr.plan("What is the Sermon on the Mount?")
        seen_queries = []
        fetches = []

        def candidates(site, query):
            seen_queries.append(query)
            return ["https://" + site["host"] + "/x/"
                    + query.replace(" ", "-") + "/"]

        article = ("<html><head><title>Sermon</title></head><body><p>"
                   + ("Jesus taught about the kingdom. " * 20)
                   + "</p></body></html>").encode()

        def get(url, allowed, max_bytes=0):
            fetches.append(url)
            if "sermon-mount" in url:
                return article, ""
            return None, "no such page"

        with patch.object(self.wr, "_candidates", side_effect=candidates), \
             patch.object(self.wr, "_get_raw", side_effect=get), \
             patch.object(self.wr.time, "sleep"):
            r = self.wr.run(p["token"])

        self.assertTrue(r["ok"])
        self.assertGreaterEqual(len(r["results"]), 1)
        self.assertTrue(any(q == "sermon mount" for q in seen_queries),
                        seen_queries)
        self.assertLessEqual(len(fetches), self.wr.MAX_FETCHES)
        self.assertEqual(len(self.wr.take_results(r["token"])),
                         len(r["results"]))

    def test_blocked_page_is_not_used(self):
        blocked = (b"<html><head><title>Human Verification</title></head>"
                   b"<body>Please verify you are human.</body></html>")
        out = self.wr._extract(blocked, "https://answersingenesis.org/x")
        self.assertFalse(self.wr._looks_real(out))

    def test_html_is_stripped(self):
        out = self.wr._extract(
            b"<html><title>T</title><script>bad()</script><p>Good text</p></html>",
            "https://bible.org/a")
        self.assertEqual(out["title"], "T")
        self.assertIn("Good text", out["text"])
        self.assertNotIn("bad()", out["text"])


class AutoWebTests(unittest.TestCase):
    def setUp(self):
        _scratch_home(self)
        from gbible import ai
        self.ai = ai

    def test_real_questions_are_offered_the_web(self):
        self.assertTrue(self.ai.needs_web_research("Who is Jesus?"))
        self.assertTrue(self.ai.needs_web_research(
            "What did the early church fathers teach about the resurrection?"))

    def test_trivial_greetings_do_not_prompt(self):
        self.assertFalse(self.ai.needs_web_research(""))
        self.assertFalse(self.ai.needs_web_research("hi"))
        self.assertFalse(self.ai.needs_web_research("hello there"))


if __name__ == "__main__":
    unittest.main()
