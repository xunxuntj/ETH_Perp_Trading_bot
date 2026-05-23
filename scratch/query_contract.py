import requests
import json

url = "https://api.gateio.ws/api/v4/futures/usdt/contracts/ETH_USDT"
try:
    resp = requests.get(url)
    resp.raise_for_status()
    data = resp.json()
    print("ETH_USDT Contract Parameters:")
    print(json.dumps(data, indent=2))
except Exception as e:
    print(f"Error querying contracts: {e}")
