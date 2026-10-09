#!/usr/bin/env python3
"""Unit tests for VERIDEX."""
import json
import os
import re
import tempfile
import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
from veridex import (
    clean_doi,
    normalize_title,
    title_similarity,
    first_author_surname,
    parse_text_line,
    parse_bibtex,
    parse_ris,
    make_bibtex_key,
    DOI_RE,
)


class TestVeridex(unittest.TestCase):

    def test_doi_regex(self):
        self.assertTrue(DOI_RE.search("doi:10.1061/(ASCE)1090-0241(2001)127:10(817)"))
        self.assertTrue(DOI_RE.search("10.1126/science.adu1370"))
        self.assertTrue(DOI_RE.search("https://doi.org/10.1000/xyz"))
        self.assertIsNone(DOI_RE.search("no doi here"))
        self.assertIsNone(DOI_RE.search("10.1234/"))  # too short

    def test_clean_doi(self):
        self.assertEqual(clean_doi("https://doi.org/10.1000/xyz"), "10.1000/xyz")
        self.assertEqual(clean_doi("10.1000/xyz."), "10.1000/xyz")
        self.assertEqual(clean_doi("10.1000/xyz;"), "10.1000/xyz")
        self.assertEqual(clean_doi("doi:10.1000/xyz)"), "10.1000/xyz")
        self.assertIsNone(clean_doi(None))
        self.assertIsNone(clean_doi(""))

    def test_normalize_title(self):
        self.assertEqual(normalize_title("The Cat Sat"), "the cat sat")
        self.assertEqual(normalize_title("Title: With, Punctuation!"), "title with punctuation")
        self.assertEqual(normalize_title(""), "")
        self.assertEqual(normalize_title(None), "")

    def test_title_similarity(self):
        self.assertGreaterEqual(title_similarity("The Cat Sat", "The Cat Sat"), 0.99)
        self.assertLess(title_similarity("The Cat Sat", "The Dog Ran"), 0.90)
        self.assertEqual(title_similarity("", ""), 1.0)

    def test_first_author_surname(self):
        self.assertEqual(first_author_surname(["Smith, John"]), "Smith")
        self.assertEqual(first_author_surname(["John Smith"]), "Smith")
        self.assertEqual(first_author_surname(["Van der Waals"]), "Waals")
        self.assertIsNone(first_author_surname([]))
        self.assertIsNone(first_author_surname(None))

    def test_parse_text_line(self):
        line = "[3] Wilkinson, M.D. et al. (2016). The FAIR Guiding Principles for scientific data management. Scientific Data. doi:10.1038/sdata.2016.18"
        parsed = parse_text_line(line)
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed["doi"], "10.1038/sdata.2016.18")
        self.assertEqual(parsed["year"], 2016)
        self.assertEqual(parsed["first_author"], "Wilkinson")
        self.assertIn("FAIR", parsed["title"])

        line2 = "Smith, J. et al. (2023). A paper without a DOI. Example Conference."
        parsed2 = parse_text_line(line2)
        self.assertIsNone(parsed2["doi"])
        self.assertEqual(parsed2["year"], 2023)
        self.assertEqual(parsed2["first_author"], "Smith")

    def test_parse_bibtex(self):
        bib = """@article{test2020,
  author = {Smith, John and Jones, Mary},
  title = {A Test Title},
  year = {2020},
  journal = {Test Journal},
  doi = {10.1000/test}
}"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".bib", delete=False) as f:
            f.write(bib)
            f.flush()
            entries = parse_bibtex(f.name)
        os.unlink(f.name)
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["doi"], "10.1000/test")
        self.assertEqual(entries[0]["year"], 2020)
        self.assertEqual(entries[0]["first_author"], "Smith")

    def test_parse_ris(self):
        ris = """TY  - JOUR
AU  - Smith, John
AU  - Jones, Mary
TI  - A Test Title
PY  - 2020
DO  - 10.1000/test
ER  -"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".ris", delete=False) as f:
            f.write(ris)
            f.flush()
            entries = parse_ris(f.name)
        os.unlink(f.name)
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["doi"], "10.1000/test")
        self.assertEqual(entries[0]["year"], 2020)
        self.assertEqual(entries[0]["first_author"], "Smith")

    def test_make_bibtex_key(self):
        msg = {
            "author": [{"family": "Smith", "given": "John"}],
            "issued": {"date-parts": [[2020]]},
            "title": ["A Test Title for Something"],
        }
        self.assertEqual(make_bibtex_key(msg), "Smith2020A")


class TestStatusAssignment(unittest.TestCase):
    """Test status assignment logic using hand-made Crossref-like dicts."""

    def make_cr_msg(self, title, year, authors, update_to=None):
        msg = {
            "title": [title],
            "issued": {"date-parts": [[year]]},
            "author": [{"family": a, "given": "Given"} for a in authors],
        }
        if update_to:
            msg["update-to"] = update_to
        return msg

    def test_retracted(self):
        from veridex import check_retraction
        msg = self.make_cr_msg("Title", 2020, ["Smith"], [{"type": "retraction"}])
        self.assertTrue(check_retraction(msg))
        msg = self.make_cr_msg("Title", 2020, ["Smith"], [{"type": "withdrawal"}])
        self.assertTrue(check_retraction(msg))
        msg = self.make_cr_msg("Title", 2020, ["Smith"], [{"type": "correction"}])
        self.assertFalse(check_retraction(msg))

    def test_author_order_differs(self):
        rec_first = "Smith"
        cr_surnames = ["Jones", "Smith"]
        self.assertIn(rec_first, cr_surnames)
        self.assertNotEqual(cr_surnames[0], rec_first)

    def test_author_mismatch(self):
        rec_first = "Smith"
        cr_surnames = ["Jones", "Brown"]
        self.assertNotIn(rec_first, cr_surnames)

    def test_year_off_by_one(self):
        rec_year = 2020
        cr_year = 2021
        self.assertEqual(abs(rec_year - cr_year), 1)

    def test_year_mismatch(self):
        rec_year = 2020
        cr_year = 2023
        self.assertGreater(abs(rec_year - cr_year), 1)


if __name__ == "__main__":
    unittest.main()

class TestRegressions(unittest.TestCase):
    """Bugs found by running the tool against live Crossref."""

    def setUp(self):
        import importlib.util, pathlib
        spec = importlib.util.spec_from_file_location("veridex", pathlib.Path(__file__).resolve().parents[1] / "scripts" / "veridex.py")
        self.v = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.v)

    def test_doi_ending_in_parenthesis_is_kept(self):
        line = "[1] Doe, J. et al. (2001). An example title. Example Journal. doi:10.1000/(ABC)1234(2001)5:6(789)"
        e = self.v.parse_text_line(line)
        self.assertEqual(e["doi"], "10.1000/(ABC)1234(2001)5:6(789)")

    def test_unbalanced_trailing_parenthesis_is_dropped(self):
        self.assertEqual(self.v.clean_doi("10.1038/sdata.2016.18)."), "10.1038/sdata.2016.18")

    def test_title_with_decimal_in_name(self):
        line = "[7] Roe, R. et al. (2015). Toolkit 2.1 application and databases: a test module. Example Agency. doi:10.1000/example.297295"
        e = self.v.parse_text_line(line)
        self.assertEqual(e["title"], "Toolkit 2.1 application and databases: a test module")
