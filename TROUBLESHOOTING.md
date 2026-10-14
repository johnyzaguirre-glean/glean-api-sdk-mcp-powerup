# When a search does not work

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

Generated reports omit credentials and retrieved document bodies, but titles, URLs, queries and environment details can still be sensitive. Review the actual report before sharing it. Keep reports local unless their contents are appropriate for the audience. Do not attach `.env`, token files, Authorization headers, raw responses or verbose network traces.

For current endpoint and authentication details, use the official [Platform Search reference](https://developers.glean.com/api/platform-api/platform-search), [API client documentation](https://developers.glean.com/libraries/api-clients) and [Glean-issued token documentation](https://developers.glean.com/api-info/client/authentication/glean-issued).
