#!/usr/bin/env python3
"""Integrity regression tests for `copy_block_if_exists`.

`copy_block_if_exists` rehydrates a block pointer into a real file (nodo calls it
per-file when building a guest rootfs). It used to stream the block straight into
the destination and return True unconditionally, so a block that was truncated or
corrupt *at rest* (torn write, interrupted store, rm race) yielded a short file
with no error — silently corrupting large binaries ("invalid ELF header" at exec).

These tests assert the fail-closed contract:
  * intact block  -> True, full content, correct hash, no temp file left behind
  * truncated block -> False, destination untouched (so callers can raise)

Run:  python -m unittest tests.test_copy_block_integrity
"""
import hashlib
import os
import tempfile
import unittest

from bee_rpc import block_builder
from bee_rpc.client import copy_block_if_exists
from bee_rpc.utils import modify_env, Enviroment


def _sha3(path: str) -> str:
    with open(path, "rb") as f:
        return hashlib.sha3_256(f.read()).hexdigest()


class CopyBlockIntegrity(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="copyblk-")
        self.blocks = os.path.join(self.root, "blocks")
        os.makedirs(self.blocks)
        modify_env(cache_dir=self.root + os.sep, block_dir=self.blocks + os.sep)

        # A real >10 MiB single-file block, content-addressed in BLOCKDIR.
        self.payload = os.urandom(11 * 1024 * 1024)
        src = os.path.join(self.root, "big.bin")
        with open(src, "wb") as f:
            f.write(self.payload)
        self.block_hash, self.block = block_builder.create_block(file_path=src, copy=True)
        self.block_file = os.path.join(Enviroment.block_dir, self.block_hash.hex())
        self.assertTrue(os.path.isfile(self.block_file))

    def _no_temp_left(self, target: str):
        parent = os.path.dirname(target) or "."
        leftovers = [n for n in os.listdir(parent) if ".beeblk-" in n]
        self.assertEqual(leftovers, [], f"temp scratch files left behind: {leftovers}")

    def test_intact_block_rehydrates_fully(self):
        target = os.path.join(self.root, "out_ok")
        ok = copy_block_if_exists(buffer=self.block.SerializeToString(), directory=target)
        self.assertTrue(ok)
        self.assertEqual(os.path.getsize(target), len(self.payload))
        self.assertEqual(_sha3(target), self.block_hash.hex())
        self._no_temp_left(target)

    def test_truncated_block_fails_closed(self):
        # Corrupt the block at rest: truncate to less than half.
        with open(self.block_file, "r+b") as f:
            f.truncate(5 * 1024 * 1024)

        target = os.path.join(self.root, "out_bad")
        ok = copy_block_if_exists(buffer=self.block.SerializeToString(), directory=target)
        self.assertFalse(ok, "must reject a truncated block instead of returning True")
        self.assertFalse(
            os.path.exists(target),
            "destination must be left untouched so the caller can raise, "
            "not written with corrupt/partial content",
        )
        self._no_temp_left(target)


if __name__ == "__main__":
    unittest.main()
