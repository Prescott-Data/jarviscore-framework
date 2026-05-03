---
icon: material/connection
---

# System Bundles & Integrations

JarvisCore ships with **19 built-in system bundles** covering ~78 discrete, versioned atoms. Each atom is a self-contained, ready-to-use tool that your agents can call directly — no wrapper code required. Bundles cover CRM, productivity, data, email, payments, developer tools, and more.

---

## Using Atoms

Atoms are registered automatically at framework startup. Reference them by name in your `system_prompt` — the agent's `FunctionRegistry` makes them available to generated code:

```python
from jarviscore import AutoAgent

class OpsAgent(AutoAgent):
    role = "ops"
    capabilities = ["slack", "jira", "notion"]
    system_prompt = """
    You have access to Slack, Jira, and Notion atoms.
    Use slack_send_message_v1 to send notifications.
    Use jira_create_issue_v1 to create tickets.
    Use notion_create_page_v1 to document findings.
    Always store your final result in `result`.
    """
```

Or load a full bundle by registering it in `setup()`:

```python
from jarviscore import AutoAgent
from jarviscore.integrations.atoms.slack import get_atoms

class CommsAgent(AutoAgent):
    role = "comms"
    capabilities = ["slack"]
    system_prompt = "Send Slack messages. Store result in `result`."

    async def setup(self):
        await super().setup()
        for atom in get_atoms():
            self._registry.register(atom)
```

Each atom follows the versioned naming convention: `{provider}_{action}_v{n}`. The `v1` suffix ensures existing agent configurations remain stable when new versions are introduced.

---

## Bundle Catalog

### Airtable

Low-code database for structured data, content pipelines, and product operations.

| Atom | Description |
|---|---|
| `airtable_create_record_v1` | Create a new record in a table |
| `airtable_get_record_v1` | Fetch a single record by ID |
| `airtable_list_records_v1` | List all records in a table with optional filter |
| `airtable_search_records_v1` | Search records by field value |
| `airtable_update_record_v1` | Update fields on an existing record |

**Required env:** `AIRTABLE_API_KEY`, `AIRTABLE_BASE_ID`

---

### Apollo

B2B sales intelligence for prospecting and enrichment.

| Atom | Description |
|---|---|
| `apollo_get_person_v1` | Look up a person by email or LinkedIn URL |
| `apollo_search_organizations_v1` | Search companies by name, domain, or industry |
| `apollo_search_people_v1` | Find leads matching title, seniority, or location filters |

**Required env:** `APOLLO_API_KEY`

---

### Brevo (formerly Sendinblue)

Transactional email and contact management.

| Atom | Description |
|---|---|
| `brevo_create_contact_v1` | Create or update a contact |
| `brevo_get_contacts_v1` | List contacts with optional filter |
| `brevo_send_email_v1` | Send a transactional email |

**Required env:** `BREVO_API_KEY`

---

### GitHub

Source control, issues, pull requests, and repository management.

| Atom | Description |
|---|---|
| `github_create_comment_v1` | Post a comment on an issue or pull request |
| `github_create_issue_v1` | Open a new issue in a repository |
| `github_get_file_v1` | Fetch the contents of a file from a branch |
| `github_get_pull_request_v1` | Retrieve a pull request by number |
| `github_get_repo_v1` | Fetch repository metadata |
| `github_list_issues_v1` | List issues with state and label filters |
| `github_list_pull_requests_v1` | List open or closed pull requests |
| `github_list_repos_v1` | List repositories for a user or organisation |

**Required env:** `GITHUB_TOKEN`

---

### Gmail

Send, read, and draft emails from a Google Workspace account.

| Atom | Description |
|---|---|
| `gmail_create_draft_v1` | Create a draft email (does not send) |
| `gmail_get_message_v1` | Fetch a message by ID |
| `gmail_list_messages_v1` | List messages matching a query |
| `gmail_send_email_v1` | Send an email immediately |

**Required env:** `GMAIL_CREDENTIALS_JSON` (OAuth2 service account or user credentials)

---

### Google Calendar

Read and write calendar events for scheduling automation.

| Atom | Description |
|---|---|
| `google_calendar_create_event_v1` | Create a calendar event with attendees and location |
| `google_calendar_delete_event_v1` | Cancel and delete an event |
| `google_calendar_list_events_v1` | List upcoming events in a date range |

**Required env:** `GOOGLE_CALENDAR_CREDENTIALS_JSON`

---

### Google Drive

File storage, sharing, and folder management.

| Atom | Description |
|---|---|
| `google_drive_create_folder_v1` | Create a new folder |
| `google_drive_download_file_v1` | Download a file by ID |
| `google_drive_share_file_v1` | Set sharing permissions on a file or folder |
| `google_drive_upload_file_v1` | Upload a file to a specific folder |

**Required env:** `GOOGLE_DRIVE_CREDENTIALS_JSON`

---

### Google Sheets

Read and write structured data to spreadsheets.

| Atom | Description |
|---|---|
| `google_sheets_append_rows_v1` | Append rows to the end of a sheet |
| `google_sheets_get_spreadsheet_v1` | Fetch spreadsheet metadata and sheet names |
| `google_sheets_read_range_v1` | Read a cell range (e.g. `Sheet1!A1:D10`) |
| `google_sheets_write_range_v1` | Write values to a specific range |

**Required env:** `GOOGLE_SHEETS_CREDENTIALS_JSON`

---

### HubSpot

CRM contacts, deals, and pipeline management.

| Atom | Description |
|---|---|
| `hubspot_create_contact_v1` | Create a new CRM contact |
| `hubspot_create_deal_v1` | Open a new deal in a pipeline |
| `hubspot_get_contact_v1` | Fetch a contact by ID or email |
| `hubspot_list_contacts_v1` | List contacts with pagination |
| `hubspot_list_deals_v1` | List deals with stage filter |

**Required env:** `HUBSPOT_API_KEY`

---

### Jira

Issue tracking, project management, and sprint workflows.

| Atom | Description |
|---|---|
| `jira_create_issue_v1` | Create a new ticket (bug, story, task, etc.) |
| `jira_get_project_v1` | Fetch project metadata and issue type schemes |
| `jira_update_issue_v1` | Update fields, status, or assignee on an existing ticket |

**Required env:** `JIRA_BASE_URL`, `JIRA_EMAIL`, `JIRA_API_TOKEN`

---

### Linear

Modern software project management for engineering teams.

| Atom | Description |
|---|---|
| `linear_get_issue_v1` | Fetch a single issue by ID |
| `linear_get_issues_v1` | List issues for a team or project |
| `linear_get_me_v1` | Get the authenticated user's profile |
| `linear_get_teams_v1` | List all teams in the workspace |
| `linear_search_issues_v1` | Full-text search across issues |

**Required env:** `LINEAR_API_KEY`

---

### Mailchimp

Email marketing, audience management, and campaign analytics.

| Atom | Description |
|---|---|
| `mailchimp_add_subscriber_v1` | Add or update a subscriber in an audience |
| `mailchimp_get_campaign_stats_v1` | Retrieve open rate, click rate, and unsubscribes for a campaign |
| `mailchimp_get_list_members_v1` | List members of an audience |

**Required env:** `MAILCHIMP_API_KEY`, `MAILCHIMP_SERVER_PREFIX`

---

### Notion

Docs, wikis, databases, and knowledge base management.

| Atom | Description |
|---|---|
| `notion_append_blocks_v1` | Append content blocks to an existing page |
| `notion_create_page_v1` | Create a new page in a workspace or database |
| `notion_get_blocks_v1` | Fetch all blocks (content) from a page |
| `notion_get_page_v1` | Retrieve page metadata and properties |
| `notion_search_v1` | Search across all pages and databases |
| `notion_update_page_v1` | Update page properties (title, status, dates, etc.) |

**Required env:** `NOTION_API_KEY`

---

### QuickBooks

Accounting, invoicing, and financial reporting for small to mid-size businesses.

| Atom | Description |
|---|---|
| `quickbooks_get_balance_sheet_v1` | Fetch a balance sheet report for a date range |
| `quickbooks_get_profit_and_loss_v1` | Fetch a P&L report for a period |
| `quickbooks_list_expenses_v1` | List expense transactions with filters |
| `quickbooks_list_invoices_v1` | List invoices by customer or status |

**Required env:** `QUICKBOOKS_CLIENT_ID`, `QUICKBOOKS_CLIENT_SECRET`, `QUICKBOOKS_REFRESH_TOKEN`, `QUICKBOOKS_REALM_ID`

---

### Salesforce

Enterprise CRM — leads, opportunities, contacts, and custom SOQL queries.

| Atom | Description |
|---|---|
| `salesforce_create_lead_v1` | Create a new lead record |
| `salesforce_create_opportunity_v1` | Open a new opportunity in a stage |
| `salesforce_get_contact_v1` | Fetch a contact by ID or email |
| `salesforce_soql_query_v1` | Run an arbitrary SOQL query and return results |

**Required env:** `SALESFORCE_USERNAME`, `SALESFORCE_PASSWORD`, `SALESFORCE_SECURITY_TOKEN`

---

### SendGrid

Transactional email delivery with analytics.

| Atom | Description |
|---|---|
| `sendgrid_get_stats_v1` | Retrieve delivery, open, and click stats for a date range |
| `sendgrid_send_email_v1` | Send a transactional email via SendGrid |

**Required env:** `SENDGRID_API_KEY`

---

### Serper

Google Search results via API — web search and news search.

| Atom | Description |
|---|---|
| `serper_news_search_v1` | Search Google News for recent articles |
| `serper_search_v1` | Perform a Google web search and return top results |

**Required env:** `SERPER_API_KEY`

---

### Slack

Team messaging, notifications, and workspace management.

| Atom | Description |
|---|---|
| `slack_add_reaction_v1` | Add an emoji reaction to a message |
| `slack_get_messages_v1` | Fetch message history from a channel |
| `slack_get_user_v1` | Look up a user profile by ID or email |
| `slack_list_channels_v1` | List public and private channels |
| `slack_list_users_v1` | List all workspace members |
| `slack_send_message_v1` | Send a message to a channel or user |

**Required env:** `SLACK_BOT_TOKEN`

---

### Stripe

Payments, subscriptions, and financial reporting.

| Atom | Description |
|---|---|
| `stripe_get_balance_v1` | Fetch the current account balance |
| `stripe_get_customer_v1` | Retrieve a customer record by ID |
| `stripe_list_charges_v1` | List charges with date and status filters |
| `stripe_list_invoices_v1` | List invoices for a customer or subscription |

**Required env:** `STRIPE_SECRET_KEY`

---

## Configuration

All credentials are read from environment variables at call time. Set them in your shell, `.env` file, or secrets manager:

```bash
# Example .env
SLACK_BOT_TOKEN=xoxb-...
NOTION_API_KEY=secret_...
GITHUB_TOKEN=ghp_...
STRIPE_SECRET_KEY=sk_live_...
```

With [python-dotenv](https://pypi.org/project/python-dotenv/):

```python
from dotenv import load_dotenv
load_dotenv()
```

Or inject via your orchestration platform (Kubernetes Secrets, AWS Secrets Manager, HashiCorp Vault).

---

## Building Custom Atoms

Write an atom as a plain Python function. The function signature is the atom's contract — every parameter becomes an argument the agent passes when calling it. Return a dict.

```python
def linear_close_issue(auth_info: dict, issue_id: str, comment: str = "") -> dict:
    """Close an issue in Linear with an optional comment."""
    import httpx
    headers = {"Authorization": auth_info["token"]}
    r = httpx.patch(
        f"https://api.linear.app/graphql",
        headers=headers,
        json={"query": "mutation { issueUpdate(id: $id, input: {stateId: $stateId}) { success } }"},
    )
    return {"success": r.status_code == 200, "issue_id": issue_id}
```

Then register it in your agent's `setup()`:

```python
from jarviscore.execution.code_registry import FunctionRegistry

class LinearAgent(AutoAgent):
    role = "linear_agent"
    capabilities = ["linear", "issue-management"]
    system_prompt = """
    Use linear_close_issue(auth_info, issue_id) to close resolved issues.
    Store confirmation in `result`.
    """

    async def setup(self):
        await super().setup()
        registry = FunctionRegistry()
        registry.register_function(
            function_name="linear_close_issue",
            source_code=inspect.getsource(linear_close_issue),
            system="linear",
            description="Close an issue in Linear with an optional comment",
            capabilities=["issue-management"],
        )
```

---

## FunctionRegistry and Atom Graduation

The `FunctionRegistry` is the internal quality system for generated and registered atoms. Every atom goes through a three-stage graduation pipeline:

`CANDIDATE` means the atom was just registered or generated. It has not been executed successfully yet. The Coder will write fresh code rather than reuse a candidate unless it scores highly on semantic search.

`VERIFIED` means the atom has had at least one successful sandbox execution. The Coder prefers verified atoms over generating new code for the same task.

`GOLDEN` means the atom has had five or more successful executions. Golden atoms are the Coder's first choice for any matching task. They appear in the bundle generated for `create_system_bundle()`.

This promotion happens automatically. When the `CoderSubAgent` successfully executes code, it calls `register_function()` and the registry increments the execution count and promotes the stage. You never call promote or update the stage manually.

Manually registered atoms start at `CANDIDATE`. They are promoted to `VERIFIED` the first time an agent successfully calls them.

The registry persists to disk at `FUNCTION_REGISTRY_PATH` (default: `./logs/function_registry`) and optionally syncs to blob storage for distributed deployments:

```bash title=".env"
FUNCTION_REGISTRY_PATH=/data/registry
FUNCTION_REGISTRY_BLOB_PREFIX=function_registry   # syncs to blob storage
```

---

## Sharing Atoms with the Community

There is no marketplace or package registry for JarvisCore atoms. To make an atom available to all JarvisCore users, open a pull request to the [jarviscore-framework repository](https://github.com/prescott-data/jarviscore-framework) with:

1. The atom file in `jarviscore/integrations/atoms/{provider}/{function_name}.py`
2. A provider entry in `jarviscore/integrations/seed_registry.py` with metadata (category, auth type, capabilities)
3. Documentation in `jarviscore/docs/guides/integrations.md`

Atoms merged into the framework ship with the next release and are available to every developer who runs `pip install jarviscore`.

---

## Summary

| Category | Bundles | Total Atoms |
|---|---|---|
| Productivity | Google Drive, Google Sheets, Google Calendar, Notion, Airtable | 23 |
| Communication | Gmail, Slack, Brevo, SendGrid, Mailchimp | 16 |
| CRM and Sales | HubSpot, Salesforce, Apollo | 12 |
| Developer Tools | GitHub, Jira, Linear | 16 |
| Payments and Finance | Stripe, QuickBooks | 8 |
| Search and Data | Serper | 2 |
| Total | 19 bundles | approximately 77 atoms |
