"""
Internet search module for performing web searches and extracting content.

Ported from integration-agent-javiscore to jarviscore-framework.
All IA-specific imports replaced with env-var driven configuration
and optional lazy imports for browser/beautifulsoup4.
"""
import logging
import os
import aiohttp
import asyncio
import traceback
import re
import time
import xml.etree.ElementTree as ET
from io import BytesIO
from typing import Dict, Any, List, Optional, Tuple, Union
from urllib.parse import quote_plus, urlparse, urljoin

# beautifulsoup4 — required for HTML→Markdown extraction.
# Part of [web] or [research] extras.
try:
    from bs4 import BeautifulSoup
    _HAS_BS4 = True
except ImportError:
    _HAS_BS4 = False
    BeautifulSoup = None  # type: ignore[assignment,misc]

# Browser automation — optional, for SPA content escalation.
# Only needed if HTTP extraction returns empty content.
_HAS_BROWSER = False
try:
    from jarviscore.browser.controller import BrowserController, BrowserConfig
    _HAS_BROWSER = True
except ImportError:
    BrowserController = None  # type: ignore[assignment,misc]
    BrowserConfig = None  # type: ignore[assignment,misc]

logger = logging.getLogger(__name__)

class CircuitBreaker:
    """
    Simple Circuit Breaker implementation.
    Prevents cascading failures by stopping requests to failing services.
    """
    def __init__(self, failure_threshold: int = 8, recovery_timeout: int = 300):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.failures = {}
        self.last_failure_time = {}
        self.state = {} # 'OPEN', 'CLOSED', 'HALF_OPEN'

    def is_open(self, service: str) -> bool:
        if self.state.get(service) == 'OPEN':
            if time.time() - self.last_failure_time.get(service, 0) > self.recovery_timeout:
                logger.info(f"Circuit breaker HALF_OPEN for {service}")
                self.state[service] = 'HALF_OPEN'
                return False
            return True
        return False

    def record_failure(self, service: str):
        self.failures[service] = self.failures.get(service, 0) + 1
        self.last_failure_time[service] = time.time()
        if self.failures[service] >= self.failure_threshold:
            logger.warning(f"Circuit breaker OPEN for {service} due to {self.failures[service]} failures")
            self.state[service] = 'OPEN'

    def record_success(self, service: str):
        if self.state.get(service) == 'HALF_OPEN':
            logger.info(f"Circuit breaker CLOSED for {service}")
            self.state[service] = 'CLOSED'
            self.failures[service] = 0
        elif self.state.get(service) == 'CLOSED':
            self.failures[service] = 0

class InternetSearch:
    """
    Class for performing internet searches and content extraction
    
    Features:
    - Search the web using SearXNG (self-hosted metasearch)
    - Extract text content from web pages
    - Combined search and extraction in a single call
    - All content returned as data, no file dependencies
    - Circuit Breaker pattern for resilience
    """

    def __init__(
        self,
        user_agent: Optional[str] = None,
        pdf_timeout_seconds: Optional[int] = None,
        pdf_max_retries: Optional[int] = None,
    ):
        self.session = None
        self.user_agent = user_agent or "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
        self.pdf_timeout_seconds = pdf_timeout_seconds or int(
            os.environ.get("RESEARCH_PDF_TIMEOUT_SECONDS", "90")
        )
        self.pdf_max_retries = pdf_max_retries or int(
            os.environ.get("RESEARCH_PDF_MAX_RETRIES", "3")
        )
        self.serper_api_key = os.environ.get("SERPER_API_KEY")
        self.searxng_url = os.environ.get("SEARXNG_INSTANCE_URL", "http://localhost:8080")
        self.circuit_breaker = CircuitBreaker()

        self._gemini_client = None
        self._gcp_project = os.environ.get("GOOGLE_CLOUD_PROJECT")
        self._gemini_grounding_model = os.environ.get("GEMINI_GROUNDING_MODEL", "gemini-2.5-flash")
        self._gemini_api_key = (
            os.environ.get("GEMINI_GROUNDING_API_KEY")
            or os.environ.get("GEMINI_API_KEY")
            or os.environ.get("GOOGLE_GENAI_API_KEY", "")
        )

    async def initialize(self):
        """Initialize the HTTP session"""
        if self.session is None or self.session.closed:
            # Create a custom SSL context that ignores verification errors
            import ssl
            ssl_context = ssl.create_default_context()
            ssl_context.check_hostname = False
            ssl_context.verify_mode = ssl.CERT_NONE
            
            # Create connector with the custom SSL context
            connector = aiohttp.TCPConnector(ssl=ssl_context)
            
            self.session = aiohttp.ClientSession(
                connector=connector,
                timeout=aiohttp.ClientTimeout(total=10),  # 10 second timeout
                headers={
                    "User-Agent": self.user_agent,
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
                    "Accept-Language": "en-US,en;q=0.5"
                }
            )
            logger.info("HTTP session initialized (SSL verification disabled)")

    @property
    def _session(self) -> aiohttp.ClientSession:
        """Return the active session. Callers must call initialize() first."""
        assert self.session is not None, "HTTP session not initialised — call initialize() first"
        return self.session

    async def close(self):
        """Close the HTTP session"""
        if self.session and not self.session.closed:
            try:
                await self.session.close()
                logger.info("HTTP session closed")
            except Exception as e:
                logger.error(f"Error closing HTTP session: {str(e)}")
            self.session = None

    async def __aenter__(self):
        """Async context manager entry - initialize session"""
        await self.initialize()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit - close session"""
        await self.close()
        return False  # Don't suppress exceptions

    async def search(
        self,
        query: str,
        max_results: int = 10,
        exclude_providers: Optional[set] = None,
    ) -> List[Dict[str, Any]]:
        """
        Search for information on the internet.
        Uses multiple providers and ranks results.

        Args:
            query: The search query
            max_results: Maximum number of results to return
            exclude_providers: Optional set of provider names to skip entirely.
                Skipping at this level avoids wasted network calls — prefer this
                over filtering results after the fact.  e.g. {"arxiv", "crossref"}

        Returns:
            A list of search results with title, snippet, and URL
        """
        await self.initialize()
        skip = set(exclude_providers or ())

        encoded_query = quote_plus(query)
        provider_tasks = []
        if "google_grounded" not in skip and (self._gcp_project or self._gemini_api_key):
            provider_tasks.append(self._search_google_grounded(query, max_results=max_results))
        if self.serper_api_key and "serper" not in skip:
            provider_tasks.append(self._search_serper(query, max_results=max_results))
        if "searxng" not in skip:
            provider_tasks.append(self._search_searxng(query, max_results=max_results))
        if "wikipedia" not in skip:
            provider_tasks.append(self._search_wikipedia(query, max_results=max_results))
        if "arxiv" not in skip:
            provider_tasks.append(self._search_arxiv(query, max_results=max_results))
        if "crossref" not in skip:
            provider_tasks.append(self._search_crossref(query, max_results=max_results))
        provider_results = await asyncio.gather(
            *(asyncio.wait_for(task, timeout=6) for task in provider_tasks),
            return_exceptions=True,
        )
        results: List[Dict[str, Any]] = []
        for batch in provider_results:
            if isinstance(batch, Exception):
                logger.warning(f"Search provider failed: {batch}")
                continue
            elif isinstance(batch, list):
                results.extend(batch)
        ranked = self._rank_results(query, results)
        return ranked[:max_results]

    def _rank_results(self, query: str, results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        tokens = set(re.findall(r"[a-z0-9]+", query.lower()))
        weights = {
            "google_grounded": 1.4,
            "serper": 1.2,
            "searxng": 1.1,
            "arxiv": 0.9,
            "crossref": 0.8,
            "wikipedia": 0.6,
        }
        deduped: Dict[str, Dict[str, Any]] = {}
        for result in results:
            url = (result.get("url") or "").strip()
            if url and not url.startswith(("http://", "https://")):
                url = "https://" + url
            result["url"] = url
            key = self._normalize_url(url) or url
            text = f"{result.get('title','')} {result.get('snippet','')}".lower()
            overlap = sum(1 for t in tokens if t in text)
            pdf_bonus = 0.1 if url.lower().endswith(".pdf") else 0.0
            base = weights.get(result.get("source") or "", 0.5)
            score = base + (overlap * 0.05) + pdf_bonus
            result["score"] = score
            if key not in deduped or score > deduped[key].get("score", 0):
                deduped[key] = result
        return sorted(deduped.values(), key=lambda r: r.get("score", 0), reverse=True)

    @staticmethod
    def _normalize_url(url: str) -> str:
        parsed = urlparse(url)
        if not parsed.netloc:
            return ""
        normalized = f"{parsed.netloc}{parsed.path}"
        return normalized.rstrip("/")

    async def _search_searxng(
        self, query: str, max_results: int = 10
    ) -> List[Dict[str, Any]]:
        """Search via a self-hosted SearXNG instance (JSON API).

        SearXNG is a free, open-source metasearch engine that aggregates
        results from Google, Bing, DuckDuckGo, and dozens of other engines.
        It provides a proper JSON API — no HTML scraping required.

        Requires:
            SEARXNG_INSTANCE_URL  (default: http://localhost:8080)

        The instance must have JSON format enabled in settings.yml:
            search:
              formats:
                - json
        """
        if self.circuit_breaker.is_open("searxng"):
            logger.warning("Skipping SearXNG search (Circuit Breaker OPEN)")
            return []

        try:
            url = f"{self.searxng_url.rstrip('/')}/search"
            params = {
                "q": query,
                "format": "json",
                "categories": "general",
                "language": "en",
                "pageno": 1,
            }

            logger.info("Searching SearXNG: %s", query)

            last_status = 0
            for attempt in range(2):
                try:
                    async with self._session.get(
                        url,
                        params=params,
                        timeout=aiohttp.ClientTimeout(total=10),
                    ) as response:
                        last_status = response.status
                        if response.status == 200:
                            data = await response.json()
                            self.circuit_breaker.record_success("searxng")
                            results = []
                            for item in data.get("results", [])[:max_results]:
                                results.append({
                                    "title": item.get("title", ""),
                                    "snippet": item.get("content", ""),
                                    "url": item.get("url", ""),
                                    "source": "searxng",
                                    "engine": item.get("engine", ""),
                                })
                            logger.info("SearXNG: %d results", len(results))
                            return results
                        if response.status in (429, 503, 504):
                            await asyncio.sleep(1.0 * (2 ** attempt))
                            continue
                except (aiohttp.ClientConnectionError, asyncio.TimeoutError) as e:
                    logger.warning("SearXNG connection attempt %d failed: %s", attempt + 1, e)
                    await asyncio.sleep(1.0 * (2 ** attempt))

            logger.warning("SearXNG search failed with status: %d", last_status)
            self.circuit_breaker.record_failure("searxng")
        except Exception as e:
            logger.error("SearXNG search error: %s", e)
            logger.debug(traceback.format_exc())
            self.circuit_breaker.record_failure("searxng")

        return []

    async def _search_serper(self, query: str, max_results: int = 10) -> List[Dict[str, Any]]:
        """Search using Serper (Google Search API)."""
        if not self.serper_api_key:
            return []
            
        if self.circuit_breaker.is_open("serper"):
            logger.warning("Skipping Serper search (Circuit Breaker OPEN)")
            return []
            
        try:
            url = "https://google.serper.dev/search"
            payload = {"q": query, "num": max_results}
            headers = {
                "X-API-KEY": self.serper_api_key,
                "Content-Type": "application/json",
                "Accept": "application/json",
            }
            for attempt in range(3):
                try:
                    async with self._session.post(
                        url,
                        json=payload,
                        headers=headers,
                        timeout=aiohttp.ClientTimeout(total=5),
                    ) as response:
                        if response.status != 200:
                            if response.status in (202, 429, 503, 504):
                                await asyncio.sleep(1.0 * (2 ** attempt))
                                continue
                            logger.warning(f"Serper search failed with status code: {response.status}")
                            self.circuit_breaker.record_failure("serper")
                            return []
                        
                        self.circuit_breaker.record_success("serper")
                        data = await response.json()
                        results = []
                        for item in data.get("organic", [])[:max_results]:
                            results.append({
                                "title": item.get("title", ""),
                                "snippet": item.get("snippet", ""),
                                "url": item.get("link", ""),
                                "source": "serper",
                            })
                        logger.info(f"Found {len(results)} results from Serper")
                        return results
                except Exception as e:
                    if attempt == 2:
                        raise e
                    await asyncio.sleep(1.0 * (2 ** attempt))
        except Exception as e:
            logger.error(f"Error in Serper search: {str(e)}")
            logger.debug(traceback.format_exc())
            self.circuit_breaker.record_failure("serper")
        return []

    async def _search_wikipedia(self, query: str, max_results: int = 10) -> List[Dict[str, Any]]:
        """Fallback search using Wikipedia API."""
        if self.circuit_breaker.is_open("wikipedia"):
            return []
            
        try:
            url = (
                "https://en.wikipedia.org/w/api.php?"
                f"action=query&list=search&format=json&utf8=1&srlimit={max_results}"
                f"&srsearch={quote_plus(query)}"
            )
            logger.info(f"Searching Wikipedia with query: {query}")
            async with self._session.get(url) as response:
                if response.status != 200:
                    logger.warning(f"Wikipedia search failed with status code: {response.status}")
                    self.circuit_breaker.record_failure("wikipedia")
                    return []
                
                self.circuit_breaker.record_success("wikipedia")
                data = await response.json()
                results = []
                for item in data.get("query", {}).get("search", []):
                    title = item.get("title", "")
                    snippet = re.sub(r"<[^>]+>", "", item.get("snippet", "") or "")
                    page_url = f"https://en.wikipedia.org/wiki/{title.replace(' ', '_')}"
                    results.append({
                        "title": title,
                        "snippet": snippet,
                        "url": page_url,
                        "source": "wikipedia"
                    })
                logger.info(f"Found {len(results)} results from Wikipedia")
                return results
        except Exception as e:
            logger.error(f"Error in Wikipedia search: {str(e)}")
            logger.debug(traceback.format_exc())
            self.circuit_breaker.record_failure("wikipedia")
            return []

    async def _search_arxiv(self, query: str, max_results: int = 10) -> List[Dict[str, Any]]:
        """Search arXiv via ATOM API."""
        if self.circuit_breaker.is_open("arxiv"):
            return []
            
        try:
            url = (
                "https://export.arxiv.org/api/query?"
                f"search_query=all:{quote_plus(query)}&start=0&max_results={max_results}"
            )
            logger.info(f"Searching arXiv with query: {query}")
            session = self.session
            if session is None:
                raise RuntimeError("HTTP session not initialized")
            async with session.get(url) as response:
                if response.status != 200:
                    logger.warning(f"arXiv search failed with status code: {response.status}")
                    self.circuit_breaker.record_failure("arxiv")
                    return []
                xml_text = await response.text()
            
            self.circuit_breaker.record_success("arxiv")
            root = ET.fromstring(xml_text)
            ns = {"atom": "http://www.w3.org/2005/Atom"}
            results: List[Dict[str, Any]] = []
            for entry in root.findall("atom:entry", ns):
                title = (entry.findtext("atom:title", default="", namespaces=ns) or "").strip()
                summary = (entry.findtext("atom:summary", default="", namespaces=ns) or "").strip()
                link = ""
                for link_elem in entry.findall("atom:link", ns):
                    if link_elem.attrib.get("type") == "application/pdf":
                        link = link_elem.attrib.get("href", "")
                        break
                if not link:
                    link = entry.findtext("atom:id", default="", namespaces=ns) or ""
                results.append({
                    "title": re.sub(r"\s+", " ", title),
                    "snippet": re.sub(r"\s+", " ", summary)[:300],
                    "url": link,
                    "source": "arxiv",
                })
                if len(results) >= max_results:
                    break
            logger.info(f"Found {len(results)} results from arXiv")
            return results
        except Exception as e:
            logger.error(f"Error in arXiv search: {str(e)}")
            logger.debug(traceback.format_exc())
            self.circuit_breaker.record_failure("arxiv")
            return []

    async def _search_crossref(self, query: str, max_results: int = 10) -> List[Dict[str, Any]]:
        """Search Crossref works API."""
        if self.circuit_breaker.is_open("crossref"):
            return []
            
        try:
            url = f"https://api.crossref.org/works?query={quote_plus(query)}&rows={max_results}"
            logger.info(f"Searching Crossref with query: {query}")
            session = self.session
            if session is None:
                raise RuntimeError("HTTP session not initialized")
            async with session.get(url) as response:
                if response.status != 200:
                    logger.warning(f"Crossref search failed with status code: {response.status}")
                    self.circuit_breaker.record_failure("crossref")
                    return []
                data = await response.json()
            
            self.circuit_breaker.record_success("crossref")
            items = data.get("message", {}).get("items", [])
            results: List[Dict[str, Any]] = []
            for item in items:
                title_list = item.get("title") or []
                title = title_list[0] if title_list else ""
                doi = item.get("DOI") or ""
                link = item.get("URL") or (f"https://doi.org/{doi}" if doi else "")
                snippet = (item.get("container-title") or [""])[0]
                results.append({
                    "title": title,
                    "snippet": snippet,
                    "url": link,
                    "source": "crossref",
                })
                if len(results) >= max_results:
                    break
            logger.info(f"Found {len(results)} results from Crossref")
            return results
        except Exception as e:
            logger.error(f"Error in Crossref search: {str(e)}")
            logger.debug(traceback.format_exc())
            self.circuit_breaker.record_failure("crossref")
            return []

    def _get_gemini_client(self):
        """Lazy-init the google.genai Client (Vertex AI or API key mode)."""
        if self._gemini_client is not None:
            return self._gemini_client
        try:
            from google import genai
            from google.genai.types import HttpOptions

            if self._gcp_project:
                gcp_location = os.environ.get("GOOGLE_CLOUD_LOCATION", "global")
                os.environ.setdefault("GOOGLE_CLOUD_PROJECT", self._gcp_project)
                os.environ.setdefault("GOOGLE_CLOUD_LOCATION", gcp_location)
                os.environ["GOOGLE_GENAI_USE_VERTEXAI"] = "True"
                self._gemini_client = genai.Client(
                    http_options=HttpOptions(api_version="v1"),
                )
                logger.info("Google Grounded Search: using Vertex AI (project=%s)", self._gcp_project)
            elif self._gemini_api_key:
                self._gemini_client = genai.Client(
                    api_key=self._gemini_api_key,
                    http_options=HttpOptions(api_version="v1alpha"),
                )
                logger.info("Google Grounded Search: using Gemini API key (v1alpha)")
            else:
                logger.warning("Google Grounded Search: no GCP project or Gemini API key — disabled")
                return None
        except ImportError:
            logger.warning("google-genai package not installed — Google Grounded Search disabled")
            return None
        except Exception as exc:
            logger.error("Failed to init Gemini client: %s", exc)
            return None
        return self._gemini_client

    async def _search_google_grounded(self, query: str, max_results: int = 10) -> List[Dict[str, Any]]:
        """Search using Gemini with Google Search grounding.

        Returns structured results (title, snippet, url) extracted from
        the grounding metadata, plus a synthesized summary from the model.
        """
        if self.circuit_breaker.is_open("google_grounded"):
            logger.warning("Skipping Google Grounded Search (Circuit Breaker OPEN)")
            return []

        client = self._get_gemini_client()
        if client is None:
            return []

        try:
            from google.genai.types import GenerateContentConfig, GoogleSearch, Tool

            response = None
            last_exc = None
            for attempt in range(3):
                try:
                    response = await asyncio.to_thread(
                        client.models.generate_content,
                        model=self._gemini_grounding_model,
                        contents=query,
                        config=GenerateContentConfig(
                            tools=[Tool(google_search=GoogleSearch())],
                        ),
                    )
                    break
                except Exception as retry_exc:
                    last_exc = retry_exc
                    err_str = str(retry_exc)
                    if "503" in err_str or "429" in err_str or "UNAVAILABLE" in err_str:
                        await asyncio.sleep(2.0 * (2 ** attempt))
                        continue
                    raise
            if response is None:
                raise last_exc or RuntimeError("Google Grounded Search: no response after retries")

            results: List[Dict[str, Any]] = []
            seen_urls: set = set()

            candidate = response.candidates[0] if response.candidates else None
            grounding = getattr(candidate, "grounding_metadata", None) if candidate else None

            if grounding:
                chunks = getattr(grounding, "grounding_chunks", None) or []
                support = getattr(grounding, "grounding_supports", None) or []

                support_map: Dict[int, str] = {}
                for s in support:
                    text = getattr(s, "segment", None)
                    text = getattr(text, "text", "") if text else ""
                    for idx_ref in getattr(s, "grounding_chunk_indices", []):
                        if text and idx_ref not in support_map:
                            support_map[idx_ref] = text

                for i, chunk in enumerate(chunks):
                    web = getattr(chunk, "web", None)
                    if not web:
                        continue
                    url = getattr(web, "uri", "") or ""
                    title = getattr(web, "title", "") or ""
                    if not url or url in seen_urls:
                        continue
                    seen_urls.add(url)
                    snippet = support_map.get(i, "")
                    results.append({
                        "title": title,
                        "snippet": snippet,
                        "url": url,
                        "source": "google_grounded",
                    })
                    if len(results) >= max_results:
                        break

            summary_text = (response.text or "").strip()
            if summary_text and not results:
                results.append({
                    "title": "Gemini Grounded Summary",
                    "snippet": summary_text[:500],
                    "url": "",
                    "source": "google_grounded",
                })

            self.circuit_breaker.record_success("google_grounded")
            logger.info("Found %d results from Google Grounded Search", len(results))
            return results

        except Exception as exc:
            logger.error("Google Grounded Search failed: %s", exc)
            logger.debug(traceback.format_exc())
            self.circuit_breaker.record_failure("google_grounded")
            return []

    async def _request_with_retries(
        self,
        url: str,
        max_retries: int = 3,
        base_backoff: float = 1.0
    ) -> Tuple[int, str]:
        """Fetch a URL with retry/backoff for transient errors."""
        last_status = 0
        last_body = ""
        for attempt in range(max_retries):
            try:
                async with self._session.get(
                    url,
                    timeout=aiohttp.ClientTimeout(total=5),
                ) as response:
                    last_status = response.status
                    last_body = await response.text()
                    if response.status == 200:
                        return response.status, last_body
                    if response.status in (202, 429, 503, 504):
                        await asyncio.sleep(base_backoff * (2 ** attempt))
                        continue
                    return response.status, last_body
            except Exception as e:
                last_body = str(e)
                await asyncio.sleep(base_backoff * (2 ** attempt))
        return last_status, last_body

    @staticmethod
    def _html_to_markdown(soup: BeautifulSoup) -> str:
        """
        Convert BeautifulSoup object to Markdown.
        High-Tech implementation preserving structure.
        """
        if not soup:
            return ""

        # Strip structural chrome — navigation, banners, footers, cookie dialogs,
        # sidebars, and ad containers are noise for API documentation extraction.
        for tag in soup(["script", "style", "nav", "header", "aside", "footer",
                         "iframe", "noscript", "svg", "form", "dialog"]):
            tag.decompose()

        # Process headings
        for i in range(1, 7):
            for h in soup.find_all(f"h{i}"):
                text = h.get_text(strip=True)
                if text:
                    h.replace_with(f"\n\n{'#' * i} {text}\n\n")

        # Process lists
        for ul in soup.find_all("ul"):
            for li in ul.find_all("li", recursive=False):
                text = li.get_text(strip=True)
                if text:
                    li.replace_with(f"* {text}\n")
            ul.replace_with(f"\n{ul.get_text()}\n")
            
        for ol in soup.find_all("ol"):
            for i, li in enumerate(ol.find_all("li", recursive=False), 1):
                text = li.get_text(strip=True)
                if text:
                    li.replace_with(f"{i}. {text}\n")
            ol.replace_with(f"\n{ol.get_text()}\n")

        # Process links
        for a in soup.find_all("a", href=True):
            text = a.get_text(strip=True)
            href = str(a.get("href") or "")
            if text and href and not href.startswith("#"):
                a.replace_with(f"[{text}]({href})")

        # Process code blocks
        for pre in soup.find_all("pre"):
            code = pre.get_text()
            pre.replace_with(f"\n```\n{code}\n```\n")
            
        for code in soup.find_all("code"):
            # Skip if inside pre (already handled)
            if code.parent and code.parent.name == "pre":
                continue
            text = code.get_text()
            code.replace_with(f"`{text}`")

        # Process tables — preserve column headers so parameter docs are usable.
        # The previous implementation collected <th> text separately and then
        # looped over <tr> looking only for <td> children.  Header rows that
        # contain only <th> elements (the standard pattern for API parameter
        # tables: "Parameter | Type | Required | Description") produced an empty
        # cols list and were silently skipped, so the table arrived at the LLM
        # with data rows but no column names.
        for table in soup.find_all("table"):
            rows = []
            col_count = 0
            for tr in table.find_all("tr"):
                # Each cell is either <th> (header) or <td> (data)
                cells = tr.find_all(["th", "td"])
                if not cells:
                    continue
                cell_texts = [c.get_text(strip=True) for c in cells]
                col_count = max(col_count, len(cell_texts))
                # Mark header rows (all cells are <th>) with separator
                is_header = all(c.name == "th" for c in cells)
                rows.append(("header" if is_header else "data", cell_texts))

            if not rows:
                continue

            md_rows = []
            separator_added = False
            for kind, cells in rows:
                md_rows.append("| " + " | ".join(cells) + " |")
                if kind == "header" and not separator_added:
                    md_rows.append("| " + " | ".join(["---"] * len(cells)) + " |")
                    separator_added = True

            # If no explicit header row existed, add a separator after the first row
            if not separator_added and md_rows:
                md_rows.insert(1, "| " + " | ".join(["---"] * col_count) + " |")

            table.replace_with("\n" + "\n".join(md_rows) + "\n")

        # Process paragraphs and divs
        for p in soup.find_all(["p", "div", "section", "article"]):
            text = p.get_text(strip=True)
            if text:
                p.replace_with(f"\n{text}\n")

        # Final cleanup
        text = soup.get_text()
        # Collapse multiple newlines
        text = re.sub(r'\n{3,}', '\n\n', text)
        return text.strip()


    async def _extract_via_browser(self, url: str) -> str:
        """Extract content using headful browser automation for SPAs and anti-bot."""
        if not _HAS_BROWSER or BrowserConfig is None or BrowserController is None:
            logger.info("Browser not available for SPA extraction. Install: pip install jarviscore[browser]")
            return ""
        logger.info(f"Using BrowserController to extract content from: {url}")
        browser_config = BrowserConfig(
            headless=os.environ.get("BROWSER_HEADLESS", "true").lower() in ("1", "true", "yes"),
            timeout_ms=30000,
            cdp_url=os.environ.get("BROWSER_CONTROL_URL") or os.environ.get("BROWSER_SERVICE_URL"),
        )
        browser = BrowserController(browser_config)
        try:
            await browser.connect()
            res = await browser.navigate(url)
            if not res.success:
                logger.warning(f"Browser navigation failed: {res.error}")
                return ""
            
            # Wait a bit for JS to render
            await asyncio.sleep(3)
            
            script = """
            (() => {
                const selectors = [
                    'article', 'main', '.main-content', '#main-content', '.content', 
                    '[role="main"]', '.documentation', '.markdown-body'
                ];
                let mainNode = null;
                for (const sel of selectors) {
                    mainNode = document.querySelector(sel);
                    if (mainNode) break;
                }
                if (!mainNode) mainNode = document.body;
                
                // Remove nav, header, footer, scripts, styles
                const clone = mainNode.cloneNode(true);
                const toRemove = clone.querySelectorAll('nav, header, footer, script, style, aside, iframe, noscript, svg');
                toRemove.forEach(el => el.remove());
                
                return clone.innerHTML;
            })();
            """
            raw_html = await browser.session.page.evaluate(script)
            if not raw_html:
                return ""
            # Convert innerHTML through the same markdown pipeline as the primary HTTP path
            # so tables, code blocks, and headings are preserved — not flattened to plain text.
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(raw_html, "html.parser")
            return self._html_to_markdown(soup)
        except Exception as e:
            logger.error(f"Browser extraction failed: {e}")
            return ""
        finally:
            try:
                await browser.session.disconnect()
            except:
                pass

    async def extract_content(self, url: str) -> Dict[str, Any]:
        """
        Extract content from a webpage
        
        Args:
            url: The URL to extract content from
            
        Returns:
            A dictionary containing the extracted content and metadata
        """
        await self.initialize()
        
        # Ensure URL has a scheme
        if not url.startswith(('http://', 'https://')):
            url = 'https://' + url
        
        try:
            logger.info(f"Extracting content from: {url}")
            
            # Parse the URL to handle special characters
            parsed_url = urlparse(url)
            
            # Create a clean URL
            clean_url = f"{parsed_url.scheme}://{parsed_url.netloc}{parsed_url.path}"
            if parsed_url.query:
                clean_url += f"?{parsed_url.query}"
            
            # Use a more robust approach with custom headers and timeout
            headers = {
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
                "Referer": "https://www.google.com/",
                "Upgrade-Insecure-Requests": "1"
            }
            
            async with self._session.get(
                clean_url,
                headers=headers,
                allow_redirects=True,
                timeout=aiohttp.ClientTimeout(total=20),
            ) as response:
                if response.status == 200:
                    # Get response metadata
                    content_type = response.headers.get("Content-Type", "").lower()
                    
                    # IGNORE BINARY/IMAGE CONTENT
                    if any(t in content_type for t in ["image/", "audio/", "video/", "application/zip", "application/octet-stream"]):
                        logger.warning(f"Skipping binary content: {clean_url} ({content_type})")
                        return {
                            "url": clean_url,
                            "error": f"Skipped binary content type: {content_type}",
                            "error_type": "SKIPPED_BINARY",
                            "content": "",
                            "content_length": 0
                        }

                    if self._is_pdf_response(clean_url, content_type):
                        status, pdf_bytes, pdf_type = await self._fetch_bytes_with_retries(clean_url)
                        if status != 200 or not pdf_bytes:
                            return {
                                "url": clean_url,
                                "error": f"HTTP error: {status}",
                                "error_type": "TRANSIENT" if status in (429, 503) else "PERMANENT",
                                "content": "",
                                "content_length": 0,
                            }
                        text = self._extract_pdf_text(pdf_bytes)
                        if text:
                            return {
                                "url": clean_url,
                                "title": "",
                                "content": text,
                                "main_content": text,
                                "content_length": len(text),
                                "content_type": pdf_type or content_type,
                                "meta_tags": {},
                            }
                        return {
                            "url": clean_url,
                            "error": "PDF extraction failed",
                            "error_type": "PROCESSING",
                            "content": "",
                            "content_length": 0,
                        }
                    
                    html = await response.text()
                    soup = BeautifulSoup(html, 'html.parser')
                    
                    # Try to get the title
                    title = ""
                    title_elem = soup.find("title")
                    if title_elem:
                        title = title_elem.get_text(strip=True)
                    
                    # Extract meta tags
                    meta_tags = {}
                    for meta in soup.find_all("meta"):
                        name = meta.get("name", "")
                        if not name:
                            name = meta.get("property", "")
                        if name:
                            content = meta.get("content", "")
                            meta_tags[name] = content


                    # --- HIGH TECH MARKDOWN EXTRACTION ---
                    # Clone soup for markdown processing to avoid destroying original if needed for links
                    md_soup = BeautifulSoup(str(soup), 'html.parser')
                    markdown_content = self._html_to_markdown(md_soup)
                    
                    # SPA / Anti-bot fallback
                    if len(markdown_content.strip()) < 500 and "body" in markdown_content.lower():
                        logger.info(f"Content too short ({len(markdown_content)} chars), likely SPA. Falling back to browser...")
                        browser_content = await self._extract_via_browser(clean_url)
                        if browser_content and len(browser_content) > len(markdown_content):
                            markdown_content = browser_content

                    
                    # Extract links for optional traversal (same-domain crawling)
                    links: List[str] = []
                    for a in soup.find_all("a", href=True):
                        href = str(a.get("href") or "").strip()
                        if not href or href.startswith(("#", "javascript:", "mailto:")):
                            continue
                        absolute = urljoin(clean_url, href)
                        if absolute.startswith(("http://", "https://")):
                            links.append(absolute)
                    # Deduplicate and cap
                    seen_links = set()
                    deduped_links: List[str] = []
                    for link in links:
                        if link in seen_links:
                            continue
                        seen_links.add(link)
                        deduped_links.append(link)
                        if len(deduped_links) >= 200:
                            break
                    
                    logger.info(f"Successfully extracted markdown content ({len(markdown_content)} characters)")
                    
                    return {
                        "url": clean_url,
                        "title": title,
                        "content": markdown_content, # Primary content is now Markdown
                        "main_content": markdown_content,
                        "content_length": len(markdown_content),
                        "content_type": content_type,
                        "meta_tags": meta_tags,
                        "links": deduped_links,
                    }
                else:
                    logger.warning(f"Failed to fetch {clean_url}, status code: {response.status}")
                    
                    # Return structured error
                    error_type = "TRANSIENT" if response.status in (429, 503, 504) else "PERMANENT"
                    if response.status in (401, 403):
                        error_type = "AUTH_REQUIRED"
                        
                    return {
                        "url": clean_url,
                        "error": f"HTTP error: {response.status}",
                        "error_type": error_type,
                        "content": "",
                        "content_length": 0
                    }
        except aiohttp.ClientError as e:
            logger.error(f"Client error fetching {url}: {str(e)}")
            return {
                "url": url, 
                "error": str(e), 
                "error_type": "NETWORK",
                "content": "", 
                "content_length": 0
            }
        except asyncio.TimeoutError:
            logger.error(f"Timeout fetching {url}")
            return {
                "url": url,
                "error": "Timeout",
                "error_type": "TRANSIENT",
                "content": "",
                "content_length": 0,
            }
        except Exception as e:
            logger.error(f"Unexpected error fetching {url}: {str(e)}")
            logger.debug(traceback.format_exc())
            return {
                "url": url,
                "error": str(e),
                "error_type": "PROCESSING",
                "content": "",
                "content_length": 0,
            }

    async def _fetch_bytes_with_retries(
        self,
        url: str,
        max_retries: Optional[int] = None,
        timeout_seconds: Optional[int] = None,
    ) -> Tuple[int, bytes, str]:
        max_retries = max_retries if max_retries is not None else self.pdf_max_retries
        timeout_seconds = (
            timeout_seconds if timeout_seconds is not None else self.pdf_timeout_seconds
        )
        last_status = 0
        last_body = b""
        last_type = ""
        for attempt in range(max_retries):
            try:
                async with self._session.get(
                    url,
                    headers={"User-Agent": self.user_agent, "Accept": "application/pdf,*/*"},
                    allow_redirects=True,
                    timeout=aiohttp.ClientTimeout(total=timeout_seconds),
                ) as response:
                    last_status = response.status
                    last_type = response.headers.get("Content-Type", "")
                    last_body = await response.read()
                    if response.status == 200:
                        return response.status, last_body, last_type
                    if response.status in (202, 429, 503, 504):
                        await asyncio.sleep(1.0 * (2 ** attempt))
                        continue
                    return response.status, last_body, last_type
            except Exception:
                await asyncio.sleep(1.0 * (2 ** attempt))
        return last_status, last_body, last_type

    @staticmethod
    def _is_pdf_response(url: str, content_type: str) -> bool:
        if "application/pdf" in (content_type or "").lower():
            return True
        return url.lower().endswith(".pdf")

    @staticmethod
    def _extract_pdf_text(pdf_bytes: bytes) -> str:
        try:
            import pypdf  # type: ignore[import-untyped]
        except Exception:
            logger.warning("pypdf not installed; cannot extract PDF content")
            return ""
        try:
            reader = pypdf.PdfReader(BytesIO(pdf_bytes))
            pages = []
            for page in reader.pages:
                page_text = page.extract_text() or ""
                if page_text:
                    pages.append(page_text)
            return "\n\n".join(pages)
        except Exception as exc:
            logger.warning(f"PDF extraction failed: {exc}")
            return ""

    async def search_and_extract(self, query: str, result_index: int = 0, max_results: int = 10) -> Dict[str, Any]:
        """
        Search for information and extract content from specified result in one operation
        
        Args:
            query: The search query
            result_index: Which search result to extract content from (0 = first result)
            max_results: Maximum number of results to return from search
            
        Returns:
            A dictionary containing search results and extracted content
        """
        # Search for the query
        search_results = await self.search(query, max_results=max_results)

        if not search_results or len(search_results) <= result_index:
            logger.warning(f"No results found or result_index {result_index} out of range")
            return {"search_results": [], "extracted_content": None, "error": "No results found"}

        target_url = search_results[result_index].get("url", "")
        extracted: Dict[str, Any] = {}
        if target_url:
            extracted = await self.extract_content(target_url)

        return {
            "search_results": search_results,
            "extracted_content": extracted,
            "target_url": target_url,
        }
