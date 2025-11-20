# scrape2md 🕷️ → 📝

[![PyPI version](https://badge.fury.io/py/scrape2md.svg)](https://pypi.org/project/scrape2md/)
[![CodeQL](https://github.com/taralika/scrape2md/actions/workflows/github-code-scanning/codeql/badge.svg)](https://github.com/taralika/scrape2md/actions/workflows/github-code-scanning/codeql)
[![Python versions](https://img.shields.io/pypi/pyversions/scrape2md.svg)](https://pypi.org/project/scrape2md/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Downloads](https://static.pepy.tech/badge/scrape2md)](https://pepy.tech/project/scrape2md)
[![GitHub stars](https://img.shields.io/github/stars/taralika/scrape2md.svg?style=social&label=Star)](https://github.com/taralika/scrape2md)

**Scrape entire websites and convert to clean markdown** — perfect for LLM training data, RAG systems, and AI applications. Handles iframes, JavaScript navigation, and complex site structures.

## Why Markdown?

Markdown is the **ideal format for working with LLMs**:
- ✅ Clean, structured text for training language models
- ✅ Perfect for RAG (Retrieval-Augmented Generation) pipelines
- ✅ Easy to process, chunk, and embed for vector databases
- ✅ Human-readable and Git-friendly for documentation

## Features

- 🕷️ **Full site crawling** with automatic link discovery
- 🖼️ **Iframe support** for embedded content
- 🧹 **Smart cleanup** removes navigation, boilerplate, and duplicates
- 📝 **Clean markdown** output with readable filenames
- 🚀 **Headless browser** powered by Playwright (handles JavaScript)

## Installation

```bash
pip install scrape2md
playwright install chromium  # One-time browser setup
```

## Quick Start

**CLI:**
```bash
scrape2md https://example.com
scrape2md https://site.com -o docs -m 50 -d 2.0
```

**Python:**
```python
from scrape2md import WebScraper

scraper = WebScraper("https://example.com", "output", max_pages=50)
scraper.scrape_site()
```

## Options

```bash
scrape2md <url> [options]

  -o, --output DIR      Output directory (default: scraped_sites)
  -m, --max-pages N     Max pages to scrape (default: 100)
  -d, --delay SECONDS   Delay between requests (default: 1.0)
  --download-images     Download images (off by default)
```

## How It Works

1. Discovers site structure from navigation menus
2. Crawls pages breadth-first with Playwright (handles JavaScript)
3. Extracts content from iframes and dynamic elements
4. Strips boilerplate (nav, footer, ads, login forms)
5. Converts to clean markdown with smart filenames
6. Detects and skips duplicate content

## Output

```
scraped_sites/
└── example_com/
    ├── Home.md
    ├── About Us.md
    ├── Documentation.md
    └── ...
```

## Limitations

- Requires Chromium browser (installed via Playwright)
- Doesn't handle login-protected content
- Google Docs embeds are linked but not downloaded
- Default limit: 100 pages per site (configurable)

## Development

```bash
git clone https://github.com/taralika/scrape2md.git
cd scrape2md
pip install -e .[dev]  # Install with dev dependencies
playwright install chromium  # One-time browser setup
pytest  # Run tests
black .  # Format code
ruff check .  # Lint code
mypy src/  # Type checking
```

## Contributing

Pull requests welcome! Please open an issue first to discuss major changes.

## License

MIT License - see [LICENSE](LICENSE) file for details

## Author

Anand Taralika - [GitHub](https://github.com/taralika)

## Changelog

**0.1.0** (2025-11-19) — Initial release
