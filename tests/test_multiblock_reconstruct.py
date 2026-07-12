#!/usr/bin/env python3
"""Reconstruction test for multiblock (directory) blocks.

Very large files are stored as *multiblock* blocks: `__block__/<id>` is a
directory with its own `_.json` referencing sub-blocks, not a single file.
`copy_block_if_exists` used to stream `read_block(block_id)` straight to the
target, but read_block's directory branch yields `Buffer.Block` marker *objects*
(ignore_blocks=False), which aren't writable bytes — so a multiblock block raised
inside the copy and returned False. Downstream (e.g. nodo's rootfs builder) then
failed closed with "Block reconstruction failed", unable to materialise the file.

copy_block_if_exists now flattens multiblock blocks via
read_multiblock_directory(ignore_blocks=True), which recursively rehydrates the
sub-blocks and yields the original flat bytes.

Run:  python -m unittest tests.test_multiblock_reconstruct
"""
import os
import shutil
import tempfile
import unittest

from bee_rpc import block_builder, buffer_pb2
from bee_rpc.client import copy_block_if_exists
from bee_rpc.reader import read_multiblock_directory, block_exists
from bee_rpc.utils import modify_env, Enviroment


class MultiblockReconstruct(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="mblk-")
        self.blocks = os.path.join(self.root, "blocks")
        os.makedirs(self.blocks)
        modify_env(cache_dir=self.root + os.sep, block_dir=self.blocks + os.sep)

    def _make_multiblock_block(self):
        # A single-file sub-block, then a multiblock object that references it.
        sub = os.path.join(self.root, "sub.bin")
        with open(sub, "wb") as f:
            f.write(os.urandom(11 * 1024 * 1024))
        sub_hash, sub_block = block_builder.create_block(file_path=sub, copy=True)

        msg = buffer_pb2.Buffer()
        msg.chunk = sub_block.SerializeToString()
        obj_id, mdir = block_builder.build_multiblock(msg, blocks=[sub_hash])

        # Install the multiblock directory as a block under __block__/<obj_id>.
        block_id = obj_id.hex()
        dest = os.path.join(Enviroment.block_dir, block_id)
        shutil.copytree(mdir, dest)
        exists, is_dir = block_exists(block_id=block_id, is_dir=True)
        self.assertTrue(exists and is_dir, "fixture is not a multiblock (dir) block")

        expected = b"".join(
            c for c in read_multiblock_directory(dest, ignore_blocks=True)
            if isinstance(c, bytes)
        )
        pointer = buffer_pb2.Buffer.Block()
        h = buffer_pb2.Buffer.Block.Hash(type=Enviroment.hash_type, value=obj_id)
        pointer.hashes.append(h)
        return pointer.SerializeToString(), expected

    def test_multiblock_block_flattens_to_original_bytes(self):
        pointer, expected = self._make_multiblock_block()
        target = os.path.join(self.root, "reconstructed")

        ok = copy_block_if_exists(buffer=pointer, directory=target)
        self.assertTrue(ok, "multiblock block must reconstruct, not return False")
        with open(target, "rb") as f:
            self.assertEqual(f.read(), expected, "flattened bytes differ from canonical reconstruction")

        # No temp scratch left behind.
        leftovers = [n for n in os.listdir(os.path.dirname(target)) if ".beeblk-" in n]
        self.assertEqual(leftovers, [])


if __name__ == "__main__":
    unittest.main()
