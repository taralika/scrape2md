"""Basic tests for scrape2md."""

import os
import tempfile
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


def test_webscraper_initialization():
    """Test WebScraper initialization with various parameters."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Test basic initialization
        scraper = WebScraper("https://example.com", tmpdir)
        assert scraper.base_url == "https://example.com"
        assert str(scraper.output_dir) == tmpdir
        assert scraper.download_images is False
        
        # Test with custom parameters
        scraper_custom = WebScraper(
            "https://test.org",
            tmpdir,
            max_pages=50,
            delay=2.0,
            download_images=True
        )
        assert scraper_custom.base_url == "https://test.org"
        assert str(scraper_custom.output_dir) == tmpdir
        assert scraper_custom.max_pages == 50
        assert scraper_custom.delay == 2.0
        assert scraper_custom.download_images is True


def test_scrape_integration():
    """Integration test: Scrape a test HTML file and verify markdown output."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Use local HTML fixture for predictable, reliable testing
        test_file = os.path.join(os.path.dirname(__file__), "fixtures", "test_page.html")
        file_url = f"file://{test_file}"
        
        scraper = WebScraper(
            file_url,
            tmpdir,
            max_pages=1,
            delay=0.1,
            download_images=False
        )
        
        # Should complete without raising exceptions
        try:
            scraper.scrape_site()
        except Exception as e:
            pytest.fail(f"Scraper raised unexpected exception: {e}")
        
        # Find created markdown files
        md_files = []
        for root, _, files in os.walk(tmpdir):
            md_files.extend([os.path.join(root, f) for f in files if f.endswith('.md')])
        
        # Should have created at least one markdown file
        assert len(md_files) > 0, "No markdown files were created"
        
        # Read the main markdown file
        main_file = md_files[0]
        with open(main_file, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Verify meaningful content was scraped (not just header)
        assert len(content) > 200, "Content is too short - scraping may have failed"
        
        # Verify markdown structure elements from our test HTML
        assert "# Main Article Title" in content or "#Main Article Title" in content, "Missing main heading"
        assert "**bold text**" in content or "bold text" in content, "Missing bold formatting"
        assert "*italic text*" in content or "_italic text_" in content, "Missing italic formatting"
        
        # Verify list items were converted
        assert "First item" in content, "Missing list content"
        assert "Second item" in content, "Missing list content"
        
        # Verify links were preserved
        assert "example.com" in content or "[" in content, "Links not preserved"
        
        # Verify section headings
        assert "Section with List" in content, "Missing section heading"
        assert "Section with Table" in content, "Missing section heading"
        
        # Verify nested content
        assert "Subsection Title" in content, "Missing subsection"
        
        # Basic structure checks
        assert content.count('#') >= 3, "Should have multiple heading levels"

