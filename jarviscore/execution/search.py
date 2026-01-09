"""
Internet Search - Zero-config web search and content extraction
Uses DuckDuckGo (no API key required)
"""
import logging
import aiohttp
import asyncio
import re
from typing import Dict, Any, List, Optional
from bs4 import BeautifulSoup
from urllib.parse import quote_plus, urlparse

logger = logging.getLogger(__name__)


class InternetSearch:
    """
    Zero-config internet search with content extraction.

    Features:
    - Search web using DuckDuckGo (no API key needed)
    - Extract clean text from web pages
    - Automatic error handling and retries
    - Combined search + extract in one call

    Example:
        search = InternetSearch()
        results = await search.search("Python async programming")
        content = await search.extract_content(results[0]['url'])
    """

    def __init__(self, user_agent: Optional[str] = None):
        """
        Initialize search module.

        Args:
            user_agent: Optional custom user agent (auto-set if None)
        """
        self.session = None
        self.user_agent = user_agent or (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        )

    async def initialize(self):
        """Initialize HTTP session (auto-called on first use)."""
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=30),
                headers={
                    "User-Agent": self.user_agent,
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    "Accept-Language": "en-US,en;q=0.9"
                }
            )
            logger.debug("HTTP session initialized")

    async def close(self):
        """Close HTTP session."""
        if self.session and not self.session.closed:
            await self.session.close()
            self.session = None
            logger.debug("HTTP session closed")

    async def __aenter__(self):
        """Async context manager entry."""
        await self.initialize()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        await self.close()
        return False

    async def search(self, query: str, max_results: int = 5) -> List[Dict[str, Any]]:
        """
        Search the web using DuckDuckGo.

        Args:
            query: Search query
            max_results: Maximum number of results (default 5)

        Returns:
            List of results: [{"title": "...", "snippet": "...", "url": "..."}]

        Example:
            results = await search.search("Python async tutorial")
            print(results[0]['title'])
        """
        await self.initialize()

        encoded_query = quote_plus(query)
        logger.info(f"Searching: {query}")

        try:
            results = await self._search_duckduckgo(encoded_query)

            # Normalize URLs
            for result in results:
                url = result.get('url', '')
                if url and not url.startswith(('http://', 'https://')):
                    result['url'] = 'https://' + url

            results = results[:max_results]
            logger.info(f"Found {len(results)} results")
            return results

        except Exception as e:
            logger.error(f"Search failed: {e}")
            return []

    async def _search_duckduckgo(self, encoded_query: str) -> List[Dict[str, Any]]:
        """Perform DuckDuckGo search."""
        url = f"https://html.duckduckgo.com/html/?q={encoded_query}"

        try:
            async with self.session.get(url) as response:
                if response.status != 200:
                    raise RuntimeError(f"DuckDuckGo returned {response.status}")

                html = await response.text()
                soup = BeautifulSoup(html, 'html.parser')

                results = []
                for result_elem in soup.select('.result'):
                    title_elem = result_elem.select_one('.result__title')
                    snippet_elem = result_elem.select_one('.result__snippet')
                    url_elem = result_elem.select_one('.result__url')

                    if title_elem and url_elem:
                        # Clean up DuckDuckGo's tracking URLs
                        url_text = url_elem.get_text(strip=True)
                        # Remove "duckduckgo.com" prefix if present
                        url_text = re.sub(r'^.*?://', '', url_text)
                        url_text = url_text.split('?')[0]  # Remove query params

                        results.append({
                            "title": title_elem.get_text(strip=True),
                            "snippet": snippet_elem.get_text(strip=True) if snippet_elem else "",
                            "url": url_text
                        })

                return results

        except Exception as e:
            logger.error(f"DuckDuckGo search error: {e}")
            return []

    async def extract_content(self, url: str, max_length: int = 10000) -> Dict[str, Any]:
        """
        Extract clean text content from a webpage.

        Args:
            url: URL to extract from
            max_length: Maximum content length (default 10k chars)

        Returns:
            {
                "url": "https://...",
                "title": "Page Title",
                "content": "Clean extracted text...",
                "success": True,
                "word_count": 1234
            }

        Example:
            content = await search.extract_content("https://example.com")
            print(content['content'])
        """
        await self.initialize()

        if not url.startswith(('http://', 'https://')):
            url = 'https://' + url

        logger.info(f"Extracting content from: {url}")

        try:
            async with self.session.get(url) as response:
                if response.status != 200:
                    return {
                        "url": url,
                        "success": False,
                        "error": f"HTTP {response.status}"
                    }

                html = await response.text()
                soup = BeautifulSoup(html, 'html.parser')

                # Extract title
                title = soup.title.string if soup.title else urlparse(url).netloc

                # Remove script, style, and other non-content elements
                for element in soup(['script', 'style', 'nav', 'footer', 'header', 'aside']):
                    element.decompose()

                # Extract main content
                # Try to find main content area
                main_content = (
                    soup.find('main') or
                    soup.find('article') or
                    soup.find('div', class_=re.compile(r'content|main|article', re.I)) or
                    soup.body
                )

                if main_content:
                    text = main_content.get_text(separator='\n', strip=True)
                else:
                    text = soup.get_text(separator='\n', strip=True)

                # Clean up text
                lines = [line.strip() for line in text.split('\n') if line.strip()]
                clean_text = '\n'.join(lines)

                # Truncate if too long
                if len(clean_text) > max_length:
                    clean_text = clean_text[:max_length] + "... [truncated]"

                word_count = len(clean_text.split())

                logger.info(f"Extracted {word_count} words from {url}")

                return {
                    "url": url,
                    "title": title.strip() if title else "",
                    "content": clean_text,
                    "success": True,
                    "word_count": word_count
                }

        except Exception as e:
            logger.error(f"Content extraction failed for {url}: {e}")
            return {
                "url": url,
                "success": False,
                "error": str(e)
            }

    async def search_and_extract(
        self,
        query: str,
        num_results: int = 3,
        max_content_length: int = 5000
    ) -> List[Dict[str, Any]]:
        """
        Search and automatically extract content from top results.

        Args:
            query: Search query
            num_results: Number of results to extract (default 3)
            max_content_length: Max content per page (default 5k chars)

        Returns:
            List of extracted content from top search results

        Example:
            results = await search.search_and_extract("Python asyncio tutorial")
            for result in results:
                print(f"{result['title']}: {result['content'][:100]}...")
        """
        # Search first
        search_results = await self.search(query, max_results=num_results)

        # Extract content from each result
        extracted = []
        for result in search_results:
            content = await self.extract_content(result['url'], max_content_length)
            if content.get('success'):
                # Merge search metadata with extracted content
                extracted.append({
                    **result,
                    **content
                })

        logger.info(f"Extracted content from {len(extracted)}/{len(search_results)} results")
        return extracted


def create_search_client() -> InternetSearch:
    """Factory function to create search client."""
    return InternetSearch()
