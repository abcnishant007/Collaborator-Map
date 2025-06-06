import time

from smartprint import smartprint as sprint

import config
from agent import resolve_affiliation_with_agent
from scholar_tools import (
    validate_and_get_papers,
    search_affiliation_snippets,
    create_map, strip_to_base_domain, map_domain_to_affiliation
)

SERPAPI_CALL_LIMIT = config.SERPAPI_CALL_LIMIT


import threading
import queue

def timed_input(prompt, timeout=10):
    result_queue = queue.Queue()

    def ask():
        user_input = input(prompt).strip()
        result_queue.put(user_input)

    thread = threading.Thread(target=ask)
    thread.daemon = True
    thread.start()

    try:
        user_input = result_queue.get(timeout=timeout)
        return user_input
    except queue.Empty:
        print("\n⏰ No valid Google Scholar input received.")
        return None





if __name__ == "__main__":
    # Prompt user for Google Scholar ID
    scholar_user_id = timed_input("Enter your Google Scholar user ID (e.g., AiujSOkAAAAJ): ", timeout=10)

    if not scholar_user_id:
        print("⚠️ Proceeding with fallback: creating graph for the repository author.")
        scholar_user_id = "AiujSOkAAAAJ"

    # Fetch author and their publications
    papers, author_name, email_domain, error = validate_and_get_papers(scholar_user_id)

    if error:
        print("❌ Error:", error)
        exit(1)

    already_processed_authors = {}
    author_affiliations_list_of_KV_pairs = []

    for paper in papers:
        print(f"\n📄 {paper['title']}")
        for author in paper['authors']:
            if author in already_processed_authors:
                continue

            print(f"\n🔍 Processing: {author}")
            if len(already_processed_authors) >= config.SERPAPI_CALL_LIMIT:
                print(f"⚠️ SERPAPI_CALL_LIMIT reached ({config.SERPAPI_CALL_LIMIT})")
                continue

            # Step 1: Check if this is the profile owner
            is_main_author = author.lower() == author_name.lower()
            affiliation = None
            confidence = 1.0

            if is_main_author and email_domain:
                base_domain = strip_to_base_domain(email_domain)
                affiliation = map_domain_to_affiliation(base_domain)
                if affiliation:
                    print(f"✅ Using verified email domain ({email_domain}) → {affiliation}")
            else:
                # Step 2: Run snippet-based search
                aff_info = search_affiliation_snippets(author, paper_title=paper["title"])
                snippets = aff_info.get("snippets", [])
                verified_aff = aff_info.get("affiliation")

                if verified_aff:
                    affiliation = verified_aff
                    print(f"✅ Found from verified domain: {affiliation}")
                elif snippets:
                    affiliation, confidence = resolve_affiliation_with_agent(author, snippets)
                    if config.HUMAN_IN_LOOP and confidence < 0.8:
                        print(f"\n🧠 Low-confidence affiliation ({confidence:.2f}): {affiliation}")
                        override = input("Enter correct affiliation or press Enter to accept: ").strip()
                        if override:
                            affiliation = override
                else:
                    affiliation = "Unknown"
                    confidence = 0.0

            print(f"📌 Final Affiliation: {author} → {affiliation}")
            already_processed_authors[author] = affiliation
            author_affiliations_list_of_KV_pairs.append({"author": author, "affiliation": affiliation})
            time.sleep(2)

    # Generate final map
    print("\n🗺️ Generating collaborator map...")
    map_obj = create_map(author_affiliations_list_of_KV_pairs)
    map_obj.save("output/collaborator_map.html")
    print("✅ Map saved to output/collaborator_map.html")
