"""Built-in service workers for common integrations.

Each worker is a :class:`~superpos_sdk.ServiceWorker` subclass that bridges an
external service into the Superpos task bus.  Import the ones you need and
instantiate them with your credentials::

    from superpos_sdk.workers import HttpWorker, SlackWorker

    worker = SlackWorker(
        base_url="https://superpos.example.com",
        hive_id="01HXYZ...",
        agent_id="01HABC...",
        secret="s3cr3t",
    )
    worker.run()

Optional dependency groups (install with pip):

- ``superpos-sdk[http]``     — :class:`HttpWorker`
- ``superpos-sdk[github]``   — :class:`GitHubWorker`
- ``superpos-sdk[slack]``    — :class:`SlackWorker`
- ``superpos-sdk[gmail]``    — :class:`GmailWorker`
- ``superpos-sdk[sheets]``   — :class:`SheetsWorker`
- ``superpos-sdk[jira]``     — :class:`JiraWorker`
- ``superpos-sdk[sql]``      — :class:`SqlWorker`
- ``superpos-sdk[workers]``  — all of the above
"""

from superpos_sdk.workers.github import GitHubWorker
from superpos_sdk.workers.gmail import GmailWorker
from superpos_sdk.workers.http import HttpWorker
from superpos_sdk.workers.jira import JiraWorker
from superpos_sdk.workers.sheets import SheetsWorker
from superpos_sdk.workers.slack import SlackWorker
from superpos_sdk.workers.sql import SqlWorker

__all__ = [
    "GitHubWorker",
    "GmailWorker",
    "HttpWorker",
    "JiraWorker",
    "SheetsWorker",
    "SlackWorker",
    "SqlWorker",
]
