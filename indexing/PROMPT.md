# Glean Tau prompt: Indexing SDK lab

Copy the following prompt into Glean Tau and give it access to this repository. Keep token values and private tenant settings out of the conversation.

---

Help me complete the optional Indexing SDK lab in this repository. I want to understand how a fictional service runbook becomes searchable in Glean with the right permissions.

Read indexing/README.md, indexing/example.env, indexing/sample_document.md, and the indexing Python scripts first. Explain the process in plain language: create a document from source content, include its ACL, submit it, wait for indexing, then prove the intended user can find it.

Use the existing implementation. Keep the Indexing SDK environment separate from the Search examples. The indexing requirements pin glean-indexing-sdk 1.2.1 with glean-api-client 0.13.0. Use .venv-indexing/bin/python for every indexing command, and do not change the root requirements or root .venv.

Help me fill in indexing/.env locally. The query must remain a .env setting. Do not source the file, interpolate its contents as shell code, or ask me to paste a token into chat. Use indexing/store_token.py for hidden token entry into an owner-only file. Never read, print, copy or commit the token.

Confirm that my administrator has prepared a dedicated test datasource with an alphanumeric API name starting with powerupdemo, an article object type, email-based references, and the necessary test-user allow-list. The only document ACL recipient must be the test email in indexing/.env. If the admin setup is missing, explain exactly what the administrator needs to supply. Do not repurpose an existing business datasource.

Run indexing/push_demo.py without flags first. Show me the purpose of its dry-run output. It should make no network requests. Explain that --apply writes one document and that --confirm-sandbox must match the configured backend hostname. Do not run the mutation until I have authorized this specific sandbox upload. Once authorized, do not ask for the same approval again.

Use only PushUploader.index_documents() for the synthetic document. Never switch to a bulk replacement or deletion method. The document body must remain the fictional Orion Service Recovery runbook with marker violet comet 641, and must match sample_document.md. Do not add private source documents, real infrastructure commands, customer data or screenshots.

After the upload, run indexing/check_demo.py. Distinguish an accepted HTTP response from completed indexing, and completed indexing from the actual user's ability to find the document in search. If status is pending, explain it and use a later read-only check rather than repeated uploads. Do not invent a successful response or label a mock test as live evidence.

If the configured datasource needs a user mapping, explain the separate indexing/index_test_user.py command. It adds or updates only the one configured tester's datasource identity and also requires explicit --apply and exact sandbox confirmation. Do not do this automatically as part of the document push. Never broaden the ACL to work around an access failure.

Finish by helping me search the .env query in the sandbox as the intended user and verify the document title, source link and marker. Remind me that the test-datasource allow-list is an additional visibility gate. Report which steps actually passed, what remains pending, and how to revoke the temporary token and arrange sandbox cleanup.
