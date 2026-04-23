def serper_news_search(auth_info: dict, query: str, num: int = 10, tbs: str = None) -> dict:
    import requests
    _h = {"X-API-KEY": auth_info.get("api_key", ""), "Content-Type": "application/json"}
    payload = {"q": query, "num": num, "type": "news"}
    if tbs: payload["tbs"] = tbs  # e.g., "qdr:d" for past day, "qdr:w" for past week
    resp = requests.post("https://google.serper.dev/news", headers=_h, json=payload, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    news = [{"title": n.get("title"), "link": n.get("link"), "snippet": n.get("snippet"), "source": n.get("source"), "date": n.get("date")} for n in data.get("news", [])]
    return {"success": True, "query": query, "news": news, "count": len(news)}
