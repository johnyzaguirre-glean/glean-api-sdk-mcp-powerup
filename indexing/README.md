# Put one fictional runbook into Glean

The earlier examples searched content that was already in Glean. This lab shows the other direction: take a source document, include its access rules, and submit it for indexing.

Our source is [PowerUp Demo: Orion Service Recovery](sample_document.md), a fictional service runbook. It describes checking service health, reviewing the last deployment, and confirming recovery with the service owner. The phrase **violet comet 641** makes the test document easy to recognize.

You will submit exactly one document to a dedicated test datasource. Its ACL names one test user. The script uses the additive `PushUploader.index_documents()` method, so rerunning it updates the same demo document. It does not replace the datasource's collection or delete documents. See the [official uploader guide](https://developers.glean.com/libraries/indexing-sdk/push/uploader).

## 1. Have an administrator prepare a test datasource

Before running this lab, have your administrator confirm:

- The destination is an approved sandbox, with a dedicated datasource for this exercise.
- Its API name starts with `powerupdemo`, followed by a unique suffix using only letters and digits. For example, `powerupdemoTRAINING1`. Use the API name, not the display label.
- The datasource is configured as a test datasource (`isTestDatasource=true`), with an `article` object type and email-based user references (`isUserReferencedByEmail=true`).
- The one test user is allowed to see this test datasource and exists in the sandbox. Test-datasource allow-listing is separate from the document's own ACL.
- You have an approved Indexing API token scoped appropriately for this dedicated datasource. A Client API Search token serves a different purpose.

The scripts do not create or reconfigure a datasource. Refer your administrator to [datasource setup](https://developers.glean.com/api-info/indexing/getting-started/setup-datasource) and [identity and permission configuration](https://developers.glean.com/libraries/indexing-sdk/permissions).

## 2. Create a separate Python environment

Run everything below from the repository's top-level folder, on macOS or Linux (WSL on Windows):

```sh
python3 -m venv .venv-indexing
.venv-indexing/bin/python -m pip install -r indexing/requirements.txt
```

Keep this environment separate from `.venv`, which runs the REST, Python Search and MCP examples. This lab pins `glean-indexing-sdk==1.2.1` and its compatible `glean-api-client==0.13.0`. The Search examples use `glean-api-client==0.17.16`. Installing both into one environment creates a version conflict.

Using the full `.venv-indexing/bin/python` command selects the correct environment without changing your terminal's active environment.

## 3. Fill in the local settings

```sh
cp indexing/example.env indexing/.env
```

Open `indexing/.env` in your editor and replace the placeholders:

| Setting | Enter this |
| --- | --- |
| `GLEAN_INDEXING_BASE_URL` | The approved sandbox's HTTPS backend origin, provided by your administrator |
| `GLEAN_INDEXING_DATASOURCE` | The dedicated datasource's API name, starting with `powerupdemo` |
| `GLEAN_INDEXING_TEST_EMAIL` | The single existing sandbox user who should see the document |
| `GLEAN_INDEXING_TOKEN_FILE` | Keep `.secrets/glean-indexing-token` for this guided setup |
| `GLEAN_INDEXING_QUERY` | Keep the quoted demo title, or use `"violet comet 641"` |

The scripts read this file as data. They do not run shell commands or interpolate variables from it. Do not `source` it or put a token value in it. Exported `GLEAN_INDEXING_*` settings take precedence over the file.

The `--confirm-sandbox` argument later requires the exact hostname from this origin. If the origin were `https://YOUR-SANDBOX-be.glean.com`, the hostname would be `YOUR-SANDBOX-be.glean.com`. The check prevents accidental target mismatches; it cannot independently prove that your organization designated the host as a sandbox.

## 4. Preview the document before sending it

```sh
.venv-indexing/bin/python indexing/push_demo.py
```

This is a dry run. It makes zero network requests and does not read a token. Check the target hostname, datasource, document title, and `acl_user_count: 1`. Review the configured email locally in `indexing/.env`. The preview does not print it.

Open [sample_document.md](sample_document.md) too. This exact file becomes the document body. The source link points back to that public fictional example in this repository.

## 5. Store your Indexing API token

```sh
.venv-indexing/bin/python indexing/store_token.py
```

Paste the approved Indexing API token into the hidden prompt and press Enter. The helper creates an owner-only file and refuses to overwrite an existing file. Token files, local settings and virtual environments are ignored by Git.

The lab supplies the credential to the SDK in memory. You do not need to export `GLEAN_INDEXING_API_TOKEN`, paste a token into code, or reuse the Search lab's token.

## 6. Send the one document

Replace the example hostname with your configured sandbox hostname:

```sh
.venv-indexing/bin/python indexing/push_demo.py --apply --confirm-sandbox YOUR-SANDBOX-be.glean.com
```

This is the step that writes to the datasource. A successful run prints `operation_completed: true` and the observed HTTP status. `PushUploader.index_documents()` does not return a document result body.

**An accepted upload is not yet proof that the document is searchable.** Processing happens asynchronously, so continue with the next two checks. See [Glean's status and debugging guide](https://developers.glean.com/libraries/indexing-sdk/status-and-debugging).

## 7. Check indexing and the user's access

```sh
.venv-indexing/bin/python indexing/check_demo.py
```

This read-only command checks the known document's current status, then asks whether the configured user can access it. It uses `StatusClient.get_documents_status()` and `StatusClient.check_document_access()`.

Look for:

- `upload_status: "UPLOADED"`: Glean received the document.
- `indexing_status: "INDEXED"` and `latest_upload_indexed: true`: indexing has caught up with the upload timestamp.
- `configured_user_has_access: true`: the access check allows the configured user.
- `ready_for_ui_search_check: true`: those checks passed, so test search in the app next.

A pending result exits with code 1. Wait for processing, then rerun this read-only check. It does not poll continuously or reupload the document. An authentication rejection or rate limit stops it from making the second request.

If a status response omits usable timestamps, the script cannot confirm that the latest upload has indexed. It reports that uncertainty rather than assuming success.

## 8. Find it in the Glean app

Sign into the same sandbox as the configured test user. Search the phrase from `GLEAN_INDEXING_QUERY`, open **PowerUp Demo: Orion Service Recovery**, and confirm the source link points to this repository's sample file. Check for the marker **violet comet 641**.

This is the final evidence that this user can find the submitted content. The API access check does not replace this test. If the document is indexed but absent from search, also check the test datasource's allow-list and the user account in the browser.

## Optional: map the test user's datasource identity

Only use this when your administrator confirms that the dedicated datasource needs the tester's identity record. The document upload does not silently add identities.

Preview the separate operation:

```sh
.venv-indexing/bin/python indexing/index_test_user.py
```

Then, when approved, add or update that one datasource user:

```sh
.venv-indexing/bin/python indexing/index_test_user.py --apply --confirm-sandbox YOUR-SANDBOX-be.glean.com
```

This uses the email in `indexing/.env`, the synthetic display name `PowerUp demo tester`, and `is_active=true`. It maps the user into this datasource for permission checks. It does not create the processed People profile used by People search or user pickers, and it does not create an identity-provider account or grant sign-in access. If a user picker cannot find the tester, ask the sandbox owner to verify the People profile separately. After processing, rerun `check_demo.py`. Keep the one-user document ACL unchanged.

## What the code does

The main indexing operation is deliberately small:

```python
uploader = PushUploader(datasource=config.datasource, timeout_ms=30000, upload_max_workers=1)
uploader.index_documents([document])
```

`lab.py` builds a `DocumentDefinition` with the source body, stable document ID, source link and one-user permission list. It adapts the pinned SDK's client factory to use a 30-second deadline, a 2 MB response limit, no automatic retries and no redirect following. Only selected status metadata is printed. Raw error bodies and credentials are omitted.

This is a one-document learning exercise. A production connector also needs source authentication, ongoing content and permission synchronization, lifecycle handling, and operational monitoring. The [Indexing SDK quickstart](https://developers.glean.com/libraries/indexing-sdk/quickstart) covers a fuller connector structure.

## Offline tests and cleanup

```sh
.venv-indexing/bin/python -m unittest discover -s indexing/tests -v
```

The tests use a mock HTTP transport with the real pinned SDK. They verify the additive endpoint, single-user ACL, dry-run behavior, exact host confirmation, status/access endpoints and output handling. They do not connect to a tenant.

When the lab is finished, revoke the temporary token through your approved process and remove its local file. Ask the sandbox owner to clean up the dedicated demo document or datasource when appropriate. This repository intentionally includes no delete or bulk-replacement command.

For guided help, use [the indexing Tau prompt](PROMPT.md). For failures, see the [Indexing SDK section of the troubleshooting guide](../TROUBLESHOOTING.md#indexing-sdk-lab).
