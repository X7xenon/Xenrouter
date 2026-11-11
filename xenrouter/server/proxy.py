"""
High-performance asynchronous streaming proxy with token metrics and failover execution.
"""

import json
import time
import uuid
from typing import AsyncGenerator, List, Optional
import httpx
from fastapi import Request
from fastapi.responses import JSONResponse, StreamingResponse

from xenrouter.backends.base import BaseBackend
from xenrouter.router import RouteTarget, Router
from xenrouter.server.state import AppState
from xenrouter.types import RequestLog
from xenrouter.key_rotator import mask_key


class ProxyEngine:
    """Dispatches requests to local inference backends with automatic failover."""

    def __init__(self, router: Router, state: AppState, client: httpx.AsyncClient):
        self.router = router
        self.state = state
        self.client = client

    async def forward_chat_completion(self, request: Request, payload: dict) -> StreamingResponse | JSONResponse:
        req_id = f"xen-{uuid.uuid4().hex[:8]}"
        client_ip = request.client.host if request.client else "127.0.0.1"
        requested_model = payload.get("model", "")
        is_stream = payload.get("stream", False)
        start_time = time.perf_counter()

        self.state.record_request_start()
        routes = self.router.resolve_routes(requested_model)

        if not routes:
            self.state.record_request_end(success=False)
            err_msg = f"No active local backend found hosting model or alias: '{requested_model}'"
            log = RequestLog(
                id=req_id,
                timestamp=time.time(),
                client_ip=client_ip,
                model_requested=requested_model,
                resolved_model="NONE",
                backend_used="NONE",
                path=request.url.path,
                status_code=503,
                duration_ms=(time.perf_counter() - start_time) * 1000.0,
                error=err_msg
            )
            self.state.add_log(log)
            return JSONResponse(status_code=503, content={"error": {"message": err_msg, "type": "xenrouter_error"}})

        if is_stream:
            return await self._handle_stream(
                req_id=req_id,
                client_ip=client_ip,
                requested_model=requested_model,
                routes=routes,
                payload=payload,
                start_time=start_time,
                path=request.url.path
            )

        # Attempt non-streaming route cascade
        last_error = "Unknown error"
        for target in routes:
            backend = target.backend
            resolved_model = target.model_id

            if not backend.acquire_slot():
                continue

            forward_payload = dict(payload)
            forward_payload["model"] = resolved_model

            target_url = f"{backend.base_url}/v1/chat/completions"
            if backend.base_url.endswith("/v1"):
                target_url = f"{backend.base_url}/chat/completions"

            total_keys = max(1, backend.key_rotator.total_keys)
            key_attempt_success = False

            cascade_timeout = httpx.Timeout(
                timeout=min(backend.timeout, 12.0),
                connect=3.0,
                read=min(backend.timeout, 10.0)
            )

            for _ in range(total_keys):
                active_key = backend.get_api_key()
                headers = backend.build_headers(active_key)

                try:
                    resp = await self.client.post(
                        target_url,
                        json=forward_payload,
                        headers=headers,
                        timeout=cascade_timeout
                    )

                    duration_ms = (time.perf_counter() - start_time) * 1000.0
                    backend.update_quota_from_headers(dict(resp.headers))

                    # Check for rate-limit or auth failure to trigger key rotation
                    if resp.status_code in [401, 403, 429]:
                        backend.report_key_result(active_key, resp.status_code, is_error=True)
                        last_error = f"HTTP {resp.status_code} on {backend.name}"
                        continue # Try next key of this backend!

                    if resp.status_code == 200:
                        backend.release_slot()
                        backend.report_key_result(active_key, 200, is_error=False)
                        key_attempt_success = True
                        data = resp.json()

                        # Parse usage metrics if provided
                        usage = data.get("usage", {})
                        prompt_toks = usage.get("prompt_tokens", 0)
                        completion_toks = usage.get("completion_tokens", 0)
                        tok_per_sec = (completion_toks / (duration_ms / 1000.0)) if duration_ms > 0 else 0.0

                        self.state.record_request_end(
                            success=True,
                            prompt_tokens=prompt_toks,
                            completion_tokens=completion_toks,
                            provider=backend.name,
                            model=resolved_model
                        )

                        log = RequestLog(
                            id=req_id,
                            timestamp=time.time(),
                            client_ip=client_ip,
                            model_requested=requested_model,
                            resolved_model=resolved_model,
                            backend_used=backend.name,
                            path=request.url.path,
                            status_code=200,
                            duration_ms=duration_ms,
                            tokens_prompt=prompt_toks,
                            tokens_completion=completion_toks,
                            tokens_per_sec=tok_per_sec,
                            streaming=False,
                            key_used_masked=mask_key(active_key)
                        )
                        self.state.add_log(log)
                        return JSONResponse(status_code=200, content=data)
                    else:
                        last_error = f"Backend {backend.name} returned HTTP {resp.status_code}: {resp.text[:120]}"
                        break # Fall over to next route target!

                except Exception as exc:
                    backend.report_key_result(active_key, 500, is_error=True)
                    last_error = f"Connection failed to {backend.name}: {exc}"
                    continue

            backend.release_slot()
            if key_attempt_success:
                break

        # If all routes exhausted
        duration_ms = (time.perf_counter() - start_time) * 1000.0
        self.state.record_request_end(success=False)
        log = RequestLog(
            id=req_id,
            timestamp=time.time(),
            client_ip=client_ip,
            model_requested=requested_model,
            resolved_model="NONE",
            backend_used="EXHAUSTED",
            path=request.url.path,
            status_code=502,
            duration_ms=duration_ms,
            error=last_error
        )
        self.state.add_log(log)
        return JSONResponse(
            status_code=502,
            content={"error": {"message": f"All cascade backends failed. Last error: {last_error}", "type": "xenrouter_gateway_error"}}
        )

    async def _handle_stream(
        self,
        req_id: str,
        client_ip: str,
        requested_model: str,
        routes: List[RouteTarget],
        payload: dict,
        start_time: float,
        path: str
    ) -> StreamingResponse:
        """Handle real-time SSE streaming pass-through with automatic cascade failover and token tracking."""

        async def stream_generator() -> AsyncGenerator[bytes, None]:
            ttft_ms = None
            token_count = 0
            prompt_tokens = 0
            stream_started = False
            active_key_used = None
            last_error_msg = "All cascade backends exhausted"
            successful_backend = None
            successful_model = None

            for target in routes:
                if stream_started:
                    break

                backend = target.backend
                resolved_model = target.model_id

                if not backend.acquire_slot():
                    continue

                forward_payload = dict(payload)
                forward_payload["model"] = resolved_model

                target_url = f"{backend.base_url}/v1/chat/completions"
                if backend.base_url.endswith("/v1"):
                    target_url = f"{backend.base_url}/chat/completions"

                total_keys = max(1, backend.key_rotator.total_keys)
                backend_succeeded = False

                step_timeout = httpx.Timeout(
                    timeout=min(backend.timeout, 12.0),
                    connect=3.0,
                    read=min(backend.timeout, 10.0)
                )

                try:
                    for _ in range(total_keys):
                        if stream_started:
                            break

                        cur_key = backend.get_api_key()
                        active_key_used = cur_key
                        cur_headers = backend.build_headers(cur_key)

                        try:
                            async with self.client.stream(
                                "POST",
                                target_url,
                                json=forward_payload,
                                headers=cur_headers,
                                timeout=step_timeout
                            ) as upstream_response:
                                status_code = upstream_response.status_code
                                backend.update_quota_from_headers(dict(upstream_response.headers))

                                if status_code in [401, 403, 429]:
                                    backend.report_key_result(cur_key, status_code, is_error=True)
                                    last_error_msg = f"HTTP {status_code} on {backend.name}"
                                    continue  # Try next key of this backend!

                                if status_code != 200:
                                    backend.report_key_result(cur_key, status_code, is_error=True)
                                    last_error_msg = f"HTTP {status_code} on {backend.name}"
                                    break  # Fall over to next target in cascade!

                                # Status is 200 OK!
                                backend.report_key_result(cur_key, 200, is_error=False)
                                successful_backend = backend
                                successful_model = resolved_model

                                async for chunk in upstream_response.aiter_bytes():
                                    if not chunk:
                                        continue

                                    if not stream_started:
                                        stream_started = True
                                        backend_succeeded = True
                                        if ttft_ms is None:
                                            ttft_ms = (time.perf_counter() - start_time) * 1000.0

                                    # Inspect SSE lines for token estimation
                                    text_chunk = chunk.decode("utf-8", errors="ignore")
                                    for line in text_chunk.split("\n"):
                                        line = line.strip()
                                        if line.startswith("data: ") and line != "data: [DONE]":
                                            try:
                                                parsed = json.loads(line[6:])
                                                choices = parsed.get("choices", [])
                                                if choices and "delta" in choices[0]:
                                                    delta = choices[0]["delta"]
                                                    if delta.get("content"):
                                                        token_count += 1
                                                if "usage" in parsed:
                                                    usage = parsed["usage"]
                                                    prompt_tokens = usage.get("prompt_tokens", prompt_tokens)
                                                    parsed_comp = usage.get("completion_tokens", 0)
                                                    if parsed_comp > 0:
                                                        token_count = parsed_comp
                                            except Exception:
                                                pass

                                    yield chunk

                                if stream_started:
                                    backend_succeeded = True
                                    break  # Successfully finished stream

                        except Exception as exc:
                            backend.report_key_result(cur_key, 500, is_error=True)
                            last_error_msg = f"{backend.name} error: {exc}"
                            if stream_started:
                                return
                            continue

                finally:
                    backend.release_slot()

                if backend_succeeded:
                    break

            if not stream_started:
                # All cascade routes exhausted without sending any bytes
                self.state.record_request_end(success=False)
                err_data = json.dumps({"error": {"message": f"All cascade backends failed. Last error: {last_error_msg}", "type": "xenrouter_cascade_exhausted"}})
                yield f"data: {err_data}\n\ndata: [DONE]\n\n".encode("utf-8")

                duration_ms = (time.perf_counter() - start_time) * 1000.0
                log = RequestLog(
                    id=req_id,
                    timestamp=time.time(),
                    client_ip=client_ip,
                    model_requested=requested_model,
                    resolved_model="NONE",
                    backend_used="EXHAUSTED",
                    path=path,
                    status_code=502,
                    duration_ms=duration_ms,
                    streaming=True,
                    error=last_error_msg
                )
                self.state.add_log(log)
            else:
                duration_ms = (time.perf_counter() - start_time) * 1000.0
                gen_duration_sec = (duration_ms - (ttft_ms or 0.0)) / 1000.0
                tokens_per_sec = (token_count / gen_duration_sec) if gen_duration_sec > 0.05 else 0.0

                self.state.record_request_end(
                    success=True,
                    prompt_tokens=prompt_tokens,
                    completion_tokens=token_count,
                    provider=successful_backend.name if successful_backend else "UNKNOWN",
                    model=successful_model or requested_model
                )

                log = RequestLog(
                    id=req_id,
                    timestamp=time.time(),
                    client_ip=client_ip,
                    model_requested=requested_model,
                    resolved_model=successful_model or requested_model,
                    backend_used=successful_backend.name if successful_backend else "UNKNOWN",
                    path=path,
                    status_code=200,
                    duration_ms=duration_ms,
                    ttft_ms=ttft_ms,
                    tokens_prompt=prompt_tokens,
                    tokens_completion=token_count,
                    tokens_per_sec=tokens_per_sec,
                    streaming=True,
                    key_used_masked=mask_key(active_key_used)
                )
                self.state.add_log(log)

        return StreamingResponse(
            stream_generator(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
                "X-Xenrouter-Request-ID": req_id
            }
        )

    async def forward_embeddings(self, request: Request, payload: dict) -> JSONResponse:
        """Forward embedding requests to an active embedding-capable backend."""
        req_id = f"xen-{uuid.uuid4().hex[:8]}"
        client_ip = request.client.host if request.client else "127.0.0.1"
        requested_model = payload.get("model", "")
        start_time = time.perf_counter()

        self.state.record_request_start()
        routes = self.router.resolve_routes(requested_model)

        if not routes:
            self.state.record_request_end(success=False)
            err_msg = f"No operational backend found for embedding model: '{requested_model}'"
            return JSONResponse(status_code=503, content={"error": {"message": err_msg}})

        target = routes[0]
        backend = target.backend
        active_key = backend.get_api_key()
        headers = backend.build_headers(active_key)
        forward_payload = dict(payload)
        forward_payload["model"] = target.model_id

        target_url = f"{backend.base_url}/v1/embeddings"
        if backend.base_url.endswith("/v1"):
            target_url = f"{backend.base_url}/embeddings"

        try:
            resp = await self.client.post(target_url, json=forward_payload, headers=headers, timeout=backend.timeout)
            duration_ms = (time.perf_counter() - start_time) * 1000.0
            is_success = resp.status_code == 200
            self.state.record_request_end(success=is_success)

            log = RequestLog(
                id=req_id,
                timestamp=time.time(),
                client_ip=client_ip,
                model_requested=requested_model,
                resolved_model=target.model_id,
                backend_used=backend.name,
                path=request.url.path,
                status_code=resp.status_code,
                duration_ms=duration_ms,
                streaming=False,
                key_used_masked=mask_key(active_key)
            )
            self.state.add_log(log)
            return JSONResponse(status_code=resp.status_code, content=resp.json())

        except Exception as exc:
            self.state.record_request_end(success=False)
            return JSONResponse(status_code=502, content={"error": {"message": str(exc)}})
