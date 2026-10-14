#!/usr/bin/env python3
"""Read indexing status and check the configured user's document access once."""
import argparse
from lab import (DOCUMENT_ID, OBJECT_TYPE, TIMEOUT, bounded_client, check_versions, configure,
                 deadline, emit, read_token, run_guarded, safe_failure, status_summary)


def main():
    argparse.ArgumentParser(description=__doc__).parse_args()
    config = configure()
    check_versions()
    token = read_token(config.token_file)
    from glean.indexing.push import StatusClient
    from glean.api_client.models import DebugDocumentRequest
    observations = []
    report = {"operation": "check_document_status_and_access", "read_only": True}
    with bounded_client(config, token, observations):
        client = StatusClient(datasource=config.datasource, timeout_ms=TIMEOUT * 1000)
        try:
            with deadline():
                response = client.get_documents_status([DebugDocumentRequest(object_type=OBJECT_TYPE, doc_id=DOCUMENT_ID)])
            report.update(status_summary(response))
        except Exception as exc:
            report["status_check"] = safe_failure(exc)
        # Do not send a second request after auth rejection or a rate limit.
        if observations and observations[-1]["http_status"] in (401, 403, 429):
            report["access_check_skipped"] = "resolve_authentication_authorization_or_rate_limit_first"
        else:
            try:
                with deadline():
                    access = client.check_document_access(object_type=OBJECT_TYPE, document_id=DOCUMENT_ID,
                                                          user_email=config.test_email)
                report["configured_user_has_access"] = access.has_access if isinstance(access.has_access, bool) else None
            except Exception as exc:
                report["access_check"] = safe_failure(exc)
    report["requests"] = observations
    report["ready_for_ui_search_check"] = report.get("latest_upload_indexed") is True and report.get("configured_user_has_access") is True
    report["next_step"] = "Search GLEAN_INDEXING_QUERY in the Glean app as the configured test user. Test-datasource allow-listing is an additional gate."
    emit(report, token)
    return 0 if report["ready_for_ui_search_check"] else 1


if __name__ == "__main__":
    raise SystemExit(run_guarded(main))
