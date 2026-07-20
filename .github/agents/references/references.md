# Reference Materials

Fetch these before writing any code:

- **OAA Python SDK docs**: https://docs.veza.com/4yItIzMvkpAvMVFAamTf/developers/api/oaa/python-sdk
- **OAA Getting Started**: https://docs.veza.com/4yItIzMvkpAvMVFAamTf/developers/api/oaa/getting-started
- **OAA Templates overview**: https://docs.veza.com/4yItIzMvkpAvMVFAamTf/developers/api/oaa/templates
- **Custom application templates**: https://docs.veza.com/4yItIzMvkpAvMVFAamTf/developers/api/oaa/templates#custom-application-templates
- **Custom Identity Provider templates**: https://docs.veza.com/4yItIzMvkpAvMVFAamTf/developers/api/oaa/templates#custom-identity-provider-templates
- **Reference — resources/sub-resources pattern**: https://github.com/pvolu-vz/NetApp (`netAppShares.py`, `install_ontap.sh`, `requirements.txt`, `.env.example-ontap`)
- **Reference — HR/API sources pattern**: https://github.com/pvolu-vz/adp_project (`adp_api.py`, `adp_OAA_veza.sh`, `requirements.txt`, `config.py`, `util.py`, `.env`)

## Community Connector Examples

Real-world OAA connectors from https://github.com/Veza/oaa-community/tree/main/connectors — study these before building a new connector:

| Connector | Main Script | Pattern / Notes |
|-----------|-------------|-----------------|
| **GitHub** | [`oaa_github.py`](https://github.com/Veza/oaa-community/blob/main/connectors/github/oaa_github.py) | CustomApplication; maps org → app, members → local users, teams → local groups, repos → resources; GitHub App (PEM key) auth; supports user CSV identity map |
| **Jira Cloud** | [`oaa_jira.py`](https://github.com/Veza/oaa-community/blob/main/connectors/jira/oaa_jira.py) | CustomApplication; maps Jira instance → app, projects → resources, groups → local groups, project roles → local groups; Atlassian API token auth |
| **Slack** | [`oaa_slack.py`](https://github.com/Veza/oaa-community/blob/main/connectors/slack/oaa_slack.py) | CustomApplication; maps workspace → app, users → local users, user groups → local groups; Slack OAuth token auth; custom properties for MFA, guest status |
| **GitLab** | [`connectors/gitlab/`](https://github.com/Veza/oaa-community/tree/main/connectors/gitlab) | CustomApplication; similar org/project/member pattern to GitHub connector |
| **Bitbucket Cloud** | [`connectors/bitbucket-cloud/`](https://github.com/Veza/oaa-community/tree/main/connectors/bitbucket-cloud) | CustomApplication; maps Bitbucket workspace/repos/users/groups |
| **Looker** | [`connectors/looker/`](https://github.com/Veza/oaa-community/tree/main/connectors/looker) | CustomApplication; maps Looker users, groups, and content permissions |
| **PagerDuty** | [`connectors/pagerduty/`](https://github.com/Veza/oaa-community/tree/main/connectors/pagerduty) | CustomApplication; maps PagerDuty users, teams, and service permissions |
| **Rollbar** | [`connectors/rollbar/`](https://github.com/Veza/oaa-community/tree/main/connectors/rollbar) | CustomApplication; maps Rollbar projects, teams, and user access levels |
| **Cerby** | [`connectors/cerby/`](https://github.com/Veza/oaa-community/tree/main/connectors/cerby) | CustomApplication; maps Cerby managed app accounts and permissions |

### Common structure across all community connectors

Each connector follows this layout:
```
oaa_<name>.py       # main connector script
requirements.txt    # pinned deps (oaaclient, requests, etc.)
Dockerfile          # optional container build
README.md           # setup, parameters table, OAA mapping table
.gitignore
```

Key patterns to replicate:
- Accept all secrets via **environment variables** with CLI flag overrides
- Include a `--save-json` / `--debug` flag pair
- Print a mapping table comment in the README showing how source entities map to OAA types (Application, Local User, Local Group, Local Role, Application Resource)
- Use `oaaclient.client.OAAClient` to push; handle `OAAClientError` and log properly


### Logging setup

log = logging.getLogger(__name__)


def _setup_logging(log_level: str = "INFO") -> None:
    """Configure file-only logging with hourly rotation to the logs/ folder."""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    log_dir = os.path.join(script_dir, "logs")
    os.makedirs(log_dir, exist_ok=True)

    timestamp = datetime.now().strftime("%d%m%Y-%H%M")
    script_name = os.path.splitext(os.path.basename(__file__))[0]
    log_file = os.path.join(log_dir, f"{script_name}_{timestamp}.log")

    handler = TimedRotatingFileHandler(
        log_file,
        when="h",
        interval=1,
        backupCount=24,
        encoding="utf-8",
    )
    handler.setFormatter(logging.Formatter(
        fmt="%(asctime)s %(levelname)-8s %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    ))

    root = logging.getLogger()
    root.setLevel(getattr(logging, log_level.upper()))
    root.addHandler(handler)