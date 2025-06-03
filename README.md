
# Collaborator-Map
Simple Agentic AI to determine the current affiliations of one's research colleagues 


## 🚀 Features

- 🔍 Automatically extracts coauthors from a Google Scholar user ID
- 🧠 Uses a local or remote LLM (DeepSeek via Ollama) to resolve affiliations
- 🌐 Uses Serper.dev to get relevant search snippets
- 📍 Geolocates affiliations and maps them
- 🗺️ Generates an interactive HTML map of academic collaborators

---

## 📦 Requirements

- Python 3.11+
- Ollama installed with a model like `deepseek-r1:7b` (can run remotely via SSH tunnel)
- Serper.dev API key (for web snippet search)
- A Google Scholar user ID

### 🔧 Python Dependencies

Install with:

```bash
pip install -r requirements.txt
```

Example `requirements.txt`:

```
scholarly
geopy
folium
requests
```

---

## 🔐 Secure Remote Ollama (Optional but Recommended)

Run the model on a powerful remote server and securely access it via SSH:

```bash
ssh -L 51134:localhost:11434 your-user@your-server
```

Then in your `agent.py` or config:

```python
OLLAMA_URL = "http://localhost:51134/api/generate"
```

On your server, just start the model:

```bash
ollama run deepseek-r1:7b
```

---

## 🧪 How to Use

1. Clone the repo:

```bash
git clone https://github.com/yourusername/scholar-affiliation-mapper.git
cd scholar-affiliation-mapper
```

2. Run the script:

```bash
python main.py
```

3. Enter your Google Scholar user ID (e.g., `AiujSOkAAAAJ`)

4. It will:
   - Fetch your papers
   - Extract coauthors
   - Use Serper + LLM to infer affiliations
   - Create a `collaborator_map.html` in the `output/` folder

---

## 🌍 Output Example

- `output/collaborator_map.html` — interactive map with coauthors and inferred affiliations

---

## 🔑 Serper API Key

You’ll need to sign up at [https://serper.dev](https://serper.dev) and get a free API key.

Add your key in `scholar_tools.py`:

```python
SERPER_API_KEY = "your-api-key-here"
```

---

## 🧠 LLM Configuration

This uses `deepseek-r1:7b` by default. You can change the model in `agent.py`:

```python
OLLAMA_MODEL = "deepseek-r1:7b"
```

You can also switch between local and remote servers by changing `OLLAMA_URL`.

---

## ✅ Example

```
Enter your Google Scholar user ID: AiujSOkAAAAJ

🔍 Searching for Alice Smith...
🧠 Prompt sent to DeepSeek via Ollama:
...
✅ Alice Smith likely affiliation: Stanford University

🗺️ Generating collaborator map...
✅ Map saved to output/collaborator_map.html
```


---

**Important**: The scholarly client has some issues when installed using the pip installation
pip install git+https://github.com/OrganicIrradiation/scholarly.git
