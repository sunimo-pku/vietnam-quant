"""Preserve SSC's legacy public archive, with explicit search coverage limits."""
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
import json
import re
import tempfile
from urllib.parse import quote, urljoin, urlparse, parse_qs

from bs4 import BeautifulSoup

from .http import Client, FetchError, utc_now

BASE = "https://ssc.gov.vn"
SEARCH = BASE + "/webcenter/portal/ubck/pages_otherpages/tmkim?SearchInput="


def parse_search(html):
    soup = BeautifulSoup(html, "html.parser")
    match = re.search(r"Tìm thấy\s*([\d,.]+)\s*kết quả", soup.get_text(" ", strip=True))
    if not match:
        raise FetchError("SSC search has no result count; coverage is unknown")
    total = int(re.sub(r"[,.]", "", match[1]))
    links = [{"title": a.get_text(" ", strip=True), "url": urljoin(BASE, a.get("href", "")),
              "text": a.parent.parent.get_text(" ", strip=True)} for a in soup.select("h3 a")]
    if len(links) > total or (total and not links):
        raise FetchError("SSC search result count and article links disagree")
    return links, total


def parse_article(html, link):
    soup = BeautifulSoup(html, "html.parser")
    body = soup.select_one(".new-content")
    if not body or not body.get_text(strip=True):
        raise FetchError("SSC article has no readable archive content")
    text = body.get_text(" ", strip=True)
    search_date = re.search(r"\b(\d{2}/\d{2}/\d{4})\b", link.get("text", ""))
    dates = re.findall(r"\b\d{2}/\d{2}/\d{4}\b", text)
    published = datetime.strptime(search_date[1], "%d/%m/%Y").date().isoformat() if search_date else None
    future_dates = sorted({datetime.strptime(d, "%d/%m/%Y").date().isoformat() for d in dates
                           if published and datetime.strptime(d, "%d/%m/%Y").date().isoformat() > published})
    return {"source": "SSC legacy archive", "article_id": parse_qs(urlparse(link["url"]).query).get("dDocName", [None])[0],
            "source_url": link["url"], "title": link["title"], "published_local": published,
            "content_html": str(body), "content_text": text,
            "body_dates_after_publication": future_dates,
            "needs_date_review": bool(future_dates),
            "scope": "Archive evidence, not an automatically inferred stock status"}


def download(root, queries, index_paths):
    target = root / "ssc"
    target.mkdir(parents=True, exist_ok=True)
    links, searches, failures = {}, [], []
    for path in index_paths:
        index = json.loads(path.read_text())
        index_links = [r for p in index["pages"] for r in p["links"]]
        unique = {r["url"]: r for r in index_links}
        total = index.get("reported_total")
        complete = total is not None and len(index_links) == total and len(unique) == total
        searches.append({"index_path": str(path.resolve()), "reported_total": total,
                         "saved_links": len(unique), "complete_for_search_query": complete,
                         "query": index.get("query"), "date_from": index.get("date_from"), "date_to": index.get("date_to")})
        links.update(unique)
    for query in queries:
        try:
            with tempfile.TemporaryDirectory() as temp:
                cookie = temp + "/cookies"
                client = Client(root / "raw" / "ssc", ["--cookie", cookie, "--cookie-jar", cookie])
                html, receipt = client.fetch(SEARCH + quote(query), cache=True)
            found, total = parse_search(html)
            searches.append({"query": query, "reported_total": total, "saved_links": len(found),
                             "complete_for_search_query": len(found) == total, "receipt": receipt,
                             "limitation": "URL search returns first page; additional pages require an exported index"})
            links.update({r["url"]: r for r in found})
        except Exception as exc:
            failures.append({"query": query, "error": str(exc)})

    def fetch(link):
        if urlparse(link["url"]).hostname != "ssc.gov.vn":
            raise FetchError("Archive index contains a non-SSC URL")
        with tempfile.TemporaryDirectory() as temp:
            cookie = temp + "/cookies"
            client = Client(root / "raw" / "ssc", ["--cookie", cookie, "--cookie-jar", cookie])
            html, receipt = client.fetch(link["url"], cache=True)
        row = parse_article(html, link)
        row["receipt"] = receipt
        return row

    rows = []
    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = {pool.submit(fetch, link): link for link in links.values()}
        for future in as_completed(futures):
            link = futures[future]
            try:
                rows.append(future.result())
            except Exception as exc:
                failures.append({"url": link["url"], "error": str(exc)})
            print(f"SSC articles {len(rows)}/{len(links)}, failures {len(failures)}", flush=True)
    rows.sort(key=lambda r: (r["published_local"] or "", r["source_url"]))
    (target / "articles.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2))
    manifest = {"generated_at": utc_now(), "articles": len(rows), "searches": searches, "failures": failures,
                "complete_for_requested_searches": not failures and all(s["complete_for_search_query"] for s in searches),
                "archive_complete_since_2000": False,
                "limitation": "Keyword search does not establish complete market coverage; body dates require manual semantic review"}
    (target / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2))
    return manifest["complete_for_requested_searches"]
