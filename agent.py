import requests
import config

#
if config.RUNNING_ON_SERVER:
    # implying that this tunnel has been created
    # ssh -L 8080:localhost:11434 username@server.sg
    OLLAMA_URL = "http://localhost:8080/api/generate"
    OLLAMA_MODEL = "deepseek-r1:7b"
elif not config.RUNNING_ON_SERVER:
    OLLAMA_URL = "http://localhost:11434/api/generate"
    OLLAMA_MODEL = "deepseek-r1:7b"
else:
    raise Exception("Wrong configuration; RUNNING_ON_SERVER")

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

def resolve_affiliation_with_agent(name, search_snippets, field="computer science", email_hint=None):

    if email_hint:
        email_prompt = " Use this verified email domain as a strong hint: {email_hint}"
    prompt = f"""You are an academic assistant.

    Given the following name and search result snippets, infer the most likely *current* or the latest institutional affiliation of the person. If there are 
    several people with the same name, then check for those who are researchers, since I am interested only in the researchers. 

    Name: {name}
    Field: {field}
    Search Results:
    """ + "\n".join([f"{i + 1}. {s}" for i, s in enumerate(search_snippets)]) + """

    When deciding upon between multiple options, look for the most senior position held. For instance a PhD Student at MIT might now be a lecturer at XY University, so
    it is highly likely that the current affiliation is XY University. Similarly, if there are three instances of the information, Post doc at ETH Zurich, PhD Student at IIT Bombay
    and assistant professor at NUS, then the latest affiliation is most likely NUS. 
    
    Very important: Give your answer clearly as the format shown below. Ensure that only the University or the institute name is present here; not the post or academic rank etc...
    
    
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

