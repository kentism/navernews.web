import requests
import json
import os
from dotenv import load_dotenv

load_dotenv()
API_KEY = os.getenv("APP_ACCESS_KEY")

def check_api():
    url = "http://127.0.0.1:8000/api/clipping-candidates"
    cookies = {"access_token": API_KEY}
    try:
        r = requests.get(url, cookies=cookies)
        print(f"Status Code: {r.status_code}")
        if r.status_code == 200:
            print(json.dumps(r.json(), indent=2, ensure_ascii=False))
        else:
            print(r.text)
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    # Note: This requires the server to be running.
    # Since I cannot guarantee the server is running on 8000, 
    # I will instead test the functions directly in python.
    from services.clipping_store import list_candidates, get_default_cutoff, to_iso, list_candidate_keywords, DEFAULT_CATEGORIES
    
    try:
        data = {
            "items": list_candidates(status="pending"),
            "categories": DEFAULT_CATEGORIES,
            "keywords": list_candidate_keywords(),
            "default_cutoff": to_iso(get_default_cutoff()),
        }
        print("API Logic Result:")
        print(json.dumps(data, indent=2, ensure_ascii=False))
    except Exception as e:
        import traceback
        traceback.print_exc()
