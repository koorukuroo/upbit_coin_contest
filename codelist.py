import requests

def get_upbit_markets():
    url = "https://api.upbit.com/v1/market/all"
    resp = requests.get(url)
    resp.raise_for_status()
    data = resp.json()
    # market 문자열만 추출
    codes = [item["market"] for item in data]
    return codes

all_codes = get_upbit_markets()
print(all_codes)  # 앞 20개만 보기
