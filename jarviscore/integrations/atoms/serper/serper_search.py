def serper_search(auth_info: dict, query: str, num: int = 10, gl: str = "ke", hl: str = "en") -> dict:
    import requests
    _h = {"X-API-KEY": auth_info.get("api_key", ""), "Content-Type": "application/json"}
    payload = {"q": query, "num": num, "gl": gl, "hl": hl}
    resp = requests.post("https://google.serper.dev/search", headers=_h, json=payload, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    results = [{"title": r.get("title"), "link": r.get("link"), "snippet": r.get("snippet"), "position": r.get("position")} for r in data.get("organic", [])]
    return {"success": True, "query": query, "results": results, "answer_box": data.get("answerBox"), "knowledge_graph": data.get("knowledgeGraph")}
