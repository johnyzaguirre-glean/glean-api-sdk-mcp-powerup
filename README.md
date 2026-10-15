# Glean API, SDK and MCP PowerUp

Find a document in Glean, find it again from code, and understand what the response tells you. Then optionally use Chat to generate an answer in your app.

This small lab is for Tech GTM: solutions engineers, solutions architects, AI outcomes managers, AI support managers and technical support engineers. Start with the REST and Python examples. Try MCP after those work.

**You only edit `.env`. The query, tenant URL and expected document details all live there.**

Want help from Glean Tau? Open [PROMPT.md](PROMPT.md), copy the prompt, and give Tau access to this repository. It will walk through the same steps below.

## Present the lab from separate terminal windows

Use the presenter runner when you want an audience to see the goal, actual command, request input and response together. By default it runs the existing exercise live, prints a short explanation, captures and highlights the actual request JSON, then shows the response and explains the outcome. It keeps failures and incomplete checks visible. The separate `--replay` option displays a clearly labeled result saved from a previous real run.

Complete the setup below and the [Indexing SDK setup](indexing/README.md) before presenting. The full sequence needs two credentials: an approved User (self) Client API token with the access required for Search, Chat and the selected MCP server, plus a separate Indexing API token restricted to the demo datasource. Confirm that their expiry covers your entire session. Save them through the hidden token prompts before sharing your screen. Never put a token value in a command, terminal title or screenshot.

1. Open a separate terminal **window** for each example you plan to show.
2. In every window, change into this repository with `cd`.
3. Run one command from the table below. The presenter selects the appropriate child Python environment automatically, including `.venv-indexing` for indexing commands.
4. Add `--step` to pause on the request payload before revealing the response. In an interactive terminal, press Enter once to show the response and its meaning. The live request has already completed when this presentation pause appears.
5. Leave the window open after the result. `--hold` waits for another Enter before returning to the shell.

Start by listing the available examples. This does not contact Glean:

```sh
.venv/bin/python scripts/present.py --list
```

Use these commands in order. Each row is a separate window:

| Window | Run from the repository root | What the audience should learn |
| --- | --- | --- |
| 1. REST Search | `.venv/bin/python scripts/present.py search-rest --color always --hold` | A direct HTTP request finds the known document. |
| 2. Python Search | `.venv/bin/python scripts/present.py search-python --color always --hold` | The official client expresses the same Search request in Python. |
| 3. Compare Search | `.venv/bin/python scripts/present.py search-compare --color always --hold` | Compare both live result sets, including the expected title and source link. |
| 4. REST Chat | `.venv/bin/python scripts/present.py chat-rest --color always --hold` | Chat generates an answer that needs source review. |
| 5. Python Chat | `.venv/bin/python scripts/present.py chat-python --color always --hold` | The Python client reaches the same Chat API. Generated wording may differ. |
| 6. Discover MCP | `.venv/bin/python scripts/present.py mcp-discover --color always --hold` | Inspect the actual Search tool schema before sending arguments. |
| 7. Call MCP Search | `.venv/bin/python scripts/present.py mcp-search --search-args-file outputs/search-args.json --color always --hold` | Invoke the discovered Search tool using reviewed arguments. |
| 8. Preview indexing | `.venv/bin/python scripts/present.py indexing-preview --color always --hold` | Preview the fictional runbook and its one-reader ACL without a network call. |
| 9. Upload the runbook | `.venv/bin/python scripts/present.py indexing-apply --confirm-sandbox YOUR-SANDBOX-be.glean.com --color always --hold` | Submit one document using the Indexing SDK. Replace the hostname with your approved sandbox's exact hostname. |
| 10. Check indexing | `.venv/bin/python scripts/present.py indexing-status --color always --hold` | Check that processing completed and the configured reader has access. |
| 11. Check permissions | `.venv/bin/python scripts/present.py indexing-permissions --color always --hold` | Separate allowed-reader evidence, denied-reader evidence and actual search coverage. |

For MCP, create `outputs/search-args.json` only after reviewing discovery, as explained in [the MCP exercise](#optional-try-mcp). If the schema requires only `query`, omit `--search-args-file`. If its query is nested, use the reviewed `--query-pointer` path. Do not use the table as a reason to guess tool arguments.

Indexing is asynchronous. After the upload, allow processing time before running the status and permission windows. If the status is pending, preserve that result and deliberately rerun the read-only status check later. Do not reupload just to hurry processing. The permission exercise can correctly show **PARTIAL** when the allowed reader passes but no second reader is configured. That is not evidence of a denied-user or revocation test. Finish the indexing demonstration by finding the runbook in the Glean app as the intended reader.

Useful controls:

```sh
# Preview the exact action without running it.
.venv/bin/python scripts/present.py search-rest --plan

# Use plain text if your terminal does not render ANSI colors well.
.venv/bin/python scripts/present.py search-rest --color never --hold
```

The request section shows the actual HTTP JSON, including SDK serialization, rather than rebuilding it from today's `.env`. Search shows the query and page size. Chat shows the question and storage options. MCP shows the initialization, discovery and tool-call arguments actually attempted. Indexing shows the document body and access rules, or the status/access lookup inputs. Only requests actually attempted are shown. The indexing preview is explicitly labeled as an SDK preview with nothing sent.

Headers, credentials and MCP session identifiers are omitted. Input content is sanitized before display and storage. The runner saves owner-only request snapshots and response summaries under `outputs/presenter/`. These files are ignored by Git. Output can still include private questions, document content, reader emails, titles, links and Chat answers, so use an audience-appropriate sandbox and question. Keep terminal windows open for rehearsal or delivery, then revoke temporary credentials through your approved process when you finish.

The optional presenter names `diagnostics-negative`, `diagnostics-filters` and `diagnostics-chat` run the corresponding extra diagnostics documented below. Negative checks deliberately send invalid requests. The diagnostic Chat probe uses a fixed prompt, not `GLEAN_CHAT_QUERY`. The token helpers and `indexing/index_test_user.py` are setup or administrator maintenance tools, not steps in this audience walkthrough.

### Reopen recorded results in 11 windows on macOS

After running all 11 exercises live, you can reopen their saved evidence for the presentation without sending the requests again. This is useful for keeping a completed rehearsal ready on screen. Each window prominently says **RECORDED RESULT**, shows the run's timestamp and original command, and preserves its actual success, failure or partial result.

First, inspect the proposed windows and check for missing recordings. This reads the saved presenter reports, opens no applications and contacts no service:

```sh
.venv/bin/python scripts/open_presenter_windows.py --plan
```

The launcher needs a valid report for every one of the 11 regular exercises in `outputs/presenter/`. Reports are local and ignored by Git, so a fresh clone will not have them. Run and record any missing exercises first using the commands above. Optional diagnostic reports are not required.

When ready, **you can double-click `scripts/open_presenter_windows.command` in Finder**, or run this yourself from the repository root:

```sh
./scripts/open_presenter_windows.command
```

This user-run macOS launcher opens a separate Terminal window for each saved exercise in teaching order. macOS may ask you to allow Terminal automation. Every window uses `--step --hold`: it starts with the input payload, waits for Enter to reveal the response, then stays open until you press Enter again. The launcher does not close existing windows. If macOS does not allow all windows to open, use the commands shown by `--plan` in separate windows yourself.

Replaying results makes no Glean requests, consumes no model usage and does not repeat the indexing upload. It does not verify that a token is still valid or that the sandbox has the same state now. To display one recorded example manually on any supported terminal:

```sh
.venv/bin/python scripts/present.py search-rest --replay --color always --hold --step
```

Replay uses the input captured with that run, even if `.env` later changes. Older recordings without inputs say so. For an older indexing upload, the latest saved indexing preview can appear under **CURRENT INPUT PREVIEW**, with its own timestamp and an explicit statement that it was not captured with the upload. This does not prove the old upload used that exact payload. Do not repeat a write merely to improve the display.

Replay uses the original saved command. Do not add live-run options such as `--confirm-sandbox` or `--search-args-file`. To obtain new evidence, deliberately run that exercise without `--replay`, following its normal setup and upload safeguards.

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

**Live verification, October 14, 2026:** Both repository examples completed against a test sandbox with generated answers and source citations. Both returned HTTP `200`, `COMPLETED`, `store:false` and no saved conversation ID. Python used `glean-api-client==0.17.16`. The REST call took about 40 seconds and the Python call about 63 seconds. Chat now allows 120 seconds after the initial 30-second deadline proved too short. These are recorded test results, not a latency guarantee.

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

Search and MCP requests have a 30-second deadline. The Chat examples allow 120 seconds for answer generation. All use no automatic retries, no redirect following and a 2 MB response limit. A failure does not automatically trigger broader permissions.

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
| [scripts/present.py](scripts/present.py) | Run one live exercise with context, a visible command and highlighted output |
| [scripts/open_presenter_windows.command](scripts/open_presenter_windows.command) | User-run macOS launcher that opens all 11 recorded results in separate windows |
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
