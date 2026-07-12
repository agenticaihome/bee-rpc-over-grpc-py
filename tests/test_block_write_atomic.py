#!/usr/bin/env python3
"""Write-side durability test for block creation.

`copy_to_block_dir` used `shutil.copyfile()` straight to the content-addressed
path, so a process death (or full disk) mid-copy left a TRUNCATED block at the
final path — which later serializes as a payload-less `Block()`. It now copies to
a temp sibling, fsyncs, and atomically renames, so a block appears only once it is
complete.

This locks in the happy-path contract: a created block has full content, matches
its id, and leaves no `.tmp-*` scratch file behind.

Run:  python -m unittest tests.test_block_write_atomic
"""
import hashlib
import os
import tempfile
import unittest

from bee_rpc import block_builder
from bee_rpc.utils import modify_env, Enviroment


class BlockWriteAtomic(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="blkwrite-")
        self.blocks = os.path.join(self.root, "blocks")
        os.makedirs(self.blocks)
        modify_env(cache_dir=self.root + os.sep, block_dir=self.blocks + os.sep)

    def test_create_block_copy_is_complete_and_clean(self):
        payload = os.urandom(11 * 1024 * 1024)
        src = os.path.join(self.root, "big.bin")
        with open(src, "wb") as f:
            f.write(payload)

        # copy=True routes through copy_to_block_dir (the hardened path).
        block_hash, _ = block_builder.create_block(file_path=src, copy=True)
        stored = os.path.join(Enviroment.block_dir, block_hash.hex())

        self.assertTrue(os.path.isfile(stored))
        self.assertEqual(os.path.getsize(stored), len(payload))
        with open(stored, "rb") as f:
            self.assertEqual(hashlib.sha3_256(f.read()).hexdigest(), block_hash.hex())

        # No temp scratch file left behind in the block dir.
        leftovers = [n for n in os.listdir(self.blocks) if ".tmp-" in n]
        self.assertEqual(leftovers, [], f"temp scratch files left behind: {leftovers}")


if __name__ == "__main__":
    unittest.main()
