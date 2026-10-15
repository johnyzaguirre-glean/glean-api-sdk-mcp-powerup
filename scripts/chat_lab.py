"""Bounded, read-only Platform Chat examples with safe, useful output."""
from __future__ import annotations

import argparse
import contextlib
import importlib.metadata
import json
import logging
import re
import unicodedata
from urllib.parse import quote

from scripts.common import (
    MAX_RESPONSE_BYTES, ROOT, QuietLogger, ResponseBodyLimitExceeded,
    SafeFailure, execute, identifier, load_config, read_token, safe_url,
    save_report, serialized_output, validate_base,
)

CHAT_TIMEOUT = 120
MAX_ANSWER_CHARACTERS = 4000
MAX_CITATIONS = 10


def chat_parser(description):
    config = load_config()
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument("--base-url", default=config.get("GLEAN_BASE_URL"))
    parser.add_argument("--token-file", default=config.get("GLEAN_TOKEN_FILE"))
    parser.add_argument("--query", default=config.get("GLEAN_CHAT_QUERY"),
                        help="question to answer; defaults to GLEAN_CHAT_QUERY")
    return parser


def prepare_chat(args):
    logging.disable(logging.CRITICAL)
    base_url = validate_base(args.base_url)
    query = args.query
    if (not isinstance(query, str) or not query.strip() or len(query) > 1000
            or any(unicodedata.category(c).startswith("C") for c in query)):
        raise SafeFailure("set GLEAN_CHAT_QUERY to a question of 1 to 1000 characters without controls")
    if "YOUR QUESTION" in query.upper():
        raise SafeFailure("replace the GLEAN_CHAT_QUERY placeholder with your question")
    return base_url, read_token(args.token_file), query


def redact(value, token):
    """Redact before truncation, including a URL-encoded copy of the credential."""
    if not isinstance(value, str):
        return ""
    if token:
        for secret in {token, quote(token, safe=""), quote(token, safe="").lower()}:
            value = value.replace(secret, "[REDACTED]")
    return value


def display_text(value, token, limit):
    value = redact(value, token)
    # Remove terminal escapes and invisible formatting/control characters.
    value = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", value)
    value = "".join(" " if unicodedata.category(c).startswith("C") else c for c in value)
    # Model answers can contain links as well as structured citation URLs.
    value = re.sub(r"https?://[^\s<>\"`]+", lambda m: safe_url(m.group()) or "[link omitted]", value)
    return value[:limit]


def safe_identifier(value, token):
    return identifier(redact(value, token))


def error_metadata(data, token):
    if not isinstance(data, dict):
        return {}
    return {key: value for key in ("code", "request_id")
            if (value := safe_identifier(data.get(key), token)) is not None}


def chat_summary(data, token):
    if not isinstance(data, dict):
        return {"json_object": False, "answer_present": False, "citation_count": 0}
    status = safe_identifier(data.get("status"), token)
    output = data.get("output")
    result = {
        "json_object": True, **error_metadata(data, token),
        "response_status": status,
        "expected_payload_present": data.get("object") == "RESPONSE"
            and isinstance(output, list) and isinstance(data.get("request_id"), str)
            and isinstance(data.get("store"), bool),
        "store": data.get("store") if isinstance(data.get("store"), bool) else None,
        "conversation_id_present": bool(data.get("conversation_id")),
        "answer_present": False, "citation_count": 0,
    }
    if status != "COMPLETED":
        result["chat_error_code"] = safe_identifier(
            data.get("error", {}).get("code") if isinstance(data.get("error"), dict) else None, token)
        return result
    answers, citations = [], []
    citation_count = source_count = 0
    for message in output if isinstance(output, list) else []:
        if not isinstance(message, dict) or message.get("role") != "ASSISTANT":
            continue
        content = message.get("content")
        for part in content if isinstance(content, list) else []:
            if not isinstance(part, dict) or part.get("type") != "OUTPUT_TEXT":
                continue
            if isinstance(part.get("text"), str):
                answers.append(part["text"])
            annotations = part.get("annotations")
            for annotation in annotations if isinstance(annotations, list) else []:
                if not isinstance(annotation, dict) or annotation.get("type") != "CITATION":
                    continue
                sources = annotation.get("sources")
                if not isinstance(sources, list) or not sources:
                    continue
                citation_count += 1
                for source in sources:
                    if not isinstance(source, dict):
                        continue
                    source_count += 1
                    if len(citations) < MAX_CITATIONS:
                        citations.append({
                            "citation": citation_count,
                            "type": safe_identifier(source.get("type"), token),
                            "title": display_text(source.get("title") or source.get("name"), token, 240),
                            "url": safe_url(redact(source.get("url"), token)),
                        })
    answer = "\n".join(answers)
    clean_answer = display_text(answer, token, MAX_ANSWER_CHARACTERS)
    result.update({
        "answer_present": bool(clean_answer.strip()),
        "answer": clean_answer,
        "answer_character_count": len(answer),
        "answer_truncated": len(answer) > MAX_ANSWER_CHARACTERS,
        "citation_count": citation_count,
        "citation_source_count": source_count,
        "citations": citations,
        "citations_truncated": source_count > MAX_CITATIONS,
    })
    if not citation_count:
        result["citation_notice"] = "No source citations returned. Review the answer before relying on it."
    return result


@contextlib.contextmanager
def bounded_client(observation):
    """No redirects or retries. Bound the body even when the SDK reads it."""
    import httpx

    class LimitedStream(httpx.SyncByteStream):
        def __init__(self, stream):
            self.stream = stream

        def __iter__(self):
            size = 0
            for chunk in self.stream:
                size += len(chunk)
                if size > MAX_RESPONSE_BYTES:
                    raise ResponseBodyLimitExceeded("body_limit")
                yield chunk

        def close(self):
            self.stream.close()

    def on_request(_request):
        observation["request_count"] += 1

    def on_response(response):
        observation["http_status"] = response.status_code
        length = response.headers.get("content-length", "")
        if length.isdigit() and int(length) > MAX_RESPONSE_BYTES:
            response.close()
            raise ResponseBodyLimitExceeded("body_limit")
        if response.headers.get("content-encoding", "identity").lower() not in ("", "identity"):
            response.close()
            raise SafeFailure("unexpected_compressed_response")
        response.stream = LimitedStream(response.stream)

    with httpx.Client(timeout=CHAT_TIMEOUT, follow_redirects=False,
                      headers={"Accept-Encoding": "identity"},
                      event_hooks={"request": [on_request], "response": [on_response]}) as client:
        yield client


def chat_probe(base_url, token, query, use_sdk=False):
    observation = {"http_status": None, "request_count": 0}
    try:
        with bounded_client(observation) as client:
            if use_sdk:
                from glean.api_client import Glean
                with Glean(api_token=token, server_url=base_url, client=client,
                           retry_config=None, timeout_ms=CHAT_TIMEOUT * 1000,
                           debug_logger=QuietLogger()) as glean:
                    # Platform Chat, distinct from legacy glean.client.chat.create.
                    reply = glean.chat.create(input=query, store=False,
                                              retries=None, timeout_ms=CHAT_TIMEOUT * 1000)
                    data = reply.model_dump(mode="json", by_alias=True)
            else:
                response = client.post(base_url + "/api/chat",
                    headers={"Authorization": "Bearer " + token, "Accept": "application/json"},
                    json={"input": query, "store": False, "stream": False})
                try:
                    data = response.json()
                except (UnicodeDecodeError, json.JSONDecodeError):
                    return {**observation, "response_json": False}
            if observation["http_status"] != 200:
                return {**observation, **error_metadata(data, token)}
            return {**observation, **chat_summary(data, token)}
    except TimeoutError:
        raise
    except Exception as exc:
        result = {**observation, "exception_type": type(exc).__name__}
        if isinstance(exc, ResponseBodyLimitExceeded):
            result["response_omitted"] = "body_limit"
        # Never render raw exceptions, response bodies, detail or validation text.
        structured = getattr(exc, "data", None)
        for key in ("code", "request_id"):
            value = safe_identifier(getattr(structured, key, None), token)
            if value is not None:
                result[key] = value
        return result


def run_chat(use_sdk=False):
    parser = chat_parser("Ask Glean one question without storing the conversation.")
    args = parser.parse_args()
    base_url, token, query = prepare_chat(args)
    version = importlib.metadata.version("glean-api-client")
    if use_sdk and version != "0.17.16":
        raise SafeFailure("reinstall requirements.txt to use glean-api-client 0.17.16")
    mode = "python" if use_sdk else "rest"
    result = execute(mode + "_chat", 200,
                     lambda: chat_probe(base_url, token, query, use_sdk=use_sdk),
                     timeout_seconds=CHAT_TIMEOUT)
    if use_sdk:
        result["sdk_version"] = version
    result["test_expectation_met"] = bool(
        result["test_expectation_met"] and result.get("response_status") == "COMPLETED"
        and result.get("answer_present") and result.get("store") is False
        and not result.get("conversation_id_present"))
    result["review_note"] = "Check the answer and its citations. Generated wording can differ between runs."
    save_report(ROOT / "outputs" / (mode + "-chat.json"), result, token)
    print(serialized_output(result, token), end="")
    return 0 if result["test_expectation_met"] else 1
