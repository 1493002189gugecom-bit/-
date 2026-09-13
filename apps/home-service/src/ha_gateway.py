"""Home Assistant transport. Errors intentionally exclude responses and credentials."""
import json
from urllib.error import HTTPError, URLError
from urllib.request import Request, build_opener, HTTPRedirectHandler, ProxyHandler


class GatewayError(Exception):
    """Sanitized HA transport failure with explicit submission certainty."""

    def __init__(self, code: str, may_have_submitted: bool = False):
        self.code = code
        self.may_have_submitted = may_have_submitted
        # Only the fixed error code enters Exception.args/repr. Never attach the
        # request, response, headers, URL error text, or access token.
        super().__init__(code)


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


class HAGateway:
    def __init__(self, url, token, timeout=5):
        if not token:
            raise ValueError('Home Assistant token required')
        self.url, self.token, self.timeout = url.rstrip('/'), token, timeout
        self.proxy_handler = ProxyHandler({})
        self.opener = build_opener(self.proxy_handler, NoRedirect())

    def request(self, method, path, data=None):
        req = Request(self.url + '/api/' + path, method=method,
                      data=None if data is None else json.dumps(data).encode(),
                      headers={'Authorization': 'Bearer ' + self.token, 'Content-Type': 'application/json'})
        try:
            with self.opener.open(req, timeout=self.timeout) as response:
                return json.load(response)
        except HTTPError as exc:
            # 404 is a definite "no such entity". A 5xx means Home Assistant
            # itself failed, which is indistinguishable from an unavailable
            # backend and must never be reported as a definite rejection.
            if exc.code == 404:
                raise GatewayError('not_found') from None
            if exc.code >= 500:
                raise GatewayError('backend_unavailable') from None
            raise GatewayError('backend_rejected') from None
        except (URLError, TimeoutError, OSError, ValueError):
            raise GatewayError('backend_unavailable') from None

    def read(self, entity):
        return self.request('GET', 'states/' + entity)

    def call(self, domain, service, data):
        try:
            return self.request('POST', 'services/' + domain + '/' + service, data)
        except GatewayError as exc:
            # urllib cannot prove whether a POST that lost its response reached
            # HA. Reads remain ordinary backend_unavailable failures, while a
            # transport failure during a service call is submission-uncertain.
            if exc.code == 'backend_unavailable':
                raise GatewayError('submission_unknown', may_have_submitted=True) from None
            raise
