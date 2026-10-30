# ChatbotAI - Multi-Modal AI Platform

An advanced Multi-Modal AI Platform featuring **Offline GPU Generation** (Ollama + ComfyUI) and **Online Cloud Generation** (Groq, OpenRouter, Google Gemini).

Note: to keep Offline Text Generation, Image Generation And Video Generation Feature On keep the Comfy UI On dont Close It.

Disclaimer: The offline Models Consumes More RAM and GPU So Make Sure Your System Meets The System requirements.

---

## 🌟 Key Features

1. **Dual Execution Modes:**
   - 🌐 **Online Cloud Mode:** Instant, zero-install inference using Groq, OpenRouter, and Google Gemini APIs. Perfect for recruiters and cloud testing on any computer without needing high-end GPUs.
   - 💻 **Offline Local Mode:** Local privacy-first inference utilizing your computer's local hardware (NVIDIA RTX GPU / CPU / RAM).

2. **Supported Local AI Capabilities:**
   - 🧠 **Text & Code Generation:** Qwen3-Coder via Ollama.
   - 🎨 **Image Generation:** FLUX.1-Schnell (fp8) via ComfyUI.
   - 🎬 **Video Generation:** Wan2.2-TI2V-5B (MP4 output) via ComfyUI.
   - 🛡️ **Cybersecurity Intelligence:** Qwen3.8-27B-Uncensored-Cyber via Ollama.

---

## 🚀 Quick Start (Online Mode)

1. Clone this repository:
   ```bash
   git clone https://github.com/your-username/chatbotai.git
   cd chatbotai
   ```
2. Install Python dependencies:
   ```bash
   pip install -r requirements.txt
   ```
3. Start the application:
   ```bash
   python app.py
   ```
4. Open `http://localhost:5000` in your web browser.
5. In the opening popup, select **Online Mode** and add your **Groq**, **OpenRouter**, or **Gemini** API key to chat instantly!

---

## 💻 Local Offline Setup (Ollama & ComfyUI)

If you select **Offline Mode**, ensure your local environment is configured with the following:

### 1. Ollama (Text & Cybersecurity Models)
- Download and install [Ollama](https://ollama.com/).
- Pull the models: use cmd to run the below bash code.
  Below are the ollama Command You Should Put it in cmd

  ollama run qwen3-coder:30b
  
  # or for cybersecurity model:

  ollama run hf.co/philbert440/Qwen3.8-27B-Uncensored-Cyber-GGUF:Q4_K_M
 
  ```
- Ollama runs locally at `http://127.0.0.1:11434`.

### 2. ComfyUI (Image & Video Models)
- Download and Install [ComfyUI Desktop](https://comfy.org/download/) 


- **For FLUX.1 Schnell Image Generation:**

Link To Download Flux Model (https://huggingface.co/Comfy-Org/Flux-1-Schnell).

Below are the paths where You have to Save The Downloaded Model.

  - ComfyUI\models\checkpoints\flux1-schnell-fp8.safetensors
  - ComfyUI\models\checkpoints\flux1-schnell.safetensors


- **For Wan 2.2 Video Generation:**

Link To Download Wan Video Model

  1. Main Video Model: (https://huggingface.co/Comfy-Org/Wan-2.2/resolve/main/split_files/diffusion_models/wan2.2_ti2v_5B_fp16.safetensors?utm_source=chatgpt.com).

  Save in ComfyUI/models/diffusion_models/

  2. Text Encoder: (https://huggingface.co/Comfy-Org/Wan-2.2/resolve/main/split_files/text_encoders/umt5_xxl_fp8_e4m3fn_scaled.safetensors?utm_source=chatgpt.com).

  Save in ComfyUI/models/text_encoders/

  2. VAE: (https://huggingface.co/Comfy-Org/Wan-2.2/resolve/main/split_files/text_encoders/umt5_xxl_fp8_e4m3fn_scaled.safetensors?utm_source=chatgpt.com).


- ComfyUI Runs Locally at `http://127.0.0.1:8188`.
