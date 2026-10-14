#!/usr/bin/env python3
"""Preview or add/update exactly one synthetic document with a one-user ACL."""
from lab import (Config, TIMEOUT, bounded_client, check_versions, configure, confirm_target,
                 deadline, emit, make_document, mutation_parser, preview, read_token,
                 run_guarded, safe_failure)


def main():
    args = mutation_parser(__doc__).parse_args()
    config = configure()
    check_versions()
    document = make_document(config)
    if not args.apply:
        emit(preview(config, "index_documents"))
        return 0
    confirm_target(config, args.confirm_sandbox)
    token = read_token(config.token_file)
    from glean.indexing.push import PushUploader
    observations = []
    report = {"mode": "applied", "operation": "index_documents", "documents_submitted": 1}
    try:
        with bounded_client(config, token, observations), deadline():
            uploader = PushUploader(datasource=config.datasource, timeout_ms=TIMEOUT * 1000, upload_max_workers=1)
            uploader.index_documents([document])
        report.update({"operation_completed": True, "indexing_and_search_visibility": "not_yet_verified"})
    except Exception as exc:
        report.update(safe_failure(exc))
    report["requests"] = observations
    emit(report, token)
    return 0 if report["operation_completed"] else 1


if __name__ == "__main__":
    raise SystemExit(run_guarded(main))
