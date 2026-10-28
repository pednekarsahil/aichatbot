import os
import random
import time
import json
import http.client
import urllib.request
import urllib.error
import urllib.parse
from flask import Flask, request, jsonify, Response, stream_with_context
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
    """Proxy ComfyUI generated image or video output directly to browser."""
    filename = request.args.get("filename", "")
    subfolder = request.args.get("subfolder", "")
    img_type = request.args.get("type", "output")
    comfy_url = f"{COMFYUI_BASE_URL}/view?filename={urllib.parse.quote(filename)}&subfolder={urllib.parse.quote(subfolder)}&type={img_type}"
    try:
        req = urllib.request.Request(comfy_url)
        with urllib.request.urlopen(req, timeout=30) as res:
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
            return Response(content, mimetype=mimetype)
    except Exception as e:
        return jsonify({"error": f"Failed to retrieve media: {e}"}), 404


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
