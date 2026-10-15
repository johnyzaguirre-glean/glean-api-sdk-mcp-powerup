# Who should be able to find this runbook?

A customer wants Glean to respect the access rules in their source system. Sending the document is only part of that integration. The source owner must also keep user identities, groups, memberships and document permissions current, including when access is removed.

This exercise checks the **existing** fictional Orion runbook. It does not upload documents, create users, change groups or edit permissions.

## Understand the three checks

1. **Source visibility:** is this reader eligible to see the test datasource? A test-group setting is an additional gate. It does not override document permissions.
2. **Document access:** does the document's ACL permit this reader, directly or through a group? Indexing a datasource user alone grants no document access.
3. **Actual retrieval:** can the reader find the expected document in Glean using their own account?

The existing lab names one allowed reader in the document ACL. Anonymous and all-datasource-user access are both disabled. The datasource identity, processed People profile and sign-in account are separate setup concerns. See the [permission model](https://developers.glean.com/api-info/indexing/documents/permissions) and [test-datasource visibility](https://developers.glean.com/api-info/indexing/getting-started/index-documents).

## 1. Prepare the readers

Finish the [indexing lab](README.md) first. Keep its approved datasource, token and separate `.venv-indexing` environment.

In your local `indexing/.env`:

- Keep `GLEAN_INDEXING_TEST_EMAIL` as the existing allowed reader.
- Optionally set `GLEAN_INDEXING_DENIED_TEST_EMAIL` to a second approved, real sandbox user who should not have access to this document. Leave it blank if you do not have one.
- Both readers need active, uploaded identities in this datasource for this check. Have the source owner verify that the second email belongs to a different person, not another email for the allowed reader. The script cannot establish that distinction.
- To isolate the **document ACL** in an end-to-end test, both readers must be eligible to see the datasource. If one cannot see the source, an empty search does not tell you which access rule blocked the document. Have an administrator review any needed test-group change separately.

Do not change `GLEAN_INDEXING_TEST_EMAIL` and rerun `push_demo.py` just to test a second reader. That would rewrite the document ACL. Do not use a made-up or unresolved email as evidence of access denial.

## 2. Run the read-only API checks

From the repository root:

```sh
.venv-indexing/bin/python indexing/check_permissions.py
```

The checker confirms the latest upload is indexed. For each configured reader, it then checks datasource identity upload/activity and calls `StatusClient.check_document_access()`. It makes at most five requests, with the lab's timeouts, response-size bound and no automatic retries. Authentication rejections and rate limits stop further requests. It does not print reader emails, ACL lists, group lists, response bodies or token values.

Read each case's `result` and `has_access`:

| Outcome | Meaning |
| --- | --- |
| Allowed reader `PASS`, `has_access: true` | The API allowed the configured reader for this document. |
| Denied reader `PASS`, `has_access: false` | An active, uploaded second datasource identity received the expected API denial. Actual search is still a separate check. |
| `FAIL` | The API returned a Boolean that differs from the expected outcome. Investigate the source permissions and identities. |
| `NOT_RUN` | No valid access conclusion was reached. A missing reader, unresolved datasource identity, pending indexing or failed request is not denial proof. |

Exit code `0` means both API cases matched expectations. Exit `2` means only the allowed case passed because no second reader was configured. Exit `1` means a mismatch or another incomplete check. `end_to_end_search: "NOT_RUN"` is intentional: this program does not impersonate users or perform their searches.

The user-debug endpoint is beta and can change. Its active/uploaded status does not prove a processed People profile, sign-in access or a distinct person. An unavailable diagnostic leaves the case `NOT_RUN`. See [user diagnostics](https://developers.glean.com/api/indexing-api/beta-get-user-information) and [document access checks](https://developers.glean.com/api/indexing-api/check-document-access).

**Verified on October 15, 2026:** a read-only sandbox run confirmed the latest document upload was indexed and the allowed reader's API access check passed. All three requests returned HTTP 200. No second reader was configured, so the denied-reader case and end-to-end search were `NOT_RUN`. This partial-coverage result corresponds to exit code `2`; it does not establish denied-user or revocation behavior.

**Pinned-client gotcha:** API client 0.13.0 can reject a valid user-debug JSON response when `Content-Type` omits `charset=UTF-8`. The checker handles only an already-received HTTP 200 `application/json` response, validates it against the user-debug model within the existing size limit, and does not resend the request. Invalid responses remain inconclusive.

## 3. Prove allow and deny in real search

Use each reader's own approved browser session. An administrator's session or the allowed reader's token cannot establish the second reader's experience.

1. As the allowed reader, search `GLEAN_INDEXING_QUERY`. Confirm the runbook's title, source URL and marker `violet comet 641`.
2. As the denied reader, first find a separate **control document** that the source owner confirms this reader is allowed to see in the same datasource. Match its title and source URL. This checks that the reader's session, source visibility and search are working.
3. Still in that reader's session, search the runbook query in the same sandbox. Confirm the Orion runbook is absent. If the permitted control document also fails to appear, investigate that failure before treating the empty runbook search as ACL-denial evidence.
4. Record the API outcomes, control-document result, actual runbook search outcomes and observation time separately. If you lack the second session or a verified permitted control document, record the end-to-end denied test as **not run**.

The [SDK permissions guide](https://developers.glean.com/libraries/indexing-sdk/permissions) recommends real restricted-user search as the end-to-end check. A successful upload or API access response does not replace it.

## 4. Validate a later access revocation

This is an optional, separately planned sandbox exercise. It is not performed by these scripts.

1. Have the source owner remove the reader's grant using the approved source permission-sync workflow. Keep a recorded restoration plan. Preserve the document and its stable ID.
2. Wait for the relevant document-permission or group-membership update to process. Processing is asynchronous; these checks do not promise a fixed propagation time.
3. Run `indexing/check_demo.py` for the original reader. Expect `configured_user_has_access: false`, then confirm the document is absent from that reader's actual search. Its nonzero exit is expected for this revocation observation because the original checker expects allowed access.
4. If access is restored through the approved workflow, wait for processing and repeat the positive API and real-search checks.

Do not rerun `push_demo.py` during the revoked phase: it resubmits the original one-reader ACL. A group-removal exercise is meaningful only if the reader has no remaining direct or other group grant. This lab's document uses a direct reader grant, so changing unrelated group membership does not revoke that grant.

## What the integration owner must maintain

The SDK provides upload and diagnostic helpers. The integration owner remains responsible for translating the source's access model, indexing referenced users before ACLs, synchronizing groups and memberships when used, applying changed or removed grants, and monitoring processing failures. The SDK cannot infer permissions that the connector does not supply. Use [status and debugging guidance](https://developers.glean.com/libraries/indexing-sdk/status-and-debugging) when the checks disagree, and keep actual observations separate from assumptions.

Choose the operation that matches the change in the source system. The following is a planning reference for the pinned SDK **1.2.1** and API client **0.13.0**, not a set of commands run by this exercise.

| What changed in the source? | Corresponding API or SDK operation | What the integration must preserve |
| --- | --- | --- |
| Only the document's ACL changed | API client `client.indexing.permissions.update_permissions(...)`, POST `/api/index/v1/updatepermissions`. The SDK's `PushUploader` has no dedicated wrapper. [Reference](https://developers.glean.com/api/indexing-api/update-document-permissions). | Target the existing datasource, object type and document ID, and send the intended updated permissions. Content stays unchanged. |
| The document content, metadata or full document definition changed | `PushUploader.index_documents([document])` adds or updates the supplied document. [Pinned implementation](https://github.com/gleanwork/glean-indexing-sdk/blob/v1.2.1/src/glean/indexing/push/uploader.py#L291-L386). | Reuse the same stable ID and object type, with the current source content and ACL. This does not remove other documents omitted from the call. |
| A reader was removed from a source group | `PushUploader.delete_membership(membership)` removes the specified membership. [Pinned identity methods](https://github.com/gleanwork/glean-indexing-sdk/blob/v1.2.1/src/glean/indexing/push/uploader.py#L559-L898). | Identify the actual source group and membership. Check for remaining direct grants or other group paths that still permit access. |
| A source user, group or document was deleted | Use the matching targeted method: `delete_user(email=...)`, `delete_group(group_name=...)` or `delete_document(object_type=..., document_id=...)`. [Identity methods](https://github.com/gleanwork/glean-indexing-sdk/blob/v1.2.1/src/glean/indexing/push/uploader.py#L559-L898), [document deletion](https://github.com/gleanwork/glean-indexing-sdk/blob/v1.2.1/src/glean/indexing/push/uploader.py#L508-L526). | Delete the corresponding datasource record. Deleting a datasource user is not an identity-provider account deletion. |
| The connector is reconciling an authoritative complete snapshot | `bulk_index_documents`, `bulk_index_users` and `bulk_index_groups` replace their respective datasource collections. `bulk_index_memberships(..., group=...)` replaces memberships for one group. [Indexing modes](https://developers.glean.com/libraries/indexing-sdk/concepts/indexing-modes), [per-group membership reference](https://developers.glean.com/api/indexing-api/bulk-index-memberships-for-a-group). | Supply the complete intended snapshot and finish the upload correctly. Omitted records can be removed as stale. A partial result is not a complete snapshot. Note the empty-identity-sequence behavior below. |

If you extend this lab into a connector, two details in the pinned SDK **1.2.1** matter:

- The streaming connector implementations do not call `get_identities()`. Prepare and synchronize identities separately. See the [synchronous implementation](https://github.com/gleanwork/glean-indexing-sdk/blob/v1.2.1/src/glean/indexing/connectors/base_streaming_datasource_connector.py#L76-L170) and [asynchronous implementation](https://github.com/gleanwork/glean-indexing-sdk/blob/v1.2.1/src/glean/indexing/connectors/base_async_streaming_datasource_connector.py#L90-L205).
- Passing an empty sequence to `bulk_index_users`, `bulk_index_groups` or `bulk_index_memberships` sends no request in this version. An empty sequence does not revoke all of those records. Design and validate the intended removal workflow explicitly. See the [pinned uploader implementation](https://github.com/gleanwork/glean-indexing-sdk/blob/v1.2.1/src/glean/indexing/push/uploader.py#L590-L821). This exercise invokes none of those bulk methods.
