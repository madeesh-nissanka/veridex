# VERIDEX v0.2.0 - reference validation and provenance auditing.
# Copyright (c) 2026 Madeesh P. Nissanka
# MIT License - see LICENSE file.
"""Tests for BibTeX parser."""
from __future__ import annotations

import pytest

from veridex.parsing.bibtex import parse_bibtex


HEADER = (
    "# VERIDEX v0.2.0 - reference validation and provenance auditing.\n"
    "# Copyright (c) 2026 Madeesh P. Nissanka\n"
    "# MIT License - see LICENSE file.\n"
)


def test_bibtex_basic_article() -> None:
    text = """@article{smith2020,
  title = {Soil consolidation under cyclic loading},
  author = {Smith, John and Jones, Mary},
  journal = {Journal of Geotechnical Engineering},
  volume = {45},
  number = {3},
  pages = {123--145},
  year = {2020},
  doi = {10.1234/jge.2020.001}
}"""
    refs = parse_bibtex(text)
    assert len(refs) == 1
    ref = refs[0]
    assert ref.title == "Soil consolidation under cyclic loading"
    assert ref.authors == ["Smith, John", "Jones, Mary"]
    assert ref.journal == "Journal of Geotechnical Engineering"
    assert ref.volume == "45"
    assert ref.issue == "3"
    assert ref.pages == "123--145"
    assert ref.year == 2020
    assert ref.doi == "10.1234/jge.2020.001"
    assert ref.format == "bib"
    assert ref.raw_fields["title"] == "Soil consolidation under cyclic loading"


def test_bibtex_nested_braces() -> None:
    text = """@article{doe2021,
  title = {Beam deflection with {composite} materials},
  author = {Doe, Jane and {{Brown}}, Robert},
  journal = {Structural Engineering Journal},
  year = {2021}
}"""
    refs = parse_bibtex(text)
    assert len(refs) == 1
    ref = refs[0]
    assert ref.title == "Beam deflection with {composite} materials"
    assert "Brown" in ref.authors[1]


def test_bibtex_string_skip() -> None:
    text = """@string{jge = {Journal of Geotechnical Engineering}}
@article{test2022,
  title = {Slope stability analysis},
  author = {White, Alice},
  journal = {Journal of Geotechnical Engineering},
  year = {2022}
}"""
    refs = parse_bibtex(text)
    assert len(refs) == 1
    ref = refs[0]
    assert ref.journal == "Journal of Geotechnical Engineering"


def test_bibtex_preamble_skip() -> None:
    text = """@preamble{"\\usepackage{amsmath}"}
@article{test2023,
  title = {Concrete durability},
  author = {Green, Bob},
  journal = {Materials Journal},
  year = {2023}
}"""
    refs = parse_bibtex(text)
    assert len(refs) == 1
    ref = refs[0]
    assert ref.title == "Concrete durability"


def test_bibtex_multi_author_and_split() -> None:
    text = """@article{multi2024,
  title = {Heat conduction in layered media},
  author = {Author One and Author Two and Author Three and Author Four},
  journal = {Physics Journal},
  year = {2024}
}"""
    refs = parse_bibtex(text)
    assert len(refs) == 1
    ref = refs[0]
    assert len(ref.authors) == 4
    assert ref.authors == ["Author One", "Author Two", "Author Three", "Author Four"]


def test_bibtex_multiple_entries() -> None:
    text = """@article{first2020,
  title = {First paper},
  author = {Alpha, A.},
  journal = {Journal A},
  year = {2020}
}
@book{second2021,
  title = {Second book},
  author = {Beta, B.},
  publisher = {Press B},
  year = {2021}
}"""
    refs = parse_bibtex(text)
    assert len(refs) == 2
    assert refs[0].title == "First paper"
    assert refs[1].title == "Second book"
    assert refs[1].publisher == "Press B"


def test_bibtex_unicode() -> None:
    text = """@article{unicode2020,
  title = {Pavement fatigue: análise e modelação},
  author = {Silva, João and Müller, Jürgen},
  journal = {Revista de Engenharia},
  year = {2020}
}"""
    refs = parse_bibtex(text)
    assert len(refs) == 1
    ref = refs[0]
    assert "análise" in ref.title
    assert "Müller" in ref.authors[1]


def test_bibtex_empty_input() -> None:
    refs = parse_bibtex("")
    assert refs == []
    refs = parse_bibtex("   \n\n  ")
    assert refs == []


def test_bibtex_malformed_missing_brace() -> None:
    text = """@article{bad2020,
  title = {Missing brace,
  author = {Test, T.},
  year = {2020}
}"""
    refs = parse_bibtex(text)
    assert len(refs) == 1
    ref = refs[0]
    assert ref.title == "Missing brace"
    assert ref.authors == ["Test, T."]
    assert ref.year == 2020


def test_bibtex_comment_skip() -> None:
    text = """@comment{This is a comment}
@article{real2020,
  title = {Real entry},
  author = {Author, A.},
  journal = {Journal},
  year = {2020}
}"""
    refs = parse_bibtex(text)
    assert len(refs) == 1
    assert refs[0].title == "Real entry"


def test_bibtex_doi_url_extraction() -> None:
    text = """@article{ids2020,
  title = {Identifiers test},
  author = {Test, T.},
  journal = {Journal},
  year = {2020},
  url = {https://example.com/paper},
  doi = {10.5555/test.2020},
  pmid = {12345678},
  arxiv = {2001.00001},
  isbn = {978-3-16-148410-0}
}"""
    refs = parse_bibtex(text)
    assert len(refs) == 1
    ref = refs[0]
    assert ref.doi == "10.5555/test.2020"
    assert ref.url == "https://example.com/paper"
    assert ref.pmid == "12345678"
    assert ref.arxiv_id == "2001.00001"
    assert ref.isbn == "9783161484100"


def test_bibtex_month_edition_ignored() -> None:
    text = """@article{month2020,
  title = {Month and edition},
  author = {Author, A.},
  journal = {Journal},
  year = {2020},
  month = {jan},
  edition = {2nd}
}"""
    refs = parse_bibtex(text)
    assert len(refs) == 1
    ref = refs[0]
    assert ref.raw_fields.get("month") == "jan"
    assert ref.raw_fields.get("edition") == "2nd"
    assert not hasattr(ref, "month")


def test_bibtex_quoted_values() -> None:
    text = """@article{quoted2020,
  title = "Quoted title with {braces}",
  author = "Author, A. and Author, B.",
  journal = "Journal Name",
  year = "2020"
}"""
    refs = parse_bibtex(text)
    assert len(refs) == 1
    ref = refs[0]
    assert ref.title == "Quoted title with {braces}"
    assert ref.authors == ["Author, A.", "Author, B."]


def test_bibtex_crossref_type_entry() -> None:
    text = """@inproceedings{conf2020,
  title = {Conference paper on bearing capacity},
  author = {Clark, C.},
  booktitle = {Proc. Int. Conf. Foundations},
  pages = {100--110},
  year = {2020},
  publisher = {Springer}
}"""
    refs = parse_bibtex(text)
    assert len(refs) == 1
    ref = refs[0]
    assert ref.journal == "Proc. Int. Conf. Foundations"
    assert ref.publisher == "Springer"
    assert ref.pages == "100--110"


def test_bibtex_bare_values() -> None:
    text = """@article{bare2020,
  title = Bare title without braces,
  author = Author, A.,
  journal = Journal Name,
  year = 2020
}"""
    refs = parse_bibtex(text)
    assert len(refs) == 1
    ref = refs[0]
    assert ref.title == "Bare title without braces"
    assert ref.authors == ["Author, A."]
    assert ref.journal == "Journal Name"
    assert ref.year == 2020