#!/usr/bin/env python3
"""Optional separate step to map the one approved tester into this demo datasource."""
from lab import (TIMEOUT, bounded_client, check_versions, configure, confirm_target, deadline,
                 emit, mutation_parser, preview, read_token, run_guarded, safe_failure)


def main():
    args = mutation_parser(__doc__).parse_args()
    config = configure()
    check_versions()
    if not args.apply:
        report = preview(config, "index_user")
        report["note"] = "Only use this if your administrator says the dedicated datasource needs the tester identity. No request sent."
        emit(report)
        return 0
    confirm_target(config, args.confirm_sandbox)
    token = read_token(config.token_file)
    from glean.indexing.push import PushUploader
    from glean.api_client.models import DatasourceUserDefinition
    observations = []
    report = {"mode": "applied", "operation": "index_user", "users_submitted": 1}
    try:
        with bounded_client(config, token, observations), deadline():
            uploader = PushUploader(datasource=config.datasource, timeout_ms=TIMEOUT * 1000, upload_max_workers=1)
            uploader.index_user(DatasourceUserDefinition(email=config.test_email, name="PowerUp demo tester", is_active=True))
        report["operation_completed"] = True
    except Exception as exc:
        report.update(safe_failure(exc))
    report["requests"] = observations
    emit(report, token)
    return 0 if report["operation_completed"] else 1


if __name__ == "__main__":
    raise SystemExit(run_guarded(main))
