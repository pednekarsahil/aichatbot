import os
import random
import time
import json
import http.client
import subprocess
import shutil
import urllib.request
import urllib.error
import urllib.parse
from flask import Flask, request, jsonify, Response, stream_with_context, send_file
from flask_cors import CORS

app = Flask(__name__, static_folder=".", static_url_path="")
CORS(app)

OLLAMA_HOST = "127.0.0.1"
OLLAMA_PORT = 11434
OLLAMA_BASE_URL = f"http://{OLLAMA_HOST}:{OLLAMA_PORT}"
DEFAULT_MODEL = "qwen3-coder:480b-cloud"

COMFYUI_HOST = "127.0.0.1"
COMFYUI_PORT = 8188
COMFYUI_BASE_URL = f"http://{COMFYUI_HOST}:{COMFYUI_PORT}"


def get_available_models():
    """Fetch all models currently available in local Ollama."""
    try:
        req = urllib.request.Request(f"{OLLAMA_BASE_URL}/api/tags")
        with urllib.request.urlopen(req, timeout=3) as response:
            if response.status == 200:
                data = json.loads(response.read().decode("utf-8"))
                return [m.get("name", "") for m in data.get("models", [])]
    except Exception as e:
        print(f"[Warning] Could not fetch models from Ollama: {e}")
    return []


def unload_model(model_name):
    """
    Unloads a specific model from GPU/VRAM/RAM immediately by setting keep_alive to 0.
    Finds exact model tag from Ollama available tags to avoid 404 errors.
    """
    if not model_name:
        return
    try:
        available = get_available_models()
        target_exact = None
        # Find exact matching tag
        for m in available:
            if model_name.lower() in m.lower():
                target_exact = m
                break

        if not target_exact:
            # Not in Ollama or not loaded, nothing to unload
            return

        payload = json.dumps({
            "model": target_exact,
            "keep_alive": 0
        }).encode("utf-8")
        req = urllib.request.Request(
            f"{OLLAMA_BASE_URL}/api/generate",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST"
        )
        with urllib.request.urlopen(req, timeout=3) as resp:
            pass
        print(f"[Ollama] Unloaded model from memory: {target_exact}")
    except Exception as e:
        # Silently pass if already unloaded or not present
        pass


def unload_all_ollama_models():
    """Unloads all models from Ollama to completely free GPU/VRAM/RAM."""
    try:
        available = get_available_models()
        for m in available:
            unload_model(m)
        print("[Ollama] Unloaded all Ollama models from memory.")
    except Exception as e:
        print(f"[Warning] Error unloading all Ollama models: {e}")


def resolve_model_name(requested_name=None):
    """
    Resolve requested model name against local Ollama models.
    Strictly separates:
    - 'uncensored': uses the heavy 27B model
    - 'text' (default): strictly uses Qwen 3 coder cloud 480b, unloading any other heavy model from RAM/VRAM
    """
    available = get_available_models()
    if not available:
        return requested_name or DEFAULT_MODEL

    req_lower = (requested_name or "").lower()

    # If the user specifically requested the uncensored or cybersecurity model
    if "uncensored" in req_lower or "cyber" in req_lower or "philbert440" in req_lower:
        target_model = None
        for m in available:
            if "philbert440" in m.lower() or "uncensored" in m.lower() or "cyber" in m.lower():
                target_model = m
                break
        if not target_model:
            target_model = "hf.co/philbert440/Qwen3.8-27B-Uncensored-Cyber-GGUF:Q4_K_M"

        # Stop all other models (e.g. qwen3-coder:30b) so no extra load is put on the system
        for m in available:
            if m != target_model:
                unload_model(m)

        return target_model

    # For default text generation, coding, and general tasks:
    # 1. Unload local heavy models from memory (such as 30b, 27b, philbert440)
    for m in available:
        m_lower = m.lower()
        if "30b" in m_lower or "philbert440" in m_lower or "27b" in m_lower or "uncensored" in m_lower:
            unload_model(m)

    # 2. Check available Ollama models for qwen 480b / cloud
    for m in available:
        m_lower = m.lower()
        if "qwen" in m_lower and ("480" in m_lower or "cloud" in m_lower):
            return m

    # 3. Check for qwen coder
    for m in available:
        m_lower = m.lower()
        if "qwen" in m_lower and "coder" in m_lower:
            return m

    # 4. Check for any qwen model
    for m in available:
        m_lower = m.lower()
        if "qwen" in m_lower:
            return m

    # 5. Check for any coder model
    for m in available:
        m_lower = m.lower()
        if "coder" in m_lower:
            return m

    return requested_name or DEFAULT_MODEL


@app.route("/api/unload-all", methods=["POST"])
def unload_all_endpoint():
    """Endpoint to explicitly unload all Ollama models from memory."""
    unload_all_ollama_models()
    return jsonify({"status": "success", "message": "All Ollama models unloaded from memory"})


@app.route("/api/unload", methods=["POST"])
def unload_endpoint():
    """Endpoint to explicitly free RAM/VRAM/GPU by unloading any model."""
    data = request.get_json(silent=True) or {}
    model_name = data.get("model")
    if not model_name:
        available = get_available_models()
        for m in available:
            if "philbert440" in m.lower() or "uncensored" in m.lower():
                unload_model(m)
        return jsonify({"status": "success", "message": "Heavy uncensored model unloaded from memory"})
    unload_model(model_name)
    return jsonify({"status": "success", "unloaded": model_name})


def fetch_web_search_context(query, max_results=3):
    """
    Fetch real-time web search summaries from DuckDuckGo Instant Answer API.
    Zero external API keys needed.
    """
    try:
        clean_query = query.strip()
        if not clean_query:
            return ""

        encoded_q = urllib.parse.quote_plus(clean_query)
        # 1. DuckDuckGo Instant Answer API
        url = f"https://api.duckduckgo.com/?q={encoded_q}&format=json&no_html=1&skip_disambig=1"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) ChatbotAI/1.0"})
        with urllib.request.urlopen(req, timeout=4) as response:
            if response.status == 200:
                data = json.loads(response.read().decode("utf-8"))
                snippets = []
                abstract = data.get("AbstractText", "").strip()
                if abstract:
                    source = data.get("AbstractSource", "Web")
                    snippets.append(f"[{source}] {abstract}")

                related = data.get("RelatedTopics", [])
                for item in related[:max_results]:
                    txt = item.get("Text", "").strip() if isinstance(item, dict) else ""
                    if txt and txt not in snippets:
                        snippets.append(f"- {txt}")

                if snippets:
                    return "\n".join(snippets[:max_results + 1])
    except Exception as e:
        print(f"[WebSearch] Error fetching live search: {e}")
    return ""


@app.route("/api/search", methods=["GET"])
def web_search_endpoint():
    """Frontend endpoint to query live internet web data."""
    q = request.args.get("q", "").strip()
    if not q:
        return jsonify({"results": ""})
    context = fetch_web_search_context(q)
    return jsonify({"query": q, "results": context})


@app.route("/api/models", methods=["GET"])
def list_models():
    """List all available models in local Ollama."""
    models = get_available_models()
    return jsonify({
        "status": "success",
        "models": models,
        "default": resolve_model_name()
    })


def free_comfyui_memory():
    """
    Tells ComfyUI to immediately unload all models from VRAM/RAM so that
    flux1-schnell-fp8 does not stay resident in memory when stopped or finished.
    """
    try:
        req = urllib.request.Request(
            f"{COMFYUI_BASE_URL}/free",
            data=json.dumps({"unload_models": True, "free_memory": True}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST"
        )
        with urllib.request.urlopen(req, timeout=3) as res:
            pass
        print("[ComfyUI] Successfully freed and unloaded models from VRAM/RAM.")
    except Exception as e:
        # Ignore if ComfyUI isn't open
        pass


@app.route("/api/chat", methods=["POST"])
def chat():
    """
    Stream or send prompt to local Ollama Qwen Coder model.
    Accepts: { "prompt": "...", "model": "...", "stream": true }
    """
    # Free ComfyUI image model so GPU/VRAM/CPU is dedicated to text generation
    free_comfyui_memory()

    data = request.get_json(silent=True) or {}
    prompt = data.get("prompt", "").strip()
    requested_model = data.get("model", "")
    stream = data.get("stream", True)

    if not prompt:
        return jsonify({"error": "Prompt cannot be empty"}), 400

    target_model = resolve_model_name(requested_model)

    ollama_payload = json.dumps({
        "model": target_model,
        "prompt": prompt,
        "stream": stream
    }).encode("utf-8")

    if stream:
        def generate():
            conn = None
            try:
                conn = http.client.HTTPConnection(OLLAMA_HOST, OLLAMA_PORT, timeout=180)
                conn.request("POST", "/api/generate", ollama_payload, {"Content-Type": "application/json"})
                res = conn.getresponse()

                if res.status != 200:
                    err_msg = res.read().decode("utf-8", errors="replace")
                    yield f"data: {json.dumps({'error': f'Ollama error ({res.status}): {err_msg}'})}\n\n"
                    return

                while True:
                    line = res.readline()
                    if not line:
                        break
                    line_str = line.decode("utf-8", errors="replace").strip()
                    if not line_str:
                        continue
                    try:
                        chunk_json = json.loads(line_str)
                        token = chunk_json.get("response", "")
                        done = chunk_json.get("done", False)
                        yield f"data: {json.dumps({'token': token, 'done': done})}\n\n"
                        if done:
                            break
                    except Exception:
                        pass
            except Exception as e:
                yield f"data: {json.dumps({'error': 'Please Try Again.'})}\n\n"
            finally:
                if conn:
                    try:
                        conn.close()
                    except Exception:
                        pass

        return Response(
            stream_with_context(generate()),
            mimetype="text/event-stream",
            headers={
                "Cache-Control": "no-cache, no-transform",
                "X-Accel-Buffering": "no",
                "Connection": "keep-alive"
            }
        )
    else:
        try:
            req = urllib.request.Request(
                f"{OLLAMA_BASE_URL}/api/generate",
                data=ollama_payload,
                headers={"Content-Type": "application/json"},
                method="POST"
            )
            with urllib.request.urlopen(req, timeout=180) as response:
                result = json.loads(response.read().decode("utf-8"))
                return jsonify({
                    "model": target_model,
                    "response": result.get("response", "")
                })
        except Exception as e:
            return jsonify({
                "error": f"Failed to connect to Ollama: {str(e)}. Make sure Ollama is running."
            }), 502


@app.route("/api/models/check-offline", methods=["GET"])
def check_offline_setup():
    """
    Check if local Ollama and ComfyUI are running and have models available.
    Used for silent health verification when switching to Offline mode.
    """
    ollama_ok = False
    comfy_ok = False
    models = []

    try:
        req = urllib.request.Request(f"{OLLAMA_BASE_URL}/api/tags")
        with urllib.request.urlopen(req, timeout=0.8) as res:
            if res.status == 200:
                data = json.loads(res.read().decode("utf-8"))
                models = [m.get("name", "") for m in data.get("models", [])]
                ollama_ok = len(models) > 0
    except Exception:
        ollama_ok = False

    try:
        req = urllib.request.Request(f"{COMFYUI_BASE_URL}/system_stats")
        with urllib.request.urlopen(req, timeout=0.8) as res:
            if res.status == 200:
                comfy_ok = True
    except Exception:
        comfy_ok = False

    # BOTH Ollama AND ComfyUI must be running and ready.
    # If any one is not running, all_ready is False.
    all_ready = bool(ollama_ok and comfy_ok)

    return jsonify({
        "status": "success",
        "ollama_ready": ollama_ok,
        "comfy_ready": comfy_ok,
        "models_count": len(models),
        "all_ready": all_ready
    })


@app.route("/api/chat-online", methods=["POST"])
def chat_online():
    """
    Proxy online cloud completions with automatic silent fallback between:
    1. Groq (Ultra-fast LPU)
    2. OpenRouter (High-capacity multi-model)
    3. Google Gemini (Multimodal Flash)
    If one provider fails, times out, or has an error, it seamlessly & silently
    switches to the next working provider without interrupting the user.
    """
    data = request.get_json(silent=True) or {}
    prompt = data.get("prompt", "").strip()
    if not prompt:
        return jsonify({"error": "Prompt cannot be empty"}), 400

    groq_key = (data.get("groq_key") or (data.get("api_key") if data.get("provider") == "groq" else "")).strip()
    openrouter_key = (data.get("openrouter_key") or (data.get("api_key") if data.get("provider") == "openrouter" else "")).strip()
    gemini_key = (data.get("gemini_key") or (data.get("api_key") if data.get("provider") == "gemini" else "")).strip()

    # Determine priority order of providers based on available keys
    provider_candidates = []
    if groq_key:
        provider_candidates.append(("groq", groq_key))
    if openrouter_key:
        provider_candidates.append(("openrouter", openrouter_key))
    if gemini_key:
        provider_candidates.append(("gemini", gemini_key))

    # Fallback to single legacy provider if passed
    if not provider_candidates and data.get("api_key"):
        provider_candidates.append((data.get("provider", "groq").lower(), data.get("api_key").strip()))

    if not provider_candidates:
        return jsonify({"error": "No valid online API key provided."}), 400

    default_user_agent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"

    online_system_instruction = (
        "You are an expert AI assistant. Always provide well-structured, clean, elegant, and readable responses.\n"
        "- Organize your answer with clear markdown headings (##, ###), clean paragraphs, and structured bullet points.\n"
        "- For ANY code snippets, ALWAYS wrap them in standard markdown code blocks with the exact language identifier "
        "(e.g. ```python, ```javascript, ```html, ```css, ```cpp, ```bash, etc.). Never output unformatted code.\n"
        "- Ensure all code is cleanly indented, complete, and properly commented.\n"
        "- Keep explanations direct, well-paced, and concise."
    )

    def try_provider_stream(provider_name, key):
        """Attempts to open a streaming connection to a specific provider. Returns (resp, error)."""
        messages = [
            {"role": "system", "content": online_system_instruction},
            {"role": "user", "content": prompt}
        ]

        if provider_name == "groq":
            groq_model = None
            try:
                models_req = urllib.request.Request(
                    "https://api.groq.com/openai/v1/models",
                    headers={"Authorization": f"Bearer {key}", "User-Agent": default_user_agent}
                )
                with urllib.request.urlopen(models_req, timeout=4) as m_resp:
                    m_data = json.loads(m_resp.read().decode("utf-8"))
                    avail_models = [m.get("id") for m in m_data.get("data", []) if m.get("id")]
                    if avail_models:
                        chat_models = [
                            m for m in avail_models
                            if not any(x in m.lower() for x in ["orpheus", "guard", "whisper", "vision", "embed", "moderation", "classification", "tts", "stt"])
                        ]
                        preferred = [
                            "llama-3.3-70b-versatile",
                            "llama-3.1-8b-instant",
                            "llama3-70b-8192",
                            "llama3-8b-8192",
                            "mixtral-8x7b-32768",
                            "gemma2-9b-it"
                        ]
                        for pref in preferred:
                            if pref in avail_models:
                                groq_model = pref
                                break
                        if not groq_model and chat_models:
                            groq_model = chat_models[0]
            except Exception:
                pass

            if not groq_model:
                groq_model = "mixtral-8x7b-32768"

            url = "https://api.groq.com/openai/v1/chat/completions"
            payload = json.dumps({
                "model": groq_model,
                "messages": messages,
                "max_tokens": 8192,
                "stream": True
            }).encode("utf-8")
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {key}",
                "User-Agent": default_user_agent,
                "Accept": "text/event-stream, application/json"
            }

        elif provider_name == "openrouter":
            url = "https://openrouter.ai/api/v1/chat/completions"
            payload = json.dumps({
                "model": "qwen/qwen-2.5-coder-32b-instruct",
                "messages": messages,
                "max_tokens": 8192,
                "stream": True
            }).encode("utf-8")
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {key}",
                "HTTP-Referer": "http://localhost:5000",
                "X-Title": "ChatbotAI",
                "User-Agent": default_user_agent,
                "Accept": "text/event-stream, application/json"
            }

        elif provider_name == "gemini":
            url = "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"
            payload = json.dumps({
                "model": "gemini-1.5-flash",
                "messages": messages,
                "max_tokens": 8192,
                "stream": True
            }).encode("utf-8")
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {key}",
                "User-Agent": default_user_agent,
                "Accept": "text/event-stream, application/json"
            }
        else:
            return None, f"Unsupported provider: {provider_name}"

        req = urllib.request.Request(url, data=payload, headers=headers, method="POST")
        try:
            resp = urllib.request.urlopen(req, timeout=300)
            return resp, None
        except urllib.error.HTTPError as he:
            err_body = he.read().decode("utf-8", errors="replace")
            try:
                err_json = json.loads(err_body)
                err_msg = err_json.get("error", {}).get("message") or err_body
            except Exception:
                err_msg = err_body
            return None, f"{provider_name.upper()} error ({he.code}): {err_msg}"
        except Exception as e:
            return None, f"{provider_name.upper()} connection error: {str(e)}"

    def stream_with_silent_fallback():
        active_resp = None
        last_error = None

        # Try providers sequentially; switch silently if one fails
        for p_name, p_key in provider_candidates:
            resp, err = try_provider_stream(p_name, p_key)
            if resp:
                print(f"[Online Chat] Successfully connected to {p_name.upper()}. Streaming response...")
                active_resp = resp
                break
            else:
                print(f"[Online Chat] {p_name.upper()} failed ({err}). Silently switching to next available provider...")
                last_error = err

        if not active_resp:
            yield f"data: {json.dumps({'error': f'All online providers failed. Last error: {last_error}'})}\n\n"
            return

        try:
            for raw_line in active_resp:
                line = raw_line.decode("utf-8", errors="replace").strip()
                if not line:
                    continue
                if line.startswith("data: "):
                    data_str = line[6:].strip()
                    if data_str == "[DONE]":
                        yield f"data: {json.dumps({'token': '', 'done': True})}\n\n"
                        break
                    try:
                        parsed = json.loads(data_str)
                        choices = parsed.get("choices", [])
                        if choices:
                            delta = choices[0].get("delta", {})
                            token = delta.get("content", "")
                            if token:
                                yield f"data: {json.dumps({'token': token, 'done': False})}\n\n"
                    except Exception:
                        pass
        except Exception as e:
            yield f"data: {json.dumps({'error': f'Stream interrupted: {str(e)}'})}\n\n"
        finally:
            try:
                active_resp.close()
            except Exception:
                pass

    return Response(
        stream_with_context(stream_with_silent_fallback()),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive"
        }
    )


# ===========================================================================
# ComfyUI Flux1-Schnell-fp8 Integration
# ===========================================================================

def load_flux_workflow():
    """Load the exported flux_schnell.json workflow."""
    workflow_path = os.path.join(os.path.dirname(__file__), "flux_schnell.json")
    if os.path.exists(workflow_path):
        with open(workflow_path, "r", encoding="utf-8") as f:
            return json.load(f)
    return None


@app.route("/api/generate-image", methods=["POST"])
def generate_image():
    """
    Execute FLUX1-Schnell-fp8 generation via ComfyUI Desktop workflow.
    Frees GPU/VRAM immediately upon completion or cancellation.
    """
    # Unload all Ollama text/code models so image model runs with full GPU/CPU/RAM
    unload_all_ollama_models()

    data = request.get_json(silent=True) or {}
    prompt_text = data.get("prompt", "").strip()
    if not prompt_text:
        return jsonify({"error": "Prompt cannot be empty"}), 400

    workflow = load_flux_workflow()
    if not workflow:
        return jsonify({"error": "flux_schnell.json workflow template not found on server."}), 500

    # Inject dynamic user prompt into Positive Prompt node (Node "6")
    if "6" in workflow and "inputs" in workflow["6"]:
        workflow["6"]["inputs"]["text"] = prompt_text

    # Set random seed into KSampler (Node "31")
    if "31" in workflow and "inputs" in workflow["31"]:
        workflow["31"]["inputs"]["seed"] = random.randint(1, 1125899906842624)

    client_id = f"chatbotai_{int(time.time() * 1000)}"
    prompt_payload = json.dumps({"prompt": workflow, "client_id": client_id}).encode("utf-8")

    try:
        # 1. Queue prompt in ComfyUI
        queue_req = urllib.request.Request(
            f"{COMFYUI_BASE_URL}/prompt",
            data=prompt_payload,
            headers={"Content-Type": "application/json"},
            method="POST"
        )
        with urllib.request.urlopen(queue_req, timeout=15) as resp:
            queue_res = json.loads(resp.read().decode("utf-8"))
            prompt_id = queue_res.get("prompt_id")

        if not prompt_id:
            err_msg = queue_res.get("error") or "ComfyUI failed to queue the prompt"
            return jsonify({"error": err_msg}), 502

        # 2. Poll ComfyUI history until completion (timeout: 240s for Flux Schnell)
        start_time = time.time()
        image_info = None

        while time.time() - start_time < 240:
            time.sleep(1.5)
            try:
                # First try specific prompt history
                hist_req = urllib.request.Request(f"{COMFYUI_BASE_URL}/history/{prompt_id}")
                with urllib.request.urlopen(hist_req, timeout=15) as h_resp:
                    hist_data = json.loads(h_resp.read().decode("utf-8"))

                target_hist = None
                if isinstance(hist_data, dict):
                    if prompt_id in hist_data:
                        target_hist = hist_data[prompt_id]
                    elif "outputs" in hist_data or "status" in hist_data:
                        target_hist = hist_data

                # Fallback to full history if prompt_id not found directly
                if not target_hist:
                    try:
                        all_hist_req = urllib.request.Request(f"{COMFYUI_BASE_URL}/history")
                        with urllib.request.urlopen(all_hist_req, timeout=10) as all_resp:
                            all_hist = json.loads(all_resp.read().decode("utf-8"))
                            if isinstance(all_hist, dict) and prompt_id in all_hist:
                                target_hist = all_hist[prompt_id]
                    except Exception:
                        pass

                if target_hist:
                    status_info = target_hist.get("status", {})
                    if status_info.get("status_str") == "error":
                        msgs = status_info.get("messages", [])
                        err_str = str(msgs[0]) if msgs else "ComfyUI reported an execution error."
                        raise Exception(err_str)

                    prompt_outputs = target_hist.get("outputs", {})
                    for node_id, out in prompt_outputs.items():
                        if isinstance(out, dict) and "images" in out and len(out["images"]) > 0:
                            image_info = out["images"][0]
                            break
                    if image_info:
                        break
            except Exception as poll_err:
                if "execution error" in str(poll_err).lower() or "error" in str(poll_err).lower():
                    raise poll_err
                # Transient network or GIL delay while loading model into GPU, continue polling
                continue

        # 3. IMMEDIATELY unload flux1-schnell-fp8 from GPU/VRAM after generation
        free_comfyui_memory()

        if not image_info:
            return jsonify({"error": "Generation timed out or no image output was produced."}), 504

        # Return image retrieval URL
        filename = image_info.get("filename")
        subfolder = image_info.get("subfolder", "")
        img_type = image_info.get("type", "output")
        image_url = f"/api/comfy-view?filename={urllib.parse.quote(filename)}&subfolder={urllib.parse.quote(subfolder)}&type={img_type}"

        return jsonify({
            "status": "success",
            "prompt": prompt_text,
            "image_url": image_url,
            "filename": filename
        })

    except urllib.error.HTTPError as e:
        free_comfyui_memory()
        error_details = ""
        try:
            raw_err = e.read().decode("utf-8")
            err_obj = json.loads(raw_err)
            node_errors = err_obj.get("node_errors", {})
            if node_errors:
                first_node_id = next(iter(node_errors))
                node_err = node_errors[first_node_id]
                errors_list = node_err.get("errors", [])
                if errors_list:
                    error_details = errors_list[0].get("message", "")
            if not error_details:
                error_details = err_obj.get("error", {}).get("message") or err_obj.get("error") or raw_err
        except Exception:
            error_details = f"HTTP {e.code}: {e.reason}"
        return jsonify({"error": f"ComfyUI Error: {error_details}"}), 400

    except urllib.error.URLError as e:
        free_comfyui_memory()
        return jsonify({
            "error": "Cannot connect to ComfyUI Desktop at 127.0.0.1:8188. Please make sure ComfyUI Desktop is running!"
        }), 503
    except Exception as e:
        free_comfyui_memory()
        return jsonify({"error": f"Error running Flux Schnell: {str(e)}"}), 500


@app.route("/api/comfy-view", methods=["GET"])
def comfy_view_proxy():
    """Proxy ComfyUI generated image or video output directly to browser with streaming & range support."""
    filename = request.args.get("filename", "")
    subfolder = request.args.get("subfolder", "")
    img_type = request.args.get("type", "output")
    comfy_url = f"{COMFYUI_BASE_URL}/view?filename={urllib.parse.quote(filename)}&subfolder={urllib.parse.quote(subfolder)}&type={img_type}"
    try:
        req_headers = {}
        if "Range" in request.headers:
            req_headers["Range"] = request.headers["Range"]

        req = urllib.request.Request(comfy_url, headers=req_headers)
        try:
            res = urllib.request.urlopen(req, timeout=30)
            status_code = res.status
        except urllib.error.HTTPError as he:
            if he.code == 206:
                res = he
                status_code = 206
            else:
                raise he

        content = res.read()
        mimetype = res.headers.get("Content-Type")
        if not mimetype:
            fn_lower = filename.lower()
            if fn_lower.endswith(".webm"):
                mimetype = "video/webm"
            elif fn_lower.endswith(".mp4"):
                mimetype = "video/mp4"
            elif fn_lower.endswith(".webp"):
                mimetype = "image/webp"
            else:
                mimetype = "image/png"

        resp = Response(content, status=status_code, mimetype=mimetype)
        resp.headers["Accept-Ranges"] = "bytes"
        resp.headers["Cache-Control"] = "public, max-age=86400, immutable"
        if res.headers.get("Content-Range"):
            resp.headers["Content-Range"] = res.headers.get("Content-Range")
        if res.headers.get("Content-Length"):
            resp.headers["Content-Length"] = res.headers.get("Content-Length")
        return resp
    except Exception as e:
        return jsonify({"error": f"Failed to retrieve media: {e}"}), 404


OUTPUTS_DIR = os.path.join(os.path.dirname(__file__), "outputs")
os.makedirs(OUTPUTS_DIR, exist_ok=True)


def find_ffmpeg():
    """Locate ffmpeg binary on system, ComfyUI Desktop installation, or environment."""
    path = shutil.which("ffmpeg")
    if path:
        return path

    try:
        import imageio_ffmpeg
        path = imageio_ffmpeg.get_ffmpeg_exe()
        if path and os.path.exists(path):
            return path
    except Exception:
        pass

    candidates = [
        r"C:\ffmpeg\bin\ffmpeg.exe",
        r"C:\Program Files\ffmpeg\bin\ffmpeg.exe",
        r"C:\Program Files (x86)\ffmpeg\bin\ffmpeg.exe",
        os.path.expanduser(r"~\AppData\Local\Programs\ComfyUI\resources\app\bin\ffmpeg.exe"),
        os.path.expanduser(r"~\AppData\Local\Programs\ComfyUI\ffmpeg.exe"),
        os.path.expanduser(r"~\AppData\Local\Microsoft\WinGet\Links\ffmpeg.exe"),
        os.path.expanduser(r"~\miniconda3\Scripts\ffmpeg.exe"),
        os.path.expanduser(r"~\anaconda3\Scripts\ffmpeg.exe"),
    ]
    for p in candidates:
        if os.path.isfile(p):
            return p

    comfy_dir = os.path.expanduser(r"~\AppData\Local\Programs\ComfyUI")
    if os.path.isdir(comfy_dir):
        for root, dirs, files in os.walk(comfy_dir):
            if "ffmpeg.exe" in files:
                return os.path.join(root, "ffmpeg.exe")

    return "ffmpeg"


def convert_to_mp4(input_path, output_mp4_path):
    """Convert any video or animated file to high-compatibility MP4 (H.264 / faststart)."""
    ffmpeg_exe = find_ffmpeg()
    cmd = [
        ffmpeg_exe,
        "-y",
        "-i", input_path,
        "-c:v", "libx264",
        "-pix_fmt", "yuv420p",
        "-preset", "veryfast",
        "-crf", "18",
        "-movflags", "+faststart",
        output_mp4_path
    ]
    try:
        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=120)
        return res.returncode == 0 and os.path.exists(output_mp4_path) and os.path.getsize(output_mp4_path) > 0
    except Exception as e:
        print(f"[Conversion Error] ffmpeg conversion failed: {e}")
        return False


@app.route("/api/video/<filename>", methods=["GET"])
def serve_video(filename):
    """Serve converted MP4 video files with range requests and caching."""
    file_path = os.path.join(OUTPUTS_DIR, filename)
    if not os.path.exists(file_path):
        return jsonify({"error": "Video not found"}), 404
    resp = send_file(file_path, mimetype="video/mp4", as_attachment=False, conditional=True)
    resp.headers["Cache-Control"] = "public, max-age=86400, immutable"
    return resp


def load_wan_video_workflow():
    """Load Wan2.2 Text to Video workflow (API format preferred, with fallback)."""
    api_path = os.path.join(os.path.dirname(__file__), "wan_video_api.json")
    if os.path.exists(api_path):
        with open(api_path, "r", encoding="utf-8") as f:
            return json.load(f)

    wf_path = os.path.join(os.path.dirname(__file__), "wantextvideo.json")
    if os.path.exists(wf_path):
        with open(wf_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, dict) and "nodes" not in data:
                return data
    return None


@app.route("/api/generate-video", methods=["POST"])
def generate_video():
    """
    Execute Wan2.2-TI2V-5B video generation via ComfyUI Desktop workflow.
    Stops all other models to ensure zero extra load on RAM, CPU, and GPU.
    """
    # 1. Unload all Ollama models so GPU/VRAM/RAM is 100% free for video generation
    unload_all_ollama_models()

    # 2. Free any previous models from ComfyUI memory
    free_comfyui_memory()

    data = request.get_json(silent=True) or {}
    prompt_text = data.get("prompt", "").strip()
    if not prompt_text:
        return jsonify({"error": "Prompt cannot be empty"}), 400

    workflow = load_wan_video_workflow()
    if not workflow:
        return jsonify({"error": "wantextvideo.json / wan_video_api.json workflow template not found on server."}), 500

    # Inject dynamic user prompt into Positive Prompt node (Node "6")
    if "6" in workflow and "inputs" in workflow["6"]:
        workflow["6"]["inputs"]["text"] = prompt_text

    # Set random seed into KSampler (Node "3")
    if "3" in workflow and "inputs" in workflow["3"]:
        workflow["3"]["inputs"]["seed"] = random.randint(1, 1125899906842624)

    client_id = f"chatbotai_video_{int(time.time() * 1000)}"
    prompt_payload = json.dumps({"prompt": workflow, "client_id": client_id}).encode("utf-8")

    try:
        # 1. Queue prompt in ComfyUI
        queue_req = urllib.request.Request(
            f"{COMFYUI_BASE_URL}/prompt",
            data=prompt_payload,
            headers={"Content-Type": "application/json"},
            method="POST"
        )
        with urllib.request.urlopen(queue_req, timeout=15) as resp:
            queue_res = json.loads(resp.read().decode("utf-8"))
            prompt_id = queue_res.get("prompt_id")

        if not prompt_id:
            err_msg = queue_res.get("error") or "ComfyUI failed to queue the video prompt"
            return jsonify({"error": err_msg}), 502

        # 2. Poll ComfyUI history until completion (timeout: 600s for Wan 2.2 5B)
        start_time = time.time()
        video_info = None

        while time.time() - start_time < 600:
            time.sleep(2.0)
            try:
                hist_req = urllib.request.Request(f"{COMFYUI_BASE_URL}/history/{prompt_id}")
                with urllib.request.urlopen(hist_req, timeout=15) as h_resp:
                    hist_data = json.loads(h_resp.read().decode("utf-8"))

                target_hist = None
                if isinstance(hist_data, dict):
                    if prompt_id in hist_data:
                        target_hist = hist_data[prompt_id]
                    elif "outputs" in hist_data or "status" in hist_data:
                        target_hist = hist_data

                if not target_hist:
                    try:
                        all_hist_req = urllib.request.Request(f"{COMFYUI_BASE_URL}/history")
                        with urllib.request.urlopen(all_hist_req, timeout=10) as all_resp:
                            all_hist = json.loads(all_resp.read().decode("utf-8"))
                            if isinstance(all_hist, dict) and prompt_id in all_hist:
                                target_hist = all_hist[prompt_id]
                    except Exception:
                        pass

                if target_hist:
                    status_info = target_hist.get("status", {})
                    if status_info.get("status_str") == "error":
                        msgs = status_info.get("messages", [])
                        err_str = str(msgs[0]) if msgs else "ComfyUI reported a video execution error."
                        raise Exception(err_str)

                    prompt_outputs = target_hist.get("outputs", {})
                    # 1. First priority: Real video files (.webm, .mp4, .mkv)
                    for node_id, out in prompt_outputs.items():
                        if isinstance(out, dict):
                            for key in ["videos", "gifs", "images"]:
                                for item in out.get(key, []):
                                    fn = (item.get("filename") or "").lower()
                                    if fn.endswith(".webm") or fn.endswith(".mp4") or fn.endswith(".mkv"):
                                        video_info = item
                                        break
                                if video_info:
                                    break
                        if video_info:
                            break

                    # 2. Second priority: If no direct video file, take any animated gif/webp/image output
                    if not video_info:
                        for node_id, out in prompt_outputs.items():
                            if isinstance(out, dict):
                                for key in ["videos", "gifs", "images"]:
                                    if key in out and len(out[key]) > 0:
                                        video_info = out[key][0]
                                        break
                            if video_info:
                                break

                    if video_info:
                        break
            except Exception as poll_err:
                if "execution error" in str(poll_err).lower() or "error" in str(poll_err).lower():
                    raise poll_err
                continue

        # Free ComfyUI memory immediately after video generation
        free_comfyui_memory()

        if not video_info:
            return jsonify({"error": "Video generation timed out or no video output was produced."}), 504

        filename = video_info.get("filename")
        subfolder = video_info.get("subfolder", "")
        file_type = video_info.get("type", "output")

        # Ensure video output is strictly MP4 (convert from webm/webp via ffmpeg)
        if not filename.lower().endswith(".mp4"):
            try:
                comfy_view_url = f"{COMFYUI_BASE_URL}/view?filename={urllib.parse.quote(filename)}&subfolder={urllib.parse.quote(subfolder)}&type={file_type}"
                temp_input = os.path.join(OUTPUTS_DIR, f"temp_{int(time.time() * 1000)}_{filename}")
                mp4_filename = f"wan2_{int(time.time() * 1000)}.mp4"
                mp4_path = os.path.join(OUTPUTS_DIR, mp4_filename)

                with urllib.request.urlopen(comfy_view_url, timeout=60) as resp:
                    with open(temp_input, "wb") as f_out:
                        f_out.write(resp.read())

                if convert_to_mp4(temp_input, mp4_path):
                    video_url = f"/api/video/{mp4_filename}"
                    filename = mp4_filename
                else:
                    video_url = f"/api/comfy-view?filename={urllib.parse.quote(filename)}&subfolder={urllib.parse.quote(subfolder)}&type={file_type}"

                if os.path.exists(temp_input):
                    try:
                        os.remove(temp_input)
                    except Exception:
                        pass
            except Exception as conv_err:
                print(f"[Warning] MP4 conversion error: {conv_err}")
                video_url = f"/api/comfy-view?filename={urllib.parse.quote(filename)}&subfolder={urllib.parse.quote(subfolder)}&type={file_type}"
        else:
            video_url = f"/api/comfy-view?filename={urllib.parse.quote(filename)}&subfolder={urllib.parse.quote(subfolder)}&type={file_type}"

        return jsonify({
            "status": "success",
            "prompt": prompt_text,
            "video_url": video_url,
            "filename": filename
        })

    except urllib.error.HTTPError as e:
        free_comfyui_memory()
        error_details = ""
        try:
            raw_err = e.read().decode("utf-8")
            err_obj = json.loads(raw_err)
            node_errors = err_obj.get("node_errors", {})
            if node_errors:
                first_node_id = next(iter(node_errors))
                node_err = node_errors[first_node_id]
                errors_list = node_err.get("errors", [])
                if errors_list:
                    error_details = errors_list[0].get("message", "")
            if not error_details:
                error_details = err_obj.get("error", {}).get("message") or err_obj.get("error") or raw_err
        except Exception:
            error_details = f"HTTP {e.code}: {e.reason}"
        return jsonify({"error": f"ComfyUI Error: {error_details}"}), 400

    except urllib.error.URLError as e:
        free_comfyui_memory()
        return jsonify({
            "error": "Cannot connect to ComfyUI Desktop at 127.0.0.1:8188. Please make sure ComfyUI Desktop is running!"
        }), 503
    except Exception as e:
        free_comfyui_memory()
        return jsonify({"error": f"Error running Wan 2.2: {str(e)}"}), 500


@app.route("/api/stop-video", methods=["POST"])
def stop_video_generation():
    """
    Immediately interrupt active ComfyUI video generation & unload model from memory.
    """
    try:
        req_interrupt = urllib.request.Request(
            f"{COMFYUI_BASE_URL}/interrupt",
            data=b"{}",
            headers={"Content-Type": "application/json"},
            method="POST"
        )
        with urllib.request.urlopen(req_interrupt, timeout=3) as res:
            pass
    except Exception:
        pass

    free_comfyui_memory()
    return jsonify({"status": "stopped", "message": "ComfyUI video generation interrupted and model unloaded."})


@app.route("/api/stop-image", methods=["POST"])
def stop_image_generation():
    """
    Immediately interrupt active ComfyUI generation & unload model from memory.
    """
    try:
        # Interrupt current generation
        req_interrupt = urllib.request.Request(
            f"{COMFYUI_BASE_URL}/interrupt",
            data=b"{}",
            headers={"Content-Type": "application/json"},
            method="POST"
        )
        with urllib.request.urlopen(req_interrupt, timeout=3) as res:
            pass
    except Exception:
        pass

    # Free model from memory completely
    free_comfyui_memory()
    return jsonify({"status": "stopped", "message": "ComfyUI generation interrupted and model unloaded."})


@app.route("/readme")
def serve_readme():
    """Serve README.md directly to the browser with clean text formatting."""
    readme_path = os.path.join(os.path.dirname(__file__), "README.md")
    if os.path.exists(readme_path):
        return send_file(readme_path, mimetype="text/plain; charset=utf-8")
    return "README.md not found.", 404


@app.route("/")
def index():
    """Serve frontend index.html."""
    return app.send_static_file("index.html")



if __name__ == "__main__":
    from livereload import Server

    resolved = resolve_model_name()

    print("=" * 60)
    print(" ChatbotAI Backend with Ollama Qwen3-Coder (480B Cloud) & Live Web Search")
    print(f" Ollama URL: {OLLAMA_BASE_URL}")
    print(f" Active Model: {resolved}")
    print(" Running on: http://127.0.0.1:5000")
    print(" Live reload: Enabled")
    print("=" * 60)

    server = Server(app)

    # Automatically reload the browser when frontend files change
    server.watch("*.html")
    server.watch("*.css")
    server.watch("*.js")

    # Watch Python files for backend changes
    server.watch("*.py")

    server.serve(
        host="127.0.0.1",
        port=5000,
        debug=True
    )
