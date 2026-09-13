"""Read HA credentials from an explicit local env file without logging them."""
import json
import os
from pathlib import Path
from urllib.request import Request, urlopen


def credentials():
    values = dict(os.environ)
    path = values.get('HA_ENV_FILE')
    if path:
        for line in Path(path).read_text(encoding='utf-8-sig').splitlines():
            key, sep, value = line.partition('=')
            if sep and key.strip() in ('HOME_ASSISTANT_URL', 'HOME_ASSISTANT_TOKEN'):
                values.setdefault(key.strip(), value.strip().strip('\"\''))
    url = values.get('HOME_ASSISTANT_URL', 'http://127.0.0.1:8123').rstrip('/')
    token = values.get('HOME_ASSISTANT_TOKEN', '')
    if not token:
        raise RuntimeError('HOME_ASSISTANT_TOKEN or HA_ENV_FILE is required')
    return url, token


def request(method, path, data=None):
    url, token = credentials()
    req = Request(url + path, method=method,
                  data=None if data is None else json.dumps(data).encode(),
                  headers={'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'})
    with urlopen(req, timeout=10) as response:
        return json.load(response)


if __name__ == '__main__':
    config = request('GET', '/api/config')
    print(json.dumps({'version': config['version'], 'mqtt_loaded': 'mqtt' in config['components']}))
