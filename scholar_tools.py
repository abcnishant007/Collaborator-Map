import http.client
import json
import pickle
import config
from slugify import slugify
from pathlib import Path
import subprocess
import requests
from geopy.geocoders import Nominatim
from scholarly import scholarly
from PIL import Image
from io import BytesIO
import base64
import config
import folium
import os
import time
import os
from typing import Optional, Dict, List
from config import HUMAN_IN_LOOP

BASE_URL = "https://lifezbeautiful.pythonanywhere.com"
HEADERS = {"X-API-Key": config.PYTHONANWYWHERE_API_KEY}
TMP_DIR = Path("tmp_logos")
TMP_DIR.mkdir(exist_ok=True)
CACHE_FILE = "institution_cache.pkl"
geolocator = Nominatim(user_agent="affiliation_mapper")

def get_or_fetch_logo(institution_name):
    slug = slugify(institution_name)
    remote_filename = f"{slug}.png"

    # Step 1: Try fetching from server
    try:
        print(f"🌐 Checking cache for {remote_filename}")
        r = requests.get(f"{BASE_URL}/logo/{remote_filename}", headers=HEADERS)
        if r.status_code == 200:
            print(f"✅ Fetched cached logo: {remote_filename}")
            return f"{BASE_URL}/logo/{remote_filename}", r.content
        else:
            print(f"❌ Cache miss: {r.status_code}")
    except Exception as e:
        print(f"⚠️ Error checking logo cache: {e}")

    # Step 2: Use brute-force fallback
    logo_url, image_bytes = get_institution_logo_brute_force(institution_name)
    if not logo_url or not image_bytes:
        print("❌ Brute-force method failed.")
        return None, None

    # Step 3: Upload to server
    try:
        print(f"📤 Uploading {remote_filename} to logo API")
        files = {"file": (remote_filename, image_bytes, "image/png")}
        data = {"name": remote_filename}
        upload_res = requests.post(f"{BASE_URL}/upload", headers=HEADERS, files=files, data=data)
        if upload_res.ok:
            print("✅ Uploaded logo to cache.")
        else:
            print(f"⚠️ Upload failed: {upload_res.status_code}, {upload_res.text}")
    except Exception as e:
        print(f"❌ Error uploading to logo API: {e}")

    return logo_url, image_bytes

def get_institution_logo_brute_force(institution_name):
    import requests
    import re
    from bs4 import BeautifulSoup
    from agent import call_deepseek

    session = requests.Session()
    base_url = "https://en.wikipedia.org/w/api.php"

    def extract_image_urls_from_html(html):
        soup = BeautifulSoup(html, "html.parser")
        image_urls = set()
        for meta in soup.find_all("meta", {"property": "og:image"}):
            content = meta.get("content")
            if content and "upload.wikimedia" in content:
                image_urls.add(content if content.startswith("http") else f"https:{content}")
        for img in soup.find_all("img"):
            src = img.get("src")
            if src and "upload.wikimedia" in src:
                image_urls.add(src if src.startswith("http") else f"https:{src}")
        image_urls = [x for x in image_urls if "logo" in x]
        svg_urls = [url for url in image_urls if url.lower().endswith(".svg")]
        raster_urls = [url for url in image_urls if not url.lower().endswith(".svg")]
        return svg_urls + raster_urls

    search_res = session.get(base_url, params={
        "action": "query",
        "list": "search",
        "srsearch": institution_name,
        "format": "json"
    }).json()
    search_results = search_res.get("query", {}).get("search", [])
    if not search_results:
        return None, None

    page_title = search_results[0]["title"]
    wiki_link = f"https://en.wikipedia.org/wiki/{page_title.replace(' ', '_')}"

    try:
        html = session.get(wiki_link, headers={"User-Agent": "Mozilla/5.0"}).text
    except Exception as e:
        print("⚠️ HTML fetch failed:", e)
        return None, None

    image_urls = extract_image_urls_from_html(html)
    if not image_urls:
        return None, None

    prompt = (
        "You are an assistant helping choose official university logos from Wikipedia pages.\n\n"
        f"Institution: {institution_name}\n\n"
        "Here are image URLs found in the page:\n" +
        "\n".join(f"{i}. {url}" for i, url in enumerate(image_urls)) +
        "\n\nPlease respond with the correct URL in your opinion. DO NOT MAKE YOUR own URL. "
        "Choose the one URL which makes the most sense as the logo from the provided list. "
        "Please respond with only one line, like: Best Logo URL: <your chosen URL from the list>"
    )

    response = call_deepseek(prompt)
    matches = re.findall(r"https?://upload\.wikimedia\.org[^\s*]+", response)
    if not matches:
        return None, None

    logo_url = matches[0].strip()

    try:
        img_res = requests.get(logo_url, headers={"User-Agent": "Mozilla/5.0"})
        if img_res.status_code == 200:
            return logo_url, img_res.content
        else:
            return logo_url, None
    except Exception as e:
        print(f"⚠️ Failed to download selected logo: {e}")
        return logo_url, None

def download_with_curl(url, output_path):
    try:
        subprocess.run([
            "curl", "-L", "-A", "Mozilla/5.0", url, "--output", str(output_path)
        ], check=True)
        return output_path.exists() and output_path.stat().st_size > 0
    except subprocess.CalledProcessError as e:
        print(f"❌ curl failed: {e}")
        return False

def get_institution_logo_and_link_no_AI(institution_name):
    session = requests.Session()
    base_url = "https://en.wikipedia.org/w/api.php"

    # Step 1: Search for the correct page title
    search_res = session.get(base_url, params={
        "action": "query",
        "list": "search",
        "srsearch": institution_name,
        "format": "json"
    }).json()
    search_results = search_res.get("query", {}).get("search", [])
    if not search_results:
        return None, None

    page_title = search_results[0]["title"]
    wiki_link = f"https://en.wikipedia.org/wiki/{page_title.replace(' ', '_')}"

    # Step 2: Try primary image
    image_res = session.get(base_url, params={
        "action": "query",
        "format": "json",
        "titles": page_title,
        "prop": "pageimages",
        "piprop": "original"
    }).json()
    pages = image_res.get("query", {}).get("pages", {})
    for page in pages.values():
        original = page.get("original", {})
        if "source" in original:
            return original["source"], wiki_link

    # Step 3: Fallback - fetch all images
    fallback_res = session.get(base_url, params={
        "action": "query",
        "format": "json",
        "prop": "images",
        "titles": page_title
    }).json()
    pages = fallback_res.get("query", {}).get("pages", {})
    for page in pages.values():
        image_list = page.get("images", [])
        if not image_list:
            return None, wiki_link

        # Sort into vectors and rasters
        svg_files = [img["title"] for img in image_list if img["title"].lower().endswith(".svg")]
        raster_files = [img["title"] for img in image_list if img["title"].lower().endswith((".png", ".jpg", ".jpeg"))]

        preferred = svg_files + raster_files  # Prioritize SVG

        for file_title in preferred:
            info_res = session.get(base_url, params={
                "action": "query",
                "format": "json",
                "titles": file_title,
                "prop": "imageinfo",
                "iiprop": "url"
            }).json()
            for fpage in info_res.get("query", {}).get("pages", {}).values():
                imageinfo = fpage.get("imageinfo", [{}])[0]
                image_url = imageinfo.get("url")
                if image_url:
                    return image_url, wiki_link

    return None, wiki_link

def validate_and_get_papers(user_id):
    try:
        try:
            author = scholarly.search_author_id(user_id)
        except AttributeError:
            author = next(scholarly.search_author(user_id))

        author = scholarly.fill(author, sections=["publications"])
        papers = []
        for pub in author.get("publications", [])[:5]:
            filled_pub = scholarly.fill(pub)
            papers.append({
                "title": filled_pub["bib"]["title"],
                "authors": filled_pub["bib"].get("author", "").split(" and ")
            })

        return papers, author.get("name"), author.get("email_domain"), None
    except Exception as e:
        return None, None, None, f"Error fetching profile: {e}"

def get_unique_coauthors(papers, owner_name=None):
    authors = set()
    for paper in papers:
        for author in paper["authors"]:
            if author != owner_name:
                authors.add(author)
    return list(authors)

def load_cache():
    if os.path.exists(CACHE_FILE):
        with open(CACHE_FILE, "rb") as f:
            return pickle.load(f)
    return {}

def save_cache(cache):
    with open(CACHE_FILE, "wb") as f:
        pickle.dump(cache, f, protocol=config.PICKLE_PROTOCOL)

def find_scholar_profile(name: str, paper_title: str = None) -> str | None:
    query = f'"{name}" site:scholar.google.com'
    if paper_title:
        query += f' "{paper_title}"'

    url = "https://www.googleapis.com/customsearch/v1"
    params = {
        'key': config.API_FOR_GOOGLE_CUSTOM_SEARCH,
        'cx': config.CX_FOR_GOOGLE_CUSTOM_SEARCH,
        'q': query,
        'num': 3
    }

    try:
        response = requests.get(url, params=params)
        response.raise_for_status()
        data = response.json()

        for item in data.get("items", []):
            link = item.get("link", "")
            if "scholar.google.com/citations?user=" in link:
                return link  # first profile found

    except Exception as e:
        print(f"❌ Error searching for scholar profile of {name}: {e}")

    return None

from playwright.sync_api import sync_playwright

def extract_verified_email(profile_url: str) -> str | None:
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(profile_url, timeout=15000)

            # Wait for the profile section to load
            page.wait_for_selector(".gsc_prf_il", timeout=8000)

            # Extract all lines with that class
            elements = page.query_selector_all(".gsc_prf_il")

            for el in elements:
                text = el.inner_text()
                if "Verified email at" in text:
                    parts = text.split(" at ")
                    if len(parts) == 2:
                        domain = parts[1].strip().lower()
                        browser.close()
                        return domain  # e.g. "mit.edu"

            browser.close()
    except Exception as e:
        print(f"❌ Failed to extract email domain from profile: {e}")

    return None

def fallback_custom_search(name, field_hint=" ", authored_paper=None):
    snippets = search_affiliation_snippets_using_serper(name, field_hint, authored_paper)
    links = [f"https://www.google.com/search?q={name}+{field_hint}"] * len(snippets)
    return list(zip(snippets, links))

def map_domain_to_affiliation(domain: str, db_path="world_universities_and_domains.json") -> str | None:
    import json

    ensure_university_json_exists(db_path)

    try:
        with open(db_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        for entry in data:
            if domain in entry.get("domains", []):
                return entry.get("name")

    except Exception as e:
        print(f"❌ Error looking up domain {domain}: {e}")

    return None


def strip_to_base_domain(domain):
    parts = domain.lower().split(".")
    if len(parts) >= 2:
        return ".".join(parts[-2:])
    return domain

def ensure_university_json_exists(db_path="world_universities_and_domains.json"):
    if not os.path.exists(db_path):
        print(f"🌐 Downloading university domain JSON to {db_path} ...")
        url = "https://raw.githubusercontent.com/Hipo/university-domains-list/master/world_universities_and_domains.json"
        try:
            subprocess.run(["curl", "-L", url, "--output", db_path], check=True)
            print("✅ Download complete.")
        except Exception as e:
            print(f"❌ Failed to download JSON: {e}")

def search_affiliation_snippets(name: str, paper_title: Optional[str] = None, field_hint: Optional[str] = None) -> Dict:
    result = {
        "verified_domain": None,
        "affiliation": None,
        "source": None,
        "profile_url": None,
        "snippets": [],
        "links": []
    }

    # Step 1: Try finding the scholar profile
    profile_url = find_scholar_profile(name, paper_title)
    if profile_url:
        result["profile_url"] = profile_url
        domain = extract_verified_email(profile_url)
        if domain:
            result["verified_domain"] = domain
            # base_domain = strip_to_base_domain(domain)
            base_domain = domain.replace(" - homepage","") # strip_to_base_domain(domain)
            affiliation = map_domain_to_affiliation(base_domain)
            if affiliation:
                result["affiliation"] = affiliation
                result["source"] = "Google Scholar"
                return result  # 🎯 SUCCESS

    # Step 2: Fallback to custom search snippets
    snippets_with_links = fallback_custom_search(name, field_hint, paper_title)
    if snippets_with_links:
        result["snippets"] = [s for s, l in snippets_with_links]
        result["links"] = [l for s, l in snippets_with_links]
        result["source"] = "Custom Search"

    # Step 3: Optional — Human-in-the-loop or AI decision point
    if HUMAN_IN_LOOP:
        print("\n🧠 Manual review suggested:")
        print("Snippets:", result["snippets"])
        print("Links:", result["links"])
        print("Enter true affiliation manually or approve later.\n")

    return result

def search_affiliation_snippets_using_serper(name, field_hint = " ", authored_paper=None):
    SERPER_API_KEY = config.SERPER_API_KEY
    query = f"Latest current institutional Affiliation of Dr {name} "
    conn = http.client.HTTPSConnection("google.serper.dev")
    payload = json.dumps({"q": query})
    headers = {
        'X-API-KEY': SERPER_API_KEY,
        'Content-Type': 'application/json'
    }

    try:
        conn.request("POST", "/search", payload, headers)
        res = conn.getresponse()
        data = res.read().decode("utf-8")
        results = json.loads(data)
        snippets = []
        for result in results.get("organic", [])[:5]:
            snippet = result.get("snippet")
            if snippet:
                snippets.append(snippet)
        return snippets
    except Exception as e:
        print(f"Search error for {name}: {e}")
        return []

def geolocate_affiliation(affiliation):
    try:
        location = geolocator.geocode(affiliation)
        if location:
            return (location.latitude, location.longitude)
    except:
        return None
    return None

def get_icon_with_aspect_ratio(image_bytes, target_height=50):
    """
    Takes raw image bytes and returns a folium.CustomIcon object
    scaled to the target height while preserving aspect ratio.
    """
    image = Image.open(BytesIO(image_bytes))
    width, height = image.size
    aspect_ratio = width / height
    new_width = int(target_height * aspect_ratio)

    # Re-encode the image as PNG in memory
    buffer = BytesIO()
    image.convert("RGBA").save(buffer, format="PNG")
    encoded = base64.b64encode(buffer.getvalue()).decode()
    data_url = f"data:image/png;base64,{encoded}"

    return folium.CustomIcon(
        icon_image=data_url,
        icon_size=(new_width, target_height)
    )

def create_map(author_affiliations):
    """
    Creates a folium map with custom markers using institution logos if enabled.
    Returns the folium.Map object.
    """
    m = folium.Map(location=[20, 0], zoom_start=2)

    for item in author_affiliations:
        affiliation = item["affiliation"]
        loc = geolocate_affiliation(affiliation)

        if not loc:
            continue

        if config.DISPLAY_LOGO:
            logo_url, logo_bytes = get_or_fetch_logo(affiliation)  # expects tuple return

            if logo_bytes:
                try:
                    icon = get_icon_with_aspect_ratio(logo_bytes)
                    folium.Marker(
                        location=loc,
                        icon=icon,
                        popup=f"{item['author']}: {affiliation}",
                        tooltip=item['author']
                    ).add_to(m)
                    continue  # Skip fallback marker if logo used
                except Exception as e:
                    print(f"⚠️ Failed to render logo for {affiliation}: {e}")

        # Fallback marker or when DISPLAY_LOGO is False
        folium.Marker(
            location=loc,
            popup=f"{item['author']}: {affiliation}",
            tooltip=item['author']
        ).add_to(m)

        time.sleep(1)

    os.makedirs("output", exist_ok=True)
    return m

if __name__ == "__main__":
    # print (get_institution_logo_and_link_no_AI("MIT USA"))
    # print (get_institution_logo_and_link_no_AI("Tel aviv_ University"))
    # print ("=========================================================")
    # print(get_institution_logo_and_link_AI("MIT USA"))
    # print(get_institution_logo_and_link_AI("Tel aviv_ University"))
    print ("=========================================================")
    # print(get_institution_logo_brute_force("MIT USA"))
    # print(get_institution_logo_brute_force("Tel aviv_ University"))
    # print ("=========================================================")
    print (get_or_fetch_logo("TEl aviv_ University"))

    # url = find_scholar_profile("Rounaq Basu", "Automated mobility-on-demand vs. mass transit")
    # print("Scholar profile:", url)

    profile_url = "https://scholar.google.com/citations?user=AiujSOkAAAAJ"
    domain = extract_verified_email(profile_url)
    print("Verified domain:", domain)

