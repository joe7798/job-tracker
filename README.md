# job-application-tracker-agent

Reads your Outlook inbox, detects job application replies, and updates the Status column in a Google Sheet automatically.

---

## Prerequisites

- Python 3.10+
- An Outlook / Hotmail account
- A Google Sheet with columns: **Company**, **Role**, **Status**
- An [Anthropic API key](https://console.anthropic.com/settings/keys)

---

## One-time setup

### 1. Azure app (Outlook access)

1. Go to [portal.azure.com](https://portal.azure.com) → **App registrations** → **New registration**
2. Supported account types: **Personal Microsoft accounts only**
3. Click **Register**, then copy the **Application (client) ID**
4. **Authentication** → Advanced settings → **Allow public client flows: Yes** → Save
5. **API permissions** → Add → Microsoft Graph → Delegated → `Mail.Read` → Add

### 2. Google service account

1. [console.cloud.google.com](https://console.cloud.google.com) → enable **Google Sheets API** and **Google Drive API**
2. **IAM & Admin** → **Service Accounts** → Create → **Keys** tab → Add Key → JSON
3. Save the downloaded file as `service_account.json` in the project root
4. Share your Google Sheet with the `client_email` from that JSON file (Editor access)

### 3. Install and configure

```bash
python -m venv .venv && .venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env
# Fill in .env with your four values
```

Your `.env`:
```
ANTHROPIC_API_KEY=sk-ant-...
AZURE_CLIENT_ID=xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
GOOGLE_SERVICE_ACCOUNT_FILE=service_account.json
SPREADSHEET_ID=<id from your sheet URL>
```

---

## Running

```bash
python -m tracker.main
```

On first run you'll be prompted to open a URL and enter a code to log in to Outlook. Tokens are cached in `token_cache.bin` — subsequent runs skip this.

### Dry run vs live

`config.toml` controls behaviour:

| Setting | Effect |
|---------|--------|
| `dry_run = true` | Prints intended changes, writes nothing |
| `dry_run = false` | Writes status updates to the sheet |

Start with `dry_run = true` to verify the output looks correct, then switch to `false`.

---

## Files to keep secret (all gitignored)

| File | Contains |
|------|----------|
| `.env` | API keys and spreadsheet ID |
| `service_account.json` | Google credentials |
| `token_cache.bin` | Outlook login tokens — delete to force re-login |
| `processed.json` | Already-processed message IDs |
| `review_queue.json` | Emails flagged for manual review |
