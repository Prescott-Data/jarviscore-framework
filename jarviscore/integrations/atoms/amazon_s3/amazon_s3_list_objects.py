from typing import Any, Dict, List, Optional

async def amazon_s3_list_objects(bucket: str, prefix: Optional[str]=None, limit: int=1000, timeout: int=30, verify_ssl: bool=True, base_url: str=None) -> dict:
    """List objects (GET ?list-type=2, SigV4 auth). Official: https://docs.aws.amazon.com/AmazonS3/latest/API/API_ListObjectsV2.html"""
    try:
        if not base_url:
            return {'records': [], 'data_count': 0, 'status': 400, 'message': 'base_url is required'}
        if not bucket:
            return {'records': [], 'data_count': 0, 'status': 400, 'message': 'bucket is required'}
        (_, region, root_err) = _s3_parse_base_url(base_url, bucket)
        if root_err:
            return {'records': [], 'data_count': 0, 'status': 400, 'message': root_err}
        (access_key, secret_key, session_token, auth_region, auth_err) = _s3_credentials()
        if auth_err:
            return {'records': [], 'data_count': 0, 'status': 401, 'message': auth_err}
        region = auth_region or region
        records = []
        token = None
        status = 0
        cap = min(max(int(limit or 1000), 1), 1000)
        pages = 0
        url = base_url.rstrip('/') + '/'
        while len(records) < cap and pages < 100:
            pages += 1
            params = {'list-type': '2', 'max-keys': str(min(cap - len(records), 1000))}
            if prefix:
                params['prefix'] = prefix
            if token:
                params['continuation-token'] = token
            resp = await _s3_request('GET', url, region, access_key, secret_key, session_token, headers={'Accept': 'application/xml'}, params=params, timeout=timeout, verify_ssl=verify_ssl)
            status = resp['status_code']
            if status >= 400:
                return {'records': records, 'data_count': len(records), 'status': status, 'message': resp['body'][:1000]}
            (batch, truncated, token) = _s3_parse_list_xml(resp['body'])
            for item in batch:
                records.append(item)
                if len(records) >= cap:
                    break
            if not truncated or not token:
                break
        return {'records': records[:cap], 'data_count': len(records[:cap]), 'status': status or 200, 'message': 'ok'}
    except Exception as e:
        return {'records': [], 'data_count': 0, 'status': 500, 'message': str(e)}

def _pct_enc(text, safe=''):
    out = []
    for ch in str(text):
        o = ord(ch)
        if ch in safe or (o < 128 and (ch.isalnum() or ch in '-_.~')):
            out.append(ch)
        else:
            for b in ch.encode('utf-8'):
                out.append(f'%{b:02X}')
    return ''.join(out)

def _parse_url(url):
    (scheme, rest) = ('', url)
    if '://' in url:
        (scheme, rest) = url.split('://', 1)
    fragment = ''
    if '#' in rest:
        (rest, fragment) = rest.split('#', 1)
    query = ''
    if '?' in rest:
        (rest, query) = rest.split('?', 1)
    if '/' in rest:
        (netloc, path) = rest.split('/', 1)
        path = '/' + path
    else:
        (netloc, path) = (rest, '/')
    return (scheme, netloc, path, query, fragment)

def _build_url(scheme, netloc, path, query='', fragment=''):
    url = f"{scheme}://{netloc}{path or '/'}"
    if query:
        url += '?' + query
    if fragment:
        url += '#' + fragment
    return url

def _query_pairs(query):
    pairs = []
    for part in (query or '').split('&'):
        if not part:
            continue
        if '=' in part:
            (k, v) = part.split('=', 1)
        else:
            (k, v) = (part, '')
        pairs.append((k, v))
    return pairs

def _urlencode(params):
    return '&'.join((f'{_pct_enc(str(k))}={_pct_enc(str(v))}' for (k, v) in params.items()))

def _s3_parse_base_url(base_url: str, bucket: str):
    (scheme, netloc, path, query, fragment) = _parse_url(base_url.rstrip('/'))
    if scheme != 'https' or not netloc:
        return (None, None, 'base_url must be https://{bucket}.s3.{region}.amazonaws.com')
    host = netloc
    if not host.endswith('.amazonaws.com'):
        return (None, None, 'base_url must match https://{bucket}.s3.{region}.amazonaws.com')
    body = host[:-len('.amazonaws.com')]
    region = 'us-east-1'
    host_bucket = None
    if '.s3.' in body:
        (host_bucket, region_part) = body.split('.s3.', 1)
        region = region_part.split('.')[0] or 'us-east-1'
    elif '.s3-' in body:
        (host_bucket, region) = body.split('.s3-', 1)
    else:
        return (None, None, 'base_url must match https://{bucket}.s3.{region}.amazonaws.com')
    if bucket and bucket != host_bucket:
        return (None, None, f'bucket parameter ({bucket}) does not match base_url bucket ({host_bucket})')
    return (host_bucket or bucket, region, None)

def _s3_credentials():
    return (None, None, None, None, None)

def _s3_sign(method: str, url: str, region: str, access_key: str, secret_key: str, session_token=None, headers=None, payload=b''):
    import hashlib as _hashlib
    import hmac as _hmac
    from datetime import datetime as _dt
    from datetime import timezone as _tz
    headers = dict(headers or {})
    (_, host, canonical_uri, query, _) = _parse_url(url)
    if not canonical_uri.startswith('/'):
        canonical_uri = '/' + canonical_uri
    canonical_uri = _pct_enc(canonical_uri, safe='/-_.~')
    canonical_query = '&'.join(sorted((f"{_pct_enc(k, safe='-_.~')}={_pct_enc(v, safe='-_.~')}" if v != '' else _pct_enc(k, safe='-_.~') for (k, v) in _query_pairs(query))))
    amz_date = _dt.now(_tz.utc).strftime('%Y%m%dT%H%M%SZ')
    date_stamp = amz_date[:8]
    payload_hash = _hashlib.sha256(payload if isinstance(payload, (bytes, bytearray)) else str(payload or '').encode('utf-8')).hexdigest()
    headers = {k.lower(): v.strip() for (k, v) in headers.items()}
    headers['host'] = host
    headers['x-amz-content-sha256'] = payload_hash
    headers['x-amz-date'] = amz_date
    if session_token:
        headers['x-amz-security-token'] = str(session_token)
    signed_header_names = sorted(headers.keys())
    canonical_headers = ''.join((f'{k}:{headers[k]}\n' for k in signed_header_names))
    signed_headers = ';'.join(signed_header_names)
    canonical_request = '\n'.join([method.upper(), canonical_uri, canonical_query, canonical_headers, signed_headers, payload_hash])
    algorithm = 'AWS4-HMAC-SHA256'
    credential_scope = f'{date_stamp}/{region}/s3/aws4_request'
    string_to_sign = '\n'.join([algorithm, amz_date, credential_scope, _hashlib.sha256(canonical_request.encode('utf-8')).hexdigest()])

    def _sign(key, msg):
        return _hmac.new(key, msg.encode('utf-8'), _hashlib.sha256).digest()
    k_date = _sign(('AWS4' + secret_key).encode('utf-8'), date_stamp)
    k_region = _sign(k_date, region)
    k_service = _sign(k_region, 's3')
    k_signing = _sign(k_service, 'aws4_request')
    signature = _hmac.new(k_signing, string_to_sign.encode('utf-8'), _hashlib.sha256).hexdigest()
    authorization = f'{algorithm} Credential={access_key}/{credential_scope}, SignedHeaders={signed_headers}, Signature={signature}'
    out = {k if k.startswith('x-amz-') or k == 'host' else k.title(): v for (k, v) in headers.items() if k not in ('host',)}
    out['Authorization'] = authorization
    out['X-Amz-Date'] = amz_date
    out['X-Amz-Content-Sha256'] = payload_hash
    if session_token:
        out['X-Amz-Security-Token'] = str(session_token)
    return out

async def _s3_request(method, url, region, access_key, secret_key, session_token=None, headers=None, params=None, data=None, timeout=30, verify_ssl=True):
    (scheme, netloc, path, query, fragment) = _parse_url(url)
    if params:
        query = _urlencode(params)
    url = _build_url(scheme, netloc, path, query, fragment)
    payload = data if isinstance(data, (bytes, bytearray)) else str(data).encode('utf-8') if data is not None else b''
    signed = _s3_sign(method, url, region, access_key, secret_key, session_token, headers, payload)
    return await nexus_call(method.upper(), url, headers=signed, data=payload if payload else None)

def _s3_parse_list_xml(text: str):
    records = []
    for block in text.split('<Contents>'):
        if '<Key>' not in block:
            continue
        item = {}
        for tag in ('Key', 'LastModified', 'ETag', 'Size'):
            open_tag = f'<{tag}>'
            close_tag = f'</{tag}>'
            if open_tag in block:
                item[tag.lower()] = block.split(open_tag, 1)[1].split(close_tag, 1)[0]
        if item:
            records.append(item)
    truncated = '<IsTruncated>true</IsTruncated>' in text
    token = None
    if '<NextContinuationToken>' in text:
        token = text.split('<NextContinuationToken>', 1)[1].split('</NextContinuationToken>', 1)[0]
    return (records, truncated, token)
