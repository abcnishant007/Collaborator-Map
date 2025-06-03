from scholar_tools import (
    validate_and_get_papers,
    get_unique_coauthors,
    search_affiliation_snippets,
    geolocate_affiliation,
    create_map
)
from agent import resolve_affiliation_with_agent
import time

SERPAPI_CALL_LIMIT = 15

if __name__ == "__main__":
    scholar_user_id = input("Enter your Google Scholar user ID (e.g., AiujSOkAAAAJ): ").strip()
    papers, error = validate_and_get_papers(scholar_user_id)

    if error:
        print("Error:", error)
        exit(1)

    coauthors = get_unique_coauthors(papers)
    limited_coauthors = coauthors[:SERPAPI_CALL_LIMIT]

    author_affiliations = []
    for author in limited_coauthors:
        print(f"\n🔍 Searching for {author}...")
        snippets = search_affiliation_snippets(author)
        if not snippets:
            affiliation = "Unknown"
        else:
            affiliation = resolve_affiliation_with_agent(author, snippets)
        print(f"✅ {author} likely affiliation: {affiliation}")
        author_affiliations.append({"name": author, "affiliation": affiliation})
        time.sleep(2)

    print("\n🗺️ Generating collaborator map...")
    map_obj = create_map(author_affiliations)
    map_obj.save("output/collaborator_map.html")
    print("✅ Map saved to output/collaborator_map.html")
