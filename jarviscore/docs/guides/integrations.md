---
icon: material/connection
---

# System Bundles & Integrations

JarvisCore ships with **46 built-in system bundles** covering 237+ discrete, versioned atoms. Each atom is a self-contained, ready-to-use tool your agents can call directly — no wrapper code required. Bundles span communication, productivity, CRM, ERP, finance, HR, developer tools, content, advertising, storage, healthcare, and more.

---

## How Atoms Work

Atoms are **pre-loaded into the FunctionRegistry** at startup via `seed_registry`, and from that point forward the Kernel's **Option A semantic search** handles discovery automatically. You do not enumerate atom names in your agent code or prompt.

### The auto-pick flow

When a task arrives, before generating any code the Kernel searches the registry semantically:

```
Task: "Send a Slack notification to #ops"
  → Kernel Option A: semantic_search("Send a Slack notification")
  → Finds: slack_send_message (stage=verified, score=4.2)
  → Injects code directly into sandbox — skips code generation entirely
```

If the search finds a `verified` or `golden` match above the confidence threshold, the Kernel reuses it. If not, `CoderSubAgent` generates fresh code.

### What devs actually write

An agent that calls Slack, Jira, and Notion needs nothing special — just a clear `system_prompt`:

```python
from jarviscore import AutoAgent

class OpsAgent(AutoAgent):
    role = "ops"
    system_prompt = """
    You are an operations agent. You send Slack notifications,
    open Jira tickets, and document findings in Notion.
    """
```

The Kernel auto-picks the right atom when the task matches. The `capabilities` field on an agent is **descriptive metadata** — it does not control which atoms are loaded.

### Seeding the registry

`seed_registry` runs automatically when the framework initialises. All 46 bundles are seeded into the registry on first startup. You can also call it manually:

```python
from jarviscore.integrations.seed_registry import seed_registry
from jarviscore.execution.code_registry import FunctionRegistry

registry = FunctionRegistry()
seed_registry(registry)
```

This is only needed if you are initialising a registry outside the normal agent lifecycle (e.g. in a standalone script or test fixture).

---

## Bundle Catalog

### Communication

#### Slack
Team messaging, notifications, and workspace management.

| Atom | Description |
|---|---|
| `slack_send_message` | Send a message to a channel or user |
| `slack_get_messages` | Fetch message history from a channel |
| `slack_list_channels` | List public and private channels |
| `slack_list_users` | List all workspace members |
| `slack_get_user` | Look up a user profile by ID or email |
| `slack_add_reaction` | Add an emoji reaction to a message |

**Required env:** `SLACK_BOT_TOKEN`

---

#### Zoom
Meeting scheduling, management, and user administration.

| Atom | Description |
|---|---|
| `zoom_create_meeting` | Schedule a new Zoom meeting |
| `zoom_get_meeting` | Fetch meeting details by ID |
| `zoom_list_meetings` | List upcoming meetings for a user |
| `zoom_update_meeting` | Update meeting settings or schedule |
| `zoom_delete_meeting` | Cancel and delete a meeting |
| `zoom_get_user` | Fetch a Zoom user's profile |

**Required env:** `ZOOM_CLIENT_ID`, `ZOOM_CLIENT_SECRET`, `ZOOM_ACCOUNT_ID`

---

#### Discord
Guild membership, connections, and identity.

| Atom | Description |
|---|---|
| `discord_get_me` | Get the authenticated user's profile |
| `discord_get_guilds` | List guilds (servers) the user belongs to |
| `discord_get_connections` | List the user's connected accounts |

**Required env:** `DISCORD_BOT_TOKEN`

---

#### Webex
Messaging, rooms, and people search.

| Atom | Description |
|---|---|
| `webex_get_me` | Get the authenticated user's profile |
| `webex_get_rooms` | List Webex spaces/rooms |
| `webex_get_room` | Fetch details of a specific room |
| `webex_get_messages` | List messages in a room |
| `webex_get_message` | Fetch a single message |
| `webex_search_people` | Search for Webex users |

**Required env:** `WEBEX_ACCESS_TOKEN`

---

#### Microsoft Graph (Teams, Outlook, Calendar)
Email, calendar, Teams chat, and meetings via the Microsoft Graph API.

| Atom | Description |
|---|---|
| `msgraph_send_email` | Send an email via Outlook |
| `msgraph_get_emails` | List emails in a mailbox folder |
| `msgraph_get_email` | Fetch a single email by ID |
| `msgraph_get_teams` | List Microsoft Teams the user belongs to |
| `msgraph_get_channels` | List channels in a Team |
| `msgraph_get_chats` | List personal chats |
| `msgraph_send_chat_message` | Send a message to a chat or channel |
| `msgraph_create_event` | Create a calendar event |
| `msgraph_get_events` | List calendar events |
| `msgraph_update_event` | Update an existing calendar event |
| `msgraph_delete_event` | Delete a calendar event |
| `msgraph_create_meeting` | Schedule an online Teams meeting |
| `msgraph_get_meeting` | Fetch online meeting details |
| `msgraph_get_me` | Get the authenticated user's profile |

**Required env:** `MSGRAPH_CLIENT_ID`, `MSGRAPH_CLIENT_SECRET`, `MSGRAPH_TENANT_ID`

---

#### Gmail
Send, read, and draft emails from a Google Workspace account.

| Atom | Description |
|---|---|
| `gmail_send_email` | Send an email immediately |
| `gmail_get_message` | Fetch a message by ID |
| `gmail_list_messages` | List messages matching a query |
| `gmail_create_draft` | Create a draft email (does not send) |

**Required env:** `GMAIL_CREDENTIALS_JSON`

---

### Productivity

#### Notion
Docs, wikis, databases, and knowledge base management.

| Atom | Description |
|---|---|
| `notion_create_page` | Create a new page in a workspace or database |
| `notion_get_page` | Retrieve page metadata and properties |
| `notion_get_blocks` | Fetch all blocks (content) from a page |
| `notion_append_blocks` | Append content blocks to an existing page |
| `notion_update_page` | Update page properties |
| `notion_search` | Search across all pages and databases |

**Required env:** `NOTION_API_KEY`

---

#### Confluence
Atlassian wiki pages and spaces.

| Atom | Description |
|---|---|
| `confluence_create_page` | Create a new Confluence page |
| `confluence_get_page` | Fetch page content and metadata |
| `confluence_update_page` | Update an existing page's content |

**Required env:** `CONFLUENCE_URL`, `CONFLUENCE_EMAIL`, `CONFLUENCE_API_TOKEN`

---

#### ClickUp
Task and project management.

| Atom | Description |
|---|---|
| `clickup_create_task` | Create a new task in a list |
| `clickup_get_task` | Fetch task details by ID |
| `clickup_update_task` | Update task status, priority, or fields |
| `clickup_create_comment` | Add a comment to a task |
| `clickup_get_lists` | List all lists in a space |
| `clickup_get_spaces` | List all spaces in a workspace |

**Required env:** `CLICKUP_API_KEY`

---

#### Todoist
Personal task management and projects.

| Atom | Description |
|---|---|
| `todoist_create_task` | Create a new task |
| `todoist_get_task` | Fetch a task by ID |
| `todoist_update_task` | Update task content, due date, or priority |
| `todoist_close_task` | Mark a task as complete |
| `todoist_get_projects` | List all projects |
| `todoist_create_project` | Create a new project |

**Required env:** `TODOIST_API_KEY`

---

#### Google Drive
File storage, sharing, and folder management.

| Atom | Description |
|---|---|
| `gdrive_upload_file` | Upload a file to a specific folder |
| `gdrive_download_file` | Download a file by ID |
| `gdrive_create_folder` | Create a new folder |
| `gdrive_share_file` | Set sharing permissions on a file or folder |

**Required env:** `GOOGLE_DRIVE_CREDENTIALS_JSON`

---

#### Dropbox
Cloud file storage and sharing.

| Atom | Description |
|---|---|
| `dropbox_upload_file` | Upload a file to Dropbox |
| `dropbox_download_file` | Download a file from Dropbox |
| `dropbox_list_folder` | List contents of a folder |
| `dropbox_create_folder` | Create a new folder |
| `dropbox_get_shared_link` | Get or create a shared link for a file |

**Required env:** `DROPBOX_ACCESS_TOKEN`

---

#### Google Sheets
Read and write structured data to spreadsheets.

| Atom | Description |
|---|---|
| `google_sheets_read_range` | Read a cell range |
| `google_sheets_write_range` | Write values to a range |
| `google_sheets_append_rows` | Append rows to the end of a sheet |
| `google_sheets_get_spreadsheet` | Fetch spreadsheet metadata |

**Required env:** `GOOGLE_SHEETS_CREDENTIALS_JSON`

---

#### Google Calendar
Read and write calendar events for scheduling automation.

| Atom | Description |
|---|---|
| `google_calendar_create_event` | Create a calendar event with attendees |
| `google_calendar_list_events` | List upcoming events in a date range |
| `google_calendar_delete_event` | Cancel and delete an event |

**Required env:** `GOOGLE_CALENDAR_CREDENTIALS_JSON`

---

#### Airtable
Low-code database for structured data and content pipelines.

| Atom | Description |
|---|---|
| `airtable_create_record` | Create a new record in a table |
| `airtable_get_record` | Fetch a single record by ID |
| `airtable_list_records` | List all records with optional filter |
| `airtable_search_records` | Search records by field value |
| `airtable_update_record` | Update fields on an existing record |

**Required env:** `AIRTABLE_API_KEY`, `AIRTABLE_BASE_ID`

---

### Developer Tools

#### GitHub
Source control, issues, pull requests, and repository management.

| Atom | Description |
|---|---|
| `github_create_issue` | Open a new issue |
| `github_create_comment` | Post a comment on an issue or PR |
| `github_get_file` | Fetch a file from a branch |
| `github_get_pull_request` | Retrieve a pull request |
| `github_get_repo` | Fetch repository metadata |
| `github_list_issues` | List issues with state and label filters |
| `github_list_pull_requests` | List open or closed pull requests |
| `github_list_repos` | List repositories for a user or org |

**Required env:** `GITHUB_TOKEN`

---

#### Jira
Issue tracking, project management, and sprint workflows.

| Atom | Description |
|---|---|
| `jira_create_issue` | Create a new ticket |
| `jira_get_project` | Fetch project metadata |
| `jira_update_issue` | Update fields, status, or assignee |

**Required env:** `JIRA_BASE_URL`, `JIRA_EMAIL`, `JIRA_API_TOKEN`

---

#### Linear
Modern engineering project management.

| Atom | Description |
|---|---|
| `linear_get_issue` | Fetch a single issue by ID |
| `linear_get_issues` | List issues for a team or project |
| `linear_get_teams` | List all teams in the workspace |
| `linear_get_me` | Get the authenticated user's profile |
| `linear_search_issues` | Full-text search across issues |

**Required env:** `LINEAR_API_KEY`

---

#### Bamboo CI
Atlassian Bamboo build and deployment pipelines.

| Atom | Description |
|---|---|
| `bamboo_list_projects` | List all Bamboo projects |
| `bamboo_list_plans` | List build plans |
| `bamboo_get_plan` | Fetch plan details |
| `bamboo_trigger_build` | Trigger a build for a plan |
| `bamboo_get_build_results` | Fetch build results |
| `bamboo_list_deployments` | List deployment environments |

**Required env:** `BAMBOO_URL`, `BAMBOO_USERNAME`, `BAMBOO_PASSWORD`

---

### CRM

#### HubSpot
CRM contacts, deals, and pipeline management.

| Atom | Description |
|---|---|
| `hubspot_create_contact` | Create a new CRM contact |
| `hubspot_get_contact` | Fetch a contact by ID or email |
| `hubspot_list_contacts` | List contacts with pagination |
| `hubspot_create_deal` | Open a new deal in a pipeline |
| `hubspot_list_deals` | List deals with stage filter |

**Required env:** `HUBSPOT_API_KEY`

---

#### Salesforce
Enterprise CRM — leads, opportunities, contacts, and SOQL.

| Atom | Description |
|---|---|
| `salesforce_create_lead` | Create a new lead record |
| `salesforce_create_opportunity` | Open a new opportunity |
| `salesforce_get_contact` | Fetch a contact by ID or email |
| `salesforce_soql_query` | Run an arbitrary SOQL query |

**Required env:** `SALESFORCE_USERNAME`, `SALESFORCE_PASSWORD`, `SALESFORCE_SECURITY_TOKEN`

---

#### Microsoft Dynamics
CRM accounts, contacts, and pipeline management.

| Atom | Description |
|---|---|
| `dynamics_create_account` | Create a new account |
| `dynamics_get_accounts` | List accounts |
| `dynamics_get_contacts` | List contacts |

**Required env:** `DYNAMICS_CLIENT_ID`, `DYNAMICS_CLIENT_SECRET`, `DYNAMICS_TENANT_ID`

---

#### Oracle CX (Sales Cloud)
Enterprise CRM for accounts, contacts, opportunities, and activities.

| Atom | Description |
|---|---|
| `oracle_cx_list_accounts` | List CRM accounts |
| `oracle_cx_list_contacts` | List contacts |
| `oracle_cx_list_opportunities` | List opportunities |
| `oracle_cx_create_opportunity` | Create a new opportunity |
| `oracle_cx_get_opportunity` | Fetch an opportunity by ID |
| `oracle_cx_list_activities` | List sales activities |

**Required env:** `ORACLE_CX_BASE_URL`, `ORACLE_CX_USERNAME`, `ORACLE_CX_PASSWORD`

---

#### Apollo
B2B sales intelligence for prospecting and enrichment.

| Atom | Description |
|---|---|
| `apollo_get_person` | Look up a person by email or LinkedIn URL |
| `apollo_search_organizations` | Search companies by name, domain, or industry |
| `apollo_search_people` | Find leads matching title, seniority, or location |

**Required env:** `APOLLO_API_KEY`

---

### ERP

#### NetSuite
ERP records, customers, and financial data.

| Atom | Description |
|---|---|
| `netsuite_create_record` | Create a NetSuite record |
| `netsuite_get_record` | Fetch a record by ID and type |
| `netsuite_update_record` | Update a record's fields |
| `netsuite_list_customers` | List customer records |
| `netsuite_list_records` | List records of a given type |
| `netsuite_search_records` | Search records with filters |

**Required env:** `NETSUITE_ACCOUNT_ID`, `NETSUITE_CONSUMER_KEY`, `NETSUITE_CONSUMER_SECRET`, `NETSUITE_TOKEN_ID`, `NETSUITE_TOKEN_SECRET`

---

#### Odoo
Open-source ERP — leads, partners, and invoices.

| Atom | Description |
|---|---|
| `odoo_create_lead` | Create a CRM lead |
| `odoo_get_lead` | Fetch a lead by ID |
| `odoo_get_leads` | List leads with filters |
| `odoo_update_lead` | Update lead fields |
| `odoo_create_partner` | Create a partner (customer/vendor) |
| `odoo_get_partners` | List partners |

**Required env:** `ODOO_URL`, `ODOO_DB`, `ODOO_USERNAME`, `ODOO_PASSWORD`

---

#### SAP
Purchase orders, sales orders, and business partners.

| Atom | Description |
|---|---|
| `sap_list_purchase_orders` | List purchase orders |
| `sap_get_sales_order` | Fetch a sales order by ID |
| `sap_list_sales_orders` | List sales orders |
| `sap_list_business_partners` | List business partners |
| `sap_get_business_partner` | Fetch a business partner |
| `sap_list_products` | List products/materials |

**Required env:** `SAP_BASE_URL`, `SAP_USERNAME`, `SAP_PASSWORD`

---

#### Oracle ERP Cloud
Invoices, journals, expenses, purchase orders, and suppliers.

| Atom | Description |
|---|---|
| `oracle_erp_list_invoices` | List payable invoices |
| `oracle_erp_get_invoice` | Fetch an invoice by ID |
| `oracle_erp_list_journal_entries` | List general ledger journal entries |
| `oracle_erp_list_purchase_orders` | List purchase orders |
| `oracle_erp_list_expenses` | List expense reports |
| `oracle_erp_list_suppliers` | List supplier records |

**Required env:** `ORACLE_ERP_BASE_URL`, `ORACLE_ERP_USERNAME`, `ORACLE_ERP_PASSWORD`

---

### Finance

#### Stripe
Payments, subscriptions, and financial reporting.

| Atom | Description |
|---|---|
| `stripe_get_balance` | Fetch the current account balance |
| `stripe_get_customer` | Retrieve a customer record |
| `stripe_list_charges` | List charges with date and status filters |
| `stripe_list_invoices` | List invoices for a customer |

**Required env:** `STRIPE_SECRET_KEY`

---

#### QuickBooks
Accounting, invoicing, and financial reporting.

| Atom | Description |
|---|---|
| `quickbooks_get_profit_and_loss` | Fetch a P&L report |
| `quickbooks_get_balance_sheet` | Fetch a balance sheet report |
| `quickbooks_list_invoices` | List invoices by customer or status |
| `quickbooks_list_expenses` | List expense transactions |

**Required env:** `QUICKBOOKS_CLIENT_ID`, `QUICKBOOKS_CLIENT_SECRET`, `QUICKBOOKS_REFRESH_TOKEN`, `QUICKBOOKS_REALM_ID`

---

#### FreshBooks
Invoicing, clients, and expense tracking for SMBs.

| Atom | Description |
|---|---|
| `freshbooks_create_client` | Create a new client |
| `freshbooks_get_client` | Fetch a client by ID |
| `freshbooks_create_invoice` | Create a new invoice |
| `freshbooks_get_invoice` | Fetch an invoice |
| `freshbooks_create_expense` | Record an expense |
| `freshbooks_get_expense` | Fetch an expense |
| `freshbooks_record_payment` | Record a payment on an invoice |
| `freshbooks_get_payment` | Fetch a payment record |

**Required env:** `FRESHBOOKS_CLIENT_ID`, `FRESHBOOKS_CLIENT_SECRET`, `FRESHBOOKS_ACCESS_TOKEN`

---

#### Zoho Books
Cloud accounting — invoices, expenses, and contacts.

| Atom | Description |
|---|---|
| `zoho_books_create_invoice` | Create a new invoice |
| `zoho_books_get_invoice` | Fetch an invoice by ID |
| `zoho_books_get_invoices` | List invoices |
| `zoho_books_create_contact` | Create a customer or vendor |
| `zoho_books_get_contact` | Fetch a contact |
| `zoho_books_get_contacts` | List contacts |
| `zoho_books_create_expense` | Record an expense |
| `zoho_books_get_expenses` | List expenses |

**Required env:** `ZOHO_BOOKS_CLIENT_ID`, `ZOHO_BOOKS_CLIENT_SECRET`, `ZOHO_BOOKS_REFRESH_TOKEN`, `ZOHO_BOOKS_ORG_ID`

---

### HR

#### Zoho People
Employee directory, attendance, and HR forms.

| Atom | Description |
|---|---|
| `zoho_people_get_employee` | Fetch an employee record |
| `zoho_people_get_all_employees` | List all employees |
| `zoho_people_get_attendance` | Fetch attendance records |
| `zoho_people_get_form_data` | Fetch data from a Zoho People form |

**Required env:** `ZOHO_PEOPLE_ACCESS_TOKEN`

---

#### Zoho Shifts
Shift scheduling and workforce management.

| Atom | Description |
|---|---|
| `zoho_shifts_get_shifts` | List shifts for a schedule |
| `zoho_shifts_create_shift` | Create a new shift |
| `zoho_shifts_update_shift` | Update a shift |
| `zoho_shifts_delete_shift` | Delete a shift |

**Required env:** `ZOHO_SHIFTS_API_KEY`

---

### Content & Social

#### LinkedIn
Organic posts, profile, and network information.

| Atom | Description |
|---|---|
| `linkedin_create_post` | Create a LinkedIn post |
| `linkedin_list_posts` | List posts for a user or org |
| `linkedin_get_profile` | Fetch the authenticated user's profile |
| `linkedin_get_organization` | Fetch an organization profile |
| `linkedin_list_organization_posts` | List posts for an organization |
| `linkedin_get_network_size` | Get first-degree connection count |

**Required env:** `LINKEDIN_CLIENT_ID`, `LINKEDIN_CLIENT_SECRET`, `LINKEDIN_ACCESS_TOKEN`

---

#### LinkedIn Ads
Campaign management and advertising analytics.

| Atom | Description |
|---|---|
| `linkedin_ads_list_accounts` | List ad accounts |
| `linkedin_ads_list_campaign_groups` | List campaign groups |
| `linkedin_ads_list_campaigns` | List campaigns |
| `linkedin_ads_get_campaign` | Fetch a campaign by ID |
| `linkedin_ads_list_creatives` | List ad creatives |
| `linkedin_ads_get_analytics` | Fetch campaign performance analytics |

**Required env:** `LINKEDIN_ADS_CLIENT_ID`, `LINKEDIN_ADS_CLIENT_SECRET`, `LINKEDIN_ADS_ACCESS_TOKEN`

---

#### YouTube
Video, playlist, and channel management.

| Atom | Description |
|---|---|
| `youtube_search` | Search YouTube for videos |
| `youtube_get_video` | Fetch video details by ID |
| `youtube_list_videos` | List videos for a channel |
| `youtube_get_channel` | Fetch channel metadata |
| `youtube_list_playlists` | List playlists for a channel |
| `youtube_get_playlist_items` | List videos in a playlist |

**Required env:** `YOUTUBE_API_KEY`

---

#### Twitter / X
Post tweets, replies, and reactions.

| Atom | Description |
|---|---|
| `twitter_post_tweet` | Post a new tweet |
| `twitter_reply_tweet` | Reply to an existing tweet |
| `twitter_like_tweet` | Like a tweet |

**Required env:** `TWITTER_BEARER_TOKEN`, `TWITTER_API_KEY`, `TWITTER_API_SECRET`, `TWITTER_ACCESS_TOKEN`, `TWITTER_ACCESS_SECRET`

---

#### Reddit
Posts, comments, and subreddit data.

| Atom | Description |
|---|---|
| `reddit_get_subreddit` | Fetch subreddit info and top posts |
| `reddit_get_post` | Fetch a post and its comments |
| `reddit_get_me` | Get the authenticated user's profile |
| `reddit_submit_post` | Submit a new post to a subreddit |
| `reddit_submit_comment` | Post a comment on a submission |
| `reddit_vote` | Upvote or downvote a post or comment |

**Required env:** `REDDIT_CLIENT_ID`, `REDDIT_CLIENT_SECRET`, `REDDIT_USERNAME`, `REDDIT_PASSWORD`

---

### Email Marketing

#### Brevo
Transactional email and contact management.

| Atom | Description |
|---|---|
| `brevo_send_email` | Send a transactional email |
| `brevo_create_contact` | Create or update a contact |
| `brevo_get_contacts` | List contacts with optional filter |

**Required env:** `BREVO_API_KEY`

---

#### SendGrid
Transactional email delivery with analytics.

| Atom | Description |
|---|---|
| `sendgrid_send_email` | Send a transactional email |
| `sendgrid_get_stats` | Retrieve delivery, open, and click stats |

**Required env:** `SENDGRID_API_KEY`

---

#### Mailchimp
Email marketing, audience management, and campaign analytics.

| Atom | Description |
|---|---|
| `mailchimp_add_subscriber` | Add or update a subscriber |
| `mailchimp_get_list_members` | List members of an audience |
| `mailchimp_get_campaign_stats` | Retrieve campaign performance stats |

**Required env:** `MAILCHIMP_API_KEY`, `MAILCHIMP_SERVER_PREFIX`

---

### Storage

#### Azure Blob Storage
Object storage for blobs and files.

| Atom | Description |
|---|---|
| `azure_storage_list_containers` | List all blob containers |
| `azure_storage_upload_blob` | Upload a file to a container |
| `azure_storage_download_blob` | Download a blob by name |

**Required env:** `AZURE_STORAGE_CONNECTION_STRING`

---

### Healthcare

#### OpenMRS
Open-source electronic medical records.

| Atom | Description |
|---|---|
| `openmrs_search_patients` | Search patients by name or ID |
| `openmrs_get_patient` | Fetch a patient record |
| `openmrs_list_visits` | List visits for a patient |
| `openmrs_list_encounters` | List encounters for a patient |
| `openmrs_list_observations` | List observations for a patient |
| `openmrs_get_concept` | Fetch a medical concept by UUID |

**Required env:** `OPENMRS_URL`, `OPENMRS_USERNAME`, `OPENMRS_PASSWORD`

---

### Government & Compliance

#### KRA (Kenya Revenue Authority)
Tax compliance, PIN verification, and obligation checks.

| Atom | Description |
|---|---|
| `kra_check_pin` | Verify a KRA PIN is valid and active |
| `kra_check_obligations` | Check outstanding tax obligations for a PIN |
| `krapinchecker` | Batch PIN validity check |
| `krataxobligations` | Bulk tax obligations lookup |

**Required env:** `KRA_API_KEY`, `KRA_BASE_URL`

---

### Search

#### Serper
Google Search results via API.

| Atom | Description |
|---|---|
| `serper_search` | Perform a Google web search |
| `serper_news_search` | Search Google News for recent articles |

**Required env:** `SERPER_API_KEY`

---

## Configuration

All credentials are read from environment variables at call time. Set them in your `.env` file or secrets manager:

```bash
# .env
SLACK_BOT_TOKEN=xoxb-...
NOTION_API_KEY=secret_...
GITHUB_TOKEN=ghp_...
ZOOM_CLIENT_ID=...
MSGRAPH_CLIENT_ID=...
```

Credentials are never passed to agent reasoning. For OAuth2 providers, register credentials with the Nexus credential layer:

```bash
jarviscore nexus register github --client-id=YOUR_ID --client-secret=YOUR_SECRET
jarviscore nexus register notion --client-id=YOUR_ID --client-secret=YOUR_SECRET
```

See the [Nexus Credentials guide](nexus.md) for the full setup flow.

---

## Building Custom Atoms

An atom is a plain Python function that follows a strict contract. The function name must match the filename, the first parameter must be `auth_info: dict` because Nexus injects credentials via this parameter, and the function must return a `dict`.

```python
def linear_close_issue(auth_info: dict, issue_id: str, comment: str = "") -> dict:
    """
    Close an issue in Linear with an optional comment.

    Args:
        auth_info: Injected by Nexus. Contains the Linear API token.
        issue_id:  Linear issue ID (e.g. 'ENG-123').
        comment:   Optional comment to post before closing.

    Returns:
        {"success": bool, "issue_id": str}
    """
    import httpx
    headers = {"Authorization": auth_info["token"]}
    r = httpx.patch(
        "https://api.linear.app/graphql",
        headers=headers,
        json={"query": "mutation { issueUpdate(id: $id, input: {stateId: $stateId}) { success } }"},
    )
    return {"success": r.status_code == 200, "issue_id": issue_id}
```

**The atom contract:**

1. The filename stem must equal the function name. The file `linear_close_issue.py` must contain `def linear_close_issue(...)`.
2. The first parameter must be `auth_info: dict`. Do not rename it and do not move it to a different position.
3. The return annotation must be `-> dict`. If your payload is list-shaped, wrap it: `{"items": [...]}`.
4. The function must have a docstring that describes its parameters and the structure of the return dict.
5. The following imports and builtins are forbidden because atoms run inside the agent sandbox: `subprocess`, `pickle`, `eval`, and `exec`.

**To register the atom:**

1. Place the file at `jarviscore/integrations/atoms/<provider>/<function_name>.py`
2. Add a provider entry in `jarviscore/integrations/seed_registry.py` with `stage: "candidate"`
3. Add the atom to the Bundle Catalog table in this file

**To test and promote it:**

Use the `jarviscore atom` CLI to validate the atom's structure before making any live API calls. Once credentials are registered, run the integration check. The full step-by-step workflow is covered in [Testing Atoms](testing-atoms.md).

To contribute an atom to the framework, open a pull request to [jarviscore-framework](https://github.com/Prescott-Data/jarviscore-framework).

---

## Bundle Summary

| Category | Bundles | Approx. Atoms |
|---|---|---|
| Communication | Slack, Zoom, Discord, Webex, MS Graph, Gmail | 37 |
| Productivity | Notion, Confluence, ClickUp, Todoist, Google Drive, Dropbox, Google Sheets, Google Calendar, Airtable | 40 |
| Developer Tools | GitHub, Jira, Linear, Bamboo | 23 |
| CRM | HubSpot, Salesforce, Dynamics, Oracle CX, Apollo | 22 |
| ERP | NetSuite, Odoo, SAP, Oracle ERP | 24 |
| Finance | Stripe, QuickBooks, FreshBooks, Zoho Books | 24 |
| HR | Zoho People, Zoho Shifts | 8 |
| Content & Social | LinkedIn, LinkedIn Ads, YouTube, Twitter/X, Reddit | 24 |
| Email Marketing | Brevo, SendGrid, Mailchimp | 8 |
| Storage | Azure Storage | 3 |
| Healthcare | OpenMRS | 6 |
| Government | KRA | 4 |
| Search | Serper | 2 |
| **Total** | **46 bundles** | **~237 atoms** |
