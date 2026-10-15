# Glean API, SDK and MCP PowerUp

Find a document in Glean, find it again from code, and understand what the response tells you. Then optionally use Chat to generate an answer in your app.

This small lab is for Tech GTM: solutions engineers, solutions architects, AI outcomes managers, AI support managers and technical support engineers. Start with the REST and Python examples. Try MCP after those work.

**You only edit `.env`. The query, tenant URL and expected document details all live there.**

Want help from Glean Tau? Open [PROMPT.md](PROMPT.md), copy the prompt, and give Tau access to this repository. It will walk through the same steps below.

## What you will prove

1. Your account can find a chosen document in the Glean app.
2. A REST request can find that document using the same account.
3. The official Python client can run the same search.
4. Optionally, a configured MCP server can expose and run its Search tool.
5. Optionally, REST and the Python client can ask the Chat API a question and let you inspect its answer and citations.

A successful HTTP status tells you the request worked. A matching document title and link tell you it found what you expected.

## Before you start

You need Git, Python 3.11 or later, and a macOS or Linux terminal. On Windows, use WSL because these scripts use POSIX request deadlines. Check your tools:

```sh
git --version
python3 --version
```

You also need access to an approved Glean sandbox or tenant with Platform Search enabled. Ask your Glean administrator for its **API backend origin**, such as `https://YOUR-TENANT-be.glean.com`, and an approved short-lived **Client API token for your own user with Search access**. The backend origin is the destination for API requests. It is different from the browser's `app.glean.com` address. Use the value your administrator provides, including any custom domain.

If you manage tokens yourself, follow [Glean's token creation instructions](https://developers.glean.com/api-info/client/authentication/glean-issued#creating-tokens). For this lab, select your own user and the Search scope. Chat and MCP are separate optional exercises. An Indexing API token does not work for these search examples.

## 1. Get the lab

Run these commands in your terminal:

```sh
git clone https://github.com/johnyzaguirre-glean/glean-api-sdk-mcp-powerup.git
cd glean-api-sdk-mcp-powerup
```

Keep this terminal open for the remaining steps.

**Already cloned the lab?** From your existing repository folder, get the new examples with:

```sh
git pull --ff-only
```

Keep your existing `.env` and token files. Do not copy `example.env` over `.env` again. The optional Chat section below shows the one new setting to add. If Git reports local code changes or a merge problem, stop and review them before updating.

## 2. Install the dependencies

Create a local Python environment, activate it, and install the pinned packages:

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

If you open a new terminal later, return to this folder and run `source .venv/bin/activate` again.

## 3. Pick a document and fill in `.env`

In the Glean app, search for a harmless document you can open. Open it and save its exact title and source link. This is the document you will look for in the API response.

Create your local settings file:

```sh
cp example.env .env
```

Open `.env` in your text editor. Replace the placeholder values:

| Setting | What to enter |
| --- | --- |
| `GLEAN_BASE_URL` | Your tenant's API backend origin, with `https://` and no API path |
| `GLEAN_QUERY` | The same search phrase you used in the Glean app |
| `GLEAN_TOKEN_FILE` | Keep `.secrets/glean-token` for the guided setup below |
| `GLEAN_EXPECTED_TITLE` | The exact document title you expect to find |
| `GLEAN_EXPECTED_URL` | The source link for that document |
| `GLEAN_MCP_URL` | Leave empty until the optional MCP exercise |
| `GLEAN_CHAT_QUERY` | A question for the optional Chat exercise, separate from your Search phrase |

For example, to search for the phrase **Your document title**, set:

```dotenv
GLEAN_QUERY='"Your document title"'
GLEAN_EXPECTED_TITLE='Your document title'
GLEAN_EXPECTED_URL='https://example.com/your-document'
```

The outer single quotes group the setting. The inner double quotes are part of the search phrase. Replace the example title and link with your own document. The expected title and URL are optional, but filling in both lets the scripts check that they found the right document.

Save the file. The scripts read `.env` automatically. Do not run `source .env`, and do not put a token value in it. Settings already exported in your terminal take precedence over `.env`.

## 4. Save your token without displaying it

Run:

```sh
python scripts/store_token.py
```

Paste your approved token at the hidden prompt and press Enter. Nothing appears while you paste. The helper saves it in the file named by `GLEAN_TOKEN_FILE`, readable only by your user. It does not print the token or overwrite an existing file.

`.env`, `.secrets/`, `.venv/` and generated outputs are ignored by Git. Keep the token out of chat, screenshots and issue reports.

Check the setup before making a request:

```sh
python scripts/check_setup.py
```

You should see: `Configuration, token-file permissions and dependencies look good. No network requests were made.` This checks your local setup. The next step checks whether the server accepts your token.

## 5. Run a REST search

```sh
python examples/rest_search.py
```

The script sends your `.env` query to `POST /api/search` and prints a short JSON summary. Look for:

- `http_status: 200`: the request succeeded.
- Returned document titles and links: find your expected document.
- `expected_document_matched: true`, when you supplied an expected title and URL: both matched the same result.

The summary leaves out document snippets and full response bodies. Displayed links omit query strings and fragments, which can contain sensitive values. The scripts compare fingerprints of the complete source links and titles, so different documents with similar-looking links do not count as a match. Those fingerprints appear as `url_sha256` and `title_sha256`. Reports can still contain private titles and links, so review them before sharing.

## 6. Run the same search with Python

```sh
python examples/python_search.py
```

This uses the official `glean-api-client` package and the same `.env` settings. Compare the returned titles and links with the REST output. You do not need to change the query or edit a Python file.

To run both methods together and save their comparison:

```sh
python scripts/run_diagnostics.py
```

The report is saved to `outputs/diagnostics.json`. Review both the success checks and the document comparison. Search ranking and source-link parameters can change between requests. A comparison is exact, including URL query strings and fragments, so investigate a mismatch using the same account, query and source link before drawing a conclusion.

**Try a different search:** change `GLEAN_QUERY`, `GLEAN_EXPECTED_TITLE` and `GLEAN_EXPECTED_URL` in `.env`, save, and rerun the same commands.

## Optional: get an answer with the Chat API

Search returns documents. Chat uses a language model to generate an answer and can include citations to the sources it used. A customer might use Chat to answer an employee's question inside a support portal, instead of displaying only a list of links. The account's permissions still apply to the context Glean can retrieve.

This exercise sends the same question through REST and the official Python API client. It uses your existing `.venv` and pinned `glean-api-client==0.17.16`. It does not use the separate Indexing SDK environment.

### 1. Get the new examples

For a fresh clone, complete steps 1 through 4 above. For an existing clone, run `git pull --ff-only` as shown above, activate `.venv`, and refresh its pinned dependencies:

```sh
source .venv/bin/activate
python -m pip install -r requirements.txt
```

### 2. Check Chat access and add your question

Use an approved, short-lived **Client API token for your own user with CHAT scope**. A Search-only token is insufficient. If you need to save a separate approved Chat token, set `GLEAN_TOKEN_FILE` in `.env` to a new ignored path such as `.secrets/glean-chat-token`, then run `python scripts/store_token.py`. Keep the original Search token file. The helper will not overwrite it. Use the token approved for the operation you are running.

Open your existing `.env` and add this setting if it is missing:

```dotenv
GLEAN_CHAT_QUERY='How do I call the Glean Search API?'
```

Choose a harmless question that your own tenant's content can answer. The example question is a starting point, not a promise that every tenant has those API documents. `GLEAN_CHAT_QUERY` is separate from `GLEAN_QUERY`, so asking a question does not change the known-document Search exercise. Keep `GLEAN_BASE_URL` and the approved `GLEAN_TOKEN_FILE` configured. Do not put a token value in `.env` or run `source .env`.

### 3. Check locally, then run both examples

```sh
python scripts/check_setup.py --chat
python examples/rest_chat.py
python examples/python_chat.py
```

The setup check is local only. It checks settings and dependencies without making a network request or proving that the server will accept the token. Each example then sends one question to `POST /api/chat`. Chat requests can consume model usage.

Both examples set `store:false`, which asks Glean not to save the conversation. This does not disable usage billing or service telemetry.

### 4. Read the answer and inspect its sources

Each run prints a bounded answer, citations, the HTTP status and a request ID when available. It also saves an owner-only report to:

- `outputs/rest-chat.json`
- `outputs/python-chat.json`

Look for `test_expectation_met: true`. The runner requires HTTP `200`, `response_status: COMPLETED`, `answer_present: true` and a response consistent with `store:false` without a saved conversation ID. That confirms the request completed, not that the answer is correct. Read it and open the citations to check whether they support what it says. An answer without citations is reported, rather than automatically treated as a failed request. Decide whether it is useful and grounded enough for the customer workflow.

Do not expect REST and Python to produce identical answer text. Compare whether they addressed the same question using appropriate sources. Change only `GLEAN_CHAT_QUERY` in `.env` to try another question, then rerun either command.

These reports can contain private generated text, source titles and links. They are ignored by Git. Keep them local and review their contents before sharing. A long answer or citation list may be shortened for the report, so do not treat the displayed excerpt as the entire response.

The examples also accept `--base-url`, `--token-file` and `--query` overrides. For the guided lab, editing `.env` is simpler. Never pass a token value on the command line.

### How the slide snippet maps to this lab

The presentation shows a short SDK or curl example. This repository adds a settings loader, private token-file handling and bounded output around the same request:

| Slide snippet | Repository setting |
| --- | --- |
| `GLEAN_SERVER_URL` | `GLEAN_BASE_URL` |
| `GLEAN_QUERY` for the Chat question | `GLEAN_CHAT_QUERY` |
| `GLEAN_API_TOKEN` | Token read from the file named by `GLEAN_TOKEN_FILE` |

Use the repository names in `.env`. The scripts load that file as data, so you do not need to export its contents into a shell. The Python example calls `g.chat.create(input=..., store=False)` through API client 0.17.16. Streaming uses a separate client method and is outside this small exercise.

Read the [Chat overview](https://developers.glean.com/api/platform-api/chat-overview), [Chat API reference](https://developers.glean.com/api/platform-api/platform-chat-create) and [streaming with citations cookbook](https://developers.glean.com/cookbook/streaming-chat-with-citations) for the full response format and additional examples.

## Optional: try MCP

MCP lets a compatible AI host discover and call tools. This exercise checks the server connection and its Search tool. It does not configure an AI host or test its choice of tools.

1. Ask your administrator for the exact enabled MCP server URL and the access required by that server. Do not construct the URL from a guess.
2. Put that URL in `GLEAN_MCP_URL` in `.env`. Confirm your token is approved for the selected MCP server and tool. Search access alone does not establish MCP access.
3. Discover the current tools without invoking Search:

   ```sh
   python scripts/run_mcp_test.py --discover-only
   ```

4. Open `outputs/mcp.json` and find `search_input_schema`. It describes the fields that this server's Search tool accepts. If its only required input is a string named `query`, run:

   ```sh
   python scripts/run_mcp_test.py
   ```

   The script inserts `GLEAN_QUERY` from `.env`, checks it against the schema, then calls Search once.

5. If the schema requires additional fields, create `outputs/search-args.json` with those fields. Tau can help interpret the schema using [PROMPT.md](PROMPT.md). For example, **only if your schema requires a string named `_user_goal` alongside `query`**, the file could contain:

   ```json
   {
     "_user_goal": "Find the reference document I already opened in Glean"
   }
   ```

   Run it with:

   ```sh
   python scripts/run_mcp_test.py --search-args-file outputs/search-args.json
   ```

   The script adds or replaces `query` using `.env`. You never need to duplicate your search phrase in this JSON file. If the discovered schema places the query somewhere else, use `--query-pointer` with that exact location, such as `/request/query`, and include the parent object in your JSON. Do not use the example fields unless your server's schema accepts them.

Look for `search_protocol_success: true` and, when you configured an expected document, `expected_fixture_result_matched: true`. The report is saved to `outputs/mcp.json`.

See the script's options with `python scripts/run_mcp_test.py --help`. The script validates arguments before invoking Search and saves a sanitized report.

## Optional diagnostics

The default diagnostics only run REST and Python Search. Additional checks are explicit:

```sh
python scripts/run_diagnostics.py --include-negative
python scripts/run_diagnostics.py --include-filters
python scripts/run_diagnostics.py --include-chat
```

`--include-negative` sends two deliberately invalid search requests. `--include-filters` retrieves available search filters. `--include-chat` is a separate connection diagnostic: it requires Chat access and sends a fixed benign prompt with `store:false`. It does not use `GLEAN_CHAT_QUERY` or replace the full Chat exercise above. It can consume usage and produce service telemetry. These examples do not run agent actions or write indexed documents.

Requests have a 30-second deadline, no automatic retries, no redirect following and a 2 MB response limit. A failure does not automatically trigger broader permissions.

## If something fails

Start with [TROUBLESHOOTING.md](TROUBLESHOOTING.md). Check the tenant URL, token expiry and required access before changing code. For a useful support report, collect the operation, status/problem code, request ID and package version. Remove private titles and links before posting anything publicly.

When finished, revoke the temporary token through your approved workflow and remove its local file. Deleting a local token file does not revoke the credential on the server.

## Files to explore

| File | Purpose |
| --- | --- |
| [example.env](example.env) | Settings to copy into your local `.env` |
| [scripts/store_token.py](scripts/store_token.py) | Hidden prompt that saves your token locally |
| [scripts/check_setup.py](scripts/check_setup.py) | Check local settings before making a request |
| [examples/rest_search.py](examples/rest_search.py) | One direct HTTP search |
| [examples/python_search.py](examples/python_search.py) | The same search through the official Python client |
| [examples/rest_chat.py](examples/rest_chat.py) | One Chat question sent through direct HTTP |
| [examples/python_chat.py](examples/python_chat.py) | The same question through the official Python API client |
| [scripts/run_diagnostics.py](scripts/run_diagnostics.py) | Search checks and optional diagnostics |
| [scripts/run_mcp_test.py](scripts/run_mcp_test.py) | MCP discovery and a schema-checked Search call |
| [PROMPT.md](PROMPT.md) | A setup prompt to use with Glean Tau |
| [TROUBLESHOOTING.md](TROUBLESHOOTING.md) | Common errors and what to check next |

## Official references

- [Platform Search](https://developers.glean.com/api/platform-api/platform-search)
- [Chat overview](https://developers.glean.com/api/platform-api/chat-overview)
- [Chat API reference](https://developers.glean.com/api/platform-api/platform-chat-create)
- [Streaming Chat with citations](https://developers.glean.com/cookbook/streaming-chat-with-citations)
- [Official API clients](https://developers.glean.com/libraries/api-clients)
- [Glean-issued Client API tokens](https://developers.glean.com/api-info/client/authentication/glean-issued)
- [MCP configuration and authentication](https://docs.glean.com/administration/platform/mcp/about)
- [Creating MCP servers](https://docs.glean.com/administration/platform/mcp/create-mcp-servers)
- [Glean cookbook](https://developers.glean.com/cookbook)

For an application you will ship to users, review the official authentication guidance, including OAuth for per-user integrations. This repository focuses on a small, repeatable learning exercise.

## Optional: put a source document into Glean with the Indexing SDK

The [Indexing SDK lab](indexing/README.md) adds the other half of the story: submit a fictional **Orion Service Recovery** runbook with a one-user ACL, check its indexing and access status, then find it in Glean. It starts with a dry run and only writes after an explicit sandbox confirmation.

This lab uses a separate `.venv-indexing` environment, separate `indexing/.env` settings and an Indexing API token. Keep the existing Search environment unchanged. Start with [the indexing walkthrough](indexing/README.md), or use [its Glean Tau setup prompt](indexing/PROMPT.md).
