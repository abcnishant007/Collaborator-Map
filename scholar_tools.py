from scholarly import scholarly
from geopy.geocoders import Nominatim
import folium
import os
import time
import http.client
import json

import config

geolocator = Nominatim(user_agent="affiliation_mapper")

import requests  # Ensure this is at the top if not already


def get_institution_logo_and_link(institution_name):
    """
    Tries to get the logo and Wikipedia page link of an institution.
    Returns (logo_url or None, wikipedia_url or None)
    """
    session = requests.Session()
    search_url = "https://en.wikipedia.org/w/api.php"

    # Search for the correct Wikipedia title
    search_params = {
        "action": "query",
        "list": "search",
        "srsearch": institution_name,
        "format": "json"
    }

    try:
        search_res = session.get(search_url, params=search_params).json()
        search_results = search_res.get("query", {}).get("search", [])
        if not search_results:
            return None, None

        # Use the title of the top result
        page_title = search_results[0]["title"]
        wikipedia_link = f"https://en.wikipedia.org/wiki/{page_title.replace(' ', '_')}"

        # Try to get the image for that page
        image_params = {
            "action": "query",
            "format": "json",
            "titles": page_title,
            "prop": "pageimages",
            "piprop": "original"
        }
        image_res = session.get(search_url, params=image_params).json()
        pages = image_res.get("query", {}).get("pages", {})
        for page in pages.values():
            original = page.get("original", {})
            return original.get("source"), wikipedia_link

        return None, wikipedia_link
    except Exception as e:
        print(f"Error fetching logo/link for {institution_name}: {e}")
        return None, None


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
    m = folium.Map(location=[20, 0], zoom_start=2)
    for item in author_affiliations:
        name = item["author"]
        affiliation = item["affiliation"]
        loc = geolocate_affiliation(affiliation)
        if not loc:
            continue

        logo_url, wiki_link = get_institution_logo_and_link(affiliation)

        if logo_url:
            icon = folium.CustomIcon(logo_url, icon_size=(50, 50))
            folium.Marker(
                location=loc,
                icon=icon,
                popup=f"{name}<br>{affiliation}",
                tooltip=name
            ).add_to(m)
        else:
            popup_html = f"""
                <b>{name}</b><br>
                {affiliation}<br>
                <a href="{wiki_link}" target="_blank">Wikipedia</a>
            """
            folium.Marker(
                location=loc,
                popup=folium.Popup(popup_html, max_width=250),
                tooltip=name
            ).add_to(m)

        time.sleep(1)
    os.makedirs("output", exist_ok=True)
    return m


if __name__ == "__main__":
    print (get_institution_logo_and_link("MIT USA"))
    print (get_institution_logo_and_link("Tel aviv_ University"))