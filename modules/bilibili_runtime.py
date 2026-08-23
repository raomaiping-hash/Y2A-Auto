#!/usr/bin/env python
# -*- coding: utf-8 -*-

import logging
import os
from typing import Optional

logger = logging.getLogger("bilibili_runtime")

_INITIALIZED = False
_LAST_ERROR: Optional[str] = None


def configure_bilibili_runtime() -> bool:
    """Configure the internal Bilibili SDK network runtime once per process."""
    global _INITIALIZED, _LAST_ERROR
    if _INITIALIZED:
        return True

    try:
        from .bili_sdk import request_settings

        impersonate = os.environ.get("BILIBILI_IMPERSONATE", "chrome131").strip()
        if impersonate:
            request_settings.set("impersonate", impersonate)

        # “本机直连”：忽略环境代理（HTTPS_PROXY / HTTP_PROXY 等），
        # 直接用本机真实出口 IP 连接 B 站。代理出口通常是共享/机房 IP，
        # 会被 B 站风控判定并触发“上传过快”(code 601) 限流；真实家用 IP 则正常。
        # 默认开启；设 BILIBILI_DIRECT_CONNECT=0 可退回走代理。
        use_direct = os.environ.get("BILIBILI_DIRECT_CONNECT", "1").strip().lower()
        if use_direct not in ("0", "false", "off", "no", ""):
            request_settings.set("trust_env", False)
            logger.info("Bilibili 上传已启用本机直连（忽略环境代理，trust_env=False）")

        _INITIALIZED = True
        _LAST_ERROR = None
        return True
    except Exception as exc:
        _LAST_ERROR = str(exc)
        logger.warning("配置 bilibili-api 网络运行时失败: %s", exc)
        return False


def get_bilibili_runtime_error() -> Optional[str]:
    return _LAST_ERROR
