import requests
from typing import Any, Dict, Optional


def jenkins_stop_build(auth_info: dict, job_name: str, build_number: str, timeout: int = 30, verify_ssl: bool = True, base_url: str = None) -> dict:
    """Stop a build in jenkins. Official: https://www.jenkins.io/doc/book/using/remote-access-api/"""
    try:
        if not build_number:
            return {"records": [], "data_count": 0, "status": 400, "message": "build_number is required", "provision_ids": []}
        base, err = _jk_root(base_url)
        if err:
            return {"records": [], "data_count": 0, "status": 400, "message": err, "provision_ids": []}
        path, perr = _jk_job_path(job_name)
        if perr:
            return {"records": [], "data_count": 0, "status": 400, "message": perr, "provision_ids": []}
        basic, auth_err = _jk_auth(auth_info)
        if auth_err:
            return {"records": [], "data_count": 0, "status": 401, "message": auth_err, "provision_ids": []}
        headers, _ = _jk_crumb(base, basic, timeout, verify_ssl)
        resp = _jk_post(f"{base}{path}/{build_number}/stop", basic, headers, None, timeout, verify_ssl)
        if resp.status_code >= 400:
            return {"records": [], "data_count": 0, "status": resp.status_code, "message": resp.text[:1000], "provision_ids": []}
        return {"records": [], "data_count": 0, "status": resp.status_code, "message": "ok", "provision_ids": [build_number]}
    except Exception as e:
        return {"records": [], "data_count": 0, "status": 500, "message": str(e), "provision_ids": []}


# Jenkins Remote Access API — https://www.jenkins.io/doc/book/using/remote-access-api/


def _jk_root(base_url):
    root = (base_url or "").rstrip("/")
    if not root:
        return None, "base_url is required (https://jenkins.example.com)"
    return root, None


def _jk_auth(auth_info):
    auth_info = auth_info or {}
    username = auth_info.get("username")
    password = auth_info.get("password")
    if not username or not password:
        return None, "auth_info requires username and password"
    return (str(username), str(password)), None


def _jk_job_path(job_name):
    parts = [p for p in str(job_name or "").split("/") if p]
    if not parts:
        return None, "job_name is required"
    return "".join(f"/job/{p}" for p in parts), None


def _jk_get(url, basic, params, timeout, verify_ssl):
    return requests.get(url, auth=basic, params=params, timeout=timeout, verify=verify_ssl)


def _jk_post(url, basic, headers, data, timeout, verify_ssl):
    return requests.post(url, auth=basic, headers=headers, data=data, timeout=timeout, verify=verify_ssl)


def _jk_crumb(base, basic, timeout, verify_ssl):
    resp = _jk_get(f"{base}/crumbIssuer/api/json", basic, None, timeout, verify_ssl)
    if resp.status_code >= 400:
        return {}, None
    data = resp.json() if resp.text else {}
    if isinstance(data, dict) and data.get("crumb"):
        hdr = data.get("crumbRequestField") or "Jenkins-Crumb"
        return {hdr: data["crumb"]}, data["crumb"]
    return {}, None
