"""
Internet Search — Multi-provider web search with content extraction.

Provider hierarchy (by relevance weight):
  1. Google Grounded Search via Gemini (weight 1.4) — primary when creds available
  2. Serper / Google Search API         (weight 1.2) — optional SERPER_API_KEY
  3. SearXNG self-hosted metasearch     (weight 1.1) — free, aggregates Google/Bing
  4. Wikipedia REST API                 (weight 0.6) — academic fallback

All providers run in parallel (asyncio.gather) with per-provider circuit breakers
and 6-second timeouts so a slow provider never blocks the others.

Required env vars (Gemini grounded — primary):
  GEMINI_API_KEY            or GEMINI_GROUNDING_API_KEY   (API key mode)
  GOOGLE_CLOUD_PROJECT                                     (Vertex AI mode)
  GEMINI_GROUNDING_MODEL    default: gemini-2.5-flash

Optional env vars:
  SERPER_API_KEY            Serper.dev API key (Google Search)
  SEARXNG_INSTANCE_URL      Self-hosted SearXNG URL (default: http://localhost:8080)
"""
import asyncio
import logging
import os
import re
import time
import xml.etree.ElementTree as ET
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote_plus, urlparse

import aiohttp

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Circuit Breaker
# ─────────────────────────────────────────────────────────────────────────────

class CircuitBreaker:
    """
    Per-provider circuit breaker.

    Once failure_threshold consecutive failures are recorded the breaker
    opens and all requests are rejected for recovery_timeout seconds.
    After recovery_timeout the breaker moves to HALF_OPEN; one successful
    call closes it again.
    """

    def __init__(self, failure_threshold: int = 8, recovery_timeout: int = 300):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self._failures: Dict[str, int] = {}
        self._last_failure_ts: Dict[str, float] = {}
        self._state: Dict[str, str] = {}  # OPEN | CLOSED | HALF_OPEN

    def is_open(self, service: str) -> bool:
        if self._state.get(service) == "OPEN":
            if time.time() - self._last_failure_ts.get(service, 0) > self.recovery_timeout:
                logger.info("CircuitBreaker: %s → HALF_OPEN", service)
                self._state[service] = "HALF_OPEN"
                return False
            return True
        return False

    def record_failure(self, service: str) -> None:
        count = self._failures.get(service, 0) + 1
        self._failures[service] = count
        self._last_failure_ts[service] = time.time()
        if count >= self.failure_threshold:
            logger.warning(
                "CircuitBreaker: %s → OPEN after %d failures", service, count
            )
            self._state[service] = "OPEN"

    def record_success(self, service: str) -> None:
        if self._state.get(service) in ("HALF_OPEN", "OPEN"):
            logger.info("CircuitBreaker: %s → CLOSED", service)
            self._state[service] = "CLOSED"
        self._failures[service] = 0


# ─────────────────────────────────────────────────────────────────────────────
# InternetSearch
# ─────────────────────────────────────────────────────────────────────────────

class InternetSearch:
    """
    Multi-provider internet search with content extraction.

    Primary provider: Google Grounded Search via Gemini (no-quota grounding).
    Fallbacks: Serper → SearXNG → Wikipedia.

    All providers run in parallel; results are ranked, deduped, and returned
    in score order. A provider failure never blocks other providers.

    Example:
        search = InternetSearch()
        results = await search.search("Python async programming 2025")
        content = await search.extract_content(results[0]["url"])
    """

    def __init__(self, user_agent: Optional[str] = None):
        self.session: Optional[aiohttp.ClientSession] = None
        self.user_agent = user_agent or (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        )

        # Serper (optional)
        self.serper_api_key = os.environ.get("SERPER_API_KEY")

        # Gemini grounded search
        self._gemini_client = None
        self._gcp_project = os.environ.get("GOOGLE_CLOUD_PROJECT")
        self._gemini_grounding_model = os.environ.get(
            "GEMINI_GROUNDING_MODEL", "gemini-2.5-flash"
        )
        # Dedicated grounding key wins, then general Gemini key
        self._gemini_api_key = (
            os.environ.get("GEMINI_GROUNDING_API_KEY")
            or os.environ.get("GEMINI_API_KEY")
        )

        self.circuit_breaker = CircuitBreaker()

        # SearXNG (free, self-hosted metasearch)
        self.searxng_url = os.environ.get("SEARXNG_INSTANCE_URL", "http://localhost:8080")

    # ──────────────────────────────────────────────────────────────────────
    # Session lifecycle
    # ──────────────────────────────────────────────────────────────────────

    async def initialize(self) -> None:
        """Initialize aiohttp session with SSL fallback (macOS compat)."""
        if self.session is None or self.session.closed:
            import ssl
            ssl_ctx = None
            try:
                import certifi
                ssl_ctx = ssl.create_default_context(cafile=certifi.where())
            except (ImportError, Exception):
                ssl_ctx = ssl.create_default_context()
                ssl_ctx.check_hostname = False
                ssl_ctx.verify_mode = ssl.CERT_NONE
                logger.debug("SSL: lenient context (certifi unavailable)")

            connector = aiohttp.TCPConnector(ssl=ssl_ctx)
            self.session = aiohttp.ClientSession(
                connector=connector,
                timeout=aiohttp.ClientTimeout(total=10),
                headers={
                    "User-Agent": self.user_agent,
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    "Accept-Language": "en-US,en;q=0.9",
                },
            )
            logger.debug("HTTP session initialized")

    async def close(self) -> None:
        """Close the aiohttp session."""
        if self.session and not self.session.closed:
            await self.session.close()
            self.session = None

    async def __aenter__(self):
        await self.initialize()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()
        return False

    @property
    def _session(self) -> aiohttp.ClientSession:
        assert self.session is not None, "HTTP session not initialised — call initialize() first"
        return self.session

    # ──────────────────────────────────────────────────────────────────────
    # Public API
    # ──────────────────────────────────────────────────────────────────────

    async def search(
        self,
        query: str,
        max_results: int = 10,
        exclude_providers: Optional[set] = None,
    ) -> List[Dict[str, Any]]:
        """
        Search the web using all available providers in parallel.

        Args:
            query: Natural language search query
            max_results: Max results to return (default 10)
            exclude_providers: Set of provider names to skip entirely
                e.g. {"arxiv", "wikipedia"}

        Returns:
            Ranked, deduped list of {title, snippet, url, source, score}
        """
        await self.initialize()
        skip = set(exclude_providers or ())

        provider_tasks = []

        # 1. Gemini Grounded (primary — highest weight)
        if "google_grounded" not in skip and (self._gcp_project or self._gemini_api_key):
            provider_tasks.append(
                self._search_google_grounded(query, max_results=max_results)
            )

        # 2. Serper (secondary)
        if self.serper_api_key and "serper" not in skip:
            provider_tasks.append(self._search_serper(query, max_results=max_results))

        # 3. SearXNG (free metasearch fallback)
        if "searxng" not in skip:
            provider_tasks.append(self._search_searxng(query, max_results=max_results))

        # 4. Wikipedia (academic fallback)
        if "wikipedia" not in skip:
            provider_tasks.append(self._search_wikipedia(query, max_results=max_results))

        # Run all providers in parallel — 6s timeout per provider
        provider_results = await asyncio.gather(
            *(asyncio.wait_for(t, timeout=6) for t in provider_tasks),
            return_exceptions=True,
        )

        results: List[Dict[str, Any]] = []
        for batch in provider_results:
            if isinstance(batch, Exception):
                logger.warning("Search provider failed: %s", batch)
                continue
            if isinstance(batch, list):
                results.extend(batch)

        ranked = self._rank_results(query, results)
        logger.info("Search '%s': %d results from %d providers", query, len(ranked), len(provider_tasks))
        return ranked[:max_results]

    # ──────────────────────────────────────────────────────────────────────
    # Provider: Google Grounded Search (Gemini)
    # ──────────────────────────────────────────────────────────────────────

    def _get_gemini_client(self):
        """
        Lazy-init google.genai Client.

        Auth modes (checked in order):
          1. Vertex AI — GOOGLE_CLOUD_PROJECT set → uses service account / workload identity
          2. Gemini API key — GEMINI_API_KEY or GEMINI_GROUNDING_API_KEY set

        Returns None on any failure so callers can fall through to other providers.
        """
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
                logger.info(
                    "Google Grounded Search: Vertex AI mode (project=%s)", self._gcp_project
                )
            elif self._gemini_api_key:
                self._gemini_client = genai.Client(
                    api_key=self._gemini_api_key,
                    http_options=HttpOptions(api_version="v1alpha"),
                )
                logger.info("Google Grounded Search: API key mode (v1alpha)")
            else:
                logger.warning(
                    "Google Grounded Search: no GCP project or Gemini API key — disabled"
                )
                return None
        except ImportError:
            logger.warning(
                "google-genai not installed — Gemini grounded search disabled. "
                "Install with: pip install google-genai"
            )
            return None
        except Exception as exc:
            logger.error("Failed to init Gemini client: %s", exc)
            return None
        return self._gemini_client

    async def _search_google_grounded(
        self, query: str, max_results: int = 10
    ) -> List[Dict[str, Any]]:
        """
        Search using Gemini with Google Search grounding tool.

        Returns structured results extracted from grounding metadata.
        If grounding produces no URLs but Gemini has a text answer,
        surfaces a synthesized summary as a single result.

        Circuit-breaker guarded. 3 retries on 429/503/UNAVAILABLE.
        """
        if self.circuit_breaker.is_open("google_grounded"):
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
                    # genai.Client.models.generate_content is sync — wrap in thread
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
                    if any(x in err_str for x in ("503", "429", "UNAVAILABLE")):
                        await asyncio.sleep(2.0 * (2 ** attempt))
                        continue
                    raise

            if response is None:
                raise last_exc or RuntimeError("Gemini: no response after retries")

            results: List[Dict[str, Any]] = []
            seen_urls: set = set()

            candidate = response.candidates[0] if response.candidates else None
            grounding = getattr(candidate, "grounding_metadata", None) if candidate else None

            if grounding:
                chunks = getattr(grounding, "grounding_chunks", None) or []
                support = getattr(grounding, "grounding_supports", None) or []

                # Build idx → snippet map from grounding_supports
                support_map: Dict[int, str] = {}
                for s in support:
                    seg = getattr(s, "segment", None)
                    text = getattr(seg, "text", "") if seg else ""
                    for idx in getattr(s, "grounding_chunk_indices", []):
                        if text and idx not in support_map:
                            support_map[idx] = text

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
                    results.append(
                        {"title": title, "snippet": snippet, "url": url, "source": "google_grounded"}
                    )
                    if len(results) >= max_results:
                        break

            # If grounding returned no URLs but Gemini has text, surface the summary
            summary_text = (response.text or "").strip()
            if summary_text and not results:
                results.append(
                    {
                        "title": "Gemini Grounded Summary",
                        "snippet": summary_text[:500],
                        "url": "",
                        "source": "google_grounded",
                    }
                )

            self.circuit_breaker.record_success("google_grounded")
            logger.info("Gemini grounded search: %d results", len(results))
            return results

        except Exception as exc:
            logger.error("Google Grounded Search failed: %s", exc)
            self.circuit_breaker.record_failure("google_grounded")
            return []

    # ──────────────────────────────────────────────────────────────────────
    # Provider: Serper (Google Search API)
    # ──────────────────────────────────────────────────────────────────────

    async def _search_serper(
        self, query: str, max_results: int = 10
    ) -> List[Dict[str, Any]]:
        """Search via Serper.dev API (requires SERPER_API_KEY)."""
        if not self.serper_api_key:
            return []
        if self.circuit_breaker.is_open("serper"):
            return []

        try:
            url = "https://google.serper.dev/search"
            payload = {"q": query, "num": max_results}
            headers = {
                "X-API-KEY": self.serper_api_key,
                "Content-Type": "application/json",
            }
            for attempt in range(3):
                try:
                    async with self._session.post(
                        url,
                        json=payload,
                        headers=headers,
                        timeout=aiohttp.ClientTimeout(total=5),
                    ) as response:
                        if response.status in (429, 503, 504):
                            await asyncio.sleep(1.0 * (2 ** attempt))
                            continue
                        if response.status != 200:
                            self.circuit_breaker.record_failure("serper")
                            return []
                        self.circuit_breaker.record_success("serper")
                        data = await response.json()
                        results = [
                            {
                                "title": item.get("title", ""),
                                "snippet": item.get("snippet", ""),
                                "url": item.get("link", ""),
                                "source": "serper",
                            }
                            for item in data.get("organic", [])[:max_results]
                        ]
                        logger.info("Serper: %d results", len(results))
                        return results
                except Exception as e:
                    if attempt == 2:
                        raise
                    await asyncio.sleep(1.0 * (2 ** attempt))
        except Exception as exc:
            logger.error("Serper search failed: %s", exc)
            self.circuit_breaker.record_failure("serper")
        return []

    # ──────────────────────────────────────────────────────────────────────
    # Provider: SearXNG (self-hosted metasearch)
    # ──────────────────────────────────────────────────────────────────────

    async def _search_searxng(
        self, query: str, max_results: int = 10
    ) -> List[Dict[str, Any]]:
        """Search via a self-hosted SearXNG instance (JSON API).

        SearXNG is a free, open-source metasearch engine that aggregates
        results from Google, Bing, DuckDuckGo, and dozens of other engines.
        No API key required — just a running instance.

        Requires:
            SEARXNG_INSTANCE_URL  (default: http://localhost:8080)
        """
        if self.circuit_breaker.is_open("searxng"):
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
                            results = [
                                {
                                    "title": item.get("title", ""),
                                    "snippet": item.get("content", ""),
                                    "url": item.get("url", ""),
                                    "source": "searxng",
                                    "engine": item.get("engine", ""),
                                }
                                for item in data.get("results", [])[:max_results]
                            ]
                            logger.info("SearXNG: %d results", len(results))
                            return results
                        if response.status in (429, 503, 504):
                            await asyncio.sleep(1.0 * (2 ** attempt))
                            continue
                except (aiohttp.ClientConnectionError, asyncio.TimeoutError) as e:
                    logger.warning("SearXNG connection attempt %d failed: %s", attempt + 1, e)
                    await asyncio.sleep(1.0 * (2 ** attempt))

            logger.warning("SearXNG: HTTP %d", last_status)
            self.circuit_breaker.record_failure("searxng")
        except Exception as exc:
            logger.error("SearXNG search failed: %s", exc)
            self.circuit_breaker.record_failure("searxng")
        return []

    # ──────────────────────────────────────────────────────────────────────
    # Provider: Wikipedia
    # ──────────────────────────────────────────────────────────────────────

    async def _search_wikipedia(
        self, query: str, max_results: int = 5
    ) -> List[Dict[str, Any]]:
        """Search Wikipedia via REST API."""
        if self.circuit_breaker.is_open("wikipedia"):
            return []

        try:
            url = (
                "https://en.wikipedia.org/w/api.php"
                f"?action=query&list=search&format=json&utf8=1"
                f"&srlimit={max_results}&srsearch={quote_plus(query)}"
            )
            async with self._session.get(
                url, timeout=aiohttp.ClientTimeout(total=5)
            ) as response:
                if response.status != 200:
                    self.circuit_breaker.record_failure("wikipedia")
                    return []
                self.circuit_breaker.record_success("wikipedia")
                data = await response.json()
                results = []
                for item in data.get("query", {}).get("search", []):
                    title = item.get("title", "")
                    snippet = re.sub(r"<[^>]+>", "", item.get("snippet", "") or "")
                    page_url = f"https://en.wikipedia.org/wiki/{title.replace(' ', '_')}"
                    results.append(
                        {"title": title, "snippet": snippet, "url": page_url, "source": "wikipedia"}
                    )
                logger.info("Wikipedia: %d results", len(results))
                return results
        except Exception as exc:
            logger.error("Wikipedia search failed: %s", exc)
            self.circuit_breaker.record_failure("wikipedia")
        return []

    # ──────────────────────────────────────────────────────────────────────
    # Ranking
    # ──────────────────────────────────────────────────────────────────────

    def _rank_results(
        self, query: str, results: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        Score, dedup, and rank results.

        Weights mirror CA's proven ranking:
          google_grounded=1.4  serper=1.2  searxng=1.1  wikipedia=0.6
        Plus keyword overlap bonus (0.05 per matching token) and PDF bonus (0.1).
        """
        tokens = set(re.findall(r"[a-z0-9]+", query.lower()))
        weights = {
            "google_grounded": 1.4,
            "serper": 1.2,
            "searxng": 1.1,
            "wikipedia": 0.6,
        }

        deduped: Dict[str, Dict[str, Any]] = {}
        for result in results:
            url = (result.get("url") or "").strip()
            if url and not url.startswith(("http://", "https://")):
                url = "https://" + url
            result["url"] = url

            key = self._normalize_url(url) or url or result.get("title", "")
            text = f"{result.get('title', '')} {result.get('snippet', '')}".lower()
            overlap = sum(1 for t in tokens if t in text)
            pdf_bonus = 0.1 if url.lower().endswith(".pdf") else 0.0
            base = weights.get(result.get("source") or "", 0.5)
            score = base + (overlap * 0.05) + pdf_bonus
            result["score"] = round(score, 4)

            if key not in deduped or score > deduped[key].get("score", 0):
                deduped[key] = result

        return sorted(deduped.values(), key=lambda r: r.get("score", 0), reverse=True)

    @staticmethod
    def _normalize_url(url: str) -> str:
        """Normalize URL for deduplication (strip scheme, trailing slash)."""
        try:
            parsed = urlparse(url)
            if not parsed.netloc:
                return ""
            return f"{parsed.netloc}{parsed.path}".rstrip("/")
        except Exception:
            return ""

    # ──────────────────────────────────────────────────────────────────────
    # Content extraction (unchanged — keep working)
    # ──────────────────────────────────────────────────────────────────────

    async def extract_content(
        self, url: str, max_length: int = 10000
    ) -> Dict[str, Any]:
        """
        Extract clean text content from a webpage.

        Returns:
            {"url", "title", "content", "success", "word_count"}
            or {"url", "success": False, "error": "..."}
        """
        await self.initialize()

        if not url.startswith(("http://", "https://")):
            url = "https://" + url

        logger.info("Extracting content from: %s", url)

        try:
            async with self._session.get(
                url, timeout=aiohttp.ClientTimeout(total=15)
            ) as response:
                if response.status != 200:
                    return {"url": url, "success": False, "error": f"HTTP {response.status}"}

                html = await response.text()
                # Lazy import (issue #63/JC-004): bs4 is a web-scraping dep —
                # importing the LLM client must not require it.
                from bs4 import BeautifulSoup
                soup = BeautifulSoup(html, "html.parser")

                title = soup.title.string if soup.title else urlparse(url).netloc

                for element in soup(["script", "style", "nav", "footer", "header", "aside"]):
                    element.decompose()

                main_content = (
                    soup.find("main")
                    or soup.find("article")
                    or soup.find("div", class_=re.compile(r"content|main|article", re.I))
                    or soup.body
                )

                text = main_content.get_text(separator="\n", strip=True) if main_content else ""
                lines = [line.strip() for line in text.split("\n") if line.strip()]
                clean_text = "\n".join(lines)

                if len(clean_text) > max_length:
                    clean_text = clean_text[:max_length] + "... [truncated]"

                word_count = len(clean_text.split())
                logger.info("Extracted %d words from %s", word_count, url)

                return {
                    "url": url,
                    "title": (title.strip() if title else ""),
                    "content": clean_text,
                    "success": True,
                    "word_count": word_count,
                }

        except Exception as e:
            logger.error("Content extraction failed for %s: %s", url, e)
            return {"url": url, "success": False, "error": str(e)}

    async def search_and_extract(
        self,
        query: str,
        num_results: int = 3,
        max_content_length: int = 5000,
    ) -> List[Dict[str, Any]]:
        """
        Search and automatically extract content from top results.

        Returns merged search metadata + extracted content for each result.
        """
        search_results = await self.search(query, max_results=num_results)
        extracted = []
        for result in search_results:
            if not result.get("url"):
                continue
            content = await self.extract_content(result["url"], max_content_length)
            if content.get("success"):
                extracted.append({**result, **content})
        logger.info("Extracted %d/%d results", len(extracted), len(search_results))
        return extracted


def create_search_client() -> InternetSearch:
    """Factory function to create a search client."""
    return InternetSearch()
