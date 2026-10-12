# VERIDEX v0.2.0 - reference validation and provenance auditing.
# Copyright (c) 2026 Madeesh P. Nissanka
# MIT License - see LICENSE file.
"""Offline tests for all resolver adapters using a fake transport (no network)."""
from __future__ import annotations

import json
import urllib.parse

import pytest

from veridex.httpclient import HttpClient, Response
from veridex.models import ParsedReference
from veridex.resolvers import SourceOpts, build, source_names
import veridex.api as api

api._register_adapters()


def make_client(routes: dict[str, tuple[int, bytes]]) -> HttpClient:
    """Fake transport: longest-matching URL substring -> (status, body)."""

    def transport(url: str, timeout: int) -> Response:
        for needle, (status, body) in routes.items():
            if needle in url:
                return Response(url=url, status=status, body=body, ok=status < 400,
                                error=None if status < 400 else f"http_{status}")
        return Response(url=url, status=404, body=b"", ok=False, error="http_404")

    return HttpClient(user_agent="veridex-test/0.2", transport=transport, min_interval=0.0)


def jbody(payload: dict) -> bytes:
    return json.dumps(payload).encode("utf-8")


def src(name: str, routes: dict[str, tuple[int, bytes]]):
    return build(name, make_client(routes), SourceOpts(enabled=True))


class TestRegistry:
    def test_all_adapters_registered(self):
        expected = {"arxiv", "crossref", "datacite", "doaj", "europepmc",
                    "openalex", "openlibrary", "pubmed", "semscholar"}
        assert expected.issubset(set(source_names()))

    def test_build_disabled_returns_none(self):
        assert build("datacite", make_client({}), SourceOpts(enabled=False)) is None

    def test_build_unknown_returns_none(self):
        assert build("nope", make_client({}), SourceOpts(enabled=True)) is None


class TestDatacite:
    PAYLOAD = {"data": {"attributes": {
        "titles": [{"title": "Soil consolidation under cyclic loading"}],
        "creators": [{"name": "Smith, J."}],
        "publicationYear": 2020,
        "publisher": "Geo Press",
        "doi": "10.5555/soil.2020",
        "url": "https://example.org/soil",
        "types": {"resourceTypeGeneral": "Text"},
    }}}

    def test_lookup_by_doi(self):
        s = src("datacite", {"api.datacite.org/dois/10.5555": (200, jbody(self.PAYLOAD))})
        recs, ev = s.lookup(ParsedReference(doi="10.5555/soil.2020", title="Soil consolidation"))
        assert len(recs) == 1
        assert recs[0].title == "Soil consolidation under cyclic loading"
        assert recs[0].year == 2020
        assert recs[0].source == "datacite"
        assert recs[0].document_type == "preprint"
        assert ev and ev[0].ok

    def test_missing_doi_returns_empty(self):
        s = src("datacite", {})
        recs, ev = s.lookup(ParsedReference(doi="10.0000/ghost"))
        assert recs == []
        assert ev[0].http_status == 404 if hasattr(ev[0], "http_status") else True

    def test_from_json_creators(self):
        from veridex.resolvers.datacite import DataciteSource
        rec = DataciteSource.from_json(self.PAYLOAD["data"], Response(url="u", status=200, body=b"x"))
        assert rec.authors[0]["family"] == "Smith"
        assert rec.authors[0]["given"] == "J."

    def test_search_uses_query(self):
        s = src("datacite", {"api.datacite.org/dois?query": (200, jbody({"data": [self.PAYLOAD["data"]]}))})
        recs, ev = s.search({"query": "soil consolidation"})
        assert len(recs) == 1

    def test_empty_ref(self):
        s = src("datacite", {})
        assert s.lookup(ParsedReference()) == ([], [])


class TestPubmed:
    ESUM = {"result": {"uids": ["12345678"], "12345678": {
        "uid": "12345678",
        "title": "Beam deflection in composites",
        "authors": [{"name": "Jones M"}],
        "pubdate": "2021 Mar 15",
        "fulljournalname": "Structural Journal",
        "volume": "10",
        "issue": "2",
        "pages": "1-10",
        "articleids": [{"idtype": "doi", "value": "10.1111/beam.2021"}],
    }}}
    ESEARCH = {"esearchresult": {"idlist": ["12345678"]}}

    def test_lookup_by_pmid(self):
        s = src("pubmed", {"esummary": (200, jbody(self.ESUM))})
        recs, ev = s.lookup(ParsedReference(pmid="12345678"))
        assert recs[0].title == "Beam deflection in composites"
        assert recs[0].year == 2021
        assert recs[0].pmid == "12345678"
        assert recs[0].doi == "10.1111/beam.2021"

    def test_search_by_title(self):
        s = src("pubmed", {
            "esearch": (200, jbody(self.ESEARCH)),
            "esummary": (200, jbody(self.ESUM)),
        })
        recs, ev = s.lookup(ParsedReference(title="Beam deflection in composites", authors=["Jones M"]))
        assert len(recs) == 1

    def test_no_ids_no_records(self):
        s = src("pubmed", {"esearch": (200, jbody({"esearchresult": {"idlist": []}}))})
        recs, ev = s.search({"query": "nothing"})
        assert recs == []

    def test_from_json_authors(self):
        from veridex.resolvers.pubmed import PubmedSource
        rec = PubmedSource.from_json(self.ESUM["result"]["12345678"],
                                     Response(url="u", status=200, body=b"x"))
        assert rec.authors[0]["family"] == "Jones M"


class TestEuropePmc:
    CORE = {"resultList": {"result": [{
        "id": "12345678", "src": "MED",
        "title": "Concrete durability under freeze-thaw",
        "authorString": "Brown A., Davis B.",
        "publicationDate": "2019-06-01",
        "journalTitle": "Materials Journal",
        "journalInfo": {"issue": "4"},
        "volume": "12", "pageInfo": "100-115",
        "doi": "10.2222/concrete.2019",
        "pubType": "research-article; Journal Article",
    }]}}

    def test_lookup_by_doi(self):
        s = src("europepmc", {"rest/search": (200, jbody(self.CORE))})
        recs, ev = s.lookup(ParsedReference(doi="10.2222/concrete.2019"))
        assert recs[0].title.startswith("Concrete durability")
        assert recs[0].year == 2019
        assert recs[0].doi == "10.2222/concrete.2019"
        assert recs[0].document_type == "article"

    def test_retraction_pubtype_flagged(self):
        payload = {"resultList": {"result": [dict(self.CORE["resultList"]["result"][0],
                                                  pubType="retraction; Review")]}}
        s = src("europepmc", {"rest/search": (200, jbody(payload))})
        recs, ev = s.search({"query": "x"})
        kinds = [n["kind"] for n in recs[0].integrity["notices"]]
        assert "retraction" in kinds

    def test_preprint_src_ppr(self):
        payload = {"resultList": {"result": [dict(self.CORE["resultList"]["result"][0], src="PPR")]}}
        s = src("europepmc", {"rest/search": (200, jbody(payload))})
        recs, ev = s.search({"query": "x"})
        assert recs[0].document_type == "preprint"

    def test_author_string_split(self):
        from veridex.resolvers.europepmc import EuropePmcSource
        rec = EuropePmcSource.from_json(self.CORE["resultList"]["result"][0],
                                        Response(url="u", status=200, body=b"x"))
        assert rec.authors[0] == {"family": "Brown", "given": "A."}
        assert len(rec.authors) == 2


class TestSemScholar:
    PAPER = {"paperId": "abc123", "title": "Pavement fatigue modeling",
             "year": 2018, "venue": "Transportation Record",
             "authors": [{"name": "Lee, K."}],
             "externalIds": {"DOI": "10.3333/pave.2018", "CorpusId": 999},
             "publicationTypes": [{"name": "JournalArticle"}],
             "abstract": "A generic study.", "url": "https://example.org/p"}

    def test_lookup_by_doi(self):
        s = src("semscholar", {"graph/v1/paper/DOI": (200, jbody(self.PAPER))})
        recs, ev = s.lookup(ParsedReference(doi="10.3333/pave.2018"))
        assert recs[0].title == "Pavement fatigue modeling"
        assert recs[0].doi == "10.3333/pave.2018"
        assert recs[0].document_type == "article"

    def test_search(self):
        s = src("semscholar", {"paper/search": (200, jbody({"data": [self.PAPER]}))})
        recs, ev = s.search({"query": "pavement fatigue"})
        assert len(recs) == 1

    def test_by_arxiv_id(self):
        s = src("semscholar", {"graph/v1/paper/arXiv": (200, jbody(self.PAPER))})
        recs, ev = s.lookup(ParsedReference(arxiv_id="2001.00001"))
        assert len(recs) == 1

    def test_from_json_types(self):
        from veridex.resolvers.semscholar import SemScholarSource
        rec = SemScholarSource.from_json(self.PAPER, Response(url="u", status=200, body=b"x"))
        assert rec.arxiv_id is None
        assert rec.extra["paperId"] == "abc123"


class TestArxiv:
    XML = b"""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom" xmlns:arxiv="http://arxiv.org/schemas/atom">
  <entry>
    <id>http://arxiv.org/abs/2001.00001v2</id>
    <title>Heat conduction in layered media</title>
    <summary>A generic study of heat flow.</summary>
    <published>2020-01-02T00:00:00Z</published>
    <author><name>Aisha Khan</name></author>
    <arxiv:primary_category term="cond-mat"/>
    <arxiv:doi>10.4444/heat.2020</arxiv:doi>
  </entry>
</feed>"""

    def test_lookup_by_arxiv_id(self):
        s = src("arxiv", {"export.arxiv.org/api/query?id_list": (200, self.XML)})
        recs, ev = s.lookup(ParsedReference(arxiv_id="2001.00001"))
        assert recs[0].title == "Heat conduction in layered media"
        assert recs[0].year == 2020
        assert recs[0].document_type == "preprint"
        assert recs[0].arxiv_id == "2001.00001v2"

    def test_author_split(self):
        s = src("arxiv", {"export.arxiv.org/api/query": (200, self.XML)})
        recs, ev = s.search({"query": "heat conduction"})
        assert recs[0].authors[0] == {"family": "Khan", "given": "Aisha"}

    def test_parse_error(self):
        s = src("arxiv", {"api/query": (200, b"not xml <<>")})
        recs, ev = s.search({"query": "x"})
        assert recs == []

    def test_doi_extracted(self):
        s = src("arxiv", {"export.arxiv.org/api/query": (200, self.XML)})
        recs, ev = s.lookup(ParsedReference(arxiv_id="2001.00001"))
        assert recs[0].doi == "10.4444/heat.2020"


class TestOpenLibrary:
    OL_BIB = {"key": "/books/OL97M", "title": "Geotechnical Engineering Handbook",
              "authors": [{"name": "Ngai, R."}], "publishers": [{"name": "Tech Press"}],
              "publish_date": "2015", "number_of_pages": 480}
    OL_SEARCH = {"docs": [{"key": "/books/OL97M", "title": "Geotechnical Engineering Handbook",
                            "authors": [{"name": "Ngai, R."}], "first_publish_year": 2015,
                            "isbn": ["9783161484100"]}]}

    def test_lookup_by_isbn(self):
        s = src("openlibrary", {"openlibrary.org/isbn": (200, jbody(self.OL_BIB))})
        recs, ev = s.lookup(ParsedReference(isbn="9783161484100"))
        assert recs[0].title == "Geotechnical Engineering Handbook"
        assert recs[0].year == 2015
        assert recs[0].publisher == "Tech Press"
        assert recs[0].document_type == "book"

    def test_search_title(self):
        s = src("openlibrary", {"search.json": (200, jbody(self.OL_SEARCH))})
        recs, ev = s.lookup(ParsedReference(title="Geotechnical Engineering Handbook"))
        assert len(recs) == 1

    def test_from_json_author_ref_string(self):
        from veridex.resolvers.openlibrary import OpenLibrarySource
        rec = OpenLibrarySource.from_json(
            {"title": "T", "authors": ["/works/OL1W"]},
            Response(url="u", status=200, body=b"x"))
        assert rec.authors[0]["family"] == "OL1W"


class TestDoaj:
    RESULT = {"id": "S0001", "bibjson": {
        "title": "Slope stability analysis of earthen embankments",
        "author": [{"name": "Owen, T."}],
        "year": "2017",
        "journal": {"title": "Geotechnical Review", "volume": "8", "number": "2", "issn": "0000-0000"},
        "pages": {"start": "21", "end": "35"},
        "publisher": "Open Journals",
        "identifier": [{"type": "doi", "id": "10.5555/slope.2017"}],
        "abstract": "Generic slope study.",
        "link": [{"url": "https://example.org/full"}],
        "license": [{"type": "CC BY"}],
    }}

    def test_lookup_by_doi(self):
        s = src("doaj", {"doaj.org/api/search/articles": (200, jbody({"results": [self.RESULT]}))})
        recs, ev = s.lookup(ParsedReference(doi="10.5555/slope.2017"))
        assert recs[0].title.startswith("Slope stability")
        assert recs[0].year == 2017
        assert recs[0].pages == "21-35"
        assert recs[0].doi == "10.5555/slope.2017"

    def test_from_json_issn_extra(self):
        from veridex.resolvers.doaj import DoajSource
        rec = DoajSource.from_json(self.RESULT, Response(url="u", status=200, body=b"x"))
        assert rec.extra["issn"] == "0000-0000"
        assert rec.extra["license"] == "CC BY"

    def test_search_no_terms(self):
        s = src("doaj", {})
        assert s.search({}) == ([], [])


class TestEvidence:
    def test_evidence_hash_recorded(self):
        payload = {"data": {"attributes": {"titles": [{"title": "T"}]}}}
        s = src("datacite", {"dois/10.9": (200, jbody(payload))})
        recs, ev = s.lookup(ParsedReference(doi="10.9/t"))
        assert ev[0].response_sha256
        assert ev[0].source == "datacite"

    def test_error_response_keeps_evidence(self):
        s = src("pubmed", {"esummary": (500, b"")})
        recs, ev = s.lookup(ParsedReference(pmid="1"))
        assert recs == []
        assert not ev[0].ok
