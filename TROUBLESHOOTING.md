# When a lab request does not work

Start with one known document. Open it in the Glean app using the account behind your User (self) token. Keep its title and source link so you can tell whether the terminal search found the right thing. A `200` response proves the request succeeded, not that it found your expected document.

The examples read your settings from `.env`. Change the search in `GLEAN_QUERY`, then rerun the same command. You do not need to edit the Python examples.

First, run the offline setup check from the repository root:

```sh
.venv/bin/python scripts/check_setup.py
```

This checks your configuration, token-file permissions and dependencies without contacting Glean or displaying your settings. Passing it means the local setup is ready to try. It does not confirm that the token is still valid on the server or that a document will be found.

## Find the problem

| What you see | What to check next |
| --- | --- |
| `python3` is missing or too old | Install Python 3.11 or later using your organization's approved method. On Windows, use WSL. |
| An error mentions `SIGALRM` or `setitimer` | Run in macOS, Linux or WSL. The bounded diagnostic code uses POSIX timers. |
| A package cannot be imported | From the repository root, install `requirements.txt` into `.venv`. Run examples with `.venv/bin/python` so they use that environment. |
| A configuration value is missing | Check `.env` against `example.env`. Use the exact variable names. Do not print the whole file into a support thread. |
| Changing `.env` seems to have no effect | Values already exported in your terminal override `.env`. Check for an existing value of the relevant variable without displaying it, then remove that override or start a clean terminal. Do not run `source .env`. |
| The token file cannot be read | Check that `GLEAN_TOKEN_FILE` points to your existing private file. The guided default is `.secrets/glean-token`. If you have not saved it, run `.venv/bin/python scripts/store_token.py` in your own interactive terminal and paste the approved token into its hidden prompt. Never paste it into chat. |
| The token file must be owner-only | The file must be a regular file owned by your account, not a symbolic link. For the default path, run `chmod 600 .secrets/glean-token`. Check permissions without displaying its contents. |
| The token helper says the file already exists | It intentionally refuses to overwrite credentials. Keep the file if it is the intended token. To store a replacement, choose a new ignored path under `.secrets/` in `GLEAN_TOKEN_FILE` and rerun the helper. Do not delete or revoke a credential you do not own. |
| The token helper needs an interactive terminal | Run `.venv/bin/python scripts/store_token.py` in your own terminal so you can enter the token at its hidden prompt. Do not pipe a secret into the command or pass it as an argument. |
| Invalid backend URL, redirect or an HTML response | Use your environment's HTTPS backend origin in `GLEAN_BASE_URL`, not the `app.glean.com` browser address or a full Search endpoint. Confirm the value with your administrator if needed. Do not bypass URL checks or follow an unexpected redirect with credentials. |
| HTTP `401` | Check whether the token expired, was revoked, or belongs to a different environment. Use the approved credential flow to resolve it. |
| HTTP `403` | Inspect the safe error code. Confirm the token type, required scope and tenant access with your administrator. A `403` can also reflect other policy or usage limits, so do not assume broader permissions are the answer. |
| HTTP `400` | Check the reported field or validation code. Confirm the request matches the endpoint's schema. An optional diagnostic may deliberately send an invalid request and expect `400`; read that test's expected outcome. |
| HTTP `404` | Confirm the backend, endpoint and feature availability. For MCP, copy the exact enabled server URL rather than guessing its path. |
| HTTP `429` | Stop and follow the applicable retry guidance or ask the service owner. Repeatedly rerunning the examples can make the limit harder to diagnose. |
| Timeout or response-size limit | The runners bound requests rather than waiting forever or dumping large responses. Check connectivity and try a narrower approved query before changing those safeguards. |
| HTTP `200`, but no results | Verify the same account can find the document in the Glean app. Check the query spelling and quotation marks. Zero results alone does not establish an authentication failure. |
| Results exist, but the expected document is missing | Open the document in Glean, confirm its exact title and source link, and verify that your test uses the same account and environment. A three-result page may not contain every matching document. |
| REST works but Python fails | Confirm both use the same `.env`, virtual environment and pinned package version. This lab uses `glean.search.query`; a similarly named legacy method targets a different API. |
| REST and Python return different results | Compare title-and-link pairs, not just counts or rank. Check the account, backend, query and page size. Content and ranking can change between live requests. |
| MCP discovery works, but Search validation stops | Read the returned Search schema. Supply only the required, reviewed arguments using the README's process. A schema mismatch is a reason to stop before invocation, not to guess another tool or bypass validation. |
| MCP cannot authenticate | Verify the selected server's authentication and scope requirements with its administrator. REST Search success does not prove the same credential is accepted by every MCP server. |
| MCP succeeds but the result parser does not confirm a match | Review the sanitized metadata and the documented result format. A parsing mismatch is not proof that the tool retrieved nothing. Do not enable raw response logging just to share it. |

## Compare the right things

Use these checks in order:

1. **Did the request succeed?** Look at the actual HTTP or MCP outcome.
2. **Did it return usable results?** Check the result count and any warnings.
3. **Did it find our document?** Match its title and source link together.
4. **Did REST and Python agree?** Compare the returned title-and-link pairs using the same configuration.

The Glean app's total result count does not need to equal a small API page. Matching one known document is a focused retrieval check. It does not prove access isolation across multiple users, every integration scenario, or all MCP host behavior.

## Get help without exposing credentials

Share a short, reviewed summary such as:

```text
Command: examples/rest_search.py
Python version: <version>
Package version: <version, if relevant>
Outcome: <HTTP status or safe failure label>
Error code and field pointer: <if present>
Request ID: <if present>
Expected document found in Glean app: yes / no
Expected title and link matched by the example: yes / no / not checked
REST and Python returned the same title-and-link pairs: yes / no / not checked
```

Search reports omit credentials and retrieved document bodies, but titles, URLs, queries and environment details can still be sensitive. Chat reports also contain bounded generated answer text and citations. Review the actual report before sharing it. Keep reports local unless their contents are appropriate for the audience. Do not attach `.env`, token files, Authorization headers, raw responses or verbose network traces.

For current endpoint and authentication details, use the official [Platform Search reference](https://developers.glean.com/api/platform-api/platform-search), [API client documentation](https://developers.glean.com/libraries/api-clients) and [Glean-issued token documentation](https://developers.glean.com/api-info/client/authentication/glean-issued).

## Chat API lab

Start with `python scripts/check_setup.py --chat` from the repository root. This only validates local setup. The examples read `GLEAN_CHAT_QUERY`, `GLEAN_BASE_URL` and `GLEAN_TOKEN_FILE` from `.env`. They do not require you to source `.env` or edit code.

| What you see | What to check next |
| --- | --- |
| `GLEAN_CHAT_QUERY` is missing | In an existing clone, add the new key to your existing `.env`. Keep your other settings. Use a harmless question that your tenant can answer. `GLEAN_QUERY` is the separate Search phrase. |
| The Chat files or `--chat` option are missing | Update the existing repository with `git pull --ff-only`, review any local code conflicts, and install the current `requirements.txt` in `.venv`. Do not overwrite `.env`. |
| Search works but Chat returns `403` | Confirm the user token is approved for CHAT scope and the tenant permits Chat. Search-only access is insufficient. Do not automatically grant broader permissions. |
| Chat returns `401` | Check token expiry, revocation and the intended tenant. Follow the approved credential process. |
| A token file already exists when saving a Chat token | Keep the original file. Set `GLEAN_TOKEN_FILE` to a new ignored path under `.secrets/` and use the hidden token helper for the approved Chat token. |
| Python cannot find `g.chat.create` or rejects an argument | Use `.venv`, install the pinned API client 0.17.16, and run the repository example. `chat.create` accepts `input` and `store`; it does not take a `stream` keyword. Streaming has a separate method. |
| A slide's environment variables do not work here | Use `GLEAN_BASE_URL`, `GLEAN_CHAT_QUERY` and `GLEAN_TOKEN_FILE` in this repo. The slide's shorter snippet uses `GLEAN_SERVER_URL`, `GLEAN_QUERY` and a direct token variable. The README maps them explicitly. |
| HTTP `200`, but the run exits unsuccessfully | The runner also requires response status `COMPLETED`, a nonempty answer, and a response consistent with `store:false` without a saved conversation ID. Read the safe status and request ID. Do not treat HTTP status alone as proof of a usable answer. |
| An answer has no citations | The runner reports this without automatically failing. Check whether the question needs company content and whether that content is available to the user. Review the answer before treating it as grounded. |
| The answer is wrong or the sources do not support it | A completed request is not a correctness test. Open the cited sources with the intended account, review the question and inspect the relevant content. Record the request ID for escalation. |
| REST and Python answers differ | Generated wording can vary. Compare whether each addresses the same question with useful, permitted sources. Do not require byte-for-byte answer equality. |
| The answer or citation list is shortened | Output is deliberately bounded. Check the local report's truncation information and use a narrower question when helpful. Do not enable full-response logging to share private content. |
| Chat times out or hits a usage limit | Stop and inspect the safe error and request ID. Follow the existing timeout and rate-limit guidance. Do not repeatedly send the same generation request. |
| `run_diagnostics.py --include-chat` asks a different question | That option is a fixed connection probe. Use `examples/rest_chat.py` or `examples/python_chat.py` for the question in `GLEAN_CHAT_QUERY`. |

Each example writes its own ignored, owner-only report: `outputs/rest-chat.json` or `outputs/python-chat.json`. Reports can contain private answer text and citation details. Share only reviewed status, error information and request IDs. Never attach token files or Authorization headers.

Both requests use `store:false`, which asks Glean not to save the conversation. It does not turn off usage billing or service telemetry. See the official [Chat API reference](https://developers.glean.com/api/platform-api/platform-chat-create) and [streaming with citations cookbook](https://developers.glean.com/cookbook/streaming-chat-with-citations).

## Indexing SDK lab

Start with [the indexing walkthrough](indexing/README.md). Its settings, credential and Python environment are separate from the Search lab.

| Symptom | What to check next |
| --- | --- |
| Dependency conflict, missing SDK, or version check fails | Install `indexing/requirements.txt` into `.venv-indexing` and use `.venv-indexing/bin/python`. SDK 1.2.1 depends on API client 0.13.x; the Search lab's 0.17.16 is separate. |
| Datasource name is rejected locally | Use the dedicated datasource's API name: `powerupdemo` plus an alphanumeric suffix. The administrator must have created it first. A display label is not the API name. |
| `--confirm-sandbox` is rejected | Use the exact hostname from `GLEAN_INDEXING_BASE_URL`, without `https://` or a trailing slash. Review the destination before running `--apply`. |
| HTTP 401 or 403 | Confirm this is an Indexing API token with access to the demo datasource and that it has not expired. A Search token is not interchangeable. Do not grant broader access automatically. |
| Upload completed but search finds nothing | Run `indexing/check_demo.py`. An accepted upload can still be waiting for indexing. Check the intended user and the test datasource's allow-list too. |
| `latest_upload_indexed` is false | The index may not have caught up, or status did not provide usable upload/index timestamps. Wait, then repeat the read-only status check. |
| `permission_identity_status` is `NOT_UPLOADED` | Have the administrator review the email-reference configuration and datasource user mapping. The optional `indexing/index_test_user.py` is a separate, explicitly authorized one-user mutation. |
| User picker cannot find the tester | A datasource user mapping is separate from a processed People profile. Have the sandbox owner verify that the tester exists in the People directory and that directory processing completed. Do not rerun document uploads or broaden ACLs to repair a People lookup. |
| Access check is false | Verify the exact intended email and the datasource identity mapping. Keep the one-user ACL intact. |
| Access check is true but UI search is empty | Confirm the browser uses that same sandbox user, the test datasource allows that user, and indexing is current. The access API alone does not prove UI visibility. |
| A diagnostic warns about source visibility, but the intended user can find the exact document | Compare three pieces of evidence: the indexed document's status, an access check for that user, and a search using that same account and environment. Record the exact warning and ask the diagnostic owner to check how it identifies the custom datasource. Do not broaden source visibility or document permissions just to clear a conflicting warning. |
| Upload returns a server error, times out or has an uncertain result | A server error can follow persistence, so the failed response does not prove that nothing was written or identify the cause. Check the document's read-only status and allow processing time before considering one deliberate retry with the same stable document ID. If it is already uploaded or indexed, continue verification instead of resending. The script does not retry automatically. |
| Source link is a GitHub page | Expected: this synthetic runbook's canonical source is `indexing/sample_document.md` in this public repository. No private source system is involved. |

The checker reads the current document-debug and access endpoints through `StatusClient`. It does not rely on deprecated document-status calls. It prints selected status fields and booleans, omitting ACL email lists, raw response bodies and credentials. See [official status guidance](https://developers.glean.com/libraries/indexing-sdk/status-and-debugging).
