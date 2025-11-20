#!/usr/bin/env python3
"""
Web scraper with iframe support, site navigation, and markdown conversion.
Handles complex sites with embedded content.
"""

import os
import re
import time
import hashlib
from pathlib import Path
from urllib.parse import urljoin, urlparse, urlunparse, parse_qs
from typing import Set, Dict, List, Optional, Tuple

from playwright.sync_api import sync_playwright, Page, TimeoutError as PlaywrightTimeout
from bs4 import BeautifulSoup
import html2text
import requests

MIN_PAGE_TEXT_LENGTH = 200
MIN_IMPORTANT_PAGE_TEXT_LENGTH = 50
MIN_TITLE_LENGTH = 3
MIN_NAV_LINKS_THRESHOLD = 3
MIN_GALLERY_HEADING_LENGTH = 5
MIN_CONTENT_HEADING_LENGTH = 3
MIN_IFRAME_TEXT_LENGTH = 200
MAX_CONTENT_HEADING_LENGTH = 100
MAX_FILENAME_LENGTH = 100
MAX_ELEMENT_TEXT_LENGTH = 200
LOW_PRIORITY_THRESHOLD = 0.8
MAX_QUERY_DISPLAY_LENGTH = 40
MAX_IMAGES_TO_DOWNLOAD = 50
DEFAULT_MAX_PAGES = 100
DELAY = 1.0
PAGE_LOAD_TIMEOUT = 10000
MAIN_RESOURCE_TIMEOUT = 30000
REQUEST_TIMEOUT = 30
CHUNK_SIZE = 8192
MARKDOWN_HEADER_SPLIT = 2
MARKDOWN_HEADER_LINES = 2

class WebScraper:
    """Scrapes websites and converts them to markdown format."""
    
    def __init__(self, base_url: str, output_dir: str, max_pages: int = DEFAULT_MAX_PAGES, 
                 delay: float = DELAY, download_images: bool = False):
        """
        Initialize the web scraper.
        
        Args:
            base_url: Starting URL to scrape
            output_dir: Directory to save markdown files
            max_pages: Maximum number of pages to scrape
            delay: Delay between requests in seconds
            download_images: Whether to download images
        """
        self.base_url = base_url
        self.output_dir = Path(output_dir)
        self.max_pages = max_pages
        self.delay = delay
        self.download_images = download_images
        
        # Track visited URLs to avoid duplicates
        self.visited_urls: Set[str] = set()
        self.downloaded_files: Dict[str, str] = {}
        self.saved_pages: Dict[str, str] = {}  # Map content hash to filename
        self.url_title_map: Dict[str, str] = {}  # Dynamic mapping from URL patterns to page titles
        
        # Parse base domain
        parsed = urlparse(base_url)
        self.base_domain = parsed.netloc
        self.base_scheme = parsed.scheme
        
        # Setup HTML to Markdown converter
        self.h2t = html2text.HTML2Text()
        self.h2t.ignore_links = False
        self.h2t.ignore_images = False
        self.h2t.body_width = 0  # Don't wrap text
        
        # Create output directory
        self.output_dir.mkdir(parents=True, exist_ok=True)
    
    def normalize_url(self, url: str) -> str:
        """Normalize URL by removing fragments and standardizing format."""
        parsed = urlparse(url)
        normalized = urlunparse((
            parsed.scheme,
            parsed.netloc,
            parsed.path.rstrip('/') if parsed.path != '/' else '/',
            parsed.params,
            parsed.query,
            ''  # Remove fragment
        ))
        return normalized
    
    def extract_url_from_javascript(self, js_link: str, context_url: str) -> Optional[str]:
        """Extract actual URL from JavaScript link like javascript:LinkTo('url','')"""
        if not js_link.startswith('javascript:'):
            return None
        
        # Match LinkTo('url','') pattern
        match = re.search(r"LinkTo\(['\"]([^'\"]+)['\"]", js_link)
        if match:
            relative_url = match.group(1)
            return urljoin(context_url, relative_url)
        
        return None
    
    def build_url_title_map_from_nav(self, html_content: str, base_url: str):
        """Extract navigation structure from page to build URL-to-title mapping."""
        soup = BeautifulSoup(html_content, 'html.parser')
        
        # Look for navigation menus
        nav_selectors = [
            'nav', 'ul.nav', 'ul.menu', 'ul.navigation',
            'div.nav', 'div.menu', 'div.navigation',
            'ul.list-group', '[class*="nav"]', '[class*="menu"]',
            'div[id*="nav"]', 'div[id*="menu"]'
        ]
        
        for selector in nav_selectors:
            nav_elements = soup.select(selector)
            for nav in nav_elements:
                links = nav.find_all('a', href=True)
                for link in links:
                    href = link['href']
                    title = link.get_text(strip=True)
                    
                    if not title or len(title) < MIN_TITLE_LENGTH:
                        continue
                    
                    if title.lower() in ['menu', 'log on', 'login', 'sign in', 'sign up', 'register']:
                        continue
                    
                    # Extract URL from JavaScript if needed
                    js_url = self.extract_url_from_javascript(href, base_url)
                    full_url = js_url if js_url else urljoin(base_url, href)
                    
                    # Store mapping using URL pattern
                    parsed = urlparse(full_url)
                    if parsed.query:
                        query_params = parse_qs(parsed.query)
                        if 'Menu_Item_ID' in query_params:
                            menu_id = query_params['Menu_Item_ID'][0]
                            self.url_title_map[f"Menu_Item_ID={menu_id}"] = title
                            print(f"  Mapped: {title} -> ...Menu_Item_ID={menu_id}")
                        else:
                            self.url_title_map[parsed.query] = title
                            print(f"  Mapped: {title} -> ...{parsed.query[:MAX_QUERY_DISPLAY_LENGTH]}")
    
    def is_low_priority_url(self, url: str) -> bool:
        """Check if URL is low priority (help pages, etc.)"""
        low_priority_patterns = ['/help.aspx', '/Help.aspx', 'help.aspx?ID=']
        return any(pattern in url for pattern in low_priority_patterns)
    
    def is_junk_page(self, url: str, html_content: str) -> bool:
        """Check if page is junk (404, login helpers, templates, etc.)"""
        if 'FormLoginHelp.aspx' in url or 'FormDetail.aspx?Form_ID=5184' in url:
            return True
        
        if 'Server Error' in html_content and '404' in html_content:
            return True
        
        if 'The resource cannot be found' in html_content:
            return True
        
        soup = BeautifulSoup(html_content, 'html.parser')
        text = soup.get_text(strip=True)
        
        # Check for Google loading errors
        google_loading_indicators = [
            "JavaScript isn't enabled in your browser",
            "Enable and reload",
            "Some slides didn't load",
            "This could take a few moments"
        ]
        
        has_loading_error = any(indicator in text for indicator in google_loading_indicators)
        has_google_ui = any(ui in text for ui in ['Open speaker notes', 'Turn on the laser pointer', 
                                                    'Enter full screen', 'Exit slideshow'])
        
        if has_loading_error and has_google_ui:
            return True
        
        # Don't filter out important pages
        important_patterns = ['/faq', '/resources/', '/about', '/guide', '/help']
        if any(pattern in url.lower() for pattern in important_patterns):
            if len(text) < MIN_IMPORTANT_PAGE_TEXT_LENGTH:
                return True
            return False
        
        if len(text) < MIN_PAGE_TEXT_LENGTH:
            return True
        
        return False
    
    def extract_page_title(self, html_content: str, url: str) -> Optional[str]:
        """Extract meaningful page title from HTML content using dynamic mapping."""
        soup = BeautifulSoup(html_content, 'html.parser')
        
        # Check dynamic URL mapping first
        parsed = urlparse(url)
        if parsed.query:
            query_params = parse_qs(parsed.query)
            
            if 'Menu_Item_ID' in query_params:
                menu_id = query_params['Menu_Item_ID'][0]
                lookup_key = f"Menu_Item_ID={menu_id}"
                if lookup_key in self.url_title_map:
                    title = self.url_title_map[lookup_key]
                elif parsed.query in self.url_title_map:
                    title = self.url_title_map[parsed.query]
                else:
                    title = None
            elif parsed.query in self.url_title_map:
                title = self.url_title_map[parsed.query]
            else:
                title = None
            
            if title:
                # For galleries, try to get specific event name
                if 'Gallery' in title or 'Photo' in title or 'Video' in title:
                    for tag in ['h3', 'h4']:
                        headings = soup.find_all(tag)
                        for heading in headings:
                            text = heading.get_text(strip=True)
                            if text and len(text) > MIN_GALLERY_HEADING_LENGTH and '(' in text and ')' in text:
                                return f"{title} - {text}"
                
                return title
        
        # Fallback: Try to find page title from content headings
        for tag in ['h1', 'h2', 'h3']:
            headings = soup.find_all(tag)
            for heading in headings:
                text = heading.get_text(strip=True)
                skip_patterns = ['menu', 'log on', 'format this site', 'slide show settings',
                                'useful links', 'sign up', 'upcoming events', 'recent events',
                                'welcome to', 'copyright']
                if text and len(text) > MIN_CONTENT_HEADING_LENGTH and len(text) < MAX_CONTENT_HEADING_LENGTH:
                    if not any(skip in text.lower() for skip in skip_patterns):
                        return text
        
        # Last resort: title tag
        title_tag = soup.find('title')
        if title_tag and title_tag.string:
            title = title_tag.string.strip()
            title = re.sub(r'\s*[-|]\s*.*$', '', title)
            if title and len(title) > MIN_TITLE_LENGTH:
                return title
        
        return None
    
    def sanitize_filename(self, title: str) -> str:
        """Convert title to safe filename."""
        safe = re.sub(r'[^\w\s\-.]', '', title)
        safe = re.sub(r'\s+', ' ', safe)
        safe = safe.strip()[:MAX_FILENAME_LENGTH]
        return safe
    
    def is_same_domain(self, url: str) -> bool:
        """Check if URL belongs to the same domain."""
        parsed = urlparse(url)
        return parsed.netloc == self.base_domain or parsed.netloc == ''
    
    def get_safe_filename(self, url: str) -> str:
        """Convert URL to safe filename."""
        parsed = urlparse(url)
        path = parsed.path.strip('/')
        
        if not path or path == '':
            filename = 'index'
        else:
            filename = re.sub(r'[^\w\-.]', '_', path.replace('/', '_'))
        
        if parsed.query:
            query_safe = re.sub(r'[^\w\-.]', '_', parsed.query)[:50]
            filename += f'_{query_safe}'
        
        return filename
    
    def extract_content_from_iframe(self, page: Page) -> Tuple[str, List[str], List[str]]:
        """Extract content from page, including iframes. Returns (html, links, images)."""
        content_parts = []
        links = []
        images = []
        
        try:
            page.wait_for_load_state('networkidle', timeout=PAGE_LOAD_TIMEOUT)
        except PlaywrightTimeout:
            print(f"  Warning: Page load timeout, proceeding anyway...")
        
        # Get main page content
        main_html = page.content()
        soup = BeautifulSoup(main_html, 'html.parser')
        
        # Extract links from main page
        for link in soup.find_all('a', href=True):
            href = link['href']
            js_url = self.extract_url_from_javascript(href, page.url)
            if js_url:
                if self.is_same_domain(js_url):
                    links.append(self.normalize_url(js_url))
            else:
                full_url = urljoin(page.url, href)
                if self.is_same_domain(full_url):
                    links.append(self.normalize_url(full_url))
        
        # Extract images from main page
        for img in soup.find_all('img', src=True):
            img_url = urljoin(page.url, img['src'])
            if img_url not in images:
                images.append(img_url)
        
        # Check for iframes
        iframes = page.frames
        print(f"  Found {len(iframes)} frame(s) on page")
        
        for idx, frame in enumerate(iframes):
            try:
                frame_html = frame.content()
                frame_soup = BeautifulSoup(frame_html, 'html.parser')
                
                # Extract links from iframe
                for link in frame_soup.find_all('a', href=True):
                    href = link['href']
                    js_url = self.extract_url_from_javascript(href, frame.url)
                    if js_url:
                        if self.is_same_domain(js_url):
                            links.append(self.normalize_url(js_url))
                    else:
                        full_url = urljoin(frame.url, href)
                        if self.is_same_domain(full_url):
                            links.append(self.normalize_url(full_url))
                
                # Extract images from iframe
                for img in frame_soup.find_all('img', src=True):
                    img_url = urljoin(frame.url, img['src'])
                    if img_url not in images:
                        images.append(img_url)
                
                # Add frame content
                if idx > 0:
                    content_parts.append(f"\n<!-- Content from frame {idx}: {frame.url} -->\n")
                    content_parts.append(frame_html)
            except Exception as e:
                print(f"  Warning: Could not extract frame {idx}: {e}")
        
        # Use iframe content if meaningful
        if content_parts:
            combined_iframe_content = '\n'.join(content_parts)
            iframe_soup = BeautifulSoup(combined_iframe_content, 'html.parser')
            iframe_text = iframe_soup.get_text(strip=True)
            if len(iframe_text) > MIN_IFRAME_TEXT_LENGTH:
                final_html = combined_iframe_content
            else:
                print(f"  Note: Iframe content too short ({len(iframe_text)} chars), using main page")
                final_html = main_html
        else:
            final_html = main_html
        
        return final_html, links, images
    
    def html_to_markdown(self, html: str, page_url: str) -> str:
        """Convert HTML to Markdown, stripping boilerplate."""
        soup = BeautifulSoup(html, 'html.parser')
        
        # Remove common boilerplate elements
        for element in soup(['script', 'style', 'nav', 'footer', 'header']):
            element.decompose()
        
        # Remove elements containing boilerplate text patterns
        boilerplate_text_patterns = [
            'log on', 'user id', 'password', 'keep me logged',
            'forgot user id', 'forgot password', 'cancel',
            'format this site', 'laptop / desktop', 'smart phone / mobile',
            'user guide', 'mobile app tutorials', 'newsletter',
            'about this site', 'copyright', 'web host services',
            'the url for this page', 'open reports as pdf',
            'bookmark this site'
        ]
        
        for elem in soup.find_all(['div', 'form', 'table', 'ul', 'li', 'p']):
            elem_text = elem.get_text().lower().strip()
            if any(pattern in elem_text for pattern in boilerplate_text_patterns):
                if len(elem_text) < MAX_ELEMENT_TEXT_LENGTH:
                    elem.decompose()
        
        # Remove navigation menus
        for table in soup.find_all('table'):
            links = table.find_all('a', href=lambda x: x and 'javascript' in str(x).lower())
            if len(links) > MIN_NAV_LINKS_THRESHOLD:
                table.decompose()
        
        # Remove login/auth forms
        for form in soup.find_all(['form', 'div'], class_=lambda x: x and any(
            term in str(x).lower() for term in ['login', 'signin', 'auth', 'logon']
        )):
            form.decompose()
        
        # Remove dialogs, modals, overlays
        for elem in soup.find_all(['div'], class_=lambda x: x and any(
            term in str(x).lower() for term in ['modal', 'dialog', 'overlay', 'popup']
        )):
            elem.decompose()
        
        # Remove elements with common boilerplate IDs/classes
        boilerplate_selectors = [
            'div.sidebar', 'div.menu', 'aside', 
            '[class*="copyright"]', '[class*="footer"]',
            '[class*="settings"]', '[class*="tools"]',
            '[id*="sidebar"]', '[id*="menu"]',
        ]
        for selector in boilerplate_selectors:
            for elem in soup.select(selector):
                elem.decompose()
        
        # Try to find main content area
        main_content = None
        main_selectors = [
            'main', 'article', '[role="main"]',
            'div.content', 'div.main-content', 'div.page-content',
            '[class*="main-content"]', '[id*="content"]'
        ]
        
        for selector in main_selectors:
            main_content = soup.select_one(selector)
            if main_content:
                soup = BeautifulSoup(str(main_content), 'html.parser')
                break
        
        # Convert to markdown
        markdown = self.h2t.handle(str(soup))
        
        # Post-process markdown
        lines = markdown.split('\n')
        cleaned_lines = []
        
        for line in lines:
            line_lower = line.lower().strip()
            
            if any(pattern in line_lower for pattern in boilerplate_text_patterns):
                continue
            
            if line.strip().startswith('---') and '|' in line:
                continue
            
            if 'javascript:' in line_lower and any(word in line_lower for word in ['menu', 'toggle', 'linkto']):
                continue
            
            cleaned_lines.append(line)
        
        markdown = '\n'.join(cleaned_lines)
        
        # Clean up excessive blank lines
        while '\n\n\n' in markdown:
            markdown = markdown.replace('\n\n\n', '\n\n')
        
        header = f"# Source: {page_url}\n\n"
        return header + markdown.strip()
    
    def detect_google_embeds(self, page: Page) -> List[str]:
        """Detect Google Docs/Slides/Sheets embeds and return their URLs."""
        google_embeds = []
        for frame in page.frames:
            if 'docs.google.com' in frame.url or 'drive.google.com' in frame.url:
                google_embeds.append(frame.url)
        return google_embeds
    
    def download_embedded_resource(self, url: str) -> str:
        """Download embedded resources (PDFs, docs, etc.)."""
        if url in self.downloaded_files:
            return self.downloaded_files[url]
        
        try:
            parsed = urlparse(url)
            filename = os.path.basename(parsed.path) or 'resource'
            
            resources_dir = self.output_dir / 'resources'
            resources_dir.mkdir(exist_ok=True)
            
            filepath = resources_dir / filename
            
            response = requests.get(url, timeout=REQUEST_TIMEOUT, stream=True)
            response.raise_for_status()
            
            with open(filepath, 'wb') as f:
                for chunk in response.iter_content(chunk_size=CHUNK_SIZE):
                    f.write(chunk)
            
            self.downloaded_files[url] = str(filepath)
            print(f"  Downloaded resource: {filename}")
            return str(filepath)
            
        except Exception as e:
            print(f"  Warning: Could not download {url}: {e}")
            return url
    
    def scrape_page(self, page: Page, url: str) -> Tuple[List[str], List[str]]:
        """Scrape a single page. Returns (high_priority_urls, low_priority_urls)."""
        if url in self.visited_urls:
            return [], []
        
        if len(self.visited_urls) >= self.max_pages:
            print(f"Reached max pages limit ({self.max_pages})")
            return [], []
        
        self.visited_urls.add(url)
        is_low_priority = self.is_low_priority_url(url)
        priority_marker = " [low priority]" if is_low_priority else ""
        print(f"\n[{len(self.visited_urls)}/{self.max_pages}] Scraping: {url}{priority_marker}")
        
        try:
            page.goto(url, wait_until='domcontentloaded', timeout=MAIN_RESOURCE_TIMEOUT)
            
            google_embeds = self.detect_google_embeds(page)
            if google_embeds:
                print(f"  Note: Found {len(google_embeds)} Google embed(s)")
            
            html_content, links, images = self.extract_content_from_iframe(page)
            
            # Build URL-to-title mapping on first page
            if len(self.visited_urls) == 1 and not self.url_title_map:
                print(f"\n  Building site navigation map...")
                self.build_url_title_map_from_nav(html_content, page.url)
                print(f"  Found {len(self.url_title_map)} pages in navigation\n")
            
            is_junk = self.is_junk_page(url, html_content)
            
            if is_junk and google_embeds:
                print(f"  Note: Page appears empty but has Google embeds - saving note")
                embed_notes = []
                for embed_url in google_embeds:
                    if 'presentation' in embed_url:
                        embed_notes.append(f"- [View Google Slides Presentation]({embed_url})")
                    elif 'spreadsheets' in embed_url:
                        embed_notes.append(f"- [View Google Sheets Document]({embed_url})")
                    elif 'document' in embed_url:
                        embed_notes.append(f"- [View Google Docs Document]({embed_url})")
                    else:
                        embed_notes.append(f"- [View Google Document]({embed_url})")
                
                markdown = f"# Source: {url}\n\n"
                markdown += "**Note:** This page contains embedded Google documents that cannot be automatically scraped.\n\n"
                markdown += "**Embedded Documents:**\n" + '\n'.join(embed_notes)
            elif is_junk:
                print(f"  Skipped: Junk/template page")
                return [], []
            else:
                markdown = self.html_to_markdown(html_content, url)
                
                if google_embeds:
                    embed_notes = []
                    for embed_url in google_embeds:
                        if 'presentation' in embed_url:
                            embed_notes.append(f"- [View Google Slides Presentation]({embed_url})")
                        elif 'spreadsheets' in embed_url:
                            embed_notes.append(f"- [View Google Sheets Document]({embed_url})")
                        elif 'document' in embed_url:
                            embed_notes.append(f"- [View Google Docs Document]({embed_url})")
                        else:
                            embed_notes.append(f"- [View Google Document]({embed_url})")
                    
                    lines = markdown.split('\n', MARKDOWN_HEADER_SPLIT)
                    if len(lines) >= MARKDOWN_HEADER_SPLIT:
                        embed_note = "\n**Note:** This page contains embedded Google documents:\n" + '\n'.join(embed_notes) + "\n"
                        markdown = lines[0] + '\n' + embed_note + '\n' + '\n'.join(lines[1:])
            
            # Check for duplicate content
            markdown_lines = markdown.split('\n')
            if markdown_lines and markdown_lines[0].startswith('# Source:'):
                content_for_hash = '\n'.join(markdown_lines[MARKDOWN_HEADER_LINES:])
            else:
                content_for_hash = markdown
            
            content_hash = hashlib.md5(content_for_hash.strip().encode()).hexdigest()
            if content_hash in self.saved_pages:
                print(f"  Skipped: Duplicate of {self.saved_pages[content_hash]}")
                return [], []
            
            # Extract page title for readable filename
            page_title = self.extract_page_title(html_content, url)
            
            is_home_page = self.normalize_url(url) == self.normalize_url(self.base_url)
            
            if is_home_page and not page_title:
                filename = "Home"
            elif is_home_page and page_title:
                generic_patterns = [self.base_domain, 'troop', 'welcome']
                is_generic = any(pattern.lower() in page_title.lower() for pattern in generic_patterns)
                
                parsed = urlparse(url)
                has_nav_title = False
                if parsed.query:
                    query_params = parse_qs(parsed.query)
                    if 'Menu_Item_ID' in query_params:
                        menu_id = query_params['Menu_Item_ID'][0]
                        has_nav_title = f"Menu_Item_ID={menu_id}" in self.url_title_map
                
                if has_nav_title:
                    filename = self.sanitize_filename(page_title)
                else:
                    filename = "Home"
            elif page_title:
                filename = self.sanitize_filename(page_title)
            else:
                filename = self.get_safe_filename(url)
            
            # Ensure unique filename
            md_path = self.output_dir / f"{filename}.md"
            counter = 1
            while md_path.exists():
                md_path = self.output_dir / f"{filename} ({counter}).md"
                counter += 1
            
            md_path.write_text(markdown, encoding='utf-8')
            self.saved_pages[content_hash] = md_path.name
            print(f"  Saved: {md_path.name}")
            
            # Download images if enabled
            if self.download_images and images and not is_low_priority:
                print(f"  Downloading {len(images)} images...")
                for img_url in images[:MAX_IMAGES_TO_DOWNLOAD]:
                    try:
                        self.download_embedded_resource(img_url)
                    except Exception as e:
                        print(f"    Warning: Could not download image: {e}")
            elif images and not is_low_priority:
                print(f"  Found {len(images)} images (skipping download)")
            
            # Separate high and low priority URLs
            high_priority = []
            low_priority = []
            
            for link in links:
                if link not in self.visited_urls:
                    if self.is_low_priority_url(link):
                        low_priority.append(link)
                    else:
                        high_priority.append(link)
            
            print(f"  Found {len(high_priority)} high-priority, {len(low_priority)} low-priority links")
            
            time.sleep(self.delay)
            
            return high_priority, low_priority
            
        except Exception as e:
            print(f"  Error scraping {url}: {e}")
            return [], []
    
    def scrape_site(self):
        """Scrape entire site starting from base URL."""
        print(f"Starting scrape of {self.base_url}")
        print(f"Output directory: {self.output_dir}")
        print(f"Max pages: {self.max_pages}, Delay: {self.delay}s\n")
        
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(
                user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
            )
            page = context.new_page()
            
            high_priority_urls = [self.normalize_url(self.base_url)]
            low_priority_urls = []
            
            while len(self.visited_urls) < self.max_pages:
                if high_priority_urls:
                    url = high_priority_urls.pop(0)
                elif low_priority_urls and len(self.visited_urls) < self.max_pages * LOW_PRIORITY_THRESHOLD:
                    url = low_priority_urls.pop(0)
                elif low_priority_urls:
                    print(f"\nSkipping {len(low_priority_urls)} low-priority URLs to focus on main content")
                    break
                else:
                    break
                
                high_pri, low_pri = self.scrape_page(page, url)
                high_priority_urls.extend(high_pri)
                low_priority_urls.extend(low_pri)
            
            browser.close()
        
        print(f"\n✓ Scraping complete!")
        print(f"  Pages scraped: {len(self.visited_urls)}")
        print(f"  Resources downloaded: {len(self.downloaded_files)}")
        print(f"  Output directory: {self.output_dir}")

