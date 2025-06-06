import time

from smartprint import smartprint as sprint

import config
from agent import resolve_affiliation_with_agent
from scholar_tools import (
    validate_and_get_papers,
    search_affiliation_snippets,
    create_map
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
    # Call it
    scholar_user_id = timed_input("Enter your Google Scholar user ID (e.g., AiujSOkAAAAJ): ", timeout=10)

    # Fallback behavior
    if not scholar_user_id:
        print("⚠️ Proceeding with fallback: creating graph for the repository author.")
        # e.g., author_name = "YourRepoOwnerName"
        scholar_user_id = "AiujSOkAAAAJ"

    # Updated: Expect email_domain from function
    papers, author_name, email_domain, error = validate_and_get_papers(scholar_user_id)

    if error:
        print("Error:", error)
        exit(1)

    already_processed_authors = {}

    author_affiliations_list_of_KV_pairs = []
    for paper in papers:
        print(paper['title'])

        for author in paper['authors']:
            if author not in already_processed_authors:
                sprint(len(already_processed_authors))
                if len(already_processed_authors) > config.SERPAPI_CALL_LIMIT:
                    sprint (len(already_processed_authors))
                    print ("Maximum number of queries reached; Check SERPAPI_CALL_LIMIT in config file")
                    continue

                searchword = author + "  " + paper['title'] + " google scholar "
                print(searchword)

                # search_affiliation_snippets (searchword)
                # already_processed_authors[author] = "Processed"

                snippets = search_affiliation_snippets(author)

                if not snippets:
                    affiliation = "Unknown"
                else:
                    # ✅ Use email domain as a hint if available
                    affiliation = resolve_affiliation_with_agent(
                        author,
                        snippets,
                        email_hint=None
                    )

                print(f"✅ {author} likely affiliation: {affiliation}")
                already_processed_authors[author] = affiliation
                author_affiliations_list_of_KV_pairs.append({"author": author, "affiliation": affiliation})
                time.sleep(2)

    print("\n🗺️ Generating collaborator map...")
    map_obj = create_map(author_affiliations_list_of_KV_pairs)
    map_obj.save("output/collaborator_map.html")
    print("✅ Map saved to output/collaborator_map.html")
