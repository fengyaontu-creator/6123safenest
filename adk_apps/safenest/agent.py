"""ADK Web discovery entry for SafeNest."""

from base64 import b64decode
from collections.abc import AsyncGenerator
from io import BytesIO
from pathlib import Path
import sys
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agents.orchestrator import root_agent as safenest_workflow
from config import settings
from google.adk.agents import LlmAgent
from google.adk.agents.invocation_context import InvocationContext
from google.adk.events import Event
from google.genai import types
from pypdf import PdfReader


MAX_CONTRACT_TEXT_CHARS = 12000


def _blob_bytes(data: bytes | str | None) -> bytes:
    if data is None:
        return b""
    if isinstance(data, bytes):
        return data
    return b64decode(data)


def _extract_pdf_text(pdf_bytes: bytes) -> str:
    if not pdf_bytes:
        return ""
    reader = PdfReader(BytesIO(pdf_bytes))
    chunks: list[str] = []
    for page in reader.pages:
        text = page.extract_text() or ""
        if text.strip():
            chunks.append(text.strip())
        if sum(len(chunk) for chunk in chunks) >= MAX_CONTRACT_TEXT_CHARS:
            break
    return "\n\n".join(chunks)[:MAX_CONTRACT_TEXT_CHARS]


def _contract_info_from_part(part: types.Part) -> dict[str, Any]:
    inline_data = getattr(part, "inline_data", None)
    if inline_data:
        mime_type = inline_data.mime_type or "application/octet-stream"
        file_name = inline_data.display_name or "uploaded_contract.pdf"
        info: dict[str, Any] = {
            "interface": "web",
            "contract_file_uploaded": True,
            "contract_file_name": file_name,
            "contract_mime_type": mime_type,
            "contract_source": "web_upload_inline",
        }
        if mime_type == "application/pdf" or file_name.lower().endswith(".pdf"):
            try:
                text = _extract_pdf_text(_blob_bytes(inline_data.data))
                if text:
                    info["contract_text"] = text
                    info["contract_text_source"] = "uploaded_pdf"
            except Exception as error:
                info["contract_text_error"] = f"{type(error).__name__}: {error}"
        return info

    file_data = getattr(part, "file_data", None)
    if file_data:
        return {
            "interface": "web",
            "contract_file_uploaded": True,
            "contract_file_name": file_data.display_name or file_data.file_uri,
            "contract_mime_type": file_data.mime_type,
            "contract_file_uri": file_data.file_uri,
            "contract_source": "web_upload_file_data",
        }

    return {}


def _merge_contract_info(ctx: InvocationContext, info: dict[str, Any]) -> None:
    if not info:
        return
    for key, value in info.items():
        if value not in (None, ""):
            ctx.session.state[key] = value


def _extract_uploaded_contracts_from_content(ctx: InvocationContext, content: types.Content | None) -> None:
    if not content or not content.parts:
        return
    for part in content.parts:
        _merge_contract_info(ctx, _contract_info_from_part(part))


async def _extract_uploaded_contracts_from_artifacts(ctx: InvocationContext) -> None:
    if not ctx.artifact_service:
        return
    try:
        artifact_names = await ctx.artifact_service.list_artifact_keys(
            app_name=ctx.app_name,
            user_id=ctx.user_id,
            session_id=ctx.session.id,
        )
    except Exception:
        return

    for artifact_name in artifact_names:
        if not artifact_name.lower().endswith(".pdf"):
            continue
        try:
            artifact = await ctx.artifact_service.load_artifact(
                app_name=ctx.app_name,
                user_id=ctx.user_id,
                session_id=ctx.session.id,
                filename=artifact_name,
            )
        except Exception:
            continue
        info = {"contract_file_name": artifact_name, "contract_source": "web_artifact"}
        if artifact:
            info.update(_contract_info_from_part(artifact))
            info["contract_file_name"] = artifact_name
            info["contract_source"] = "web_artifact"
        _merge_contract_info(ctx, info)
        return


async def _capture_uploaded_contracts(ctx: InvocationContext) -> None:
    ctx.session.state["interface"] = "web"
    _extract_uploaded_contracts_from_content(ctx, ctx.user_content)
    for event in ctx.session.events:
        _extract_uploaded_contracts_from_content(ctx, event.content)
    await _extract_uploaded_contracts_from_artifacts(ctx)


def _sanitized_content(content: types.Content | None) -> types.Content | None:
    """Remove uploaded file/blob parts before the internal text-only workflow."""

    if not content or not content.parts:
        return content

    parts: list[types.Part] = []
    omitted_files = 0
    for part in content.parts:
        if part.text:
            parts.append(types.Part(text=part.text))
        elif getattr(part, "inline_data", None) or getattr(part, "file_data", None):
            omitted_files += 1

    if omitted_files:
        parts.append(
            types.Part(
                text=(
                    f"[{omitted_files} uploaded file(s) omitted from LLM context. "
                    "Use extracted contract state if available; otherwise ask the "
                    "user to upload the contract PDF file.]"
                )
            )
        )

    if not parts:
        return content

    return types.Content(role=content.role or "user", parts=parts)


def _sanitize_session_history(ctx: InvocationContext) -> None:
    for event in ctx.session.events:
        sanitized = _sanitized_content(event.content)
        if sanitized is not event.content:
            event.content = sanitized


class SafeNestWebAgent(LlmAgent):
    """LlmAgent-compatible web shell that does not emit transfer/tool events."""

    async def _run_async_impl(
        self,
        ctx: InvocationContext,
    ) -> AsyncGenerator[Event, None]:
        await _capture_uploaded_contracts(ctx)
        _sanitize_session_history(ctx)
        workflow_ctx = ctx.model_copy(update={"user_content": _sanitized_content(ctx.user_content)})
        async for event in safenest_workflow.run_async(workflow_ctx):
            yield event


root_agent = SafeNestWebAgent(
    name="safenest",
    model=settings.web_entry_model,
    instruction=(
        "SafeNest web shell. Run the internal SafeNest workflow directly. "
        "Visible chat output must be limited to missing-information questions "
        "and the final tenant-facing report."
    ),
)


__all__ = ["SafeNestWebAgent", "root_agent"]
