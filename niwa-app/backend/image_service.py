"""Image generation service for Niwa."""
import json
import os
import urllib.request
import urllib.error
import base64
import time


def generate_image(prompt, provider=None, api_key=None, model=None, size=None):
    """Generate an image from a text prompt. Returns dict with url or base64 and metadata."""
    if not provider or not api_key:
        from app import get_service_config
        config = get_service_config("image")
        provider = provider or config.get("provider", "openai")
        api_key = api_key or config.get("api_key")
        model = model or config.get("model", "dall-e-3")
        size = size or config.get("default_size", "1024x1024")

    if not api_key:
        return {"error": "No hay API key configurada para generación de imágenes. Ve a Sistema > Servicios para configurarla."}

    if provider == "openai":
        return _generate_openai(prompt, api_key, model or "dall-e-3", size or "1024x1024")
    elif provider == "stability":
        return _generate_stability(prompt, api_key, model or "stable-diffusion-xl-1024-v1-0", size or "1024x1024")
    elif provider == "replicate":
        return _generate_replicate(prompt, api_key, model or "black-forest-labs/flux-1.1-pro", size or "1024x1024")
    elif provider == "fal":
        return _generate_fal(prompt, api_key, model or "fal-ai/flux-pro/v1.1", size or "1024x1024")
    elif provider == "together":
        return _generate_together(prompt, api_key, model or "black-forest-labs/FLUX.1-schnell-Free", size or "1024x1024")
    else:
        return {"error": f"Proveedor desconocido: {provider}"}


def _generate_openai(prompt, api_key, model, size):
    """Generate via OpenAI DALL-E API."""
    url = "https://api.openai.com/v1/images/generations"
    payload = json.dumps({
        "model": model,
        "prompt": prompt,
        "n": 1,
        "size": size,
        "response_format": "url"
    }).encode()
    req = urllib.request.Request(url, data=payload, headers={
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    })
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read())
            img = data["data"][0]
            return {
                "url": img.get("url"),
                "revised_prompt": img.get("revised_prompt", prompt),
                "model": model,
                "size": size,
                "provider": "openai"
            }
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        try:
            err = json.loads(body)
            msg = err.get("error", {}).get("message", body)
        except Exception:
            msg = body
        return {"error": f"OpenAI error: {msg}"}
    except Exception as e:
        return {"error": f"Error generando imagen: {e}"}


def _generate_stability(prompt, api_key, model, size):
    """Generate via Stability AI API."""
    w, h = size.split("x")
    url = f"https://api.stability.ai/v1/generation/{model}/text-to-image"
    payload = json.dumps({
        "text_prompts": [{"text": prompt, "weight": 1}],
        "cfg_scale": 7,
        "height": int(h),
        "width": int(w),
        "samples": 1,
        "steps": 30,
    }).encode()
    req = urllib.request.Request(url, data=payload, headers={
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "Accept": "application/json"
    })
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read())
            img = data["artifacts"][0]
            return {
                "base64": img["base64"],
                "model": model,
                "size": size,
                "provider": "stability"
            }
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        return {"error": f"Stability AI error: {body}"}
    except Exception as e:
        return {"error": f"Error generando imagen: {e}"}


def _generate_replicate(prompt, api_key, model, size):
    """Generate via Replicate API."""
    url = "https://api.replicate.com/v1/predictions"
    w, h = size.split("x")
    payload = json.dumps({
        "model": model,
        "input": {"prompt": prompt, "width": int(w), "height": int(h)}
    }).encode()
    req = urllib.request.Request(url, data=payload, headers={
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "Prefer": "wait"
    })
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read())
            output = data.get("output")
            if isinstance(output, list) and output:
                return {"url": output[0], "model": model, "size": size, "provider": "replicate"}
            elif isinstance(output, str):
                return {"url": output, "model": model, "size": size, "provider": "replicate"}
            return {"error": f"Respuesta inesperada de Replicate: {data}"}
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        return {"error": f"Replicate error: {body}"}
    except Exception as e:
        return {"error": f"Error: {e}"}


def _generate_fal(prompt, api_key, model, size):
    """Generate via fal.ai API."""
    w, h = size.split("x")
    url = f"https://fal.run/{model}"
    payload = json.dumps({
        "prompt": prompt, "image_size": {"width": int(w), "height": int(h)}, "num_images": 1
    }).encode()
    req = urllib.request.Request(url, data=payload, headers={
        "Authorization": f"Key {api_key}",
        "Content-Type": "application/json"
    })
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read())
            images = data.get("images", [])
            if images:
                return {"url": images[0].get("url", ""), "model": model, "size": size, "provider": "fal"}
            return {"error": "No se generó ninguna imagen"}
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        return {"error": f"fal.ai error: {body}"}
    except Exception as e:
        return {"error": f"Error: {e}"}


def _generate_together(prompt, api_key, model, size):
    """Generate via Together AI API."""
    w, h = size.split("x")
    url = "https://api.together.xyz/v1/images/generations"
    payload = json.dumps({
        "model": model, "prompt": prompt, "width": int(w), "height": int(h), "n": 1, "response_format": "url"
    }).encode()
    req = urllib.request.Request(url, data=payload, headers={
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    })
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read())
            images = data.get("data", [])
            if images:
                return {"url": images[0].get("url", ""), "model": model, "size": size, "provider": "together"}
            return {"error": "No se generó ninguna imagen"}
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        return {"error": f"Together AI error: {body}"}
    except Exception as e:
        return {"error": f"Error: {e}"}


def test_connection(provider, api_key):
    """Test that the API key works without generating a full image."""
    if not api_key:
        return {"ok": False, "message": "No hay API key configurada."}
    if provider == "openai":
        url = "https://api.openai.com/v1/models"
        req = urllib.request.Request(url, headers={"Authorization": f"Bearer {api_key}"})
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                return {"ok": True, "message": "Conexión con OpenAI verificada ✓"}
        except urllib.error.HTTPError as e:
            if e.code == 401:
                return {"ok": False, "message": "API key inválida. Revisa que la hayas copiado bien."}
            return {"ok": False, "message": f"Error HTTP {e.code}"}
        except Exception as e:
            return {"ok": False, "message": f"Error de conexión: {e}"}
    elif provider == "stability":
        url = "https://api.stability.ai/v1/user/account"
        req = urllib.request.Request(url, headers={"Authorization": f"Bearer {api_key}"})
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read())
                credits = data.get("credits", "?")
                return {"ok": True, "message": f"Conexión verificada ✓ — Créditos: {credits}"}
        except urllib.error.HTTPError as e:
            if e.code == 401:
                return {"ok": False, "message": "API key inválida."}
            return {"ok": False, "message": f"Error HTTP {e.code}"}
        except Exception as e:
            return {"ok": False, "message": f"Error de conexión: {e}"}
    elif provider == "replicate":
        url = "https://api.replicate.com/v1/models"
        req = urllib.request.Request(url, headers={"Authorization": f"Bearer {api_key}"})
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                return {"ok": True, "message": "Replicate conectado ✓"}
        except urllib.error.HTTPError as e:
            if e.code == 401:
                return {"ok": False, "message": "API key inválida."}
            return {"ok": False, "message": f"Error HTTP {e.code}"}
        except Exception as e:
            return {"ok": False, "message": f"Error de conexión: {e}"}
    elif provider == "fal":
        # fal.ai doesn't have a simple status endpoint, just validate key format
        if api_key and len(api_key) > 5:
            return {"ok": True, "message": "fal.ai configurado ✓ — API key presente"}
        return {"ok": False, "message": "API key parece inválida."}
    elif provider == "together":
        url = "https://api.together.xyz/v1/models"
        req = urllib.request.Request(url, headers={"Authorization": f"Bearer {api_key}"})
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                return {"ok": True, "message": "Together AI conectado ✓"}
        except urllib.error.HTTPError as e:
            if e.code == 401:
                return {"ok": False, "message": "API key inválida."}
            return {"ok": False, "message": f"Error HTTP {e.code}"}
        except Exception as e:
            return {"ok": False, "message": f"Error de conexión: {e}"}
    return {"ok": False, "message": f"Proveedor desconocido: {provider}"}
