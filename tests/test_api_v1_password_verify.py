#!/usr/bin/env python
# -*- coding: utf-8 -*-

import unittest

from modules.security_utils import hash_password, verify_password, needs_rehash


class ApiV1PasswordVerifyTests(unittest.TestCase):
    """验证 api_v1 登录逻辑搭配 security_utils 的哈希校验：新哈希 + 旧明文向后兼容。"""

    def _login_check(self, stored_password, submitted):
        """模拟 api_v1.auth_login 的判定逻辑（不含 session/CSRF），保持与实现一致。"""
        is_hash = str(stored_password).startswith('pbkdf2_sha256:')
        if not stored_password:
            return False
        return bool(submitted and (
            verify_password(submitted, stored_password)
            or (not is_hash and submitted == stored_password)
        ))

    def test_hash_password_login_succeeds(self):
        h = hash_password('s3cret')
        self.assertTrue(self._login_check(h, 's3cret'))

    def test_hash_password_wrong_rejected(self):
        h = hash_password('s3cret')
        self.assertFalse(self._login_check(h, 'wrong'))

    def test_legacy_plaintext_fallback_succeeds(self):
        """旧明文密码（非哈希格式）通过向后兼容分支登录成功。"""
        self.assertTrue(self._login_check('oldplain', 'oldplain'))

    def test_legacy_plaintext_wrong_rejected(self):
        self.assertFalse(self._login_check('oldplain', 'other'))

    def test_empty_password_never_succeeds(self):
        self.assertFalse(self._login_check('', ''))
        self.assertFalse(self._login_check('', 'x'))

    def test_needs_rehash_for_plaintext_triggers_migration(self):
        """旧明文应触发 needs_rehash，从而在保存/加载时被迁移为哈希。"""
        self.assertTrue(needs_rehash('oldplain'))
        self.assertFalse(needs_rehash(hash_password('x')))


if __name__ == '__main__':
    unittest.main()
