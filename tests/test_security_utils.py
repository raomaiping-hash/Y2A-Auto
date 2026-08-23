#!/usr/bin/env python
# -*- coding: utf-8 -*-

import unittest

from modules.security_utils import (
    hash_password,
    verify_password,
    needs_rehash,
    PBKDF2_HASH_PREFIX,
)


class SecurityUtilsTests(unittest.TestCase):
    def test_hash_password_roundtrip(self):
        h = hash_password('s3cret-pass')
        self.assertTrue(h.startswith(PBKDF2_HASH_PREFIX))
        self.assertIn('$', h)
        # 正确密码可验证
        self.assertTrue(verify_password('s3cret-pass', h))

    def test_wrong_password_fails(self):
        h = hash_password('abc123')
        self.assertFalse(verify_password('wrong', h))

    def test_salt_makes_hash_unique(self):
        self.assertNotEqual(hash_password('same'), hash_password('same'))

    def test_empty_password_rejected(self):
        h = hash_password('abc')
        self.assertFalse(verify_password('', h))
        self.assertFalse(verify_password(None, h))

    def test_invalid_stored_hash_returns_false(self):
        self.assertFalse(verify_password('k', ''))
        self.assertFalse(verify_password('k', 'plaintext-not-hash'))
        self.assertFalse(verify_password('k', 'pbkdf2_sha256:bad'))

    def test_needs_rehash_on_plaintext(self):
        self.assertTrue(needs_rehash(''))
        self.assertTrue(needs_rehash('plaintext-password'))
        # 新哈希不需要重哈希
        self.assertFalse(needs_rehash(hash_password('x')))

    def test_verify_uses_app_compatible_format(self):
        """与 app.py 既有 TB Bot 哈希格式兼容（prefix + iterations$salt$digest）。"""
        h = hash_password('hello')
        parts = h[len(PBKDF2_HASH_PREFIX):].split('$')
        self.assertEqual(len(parts), 3)
        int(parts[0])  # iterations 可解析为 int
        self.assertTrue(parts[1])  # salt 非空
        self.assertTrue(parts[2])  # digest 非空


if __name__ == '__main__':
    unittest.main()
