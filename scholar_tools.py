import http.client
import json
import pickle

from geopy.geocoders import Nominatim
from scholarly import scholarly

import config

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

import requests
from slugify import slugify
from pathlib import Path
import subprocess
# from your_module import get_institution_logo_brute_force  # replace with actual import

API_KEY = config.PYTHONANWYWHERE_API_KEY
BASE_URL = "https://lifezbeautiful.pythonanywhere.com"
HEADERS = {"X-API-Key": API_KEY}
TMP_DIR = Path("tmp_logos")
TMP_DIR.mkdir(exist_ok=True)

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




CACHE_FILE = "institution_cache.pkl"

def load_cache():
    if os.path.exists(CACHE_FILE):
        with open(CACHE_FILE, "rb") as f:
            return pickle.load(f)
    return {}

def save_cache(cache):
    with open(CACHE_FILE, "wb") as f:
        pickle.dump(cache, f, protocol=config.PICKLE_PROTOCOL)



def search_affiliation_snippets(name, field_hint="computer science"):
    SERPER_API_KEY = config.SERPER_API_KEY
    query = f"{name} {field_hint} affiliation"
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
        for result in results.get("organic", [])[:3]:
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



import folium
import os
import time

import os
import time
import folium

from PIL import Image
from io import BytesIO
import base64
import folium

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
    Creates a folium map with custom markers using institution logos.
    Returns the folium.Map object.
    """
    m = folium.Map(location=[20, 0], zoom_start=2)

    for item in author_affiliations:
        affiliation = item["affiliation"]
        loc = geolocate_affiliation(affiliation)

        if loc:
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
                except Exception as e:
                    print(f"⚠️ Failed to render logo for {affiliation}: {e}")
                    # fallback marker
                    folium.Marker(
                        location=loc,
                        popup=f"{item['author']}: {affiliation}",
                        tooltip=item['author']
                    ).add_to(m)
            else:
                # fallback marker
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

