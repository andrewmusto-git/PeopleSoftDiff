#!/usr/bin/env python3
"""
PeopleSoft Diff -> Veza OAA Integration Script

Connects to PeopleSoft HCM via the REST Web Services connector interface,
fetches employee records via the differential aggregation query
(ZPS_SP_DIFFERNTIAL), and pushes identity and access data into
Veza's Access Graph using OAA CustomApplication.

Entity Model:
  Local User       one per EMPLID; is_active derived from EMPL_STATUS
  Local Group      one per unique DEPTID (department)
  Custom Permission  department_member, active_employee

Usage:
    python3 peoplesoft_diff.py --help
"""

import argparse
import gc
import json
import logging
import os
import sys
import time
import xml.etree.ElementTree as ET
from datetime import datetime
from logging.handlers import TimedRotatingFileHandler
from typing import Dict, Generator, List, Optional

import requests
from dotenv import load_dotenv
from oaaclient.client import OAAClient, OAAClientError
from oaaclient.templates import CustomApplication, OAAPermission, OAAPropertyType

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_PROVIDER_NAME = "PeopleSoft HR"
DEFAULT_DATASOURCE_NAME = "PeopleSoft Differential"

# PeopleSoft REST Adhoc Query endpoint (relative path, appended to base URL)
QUERY_ENDPOINT = "/PSIGW/RESTListeningConnector/PSFT_HR/ExecuteAdhocQuery.v1/executeadhocquery"

REQUEST_TIMEOUT_SECONDS = 120

# Number of employee records fetched per PeopleSoft API page.
# PeopleSoft's ExecuteAdhocQuery endpoint supports <StartRow>/<MaxRow> pagination.
# Tuning guidance:
#   - Larger pages mean fewer round-trips but higher peak memory.
#   - If the InsightPoint host has limited RAM, lower this (e.g. 500–1000).
#   - If the PeopleSoft host is fast and well-resourced, raise it (e.g. 3000–5000).
DEFAULT_PAGE_SIZE = 2000

# Default name for the on-disk staging file written during Phase 1.
# Each line is a JSON-serialized employee record dict (JSON Lines / JSONL format).
STAGING_FILE_DEFAULT = "staging_employees.jsonl"

# EMPL_STATUS codes where the employee is considered active for access purposes.
# A=Active, L=Leave of Absence, P=Leave With Pay, S=Short Work Break
ACTIVE_STATUS_CODES: frozenset = frozenset({"A", "L", "P", "S"})

EMPL_STATUS_DESCRIPTIONS: Dict[str, str] = {
    "A": "Active",
    "L": "Leave of Absence",
    "P": "Leave With Pay",
    "S": "Short Work Break",
    "W": "Retired With Pay",
    "D": "Deceased",
    "R": "Retired",
    "T": "Terminated",
    "U": "Terminated With Pay",
    "Q": "Furloughed",
    "V": "Terminated Pension Pay Out",
}

# XML body for the PeopleSoft differential aggregation query.
# StartRow (1-based) and MaxRow are injected at runtime to support pagination.
# The Prompts section is intentionally empty so PeopleSoft returns all records
# in the differential dataset for each page.
_DIFFERENTIAL_QUERY_BODY = """\
<?xml version="1.0"?>
<QAS_EXEQRY_SYNC_REQ_MSG>
   <QAS_EXEQRY_SYNC_REQ>
      <QueryName>ZPS_SP_DIFFERNTIAL</QueryName>
      <isConnectedQuery>N</isConnectedQuery>
      <OwnerType>PUBLIC</OwnerType>
      <BlockSizeKB>0</BlockSizeKB>
      <StartRow>{start_row}</StartRow>
      <MaxRow>{max_rows}</MaxRow>
      <OutResultType>xmlp</OutResultType>
      <OutResultFormat>NONFILE</OutResultFormat>
      <Prompts>
      </Prompts>
   </QAS_EXEQRY_SYNC_REQ>
</QAS_EXEQRY_SYNC_REQ_MSG>"""


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

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
    root.setLevel(getattr(logging, log_level.upper(), logging.INFO))
    root.addHandler(handler)


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

def load_config(args: argparse.Namespace) -> dict:
    """Load configuration.  Precedence: CLI flag > env var > .env file."""
    env_file = getattr(args, "env_file", ".env") or ".env"
    if os.path.exists(env_file):
        load_dotenv(env_file)
        log.info("Loaded configuration from %s", env_file)
    else:
        log.warning("Environment file not found: %s", env_file)

    cfg = {
        "peoplesoft_base_url": (
            getattr(args, "peoplesoft_url", None)
            or os.getenv("PEOPLESOFT_BASE_URL", "")
        ).rstrip("/"),
        "peoplesoft_username": (
            getattr(args, "peoplesoft_username", None)
            or os.getenv("PEOPLESOFT_USERNAME", "")
        ),
        "peoplesoft_password": (
            getattr(args, "peoplesoft_password", None)
            or os.getenv("PEOPLESOFT_PASSWORD", "")
        ),
        "veza_url": (
            getattr(args, "veza_url", None)
            or os.getenv("VEZA_URL", "")
        ).rstrip("/"),
        "veza_api_key": (
            getattr(args, "veza_api_key", None)
            or os.getenv("VEZA_API_KEY", "")
        ),
    }

    errors = []
    if not cfg["peoplesoft_base_url"]:
        errors.append("PEOPLESOFT_BASE_URL is required (--peoplesoft-url or env)")
    if not cfg["peoplesoft_username"]:
        errors.append("PEOPLESOFT_USERNAME is required (--peoplesoft-username or env)")
    if not cfg["peoplesoft_password"]:
        errors.append("PEOPLESOFT_PASSWORD is required (--peoplesoft-password or env)")
    if not args.dry_run:
        if not cfg["veza_url"]:
            errors.append("VEZA_URL is required (--veza-url or env)")
        if not cfg["veza_api_key"]:
            errors.append("VEZA_API_KEY is required (--veza-api-key or env)")

    if errors:
        for err in errors:
            log.error("Configuration error: %s", err)
        sys.exit(1)

    return cfg


# ---------------------------------------------------------------------------
# PeopleSoft API client
# ---------------------------------------------------------------------------

def _build_session(username: str, password: str) -> requests.Session:
    """Return a requests Session configured for PeopleSoft Basic auth."""
    session = requests.Session()
    session.auth = (username, password)
    session.headers.update({"Content-Type": "text/xml"})
    return session


def _fetch_employee_page(session: requests.Session, url: str, start_row: int, page_size: int) -> List[dict]:
    """POST one paginated page of the differential aggregation query to PeopleSoft.

    Uses PeopleSoft's <StartRow>/<MaxRow> pagination.  Returns the list of
    employee attribute dicts for this page; an empty list signals end-of-data.
    """
    body = _DIFFERENTIAL_QUERY_BODY.format(start_row=start_row, max_rows=page_size)
    log.debug(
        "Fetching employee page: start_row=%d max_rows=%d url=%s",
        start_row, page_size, url,
    )

    try:
        response = session.post(url, data=body, timeout=REQUEST_TIMEOUT_SECONDS, verify=True)
        response.raise_for_status()
    except requests.exceptions.SSLError as exc:
        log.error("SSL verification failed for %s: %s", url, exc)
        log.error(
            "If using a self-signed or internal CA certificate, set the "
            "REQUESTS_CA_BUNDLE environment variable to your CA bundle path."
        )
        sys.exit(1)
    except requests.exceptions.ConnectionError as exc:
        log.error("Connection failed for %s: %s", url, exc)
        sys.exit(1)
    except requests.exceptions.Timeout:
        log.error(
            "Request timed out after %d seconds — consider increasing REQUEST_TIMEOUT_SECONDS "
            "or reducing --page-size",
            REQUEST_TIMEOUT_SECONDS,
        )
        sys.exit(1)
    except requests.exceptions.HTTPError as exc:
        log.error("HTTP error from PeopleSoft: %s", exc)
        log.debug("Response body: %s", exc.response.text[:1000] if exc.response else "")
        sys.exit(1)

    return _parse_xml_response(response.text)


def stream_employee_pages(
    cfg: dict,
    page_size: int = DEFAULT_PAGE_SIZE,
    page_delay: float = 0.0,
) -> Generator[List[dict], None, None]:
    """Generator that yields pages of employee records from PeopleSoft.

    Fetches the differential aggregation query in chunks of *page_size* rows
    using PeopleSoft's <StartRow>/<MaxRow> pagination so that the entire
    dataset is never held in memory at once.  Each yielded page is a list of
    employee attribute dicts; callers should process and release each page
    before requesting the next.

    Pagination stops when a page contains fewer rows than *page_size*, which
    signals the last (or only) page.

    Args:
        cfg:        Integration configuration dict from load_config().
        page_size:  Rows per PeopleSoft API request (default DEFAULT_PAGE_SIZE).
        page_delay: Optional sleep (seconds) between pages to reduce sustained
                    load on the InsightPoint host or PeopleSoft server.
    """
    base_url = cfg["peoplesoft_base_url"]
    url = f"{base_url}{QUERY_ENDPOINT}"
    session = _build_session(cfg["peoplesoft_username"], cfg["peoplesoft_password"])

    log.info(
        "Streaming employees from PeopleSoft: %s  (page_size=%d)", url, page_size
    )

    start_row = 1
    page_num = 0
    total_fetched = 0
    prev_page_fingerprint: Optional[tuple] = None

    while True:
        page_num += 1
        employees = _fetch_employee_page(session, url, start_row, page_size)

        if not employees:
            log.info(
                "PeopleSoft returned an empty page at start_row=%d — end of data", start_row
            )
            break

        # Guard against a pagination loop where the backend ignores StartRow
        # and repeatedly returns the same first page forever.
        first_emp = employees[0]
        last_emp = employees[-1]
        page_fingerprint = (
            len(employees),
            first_emp.get("EMPLID", ""),
            first_emp.get("EMPL_RCD", ""),
            last_emp.get("EMPLID", ""),
            last_emp.get("EMPL_RCD", ""),
        )
        if prev_page_fingerprint is not None and page_fingerprint == prev_page_fingerprint:
            log.error(
                "Detected repeated page fingerprint at start_row=%d; "
                "pagination may be stuck (StartRow ignored). Stopping fetch.",
                start_row,
            )
            break
        prev_page_fingerprint = page_fingerprint

        total_fetched += len(employees)
        log.info(
            "Page %d: %d records fetched (start_row=%d; running total: %d)",
            page_num, len(employees), start_row, total_fetched,
        )
        ts = datetime.now().strftime("%H:%M:%S")
        print(
            f"  [{ts}] Fetched page {page_num}: {len(employees):,} records "
            f"(rows {start_row}–{start_row + len(employees) - 1}) | "
            f"Running total: {total_fetched:,}",
            flush=True,
        )

        yield employees

        # Advance to the next page.
        # NOTE: We do NOT stop on a short page.  PeopleSoft may return fewer
        # rows than page_size on any page (e.g. due to a server-side cap) even
        # when more records remain.  The only reliable end-of-data signal is an
        # empty response, which is caught at the top of the loop.
        start_row += len(employees)

        if page_delay > 0:
            time.sleep(page_delay)

    ts = datetime.now().strftime("%H:%M:%S")
    print(
        f"  [{ts}] Fetch complete: {total_fetched:,} total records across {page_num} page(s)",
        flush=True,
    )
    log.info(
        "Employee stream complete: %d total records across %d page(s)",
        total_fetched, page_num,
    )


# ---------------------------------------------------------------------------
# Phase 1 — Fetch PeopleSoft records to a JSONL staging file
# ---------------------------------------------------------------------------

def fetch_to_staging(
    cfg: dict,
    staging_path: str,
    page_size: int = DEFAULT_PAGE_SIZE,
    page_delay: float = 0.0,
) -> int:
    """Stream all PeopleSoft records page-by-page and write to a JSONL staging file.

    Each record is written as a single JSON line so the file can be streamed
    back in Phase 2 without loading it entirely into memory.  The write goes
    to a temporary path first; on successful completion it is renamed atomically
    to *staging_path* so a partial fetch never leaves a corrupt staging file
    behind.

    Returns the total number of records written.
    """
    tmp_path = staging_path + ".tmp"

    log.info("Phase 1 — Fetching PeopleSoft records to staging file: %s", staging_path)
    print(f"\nPhase 1  —  Fetch PeopleSoft records to disk")
    print(f"  Staging file  : {staging_path}")
    print(f"  Page size     : {page_size:,} records / page")
    if page_delay > 0:
        print(f"  Page delay    : {page_delay}s between pages")
    print()

    total_written = 0

    try:
        with open(tmp_path, "w", encoding="utf-8") as fh:
            for page in stream_employee_pages(cfg, page_size=page_size, page_delay=page_delay):
                for record in page:
                    fh.write(json.dumps(record, ensure_ascii=False))
                    fh.write("\n")
                    total_written += 1
                # Flush after every page so data is safe before the next request
                fh.flush()
                del page
                gc.collect()
    except Exception:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        raise

    # Atomic promotion: temp file -> final staging path
    os.replace(tmp_path, staging_path)

    ts = datetime.now().strftime("%H:%M:%S")
    log.info("Phase 1 complete: %d records written to %s", total_written, staging_path)
    print(f"  [{ts}] Phase 1 complete: {total_written:,} records staged to disk\n")
    return total_written


# ---------------------------------------------------------------------------
# Phase 2 — Stream records back from the JSONL staging file
# ---------------------------------------------------------------------------

def stream_staging_pages(
    staging_path: str,
    batch_size: int = DEFAULT_PAGE_SIZE,
) -> Generator[List[dict], None, None]:
    """Read the JSONL staging file and yield batches of employee-record dicts.

    Reads line-by-line so at most *batch_size* raw records occupy memory at
    once, regardless of how large the staging file grows.  The yielded batches
    are the same shape as the pages yielded by *stream_employee_pages*, so the
    existing *build_oaa_payload* function consumes them unchanged.
    """
    log.info(
        "Phase 2 — Streaming staging file: %s  (batch_size=%d)", staging_path, batch_size
    )

    total_read = 0
    batch: List[dict] = []
    batch_num = 0

    with open(staging_path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                log.warning("Skipping malformed staging line %d: %s", total_read + 1, exc)
                continue

            batch.append(record)
            total_read += 1

            if len(batch) >= batch_size:
                batch_num += 1
                ts = datetime.now().strftime("%H:%M:%S")
                print(
                    f"  [{ts}] Staging batch {batch_num}: "
                    f"processing {len(batch):,} records "
                    f"(total read so far: {total_read:,})",
                    flush=True,
                )
                log.debug(
                    "Staging batch %d: %d records (total: %d)",
                    batch_num, len(batch), total_read,
                )
                yield batch
                batch = []
                gc.collect()

    # Yield any remaining records that didn't fill a full batch
    if batch:
        batch_num += 1
        ts = datetime.now().strftime("%H:%M:%S")
        print(
            f"  [{ts}] Staging batch {batch_num} (final): "
            f"processing {len(batch):,} records "
            f"(total: {total_read:,})",
            flush=True,
        )
        log.debug("Staging batch %d (final): %d records", batch_num, len(batch))
        yield batch

    log.info(
        "Staging stream complete: %d records in %d batch(es)", total_read, batch_num
    )


# ---------------------------------------------------------------------------
# XML parsing
# ---------------------------------------------------------------------------

def _local_tag(xml_tag: str) -> str:
    """Strip the XML namespace URI from a tag.

    '{http://xmlns.oracle.com/.../QAS_QUERYRESULTS_XMLP_RESP.VERSION_1}row'
    becomes 'row'.
    """
    return xml_tag.split("}", 1)[1] if "}" in xml_tag else xml_tag


def _strip_table_alias(field: str) -> str:
    """Strip PeopleSoft query table alias prefix.

    The SailPoint resMappingObj uses 'A.EMPLID' to reference the EMPLID field
    of table alias A.  In the XMLP response the element is also named 'A.EMPLID'
    (dots are valid in XML Names).  Strip the alias so callers see 'EMPLID'.
    """
    return field.split(".", 1)[1] if "." in field else field


def _parse_xml_response(xml_text: str) -> List[dict]:
    """Parse a PeopleSoft XMLP query response into a list of field dicts.

    Rows are found by iterating the entire tree for <row> elements (handling
    any namespace prefix such as query:row).  Within each row, child element
    local names are normalised by stripping any table alias prefix (e.g. A.).
    """
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        log.error("Failed to parse XML response: %s", exc)
        log.debug("Raw response snippet: %.500s", xml_text)
        raise

    employees: List[dict] = []
    for element in root.iter():
        if _local_tag(element.tag).lower() != "row":
            continue
        record: Dict[str, str] = {}
        for child in element:
            field = _strip_table_alias(_local_tag(child.tag))
            record[field] = (child.text or "").strip()
        # Only treat rows with a real EMPLID as employee data rows.
        # This avoids false positives from non-data <row> elements that can
        # otherwise keep pagination from ever appearing empty.
        if record.get("EMPLID", "").strip():
            employees.append(record)

    return employees


# ---------------------------------------------------------------------------
# OAA payload builder
# ---------------------------------------------------------------------------

def build_oaa_payload(
    employee_pages: Generator[List[dict], None, None],
    args: argparse.Namespace,
) -> CustomApplication:
    """Build an OAA CustomApplication by streaming pages of PeopleSoft employee records.

    Processes one page at a time and releases raw record data after each page
    so that peak memory is proportional to *page_size*, not the total dataset.
    Department groups are registered lazily on first encounter within each page,
    eliminating the need for a separate pre-pass over all data.

    Entity mapping
    ~~~~~~~~~~~~~~
    PeopleSoft field(s)          -> OAA entity / property
    ---------------------------  -----------------------------------------------
    EMPLID                       -> LocalUser.unique_id
    FIRST_NAME / PREF_FIRST_NAME -> LocalUser.name (first part)
    LAST_NAME / ZPS_PREF_LAST_NAME -> LocalUser.name (last part)
    EMAIL_ADDR / ZPS_UPNE_EMAILID -> LocalUser identity (email) — SoA correlation
    ZPS_LAN_ID                   -> LocalUser identity (LAN/AD username) — SoA correlation
    ZPS_LEG_LANID                -> LocalUser identity (legacy LAN username) — SoA correlation
    ZPS_CMI_ID                   -> LocalUser identity (CMI ID) — SoA correlation
    ALTER_EMPLID                 -> LocalUser identity (alternate employee ID) — SoA correlation
    EMPL_STATUS in ACTIVE_SET    -> LocalUser.is_active = True
    DEPTID                       -> LocalGroup.unique_id (department)
    DESCR                        -> LocalGroup.name  (department display name)

    Source of Authority notes
    ~~~~~~~~~~~~~~~~~~~~~~~~~
    When this provider is designated as Veza SoA, the identities list is the
    mechanism by which Veza correlates each PeopleSoft person to accounts in
    downstream systems (AD, SAP, etc.).  All non-empty identifier fields are
    included so Veza has the maximum number of correlation keys to work with.
    The ordering in identities is: primary email, UPN email, LAN ID, legacy
    LAN ID, CMI ID, alternate EMPLID.  Veza will attempt each in turn.
    """
    app = CustomApplication(
        name=args.datasource_name,
        application_type=args.provider_name,
    )

    # --- Custom permissions ---
    app.add_custom_permission("active_employee",    [OAAPermission.DataRead])
    app.add_custom_permission("department_member",  [OAAPermission.DataRead])

    # --- Custom property definitions for local users ---
    for prop_name in (
        "emplid",           "empl_rcd",          "empl_status_code",
        "empl_status_desc", "empl_type",          "per_org",
        "hire_date",        "last_date_worked",   "department_id",
        "department_name",  "company",            "company_name",
        "business_unit",    "location",           "position_nbr",
        "job_code",         "manager_id",         "lan_id",
        "legacy_lan_id",    "cmi_id",             "reg_region",
        "segment",          "org_group",          "function_code",
        "req_it_access",    "legal_hold",         "acquisition",
    ):
        app.property_definitions.define_local_user_property(prop_name, OAAPropertyType.STRING)
    log.debug("Registered custom user properties")

    # --- Streaming single-pass processing ---
    # Department groups are created lazily on first encounter so we avoid a
    # separate pre-pass.  registered_groups maps deptid -> display name.
    registered_groups: Dict[str, str] = {}

    active_count   = 0
    inactive_count = 0
    skipped_count  = 0
    page_num       = 0

    for page in employee_pages:
        page_num += 1

        for emp in page:
            emplid = emp.get("EMPLID", "").strip()
            if not emplid:
                log.warning("Skipping record with empty EMPLID (ROWKEY=%s)", emp.get("ROWKEY", "?"))
                skipped_count += 1
                continue

            # --- Lazily register department group ---
            deptid = emp.get("DEPTID", "").strip()
            if deptid and deptid not in registered_groups:
                gname = (emp.get("DESCR", "").strip()) or deptid
                app.add_local_group(name=gname, unique_id=deptid)
                registered_groups[deptid] = gname

            first = (emp.get("PREF_FIRST_NAME") or emp.get("FIRST_NAME") or "").strip()
            last  = (emp.get("ZPS_PREF_LAST_NAME") or emp.get("LAST_NAME") or "").strip()
            full_name = f"{first} {last}".strip() or emplid

            email: Optional[str] = (
                emp.get("EMAIL_ADDR") or emp.get("ZPS_UPNE_EMAILID") or ""
            ).strip() or None

            empl_status = emp.get("EMPL_STATUS", "").strip()
            is_active   = empl_status in ACTIVE_STATUS_CODES

            # Build the identities list — critical for Source of Authority (SoA) use.
            identities: List[str] = []
            if email:
                identities.append(email)
            upn_email = emp.get("ZPS_UPNE_EMAILID", "").strip()
            if upn_email and upn_email not in identities:
                identities.append(upn_email)
            lan_id = emp.get("ZPS_LAN_ID", "").strip()
            if lan_id:
                identities.append(lan_id)
            leg_lan = emp.get("ZPS_LEG_LANID", "").strip()
            if leg_lan and leg_lan not in identities:
                identities.append(leg_lan)
            cmi_id = emp.get("ZPS_CMI_ID", "").strip()
            if cmi_id:
                identities.append(cmi_id)
            alt_emplid = emp.get("ALTER_EMPLID", "").strip()
            if alt_emplid and alt_emplid not in identities:
                identities.append(alt_emplid)

            user = app.add_local_user(
                name=full_name,
                unique_id=emplid,
                identities=identities if identities else None,
            )
            user.is_active = is_active

            if is_active:
                user.add_permission("active_employee", apply_to_application=True)
                active_count += 1
            else:
                inactive_count += 1

            if deptid and deptid in registered_groups:
                user.add_group(registered_groups[deptid])
                user.add_permission("department_member", apply_to_application=True)

            # Custom properties
            user.set_property("emplid",            emplid)
            user.set_property("empl_rcd",          emp.get("EMPL_RCD",           ""))
            user.set_property("empl_status_code",  empl_status)
            user.set_property("empl_status_desc",  EMPL_STATUS_DESCRIPTIONS.get(empl_status, empl_status))
            user.set_property("empl_type",         emp.get("EMPL_TYPE",          ""))
            user.set_property("per_org",           emp.get("PER_ORG",            ""))
            user.set_property("hire_date",         emp.get("HIRE_DT",            ""))
            user.set_property("last_date_worked",  emp.get("LAST_DATE_WORKED",   ""))
            user.set_property("department_id",     emp.get("DEPTID",             ""))
            user.set_property("department_name",   emp.get("DESCR",              ""))
            user.set_property("company",           emp.get("COMPANY",            ""))
            user.set_property("company_name",      emp.get("DESCR30",            ""))
            user.set_property("business_unit",     emp.get("BUSINESS_UNIT",      ""))
            user.set_property("location",          emp.get("LOCATION",           ""))
            user.set_property("position_nbr",      emp.get("POSITION_NBR",       ""))
            user.set_property("job_code",          emp.get("JOBCODE",            ""))
            user.set_property("manager_id",        emp.get("MANAGER_ID",         ""))
            user.set_property("lan_id",            emp.get("ZPS_LAN_ID",         ""))
            user.set_property("legacy_lan_id",     emp.get("ZPS_LEG_LANID",      ""))
            user.set_property("cmi_id",            emp.get("ZPS_CMI_ID",         ""))
            user.set_property("reg_region",        emp.get("REG_REGION",         ""))
            user.set_property("segment",           emp.get("ZPS_SEGMENT",        ""))
            user.set_property("org_group",         emp.get("ZPS_GROUP",          ""))
            user.set_property("function_code",     emp.get("ZPS_FUNCTION",       ""))
            user.set_property("req_it_access",     emp.get("ZPS_REQ_IT_ACCESS",  ""))
            user.set_property("legal_hold",        emp.get("ZPS_LEGAL_HOLD",     ""))
            user.set_property("acquisition",       emp.get("ZPS_ACQUISITION",    ""))

        # Release raw page data before fetching the next page
        del page
        gc.collect()
        log.debug("Page %d processed and released from memory", page_num)

        ts = datetime.now().strftime("%H:%M:%S")
        total_users = active_count + inactive_count
        print(
            f"  [{ts}] Built page {page_num}: "
            f"{total_users:,} users added to payload "
            f"({active_count:,} active, {inactive_count:,} inactive) | "
            f"{len(registered_groups):,} departments | "
            f"{skipped_count:,} skipped",
            flush=True,
        )

    ts = datetime.now().strftime("%H:%M:%S")
    total_users = active_count + inactive_count
    print(
        f"  [{ts}] Payload build complete: "
        f"{total_users:,} users | {active_count:,} active | {inactive_count:,} inactive | "
        f"{len(registered_groups):,} departments | {skipped_count:,} skipped",
        flush=True,
    )
    log.info(
        "Payload summary: %d active users, %d inactive users, "
        "%d skipped (empty EMPLID), %d departments (across %d pages)",
        active_count, inactive_count, skipped_count, len(registered_groups), page_num,
    )
    return app


# ---------------------------------------------------------------------------
# Veza push
# ---------------------------------------------------------------------------

def push_to_veza(
    veza_url: str,
    veza_api_key: str,
    provider_name: str,
    datasource_name: str,
    app: CustomApplication,
    dry_run: bool = False,
    save_json: bool = False,
) -> None:
    """Optionally save JSON payload and push to Veza."""
    script_dir = os.path.dirname(os.path.abspath(__file__))

    if save_json:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        json_path = os.path.join(script_dir, f"oaa_payload_{ts}.json")
        try:
            raw = app.serialize()
            with open(json_path, "w", encoding="utf-8") as fh:
                if isinstance(raw, str):
                    fh.write(raw)
                else:
                    json.dump(raw, fh, indent=2)
            log.info("OAA payload saved to %s", json_path)
            print(f"Payload saved: {json_path}")
        except Exception as exc:  # noqa: BLE001
            log.warning("Could not save JSON payload: %s", exc)

    if dry_run:
        log.info("[DRY RUN] Payload built successfully — Veza push skipped")
        print("[DRY RUN] Payload built — push skipped")
        return

    log.info("Pushing to Veza: provider=%s datasource=%s", provider_name, datasource_name)
    veza_con = OAAClient(url=veza_url, token=veza_api_key)

    try:
        response = veza_con.push_application(
            provider_name=provider_name,
            data_source_name=datasource_name,
            application_object=app,
            create_provider=True,
        )
        if response and response.get("warnings"):
            for w in response["warnings"]:
                log.warning("Veza warning: %s", w)
        log.info(
            "Successfully pushed to Veza — provider=%s datasource=%s",
            provider_name, datasource_name,
        )
    except OAAClientError as exc:
        log.error(
            "Veza push failed: %s — %s (HTTP %s)",
            getattr(exc, "error",       "unknown"),
            getattr(exc, "message",     str(exc)),
            getattr(exc, "status_code", "?"),
        )
        if hasattr(exc, "details"):
            for detail in exc.details:
                log.error("  Detail: %s", detail)
        sys.exit(1)


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------

def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="PeopleSoft Diff -> Veza OAA integration",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )

    src = parser.add_argument_group("PeopleSoft source")
    src.add_argument(
        "--peoplesoft-url", metavar="URL",
        help="PeopleSoft base URL including port, e.g. https://host:5043  (env: PEOPLESOFT_BASE_URL)",
    )
    src.add_argument(
        "--peoplesoft-username", metavar="USER",
        help="PeopleSoft service account username  (env: PEOPLESOFT_USERNAME)",
    )
    src.add_argument(
        "--peoplesoft-password", metavar="PASS",
        help="PeopleSoft service account password  (env: PEOPLESOFT_PASSWORD)",
    )

    veza = parser.add_argument_group("Veza target")
    veza.add_argument(
        "--veza-url", metavar="URL",
        help="Veza instance URL  (env: VEZA_URL)",
    )
    veza.add_argument(
        "--veza-api-key", metavar="KEY",
        help="Veza API key  (env: VEZA_API_KEY)",
    )

    oaa = parser.add_argument_group("OAA settings")
    oaa.add_argument("--provider-name",    default=DEFAULT_PROVIDER_NAME,
                     help="Provider name shown in Veza")
    oaa.add_argument("--datasource-name",  default=DEFAULT_DATASOURCE_NAME,
                     help="Data source name shown in Veza")

    run = parser.add_argument_group("Run options")
    run.add_argument("--env-file",    default=".env",  help="Path to .env configuration file")
    run.add_argument("--dry-run",     action="store_true",
                     help="Build OAA payload but do not push to Veza")
    run.add_argument("--save-json",   action="store_true",
                     help="Save OAA payload as a JSON file for inspection")
    run.add_argument("--log-level",   default="INFO",
                     choices=["DEBUG", "INFO", "WARNING", "ERROR"],
                     help="Logging verbosity")
    run.add_argument(
        "--page-size",
        type=int,
        default=DEFAULT_PAGE_SIZE,
        metavar="N",
        help=(
            f"Number of employee records fetched per PeopleSoft API page "
            f"(default: {DEFAULT_PAGE_SIZE}). Reduce on memory-constrained hosts; "
            f"raise for fewer round-trips on well-resourced hosts."
        ),
    )
    run.add_argument(
        "--page-delay",
        type=float,
        default=0.0,
        metavar="SECONDS",
        help=(
            "Seconds to sleep between PeopleSoft API pages (default: 0). "
            "Use 0.5–2.0 on memory-constrained hosts to reduce sustained load "
            "on the InsightPoint or PeopleSoft server."
        ),
    )
    run.add_argument(
        "--staging-file",
        metavar="PATH",
        default=None,
        help=(
            f"Path for the JSONL staging file written by Phase 1 and consumed by Phase 2 "
            f"(default: <script_dir>/{STAGING_FILE_DEFAULT}).  "
            f"The file persists after the run so Phase 2 can be retried with --skip-fetch."
        ),
    )
    run.add_argument(
        "--skip-fetch",
        action="store_true",
        help=(
            "Skip Phase 1 (PeopleSoft fetch) and re-use an existing staging file.  "
            "Useful when the fetch already completed but the Veza push failed and needs "
            "to be retried without hitting PeopleSoft again."
        ),
    )

    return parser.parse_args()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    args = _parse_args()
    _setup_logging(args.log_level)

    script_dir = os.path.dirname(os.path.abspath(__file__))
    staging_path = args.staging_file or os.path.join(script_dir, STAGING_FILE_DEFAULT)

    print("=" * 60)
    print("  PeopleSoft Diff -> Veza OAA Integration")
    print(f"  Provider   : {args.provider_name}")
    print(f"  Datasource : {args.datasource_name}")
    print(f"  Page size  : {args.page_size} records/page")
    print(f"  Page delay : {args.page_delay}s")
    print(f"  Staging    : {staging_path}")
    print(f"  Skip fetch : {args.skip_fetch}")
    print(f"  Dry-run    : {args.dry_run}")
    print(f"  Save JSON  : {args.save_json}")
    print("=" * 60)

    cfg = load_config(args)

    # ------------------------------------------------------------------
    # Phase 1 — Fetch all PeopleSoft records to the JSONL staging file
    # ------------------------------------------------------------------
    if args.skip_fetch:
        if not os.path.exists(staging_path):
            log.error(
                "--skip-fetch was set but staging file does not exist: %s", staging_path
            )
            print(
                f"ERROR: --skip-fetch was set but staging file not found:\n  {staging_path}\n"
                "Run without --skip-fetch to fetch fresh data first."
            )
            sys.exit(1)
        staging_size = os.path.getsize(staging_path)
        log.info(
            "--skip-fetch: reusing existing staging file: %s (%d bytes)",
            staging_path, staging_size,
        )
        print(
            f"\nPhase 1  —  Skipped (--skip-fetch)\n"
            f"  Reusing staging file : {staging_path}\n"
            f"  File size            : {staging_size:,} bytes\n"
        )
    else:
        if args.page_delay > 0:
            log.info("Page delay enabled: %.1f seconds between PeopleSoft pages", args.page_delay)
        fetch_to_staging(
            cfg,
            staging_path=staging_path,
            page_size=args.page_size,
            page_delay=args.page_delay,
        )

    # ------------------------------------------------------------------
    # Phase 2 — Build OAA payload from staging file, then push to Veza
    # ------------------------------------------------------------------
    print(f"\nPhase 2  —  Build OAA payload from staging file")

    employee_pages = stream_staging_pages(staging_path, batch_size=args.page_size)
    app = build_oaa_payload(employee_pages, args)

    # Sanity check: if the app has no users the stream returned nothing
    user_count = len(getattr(app, "local_users", {}))
    if user_count == 0:
        log.warning("No employee records were processed — nothing to push")
        print("WARNING: No employee records returned. Verify the staging file and API connection.")
        sys.exit(0)

    push_to_veza(
        veza_url=cfg["veza_url"],
        veza_api_key=cfg["veza_api_key"],
        provider_name=args.provider_name,
        datasource_name=args.datasource_name,
        app=app,
        dry_run=args.dry_run,
        save_json=args.save_json,
    )


if __name__ == "__main__":
    main()
