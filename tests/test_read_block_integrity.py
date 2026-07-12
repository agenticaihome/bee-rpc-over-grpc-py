#!/usr/bin/env python3
"""Serialize-side integrity regression tests for `read_block`.

`read_block()` streams a block's bytes into an outgoing buffer (this is what
`write_to_file`/`read_from_registry` use to serialize a service). It used to
delegate straight to `read_file_by_chunks`, which swallows errors and does no
length/hash check — so a block file that is present but truncated/corrupt at rest
(torn write, interrupted copy, a race with an `rm -rf __block__` cleanup) was
streamed as short/empty content with NO error. The resulting `.bee` carried the
`Block()` marker but little or no payload ("has Block() but no blocks").

These tests assert the fail-closed contract:
  * intact block  -> full content streamed
  * truncated block -> read_block raises (aborting the stream) instead of emitting
    a payload-less marker

Run:  python -m unittest tests.test_read_block_integrity
"""
import os
import tempfile
import unittest

from bee_rpc import block_builder
from bee_rpc.reader import read_block
from bee_rpc.utils import modify_env, Enviroment


class ReadBlockIntegrity(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="readblk-")
        self.blocks = os.path.join(self.root, "blocks")
        os.makedirs(self.blocks)
        modify_env(cache_dir=self.root + os.sep, block_dir=self.blocks + os.sep)

        self.payload = os.urandom(11 * 1024 * 1024)
        src = os.path.join(self.root, "big.bin")
        with open(src, "wb") as f:
            f.write(self.payload)
        self.block_hash, _ = block_builder.create_block(file_path=src, copy=True)
        self.block_file = os.path.join(Enviroment.block_dir, self.block_hash.hex())

    def test_intact_block_streams_full_content(self):
        streamed = b"".join(
            c for c in read_block(block_id=self.block_hash.hex()) if isinstance(c, bytes)
        )
        self.assertEqual(len(streamed), len(self.payload))
        self.assertEqual(streamed, self.payload)

    def test_truncated_block_aborts_stream(self):
        with open(self.block_file, "r+b") as f:
            f.truncate(0)  # present but empty
        with self.assertRaises(Exception):
            # Must raise before/while iterating — never silently yield a short stream.
            list(read_block(block_id=self.block_hash.hex()))


if __name__ == "__main__":
    unittest.main()
