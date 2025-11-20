"""Basic tests for scrape2md."""

import pytest
from scrape2md import WebScraper
from scrape2md.scraper import MAX_FILENAME_LENGTH

LONG_TITLE_LENGTH = 200

def test_normalize_url():
    """Test URL normalization."""
    scraper = WebScraper("https://example.com", "test_output")
    
    # Remove fragment
    assert scraper.normalize_url("https://example.com/page#section") == "https://example.com/page"
    
    # Trailing slash handling
    assert scraper.normalize_url("https://example.com/page/") == "https://example.com/page"
    
    # Keep root slash
    assert scraper.normalize_url("https://example.com/") == "https://example.com/"


def test_sanitize_filename():
    """Test filename sanitization."""
    scraper = WebScraper("https://example.com", "test_output")
    
    # Remove special characters
    assert scraper.sanitize_filename("Hello, World!") == "Hello World"
    
    # Handle multiple spaces
    assert scraper.sanitize_filename("Too   Many   Spaces") == "Too Many Spaces"
    
    # Length limiting
    long_title = "A" * LONG_TITLE_LENGTH
    assert len(scraper.sanitize_filename(long_title)) <= MAX_FILENAME_LENGTH


def test_is_same_domain():
    """Test domain checking."""
    scraper = WebScraper("https://example.com", "test_output")
    
    # Same domain
    assert scraper.is_same_domain("https://example.com/page")
    
    # Different domain
    assert not scraper.is_same_domain("https://other.com/page")
    
    # Relative URL (empty netloc)
    assert scraper.is_same_domain("/relative/path")


def test_extract_url_from_javascript():
    """Test JavaScript URL extraction."""
    scraper = WebScraper("https://example.com", "test_output")
    
    # Valid JavaScript link
    js_link = "javascript:LinkTo('page.html','')"
    result = scraper.extract_url_from_javascript(js_link, "https://example.com/")
    assert result == "https://example.com/page.html"
    
    # Non-JavaScript link
    assert scraper.extract_url_from_javascript("https://example.com", "https://example.com/") is None
    
    # Invalid JavaScript pattern
    assert scraper.extract_url_from_javascript("javascript:alert('hi')", "https://example.com/") is None


def test_is_low_priority_url():
    """Test low priority URL detection."""
    scraper = WebScraper("https://example.com", "test_output")
    
    # Help pages should be low priority
    assert scraper.is_low_priority_url("https://example.com/help.aspx")
    assert scraper.is_low_priority_url("https://example.com/Help.aspx?ID=123")
    
    # Regular pages should not be low priority
    assert not scraper.is_low_priority_url("https://example.com/about.html")


def test_version():
    """Test that version is defined."""
    from scrape2md import __version__
    assert __version__ == "0.1.0"

