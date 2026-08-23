#!/usr/bin/env python
# -*- coding: utf-8 -*-

import logging

from .utils.network import (
    Api,
    BiliAPIClient,
    BiliAPIFile,
    BiliAPIResponse,
    BiliWsMsgType,
    Credential,
    HEADERS,
    get_client,
    get_selected_client,
    refresh_buvid,
    register_client,
    request_settings,
    select_client,
)
from .exceptions import ArgsException, NetworkException, ResponseCodeException
from . import login_v2, video_uploader, video_zone

BILIBILI_API_VERSION = "17.4.2-y2a"
BILI_API_VERSION = BILIBILI_API_VERSION
logger = logging.getLogger("bili_sdk")


def _register_clients():
    try:
        from .clients.CurlCFFIClient import CurlCFFIClient
        # 使用 Chrome 131 浏览器指纹伪装：空 impersonate 会暴露脚本 TLS 指纹，
        # 导致 B 站风控在 preupload 阶段直接返回 406。chrome131 实测对
        # api.bilibili.com 返回 200（与上传器 User-Agent Chrome/131 一致）。
        register_client("curl_cffi", CurlCFFIClient, {"impersonate": "chrome131", "http2": True})
        select_client("curl_cffi")
    except Exception as exc:
        logger.warning("注册 Bilibili curl_cffi 客户端失败: %s", exc)


_register_clients()


__all__ = [
    "Api",
    "ArgsException",
    "BILI_API_VERSION",
    "BILIBILI_API_VERSION",
    "BiliAPIClient",
    "BiliAPIFile",
    "BiliAPIResponse",
    "BiliWsMsgType",
    "Credential",
    "HEADERS",
    "NetworkException",
    "ResponseCodeException",
    "get_client",
    "get_selected_client",
    "login_v2",
    "refresh_buvid",
    "request_settings",
    "select_client",
    "video_uploader",
    "video_zone",
]
