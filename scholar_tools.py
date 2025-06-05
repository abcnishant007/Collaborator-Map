from scholarly import scholarly
from geopy.geocoders import Nominatim
import folium
import os
import time
import http.client
import json

import config

geolocator = Nominatim(user_agent="affiliation_mapper")

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

def create_map(author_affiliations):
    m = folium.Map(location=[20, 0], zoom_start=2)
    for item in author_affiliations:
        try:
            loc = geolocate_affiliation(item["affiliation"])
        except Exception as e:
            # print (item)
            # print (item["affiliation"])
            raise Exception(f"Error geolocating affiliation: {e}")
        if loc:
            folium.Marker(
                location=loc,
                popup=f"{item['author']}: {item['affiliation']}",
                tooltip=item['author']
            ).add_to(m)
        time.sleep(1)
    os.makedirs("output", exist_ok=True)
    return m
