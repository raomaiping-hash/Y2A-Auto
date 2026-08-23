#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
密码与令牌哈希工具（共享脚手架）。

集中封装 pbkdf2_sha256 的哈希与验证逻辑，供设置页保存密码、
登录验证、TG Bot Token 等场景复用。避免管理密码与令牌哈希逻辑
散落在多处导致实现不一致。

约定：
  - 存储格式:  <prefix><iterations>$<salt>$<digest>
  - prefix:   "pbkdf2_sha256:"
  - 每次哈希自动生成随机盐，验证用 constant-time 比较。
"""

import hashlib
import secrets
import hmac

# 与既有 app.py 中 TG Bot Token 哈希参数保持一致，避免新旧存储互不兼容。
PBKDF2_HASH_PREFIX = 'pbkdf2_sha256:'
PBKDF2_HASH_ITERATIONS = 260000


def _is_hashed(value: str) -> bool:
    """判断字符串是否已是本模块产出的哈希格式。"""
    return bool(value) and value.startswith(PBKDF2_HASH_PREFIX) and ('$' in value)


def hash_password(password: str) -> str:
    """
    对明文密码做 pbkdf2_sha256 加盐哈希。

    Args:
        password: 明文密码（非空）

    Returns:
        形如 "pbkdf2_sha256:<iterations>$<salt>$<digest>" 的字符串。
    """
    salt = secrets.token_urlsafe(16)
    digest = hashlib.pbkdf2_hmac(
        'sha256',
        str(password).encode('utf-8'),
        salt.encode('utf-8'),
        PBKDF2_HASH_ITERATIONS,
    ).hex()
    return f'{PBKDF2_HASH_PREFIX}{PBKDF2_HASH_ITERATIONS}${salt}${digest}'


def verify_password(password: str, stored_hash: str) -> bool:
    """
    校验明文密码是否与存储的哈希匹配。

    Args:
        password: 用户提交的明文密码
        stored_hash: 存储的哈希串

    Returns:
        bool: 匹配返回 True；格式非法或密码为空一律返回 False。
    """
    if not stored_hash or not stored_hash.startswith(PBKDF2_HASH_PREFIX):
        return False
    payload = stored_hash[len(PBKDF2_HASH_PREFIX):]
    try:
        iterations_text, salt, expected_digest = payload.split('$', 2)
        iterations = int(iterations_text)
    except (TypeError, ValueError):
        return False
    if iterations < 1 or not salt or not expected_digest:
        return False
    actual_digest = hashlib.pbkdf2_hmac(
        'sha256',
        str(password or '').encode('utf-8'),
        salt.encode('utf-8'),
        iterations,
    ).hex()
    return hmac.compare_digest(expected_digest, actual_digest)


def needs_rehash(stored_hash: str) -> bool:
    """判断存储的哈希是否为旧格式（如明文或迭代数过低的旧哈希），需要重新哈希。"""
    if not stored_hash:
        return True
    if not stored_hash.startswith(PBKDF2_HASH_PREFIX):
        return True
    try:
        iterations_text = stored_hash[len(PBKDF2_HASH_PREFIX):].split('$', 1)[0]
        iterations = int(iterations_text)
    except (TypeError, ValueError):
        return True
    return iterations < PBKDF2_HASH_ITERATIONS
