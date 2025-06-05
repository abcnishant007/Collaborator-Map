import http.client
import json
import pickle

from geopy.geocoders import Nominatim
from scholarly import scholarly

import config

geolocator = Nominatim(user_agent="affiliation_mapper")

import requests


import requests

import requests

def get_institution_logo_brute_force(institution_name):
    import requests
    import re
    from bs4 import BeautifulSoup
    from urllib.parse import quote
    from agent import call_deepseek

    session = requests.Session()
    base_url = "https://en.wikipedia.org/w/api.php"

    def extract_image_urls_from_html(html):
        soup = BeautifulSoup(html, "html.parser")
        image_urls = set()

        # Extract og:image meta tags
        for meta in soup.find_all("meta", {"property": "og:image"}):
            content = meta.get("content")
            if content and "upload.wikimedia" in content:
                image_urls.add(content if content.startswith("http") else f"https:{content}")

        # Extract all <img> tags pointing to upload.wikimedia
        for img in soup.find_all("img"):
            src = img.get("src")
            if src and "upload.wikimedia" in src:
                image_urls.add(src if src.startswith("http") else f"https:{src}")

        # Prioritize SVGs first
        image_urls = list(image_urls)
        image_urls = [x for x in list(image_urls) if "logo" in x]
        svg_urls = [url for url in image_urls if url.lower().endswith(".svg")]
        raster_urls = [url for url in image_urls if not url.lower().endswith(".svg")]
        return svg_urls + raster_urls

    # Step 1: Get Wikipedia page title
    search_res = session.get(base_url, params={
        "action": "query",
        "list": "search",
        "srsearch": institution_name,
        "format": "json"
    }).json()
    search_results = search_res.get("query", {}).get("search", [])
    if not search_results:
        print("⚠️ No search results found for institution:", institution_name)
        return None, None

    page_title = search_results[0]["title"]
    wiki_link = f"https://en.wikipedia.org/wiki/{page_title.replace(' ', '_')}"

    # Step 2: Fetch HTML and extract images
    try:
        html = session.get(wiki_link, headers={"User-Agent": "Mozilla/5.0"}).text
    except Exception as e:
        print("⚠️ HTML fetch failed:", e)
        return None, wiki_link

    image_urls = extract_image_urls_from_html(html)

    if not image_urls:
        print("⚠️ No image URLs found in HTML.")
        return None, wiki_link

    # Step 3: Ask AI to select the best logo
    prompt = (
        "You are an assistant helping choose official university logos from Wikipedia pages.\\n\\n"
        f"Institution: {institution_name}\\n\\n"
        "Here are image URLs found in the page:\\n" +
        "\\n".join(f"{i}. {url}" for i, url in enumerate(image_urls)) +
        "\\n\\nPlease respond with the correct URL in your opinion. DO NOT MAKE YOUR own URL. "
        "CHoose the one URL which makes the most sense as the logo from the provided list. "
        "Please respond with only one line, like: "
        ""
        "Best Logo URL: <your chosen URL from the list>"



    )
    print("🧠 Prompt to AI:\\n", prompt)

    response = call_deepseek(prompt)

    # print ("AI response: ", response)
    # # match = re.search(r"Best Logo URL:\\s*(https?://\\S+)", response)
    # try:
    #     photolink = "https://" + response.split("https://")[1].split("\*\*")[0]
    #     return photolink, wiki_link
    # except:
    #     print("⚠️ AI failed to extract a valid logo URL.")
    #     if response.strip() == "-1":
    #         return None, wiki_link
    #     return None, wiki_link
    # # # if match:
    # #     return match.group(1).strip(), wiki_link
    #
    #
    # return photolink, wiki_link

    # Try robustly extracting the first valid Wikimedia URL from the AI's response
    matches = re.findall(r"https?://upload\.wikimedia\.org[^\s*]+", response)
    if matches:
        return matches[0].strip(), wiki_link

def get_institution_logo_brute_force_1(institution_name):
    import requests
    import re
    from urllib.parse import quote
    from agent import call_deepseek

    session = requests.Session()
    base_url = "https://en.wikipedia.org/w/api.php"

    def extract_image_urls_from_html(html):
        # Extract <meta property="og:image"> and Wikimedia-hosted <img src="...">
        urls = re.findall(r'<meta[^>]+property="og:image"[^>]+content="([^"]+)"', html)
        urls += re.findall(r'<img[^>]+src="([^"]+upload\\.wikimedia[^"]+)"', html)

        # Normalize protocol-relative URLs (e.g. //upload...)
        urls = [
            url if url.startswith("http") else f"https:{url}"
            for url in urls
            if "upload.wikimedia" in url
        ]

        # Prioritize vector (SVG) first, fallback to PNG/JPG
        svg_urls = [url for url in urls if url.lower().endswith(".svg")]
        raster_urls = [url for url in urls if not url.lower().endswith(".svg")]
        return svg_urls + raster_urls

    # Step 1: Get Wikipedia page title
    search_res = session.get(base_url, params={
        "action": "query",
        "list": "search",
        "srsearch": institution_name,
        "format": "json"
    }).json()
    search_results = search_res.get("query", {}).get("search", [])
    if not search_results:
        print("⚠️ No search results found for institution:", institution_name)
        return None, None

    page_title = search_results[0]["title"]
    wiki_link = f"https://en.wikipedia.org/wiki/{page_title.replace(' ', '_')}"

    # Step 2: Fetch HTML and extract images
    try:
        html = requests.get(wiki_link, headers={"User-Agent": "Mozilla/5.0"}).text
    except Exception as e:
        print("⚠️ HTML fetch failed:", e)
        return None, wiki_link

    image_urls = extract_image_urls_from_html(html)

    if not image_urls:
        print("⚠️ No image URLs found in HTML.")
        return None, wiki_link

    # Step 3: Ask AI to select the best logo
    prompt = (
        "You are an assistant helping choose official university logos from Wikipedia pages.\n\n"
        f"Institution: {institution_name}\n\n"
        "Here are image URLs found in the page:\n" +
        "\n".join(f"{i+1}. {url}" for i, url in enumerate(image_urls)) +
        "\n\nPlease respond with the best logo.\nBest Logo URL:"
    )
    print("🧠 Prompt to AI:\n", prompt)

    response = call_deepseek(prompt)
    match = re.search(r"Best Logo URL:\s*(https?://\S+)", response)
    if match:
        return match.group(1).strip(), wiki_link

    print("⚠️ AI failed to extract a valid logo URL.")
    return None, wiki_link



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

def create_map(author_affiliations):
    """
    Creates a folium map with custom markers using institution logos.
    """
    m = folium.Map(location=[20, 0], zoom_start=2)
    for item in author_affiliations:
        affiliation = item["affiliation"]
        loc = geolocate_affiliation(affiliation)
        if loc:
            logo_url = get_institution_logo_brute_force(affiliation)
            if logo_url:
                icon = folium.CustomIcon(
                    logo_url,
                    icon_size=(50, 50)
                )
                folium.Marker(
                    location=loc,
                    icon=icon,
                    popup=f"{item['name']}: {affiliation}",
                    tooltip=item['name']
                ).add_to(m)
            else:
                # Fallback to default marker if logo not found
                folium.Marker(
                    location=loc,
                    popup=f"{item['name']}: {affiliation}",
                    tooltip=item['name']
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
    print(get_institution_logo_brute_force("MIT USA"))
    print(get_institution_logo_brute_force("Tel aviv_ University"))

