import requests
from bs4 import BeautifulSoup
import time
import random
import json
from urllib.parse import urljoin
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from playwright.sync_api import sync_playwright

# Initial pages
pages = [
    {"url": "https://creations.mattel.com/collections/hot-wheels-collectors", "region": "us"},
    {"url": "https://creations.mattel.com/collections/matchbox-collectors", "region": "us"},
    {"url": "https://creations.mattel.com/collections/mattel-creations", "region": "us"},
    {"url": "https://uk.creations.mattel.com/collections/hot-wheels-collectors", "region": "uk"},
    {"url": "https://de.creations.mattel.com/collections/hot-wheels-collectors", "region": "de"}
]

# Non-diecast items to skip (case-insensitive)
non_diecast = [
    "snapback cap", "t-shirt", "hoodie", "jersey", "socks",
    "pin set", "mug", "bag", "beanie", "backpack", "sweatshirt", "hat",
    "shirt", "raglan"
]

# Headers to mimic a browser
headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36"
}

# Set up session with retries
session = requests.Session()
retries = Retry(total=3, backoff_factor=1, status_forcelist=[429, 500, 502, 503, 504])
session.mount("https://", HTTPAdapter(max_retries=retries))


def get_soup(url):
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        try:
            page.goto(url)
            page.wait_for_selector("article.collection-grid__product", timeout=10000)
            html = page.content()
            return BeautifulSoup(html, "html.parser")
        except Exception as e:
            print(f"Error fetching {url}: {e}")
            return None
        finally:
            browser.close()


def get_pagination_urls(soup, base_url):
    """Extract pagination URLs from the page."""
    pagination_urls = [base_url]  # Include the initial page
    if not soup:
        return pagination_urls

    pagination = soup.find("ol", class_="collection-grid__pagination")
    if pagination:
        links = pagination.find_all("a", class_="collection-grid__pagination-btn")
        for link in links:
            href = link.get("href")
            if href:
                full_url = urljoin(base_url, href)
                if full_url not in pagination_urls:
                    pagination_urls.append(full_url)

    return pagination_urls


def categorize_product(name, is_matchbox):
    """Determine the category of a product based on its name."""
    name_lower = name.lower()

    # Skip non-diecast items
    if any(item.lower() in name_lower for item in non_diecast):
        return None

    # Matchbox collection
    if is_matchbox:
        return "Matchbox"

    # Specific keyword-based categories
    if "rlc" in name_lower:
        return "RLC"
    if "elite 64" in name_lower:
        return "Elite 64"
    if any(keyword in name_lower for keyword in ["hot wheels boulevard", "hot wheels premium", "car culture",
                                                 "premium collector set", "premium series"]):
        return "Premium"
    if "mattel brick shop" in name_lower:
        return "Brick Shop"
    if "hot wheels x" in name_lower:
        return "Mattel Creations"

    # Default to Others for non-excluded items
    return "Others"


def scrape_page(url, region, is_matchbox=False, is_mattel_creations=False):
    """Scrape product URLs and names from a single page."""
    soup = get_soup(url)
    if not soup:
        return []

    products = []
    articles = soup.find_all("article", class_="collection-grid__product")
    for article in articles:
        # Get product name
        name_tag = article.find("h2", class_="collection-grid__product-name")
        if not name_tag:
            continue
        name = name_tag.get_text(strip=True)

        # For mattel-creations, only include items with "Hot Wheels"
        if is_mattel_creations and "hot wheels" not in name.lower():
            continue

        # Categorize product
        category = categorize_product(name, is_matchbox)
        if not category:  # Skip non-diecast items
            continue

        # SKIP OTHERS
        if category == "Others":
            continue

        # Get product URL
        link_tag = article.find("a", class_="pi__link")
        if not link_tag or not link_tag.get("href"):
            continue
        product_url = urljoin(url, link_tag.get("href"))

        products.append({"name": name, "url": product_url, "category": category, "region": region})

    return products


def scrape_collection(base_url, region, is_matchbox=False, is_mattel_creations=False):
    """Scrape all pages in a collection."""
    soup = get_soup(base_url)
    if not soup:
        return []

    # Get all pagination URLs
    pagination_urls = get_pagination_urls(soup, base_url)

    all_products = []
    for page_url in pagination_urls:
        print(f"Scraping {page_url}")
        products = scrape_page(page_url, region, is_matchbox, is_mattel_creations)
        all_products.extend(products)
        time.sleep(random.uniform(1, 3))  # Random delay between requests

    return all_products


def main():
    # Collect all products
    all_products = []
    for page in pages:
        is_matchbox = "matchbox-collectors" in page["url"]
        is_mattel_creations = "mattel-creations" in page["url"] and "uk" not in page["url"] and "de" not in page["url"]
        products = scrape_collection(page["url"], page["region"], is_matchbox, is_mattel_creations)
        all_products.extend(products)

    # Organize products by region and category
    output = {"us": [], "uk": [], "de": []}
    for region in output:
        # Get products for this region
        region_products = [p for p in all_products if p["region"] == region]

        # Group by category, ensuring unique URLs
        categories = {}
        for product in region_products:
            category = product["category"]
            if category not in categories:
                categories[category] = set()  # Use set to store unique URLs
            categories[category].add(product["url"])

        # Format output
        for category, urls in categories.items():
            output[region].append({"name": category, "urls": sorted(list(urls))})  # Convert set to sorted list

        # Sort categories alphabetically
        output[region].sort(key=lambda x: x["name"])

    # Remove empty regions
    output = {k: v for k, v in output.items() if v}

    # Print JSON output
    print(json.dumps(output, indent=2))

    # Save to file
    with open("urls.json", "w") as f:
        json.dump(output, f, indent=2)


if __name__ == "__main__":
    main()
