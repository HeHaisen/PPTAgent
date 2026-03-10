import asyncio
import os
import tempfile
import zipfile
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import aiohttp


async def parse_pdf_offline(pdf_path: str, output_path: str, url: str) -> None:
    """Parse PDF using a local/compatible MinerU endpoint."""
    os.makedirs(output_path, exist_ok=True)
    pdf_path_obj = Path(pdf_path)

    async with aiohttp.ClientSession() as session:
        content = await _post_offline_parse_request(session, url, pdf_path_obj)

    _extract_zip_bytes(content, output_path)


async def _post_offline_parse_request(
    session: aiohttp.ClientSession, url: str, pdf_path_obj: Path
) -> bytes:
    attempt_errors: list[tuple[str, int, object]] = []

    for attempt in _offline_parse_attempts():
        request_url = (
            _append_query_params(url, response_format_zip="true")
            if attempt["zip_in_query"]
            else url
        )
        form = aiohttp.FormData()
        with pdf_path_obj.open("rb") as file_obj:
            form.add_field(
                attempt["field_name"],
                file_obj,
                filename=pdf_path_obj.name,
                content_type="application/pdf",
            )
            if attempt["zip_in_form"]:
                form.add_field("response_format_zip", "true")

            async with session.post(request_url, data=form) as resp:
                if resp.status == 200:
                    content = await resp.read()
                    if content[:2] != b"PK":
                        raise RuntimeError(
                            "MinerU local endpoint returned a non-zip payload. "
                            "Please confirm the service supports response_format_zip."
                        )
                    return content
                attempt_errors.append(
                    (attempt["name"], resp.status, await _read_error_payload(resp))
                )

    raise RuntimeError(_format_offline_attempt_errors(attempt_errors))


async def parse_pdf_online(
    pdf_path: str, output_path: str, token: str, model_version: str = "vlm"
) -> None:
    """Parse PDF using MinerU external API

    Args:
        pdf_path: PDF file path
        output_path: Output directory
        token: API Token
        model_version: Model version (vlm/pipeline)
    """
    os.makedirs(output_path, exist_ok=True)
    pdf_path = Path(pdf_path)

    async with aiohttp.ClientSession() as session:
        batch_id, upload_url, upload_headers = await _request_upload_url(
            session, pdf_path.name, pdf_path.stem[:128], model_version, token
        )

        await _upload_file(session, upload_url, pdf_path, upload_headers)

        zip_url = await _poll_result(session, batch_id, token)

        await _download_and_extract(session, zip_url, output_path)


async def _request_upload_url(
    session: aiohttp.ClientSession,
    filename: str,
    data_id: str,
    model_version: str,
    token: str,
) -> tuple[str, str, dict[str, str] | None]:
    """Request upload URL, returns (batch_id, upload_url, upload_headers)"""
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {token}"}
    payload = {
        "files": [{"name": filename, "data_id": data_id}],
        "model_version": model_version,
    }

    async with session.post(
        "https://mineru.net/api/v4/file-urls/batch", headers=headers, json=payload
    ) as resp:
        resp.raise_for_status()
        result = await resp.json()
        if result["code"] != 0:
            raise RuntimeError(
                f"Failed to request upload URL: {result.get('msg', 'Unknown error')}"
            )

        data = result["data"]
        upload_headers = data.get("headers", [None])[0] if "headers" in data else None
        return data["batch_id"], data["file_urls"][0], upload_headers


async def _upload_file(
    session: aiohttp.ClientSession,
    upload_url: str,
    pdf_path: Path,
    headers: dict[str, str] | None = None,
) -> None:
    """Upload PDF file to OSS"""
    file_data = pdf_path.read_bytes()

    upload_headers = headers if headers else {}

    async with session.put(
        upload_url,
        data=file_data,
        headers=upload_headers,
        skip_auto_headers={"Content-Type"},
    ) as resp:
        resp.raise_for_status()


async def _poll_result(
    session: aiohttp.ClientSession, batch_id: str, token: str
) -> str:
    """Poll parsing result, returns download URL"""
    headers = {"Authorization": f"Bearer {token}"}
    url = f"https://mineru.net/api/v4/extract-results/batch/{batch_id}"

    while True:
        async with session.get(url, headers=headers) as resp:
            resp.raise_for_status()
            result = await resp.json()

            if result["code"] != 0:
                raise RuntimeError(
                    f"Query failed: {result.get('msg', 'Unknown error')}"
                )

            extract = result["data"]["extract_result"][0]
            state = extract["state"]

            if state == "done":
                return extract["full_zip_url"]
            elif state == "failed":
                raise RuntimeError(
                    f"Parsing failed: {extract.get('err_msg', 'Unknown error')}"
                )

            await asyncio.sleep(5)


async def _download_and_extract(
    session: aiohttp.ClientSession, zip_url: str, output_path: str
) -> None:
    """Download and extract result"""
    async with session.get(zip_url) as resp:
        resp.raise_for_status()
        content = await resp.read()

    _extract_zip_bytes(content, output_path)


async def _raise_parsedoc_error(resp: aiohttp.ClientResponse) -> None:
    """Raise a RuntimeError with parsed error content."""
    raise RuntimeError(await _read_error_payload(resp))


async def _read_error_payload(resp: aiohttp.ClientResponse) -> object:
    try:
        return await resp.json()
    except Exception:
        return await resp.text()


def _append_query_params(url: str, **params: str) -> str:
    parts = urlsplit(url)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    query.update(params)
    return urlunsplit(
        (parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment)
    )


def _offline_parse_attempts() -> list[dict[str, object]]:
    return [
        {
            "name": "files + response_format_zip(form)",
            "field_name": "files",
            "zip_in_form": True,
            "zip_in_query": False,
        },
        {
            "name": "files + response_format_zip(query)",
            "field_name": "files",
            "zip_in_form": False,
            "zip_in_query": True,
        },
        {
            "name": "files only",
            "field_name": "files",
            "zip_in_form": False,
            "zip_in_query": False,
        },
        {
            "name": "files[] + response_format_zip(form)",
            "field_name": "files[]",
            "zip_in_form": True,
            "zip_in_query": False,
        },
        {
            "name": "pdf compat",
            "field_name": "pdf",
            "zip_in_form": False,
            "zip_in_query": False,
        },
    ]


def _format_offline_attempt_errors(attempt_errors: list[tuple[str, int, object]]) -> str:
    details = "\n".join(
        f"- {name}: HTTP {status}, payload={payload!r}"
        for name, status, payload in attempt_errors
    )
    return (
        "MinerU local endpoint rejected all tested upload variants.\n"
        f"{details}"
    )


def _extract_zip_bytes(content: bytes, output_path: str) -> None:
    """Extract zip bytes into output_path."""
    with tempfile.NamedTemporaryFile(delete=False, suffix=".zip") as tmp:
        tmp.write(content)
        zip_path = tmp.name

    with zipfile.ZipFile(zip_path, "r") as zip_ref:
        all_names = [name for name in zip_ref.namelist() if name.strip()]
        top_level = {name.split("/", 1)[0] for name in all_names}

        if len(top_level) == 1 and all("/" in name for name in all_names):
            prefix = list(top_level)[0] + "/"
        else:
            prefix = ""

        for member in zip_ref.infolist():
            if not member.is_dir():
                rel_path = (
                    member.filename.removeprefix(prefix) if prefix else member.filename
                )
                dest_path = os.path.join(output_path, rel_path)
                os.makedirs(os.path.dirname(dest_path), exist_ok=True)
                with zip_ref.open(member) as src, open(dest_path, "wb") as dst:
                    dst.write(src.read())

    os.unlink(zip_path)
