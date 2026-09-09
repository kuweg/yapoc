"""Suppress credential-bearing HTTP diagnostics before standard logging emits them."""
import logging


class GitHubHTTPFilter(logging.Filter):
    def filter(self, record):
        # Request lines may include signed log-storage URLs. Redact credentials
        # in other diagnostics without disabling unrelated HTTP logging.
        message = record.getMessage()
        from app.utils.github.client import redact
        if any(host in message for host in (
            'api.github.com', '.blob.core.windows.net', '.actions.githubusercontent.com',
        )):
            record.msg, record.args = 'GitHub HTTP diagnostic omitted.', ()
        else:
            record.msg, record.args = redact(message), ()
        return True


def install_filter():
    for name in ('httpx', 'httpcore.connection', 'httpcore.http11', 'httpcore.http2',
                 'httpcore.proxy', 'httpcore.socks'):
        logger = logging.getLogger(name)
        if not any(isinstance(f, GitHubHTTPFilter) for f in logger.filters):
            logger.addFilter(GitHubHTTPFilter())
