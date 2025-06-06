import requests
from slugify import slugify
from pathlib import Path

from scholar_tools import get_institution_logo_brute_force

# from your_module import get_institution_logo_brute_force  # Replace with your actual import

# Configuration
API_KEY = "abc123xyzSECRETkey"
BASE_URL = "https://lifezbeautiful.pythonanywhere.com"
HEADERS = {"X-API-Key": API_KEY}
LOCAL_TMP = Path("tmp_logos")
LOCAL_TMP.mkdir(exist_ok=True)


import subprocess

def download_with_curl(url, output_path):
    try:
        subprocess.run([
            "curl", "-L", "-A", "Mozilla/5.0", url, "--output", output_path
        ], check=True)
        return True
    except subprocess.CalledProcessError as e:
        print(f"❌ curl failed: {e}")
        return False


def get_logo_from_server(slug):
    url = f"{BASE_URL}/logo/{slug}.svg"
    response = requests.get(url, headers=HEADERS)
    if response.status_code == 200:
        print(f"✅ Found logo on server: {slug}.svg")
        return response.content
    elif response.status_code == 404:
        print(f"❌ Logo not found on server for: {slug}")
        return None
    else:
        print(f"⚠️ Error fetching logo: {response.status_code}")
        return None

def upload_logo_to_server(file_path, slug):
    with open(file_path, "rb") as f:
        files = {"file": (f"{slug}.svg", f, "image/svg+xml")}
        data = {"name": f"{slug}.svg"}
        response = requests.post(f"{BASE_URL}/upload", headers=HEADERS, files=files, data=data)
    if response.ok:
        print(f"📤 Uploaded logo to server: {slug}.svg")
    else:
        print(f"❌ Upload failed: {response.status_code}, {response.text}")

def get_or_fetch_logo(institution_name):
    slug = slugify(institution_name)
    server_logo = get_logo_from_server(slug)
    if server_logo:
        # Save locally for use
        local_file = LOCAL_TMP / f"{slug}.svg"
        local_file.write_bytes(server_logo)
        return str(local_file)

    # Not found — fetch using your existing method
    logo_url, _ = get_institution_logo_brute_force(institution_name)
    if not logo_url:
        print("❌ Logo not found via brute-force method.")
        return None

    print(f"🌐 Downloading logo from: {logo_url}")
    headers = {"User-Agent": "Mozilla/5.0 (compatible; LogoBot/1.0; +https://your-site.com)"}

    local_file = LOCAL_TMP / f"{slug}.svg"
    success = download_with_curl(logo_url, str(local_file))
    if not success or not local_file.exists() or local_file.stat().st_size == 0:
        print("❌ Failed to download image via curl.")
        return None

    # Proceed to upload it to your server
    upload_logo_to_server(local_file, slug)
    return str(local_file)

    # Upload it
    upload_logo_to_server(local_file, slug)
    return str(local_file)

# 🔧 Test
if __name__ == "__main__":
    uni_name = "Harvard University"
    result = get_or_fetch_logo(uni_name)
    if result:
        print(f"🎯 Logo available at local file: {result}")
    else:
        print("❌ Failed to obtain logo.")

