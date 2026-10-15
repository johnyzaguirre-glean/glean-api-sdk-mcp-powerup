#!/usr/bin/env python3
"""Read-only allow/deny checks for the existing fictional indexing document."""
import argparse

from lab import (DOCUMENT_ID, MAX_RESPONSE_BYTES, OBJECT_TYPE, TIMEOUT, bounded_client, check_versions,
                 configure, deadline, emit, read_token, run_guarded, status_summary)

STOP_STATUSES = {401, 403, 429}


def not_run(expected, reason):
    return {"expected_has_access": expected, "result": "NOT_RUN", "reason": reason}


def read_failure(exc):
    report = {"exception_type": type(exc).__name__, "note": "Read-only check failed. No permissions changed."}
    status = getattr(exc, "status_code", None)
    if isinstance(status, int):
        report["http_status"] = status
    return report


def must_stop(observations):
    return bool(observations and observations[-1]["http_status"] in STOP_STATUSES)


def read_datasource_identity(identity_client, email):
    """Accept a bounded JSON 200 already fetched by the pinned client's debug method."""
    from glean.api_client.errors import GleanError
    from glean.api_client.models import DebugUserResponse

    try:
        return identity_client.debug_user(email=email)
    except GleanError as error:
        # Client 0.13.0 expects a charset on this response. Some servers omit it.
        # Parse only the existing response, never resend or weaken transport checks.
        response = error.raw_response
        media_type = response.headers.get("content-type", "").partition(";")[0].strip().lower()
        if response.status_code != 200 or media_type != "application/json":
            raise
        try:
            body = response.content  # Already consumed through the bounded transport.
            if len(body) > MAX_RESPONSE_BYTES:
                raise ValueError("response exceeds the existing limit")
            return DebugUserResponse.model_validate_json(body, strict=True)
        except Exception:
            raise error from None


def check_reader(client, identity_client, email, expected):
    report = not_run(expected, "datasource_identity_not_confirmed")
    try:
        # This beta diagnostic checks the datasource identity, not People/SSO setup.
        with deadline():
            identity = read_datasource_identity(identity_client, email)
        status = identity.status
        ready = bool(status and status.upload_status == "UPLOADED" and status.is_active_user is True)
        report["active_uploaded_datasource_identity"] = ready
        if not ready:
            return report
        with deadline():
            access = client.check_document_access(object_type=OBJECT_TYPE, document_id=DOCUMENT_ID,
                                                  user_email=email)
        actual = access.has_access
        if not isinstance(actual, bool):
            report["reason"] = "access_result_missing"
            return report
        report.update(has_access=actual, result="PASS" if actual == expected else "FAIL")
        report.pop("reason", None)
    except Exception as exc:
        report["reason"] = "read_only_check_failed"
        report["error"] = read_failure(exc)
    return report


def run_checks(config, token, transport=None):
    from glean.api_client.models import DebugDocumentRequest
    from glean.indexing.push import PushUploader, StatusClient

    observations = []
    report = {
        "operation": "check_existing_document_permissions", "read_only": True,
        "allowed_reader": not_run(True, "document_not_confirmed_indexed"),
        "denied_reader": not_run(False, "second_reader_not_configured" if not config.denied_test_email
                                 else "document_not_confirmed_indexed"),
        "end_to_end_search": "NOT_RUN",
        "limits": "Checks the existing document through the API. Does not verify sign-in, People profiles, distinct-person aliases, source visibility or actual search.",
    }
    with bounded_client(config, token, observations, transport=transport):
        client = StatusClient(datasource=config.datasource, timeout_ms=TIMEOUT * 1000)
        identity_client = PushUploader(datasource=config.datasource, timeout_ms=TIMEOUT * 1000)
        try:
            with deadline():
                response = client.get_documents_status([
                    DebugDocumentRequest(object_type=OBJECT_TYPE, doc_id=DOCUMENT_ID)])
            report["document"] = status_summary(response)
        except Exception as exc:
            report["document_error"] = read_failure(exc)
        if report.get("document", {}).get("latest_upload_indexed") is True:
            for label, email, expected in (("allowed_reader", config.test_email, True),
                                            ("denied_reader", config.denied_test_email, False)):
                if not email:
                    continue
                if must_stop(observations):
                    report[label] = not_run(expected, "resolve_authentication_authorization_or_rate_limit_first")
                    continue
                report[label] = check_reader(client, identity_client, email, expected)
    report["requests"] = observations
    results = [report[label]["result"] for label in ("allowed_reader", "denied_reader")]
    report["api_matrix_complete"] = all(result in {"PASS", "FAIL"} for result in results)
    report["all_expected_results_observed"] = results == ["PASS", "PASS"]
    report["next_step"] = (
        "Use each real reader's approved session to search the same query. Both need source visibility to isolate the document ACL. Follow indexing/PERMISSIONS.md."
        if report["all_expected_results_observed"] else
        "Review the case labels and indexing/PERMISSIONS.md. NOT_RUN is not denial proof. Do not change permissions just to make a check pass."
    )
    return report


def main():
    argparse.ArgumentParser(description=__doc__).parse_args()
    config = configure()
    check_versions()
    token = read_token(config.token_file)
    report = run_checks(config, token)
    emit(report, token)
    if report["all_expected_results_observed"]:
        return 0
    if report["allowed_reader"]["result"] == "PASS" and not config.denied_test_email:
        return 2  # Partial coverage, not an authentication or permission failure.
    return 1


if __name__ == "__main__":
    raise SystemExit(run_guarded(main))
