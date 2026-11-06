import json
import re
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from collections.abc import Callable
from dataclasses import dataclass

BASE_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/"
REQUEST_GAP_S = 0.4
TIMEOUT_S = 30

STUDIES_ONLY = (
    " AND (meta-analysis[pt] OR systematic review[pt] OR randomized controlled trial[pt]"
    " OR review[pt] OR clinical trial[pt]) AND hasabstract AND english[la]"
)
STUDY_FILTER = STUDIES_ONLY + ' AND "last 5 years"[dp]'
PUBMED_SYNTAX = re.compile(r'[\[\]"()*]|\b(?:AND|OR|NOT)\b')


@dataclass
class Paper:
    pmid: str
    doi: str | None
    title: str
    authors: list[str]
    journal: str | None
    year: int | None
    abstract: str
    publication_types: list[str]


def http_get(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "garmin-coach"})
    with urllib.request.urlopen(request, timeout=TIMEOUT_S) as response:
        body: bytes = response.read()
        return body


def text_of(element: ET.Element | None) -> str:
    return "".join(element.itertext()).strip() if element is not None else ""


def parse_year(article: ET.Element) -> int | None:
    for path in (".//JournalIssue/PubDate/Year", ".//ArticleDate/Year", ".//PubDate/MedlineDate"):
        value = article.findtext(path)
        if value and value[:4].isdigit():
            return int(value[:4])
    return None


def parse_articles(xml: bytes) -> list[Paper]:
    papers = []
    for article in ET.fromstring(xml).iter("PubmedArticle"):
        sections = []
        for part in article.iter("AbstractText"):
            label = part.get("Label")
            body = text_of(part)
            sections.append(f"{label}: {body}" if label else body)
        authors = [
            f"{author.findtext('LastName')} {author.findtext('Initials') or ''}".strip()
            for author in article.iter("Author")
            if author.findtext("LastName")
        ]
        papers.append(
            Paper(
                pmid=article.findtext(".//PMID") or "",
                doi=next(
                    (a.text for a in article.iter("ArticleId") if a.get("IdType") == "doi"), None
                ),
                title=text_of(article.find(".//ArticleTitle")),
                authors=authors,
                journal=article.findtext(".//Journal/ISOAbbreviation")
                or article.findtext(".//Journal/Title"),
                year=parse_year(article),
                abstract="\n".join(sections),
                publication_types=[t.text or "" for t in article.iter("PublicationType")],
            )
        )
    return papers


class PubMed:
    def __init__(
        self,
        get: Callable[[str], bytes] = http_get,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.get = get
        self.sleep = sleep

    def _call(self, endpoint: str, params: dict[str, str]) -> bytes:
        self.sleep(REQUEST_GAP_S)
        query = urllib.parse.urlencode({**params, "db": "pubmed", "tool": "garmin-coach"})
        return self.get(f"{BASE_URL}{endpoint}?{query}")

    def search(self, term: str, limit: int) -> list[str]:
        body = self._call(
            "esearch.fcgi",
            {"term": term, "retmax": str(limit), "sort": "relevance", "retmode": "json"},
        )
        ids: list[str] = json.loads(body)["esearchresult"]["idlist"]
        return ids

    def find_studies(self, query: str, limit: int) -> list[str]:
        if PUBMED_SYNTAX.search(query):
            return self.search(f"({query}){STUDIES_ONLY}", limit)
        pmids: list[str] = []
        for field in ("ti", "tiab"):
            words = " AND ".join(f"{word}[{field}]" for word in query.split())
            found = self.search(f"({words}){STUDIES_ONLY}", limit)
            pmids += [pmid for pmid in found if pmid not in pmids]
            if len(pmids) >= limit:
                break
        return pmids[:limit]

    def fetch(self, pmids: list[str]) -> list[Paper]:
        if not pmids:
            return []
        return parse_articles(self._call("efetch.fcgi", {"id": ",".join(pmids), "retmode": "xml"}))
