# Copyright 2025 ZTE Corporation.
# All Rights Reserved.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.
import os
import httpx

from app.common.logger_util import logger
from app.cosight.llm.chat_llm import ChatLLM
from config.config import *

# Langfuse可观测性集成（可选）
# 如果启用Langfuse，使用包装的OpenAI客户端；否则使用原生OpenAI
langfuse_enabled = os.environ.get("LANGFUSE_ENABLED", "false").lower() in ("true", "1", "yes")

if langfuse_enabled:
    try:
        from langfuse.openai import OpenAI
        logger.info("✅ Langfuse tracing enabled")
    except ImportError:
        from openai import OpenAI
        logger.warning("❌ Langfuse not installed, using standard OpenAI client. Install: pip install langfuse")
else:
    from openai import OpenAI
    logger.info("Langfuse tracing disabled")


<<<<<<< Updated upstream
=======
def safe_model_config(model_config: dict) -> dict:
    """Return a log-safe copy without exposing API credentials."""
    safe_config = dict(model_config)
    api_key = safe_config.get("api_key")
    if api_key:
        safe_config["api_key"] = f"{api_key[:4]}****{api_key[-4:]}"
    return safe_config


def _check_model_connectivity(model_config: dict) -> tuple[bool, str]:
    """Quick connectivity check to the configured LLM API endpoint.
    
    Returns (ok, message). Does NOT consume tokens – uses a minimal models.list() call.
    """
    if not model_config.get("api_key") or "如：" in str(model_config.get("api_key", "")):
        return False, "API Key 未配置或仍为模板占位符，请在 .env 中设置真实的 API_KEY。"
    if not model_config.get("base_url"):
        return False, "API Base URL 未配置，请在 .env 中设置 API_BASE_URL。"

    try:
        import httpx
        client = httpx.Client(verify=False, trust_env=False, timeout=httpx.Timeout(connect=10.0, read=15.0))
        headers = {"Authorization": f"Bearer {model_config['api_key']}"}
        resp = client.get(
            f"{model_config['base_url'].rstrip('/')}/models",
            headers=headers,
        )
        if resp.status_code == 200:
            data = resp.json()
            model_ids = [m.get("id", "") for m in data.get("data", [])[:5]]
            return True, f"模型服务连通正常（可用模型: {', '.join(model_ids) if model_ids else '已连接'}）"
        elif resp.status_code == 401:
            return False, f"API Key 认证失败（HTTP {resp.status_code}），请检查 .env 中的 API_KEY 是否正确。"
        else:
            return False, f"模型服务返回异常状态码 {resp.status_code}: {resp.text[:200]}"
    except httpx.ConnectError:
        return False, f"无法连接到 {model_config['base_url']}，请检查网络和 API_BASE_URL 配置。"
    except httpx.TimeoutException:
        return False, f"连接 {model_config['base_url']} 超时，请检查网络或代理设置。"
    except Exception as exc:
        return False, f"模型连通性检测失败: {str(exc)[:200]}"


>>>>>>> Stashed changes
def set_model(model_config: dict[str, Optional[str | int | float]]):
    # 从环境变量读取超时配置（秒），默认180秒（3分钟）
    timeout_seconds = float(os.environ.get("LLM_TIMEOUT", "180"))
    
    http_client_kwargs = {
<<<<<<< Updated upstream
        "headers": {
            'Content-Type': 'application/json',
            'Authorization': model_config['api_key']
        },
=======
>>>>>>> Stashed changes
        "verify": False,
        "trust_env": False,
        "timeout": httpx.Timeout(
            connect=30.0,        # 连接超时：30秒
            read=timeout_seconds,    # 读取超时：可配置，默认180秒
            write=30.0,          # 写入超时：30秒
            pool=10.0            # 连接池超时：10秒
        )
    }

    if model_config['proxy']:
        http_client_kwargs["proxy"] = model_config['proxy']

    openai_llm = OpenAI(
        base_url=model_config['base_url'],
        api_key=model_config['api_key'],
        http_client=httpx.Client(**http_client_kwargs)
    )

    chat_llm_kwargs = {
        "model": model_config['model'],
        "base_url": model_config['base_url'],
        "api_key": model_config['api_key'],
        "client": openai_llm
    }

    if model_config.get('max_tokens') is not None:
        chat_llm_kwargs['max_tokens'] = model_config['max_tokens']
    if model_config.get('temperature') is not None:
        chat_llm_kwargs['temperature'] = model_config['temperature']
    if model_config.get('thinking_mode') is not None:
        chat_llm_kwargs['thinking_mode'] = model_config['thinking_mode']

    return ChatLLM(**chat_llm_kwargs)


plan_model_config = get_plan_model_config()
logger.info(f"plan_model_config:{plan_model_config}\n")
llm_for_plan = set_model(plan_model_config)

act_model_config = get_act_model_config()
logger.info(f"act_model_config:{act_model_config}\n")
llm_for_act = set_model(act_model_config)

tool_model_config = get_tool_model_config()
logger.info(f"tool_model_config:{tool_model_config}\n")
llm_for_tool = set_model(tool_model_config)

vision_model_config = get_vision_model_config()
logger.info(f"vision_model_config:{vision_model_config}\n")
llm_for_vision = set_model(vision_model_config)

credibility_model_config = get_credibility_model_config()
logger.info(f"credibility_model_config:{credibility_model_config}\n")
llm_for_credibility = set_model(credibility_model_config)


# ---- 启动时模型连通性检测 ----
def _run_connectivity_checks():
    """Check LLM connectivity at startup; log warnings but never crash the server."""
    logger.info("\n=== 大模型连通性检测 ===")
    checked = set()
    for label, cfg in [
        ("主模型 (Plan)", plan_model_config),
        ("执行模型 (Act)", act_model_config),
        ("工具模型 (Tool)", tool_model_config),
        ("视觉模型 (Vision)", vision_model_config),
        ("可信分析模型 (Credibility)", credibility_model_config),
    ]:
        cfg_key = (cfg.get("base_url"), cfg.get("api_key"))
        if cfg_key in checked:
            continue
        checked.add(cfg_key)
        ok, msg = _check_model_connectivity(cfg)
        if ok:
            logger.info(f"  ✅ {label}: {msg}")
        else:
            logger.warning(f"  ⚠️ {label}: {msg}")
    logger.info("=== 连通性检测完成 ===\n")


# 延迟到模块导入完成后再执行（避免循环导入），但不在导入时阻塞
import threading
threading.Thread(target=_run_connectivity_checks, daemon=True).start()
