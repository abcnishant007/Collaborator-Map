import requests

OLLAMA_URL = "http://localhost:11434/api/generate"
OLLAMA_MODEL = "deepseek-r1:7b"

def call_deepseek(prompt, model=OLLAMA_MODEL):
    response = requests.post(
        OLLAMA_URL,
        json={
            "model": model,
            "prompt": prompt,
            "stream": False
        }
    )
    result = response.json()
    return result.get("response", "").strip()

def resolve_affiliation_with_agent(name, search_snippets, field="computer science"):
    prompt = f"""You are an academic assistant.

    Given the following name and search result snippets, infer the most likely *current* institutional affiliation of the person. If there are 
    several people with the same name, then check for those who are researchers, since I am interested only in the researchers. 

    Name: {name}
    Field: {field}
    Search Results:
    """ + "\n".join([f"{i + 1}. {s}" for i, s in enumerate(search_snippets)]) + """

    Give your answer clearly as:

    Affiliation: <Your Answer Here>
    """
    print("🧠 Prompt sent to DeepSeek via Ollama:\n", prompt)
    response = call_deepseek(prompt)
    print("🧠 Raw model response:\n", response)

    # Use regex or a fallback to extract the answer
    import re
    match = re.search(r"Affiliation:\s*(.+)", response)
    answer = match.group(1).strip() if match else response.strip().split("\n")[0]

    # response = call_deepseek(prompt)
    # answer = response.split("Final Answer:")[-1].strip().split("\n")[0]
    return answer


def extract_after_think_tag(response: str) -> str:
    if '</think>' in response:
        return response.split('</think>', 1)[-1].strip()
    return response.strip()

if __name__ == "__main__":
    prompt = f"""You are an academic assistant.

        Given the following name and search result snippets, infer the most likely *current* institutional affiliation of the person.

        Name: Ron Rivest
        
        Search Results:
          
        
        Ronald L. Rivest : HomePage - People | MIT CSAIL
        Rivest. Professor Rivest is an Institute Professor at MIT. He joined MIT in 1974 as a faculty member in the Department of Electric...
        
        Massachusetts Institute of Technology
        
        Ron Rivest - Wikipedia
        At MIT, Rivest is a member of the Theory of Computation Group, and founder of MIT CSAIL's Cryptography and Information Security Gr...
        
        Wikipedia
        
        Ronald L. Rivest : Biographical Information - People | MIT CSAIL
        Professor Rivest is a member of the following professional societies: * AAAS (American Academy of Arts and Sciences) Member since...
        
        Massachusetts Institute of Technology


        Give your answer clearly as:

        Affiliation: <Your Answer Here>
        """
    print("🧠 Prompt sent to DeepSeek via Ollama:\n", prompt)
    response = call_deepseek(prompt)
    print("🧠 Raw model response:\n", response)



    print ("Response without think tags ", extract_after_think_tag(response))

