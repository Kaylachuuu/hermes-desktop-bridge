"""Conversation-owned PC control, separate from the server's computer_use tool."""
import base64
import json
import copy
from pathlib import Path

READS = {"check_permissions", "list_apps", "list_windows", "get_window_state",
         "get_accessibility_tree", "get_desktop_state", "verify_state"}


def _use_aux_vision():
    from agent.auxiliary_client import _read_main_model, _read_main_provider
    from hermes_cli.config import load_config
    from tools.computer_use.vision_routing import should_route_capture_to_aux_vision
    return should_route_capture_to_aux_vision(_read_main_provider() or "", _read_main_model() or "", load_config())


def render_result(result):
    if not isinstance(result, dict) or not isinstance(result.get("content"), list):
        raise ValueError("Desktop returned no MCP result; outcome is unknown. Do not replay.")
    parts, images = [], []
    for block in result["content"]:
        if not isinstance(block, dict):
            continue
        if block.get("type") == "text":
            parts.append(str(block.get("text", "")))
        elif block.get("type") == "image":
            mime = block.get("mimeType")
            ext = {"image/png": ".png", "image/jpeg": ".jpg"}.get(mime)
            encoded = block.get("data", "")
            if not ext or not isinstance(encoded, str) or len(encoded) > 12000000:
                raise ValueError("Unsupported or oversized Desktop screenshot")
            raw = base64.b64decode(encoded, validate=True)
            from gateway.platforms.base import cache_image_from_bytes
            path = cache_image_from_bytes(raw, ext=ext)
            parts.append("MEDIA:" + path)
            images.append((mime, encoded, path))
    shaped = {"isError": bool(result.get("isError")), "output": "\n".join(parts),
              "structuredContent": result.get("structuredContent")}
    if shaped["isError"]:
        shaped.update(retry=False, guidance="Stop and report this error. Do not guess arguments or repeat a refused browser action.")
    summary = json.dumps(shaped, ensure_ascii=False)
    if images:
        if _use_aux_vision():
            from model_tools import _run_async
            from tools.vision_tools import vision_analyze_tool
            analyses = [_run_async(vision_analyze_tool(path, "Describe this desktop screenshot accurately. Cross-check the accessibility information; do not invent controls.\n" + summary))
                        for _, _, path in images]
            return json.dumps({"result": json.loads(summary), "screenshot_analysis": analyses}, ensure_ascii=False)
        return {"_multimodal": True, "text_summary": summary,
                "content": [{"type": "text", "text": summary}, *[
                    {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{encoded}"}}
                    for mime, encoded, _ in images]]}
    return summary


def install(ctx, bridge):
    docs = json.loads(Path(__file__).with_name("pc-schemas.json").read_text(encoding="utf-8"))
    from tui_gateway.contracts.registry import SERVER_REQUESTS, server_request
    from tui_gateway.contracts.server_requests import ServerRequestParams, ValueResult
    if "desktop.pc" not in SERVER_REQUESTS:
        class DesktopPcParams(ServerRequestParams):
            action: str
            arguments: dict = {}
        server_request("desktop.pc", params=DesktopPcParams, result=ValueResult,
                       doc="Call the PC driver on the session-owning Desktop, with native consent.")

    def handler(args, **kwargs):
        try:
            action = args.get("action")
            params = args.get("arguments") or {}
            if action not in {*docs, "describe", "status", "revoke"}:
                raise ValueError("Unsupported PC action")
            # Even introspection is restricted to a live, uniquely owned Desktop conversation.
            sid = bridge._owner(bridge._session_key())
            if action == "describe":
                tool = params.get("tool")
                return json.dumps(docs[tool] if tool in docs else {"available_actions": list(docs)})
            if not isinstance(params, dict) or "session" in params or "screenshot_out_file" in params:
                raise ValueError("Desktop manages session identity and screenshot paths")
            from tui_gateway import server_requests
            reply = server_requests.send("desktop.pc", sid, {"action": action, "arguments": params}, timeout=180)
            if not isinstance(reply, dict):
                raise ValueError("Desktop did not answer; outcome is unknown. Do not replay.")
            result = reply.get("value", reply)
            if isinstance(result, str):
                result = json.loads(result)
            return render_result(result)
        except Exception as exc:
            return json.dumps({"isError": True, "error": str(exc), "retry": False,
                               "guidance": "No automatic retry or server fallback. Inspect fresh state before another action."})

    ctx.register_tool("desktop_pc", "hermes-desktop-bridge", {
        "name": "desktop_pc",
        "description": "Control the session-owning Desktop PC. First call describe with arguments.tool to learn each exact PC action schema. Discover exact pid/window_id with list_windows; capture get_window_state, then act using fresh element tokens and verify. Windows text entry should target the exact editor field token; delivery alone does not confirm effect. For browser operations use the dedicated desktop_browser_prepare/read/navigate/click/type/pointer/dialog tools with their flat parameters. Desktop asks native permission. status reports availability; revoke ends this conversation's access. Keep this conversation visible. Stop on errors; never guess arguments or retry an uncertain action. Edge and Firefox are available in the updated prototype; macOS and Linux remain pending live validation.",
        "parameters": {"type": "object", "properties": {
            "action": {"type": "string", "enum": ["describe", "status", "revoke", *[name for name in docs if not name.startswith('browser_') and name != 'get_browser_state']]},
            "arguments": {"type": "object", "description": "Native driver arguments from describe; never provide session or screenshot_out_file."}
        }, "required": ["action"], "additionalProperties": False}
    }, handler, description="PC control on the owning Desktop", emoji="🖥️")

    for operation in ("list_windows", "browser_prepare", "get_browser_state", "browser_navigate", "browser_click", "browser_type", "browser_pointer", "browser_dialog"):
        tool_name = "desktop_browser_read" if operation == "get_browser_state" else "desktop_" + operation
        parameters = copy.deepcopy(docs[operation]["parameters"])
        for managed in ("session", "screenshot_out_file"):
            parameters.get("properties", {}).pop(managed, None)
            if managed in parameters.get("required", []):
                parameters["required"].remove(managed)
        description = docs[operation]["description"] + " Desktop supplies the conversation session internally; never supply session. Stop and report any refusal rather than guessing or looping."
        if operation == "get_browser_state":
            parameters["anyOf"] = [{"required": ["pid", "window_id"]}, {"required": ["target_id", "tab_id"]}]
        if operation == "browser_prepare":
            # The client supports exactly this setup form. Make omissions impossible at validation.
            parameters = {"type": "object", "properties": {
                "browser": {"type": "string", "enum": ["chrome", "edge", "firefox"], "description": "Browser to launch. Omit for the existing default Chromium route."},
                "allow_launch": {"type": "boolean"},
                "pid": {"type": "integer", "minimum": 1},
                "window_id": {"type": "integer", "minimum": 1},
                "profile": {"type": "object", "properties": {
                    "mode": {"type": "string", "enum": ["isolated_new", "athena_profile", "existing_profile"]}
                }, "required": ["mode"], "additionalProperties": False}
            }, "required": ["allow_launch", "profile"], "additionalProperties": False,
                "oneOf": [
                    {"properties": {"profile": {"properties": {"mode": {"enum": ["isolated_new", "athena_profile"]}}}, "allow_launch": {"const": True}}, "not": {"anyOf": [{"required": ["pid"]}, {"required": ["window_id"]}]}},
                    {"properties": {"profile": {"properties": {"mode": {"const": "existing_profile"}}}, "allow_launch": {"const": False}, "browser": {"enum": ["chrome", "edge"]}}, "required": ["pid", "window_id"]}
                ]}
            description = "Prepare the owning Desktop browser in an explicitly chosen mode. Private: allow_launch=true, profile={mode:isolated_new}. Separate persistent signed-in Athena profile: allow_launch=true, profile={mode:athena_profile}. Existing Chrome/Edge window: allow_launch=false, profile={mode:existing_profile}, exact pid and window_id from desktop_list_windows. browser selects chrome, edge or firefox for new profiles. Account-enabled modes need separate native approval for each call or this conversation. Existing Firefox attachment is unavailable. Edge/Firefox private and Athena profiles return target_id/tab_id directly; existing windows and default Chrome require exact native window binding with desktop_browser_read. Stop on refusals; never switch modes or retry without user instruction."
        def browser_handler(args, _operation=operation, **kwargs):
            return handler({"action": _operation, "arguments": args}, **kwargs)
        ctx.register_tool(tool_name, "hermes-desktop-bridge", {
            "name": tool_name, "description": description, "parameters": parameters
        }, browser_handler, description="Browser control on the owning Desktop", emoji="🌐")
