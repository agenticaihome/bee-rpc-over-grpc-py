import hashlib
import json
import os
from shutil import rmtree
from threading import Condition

import typing

# GrpcBigBuffer.
CHUNK_SIZE = 1024 * 1024  # 1MB
MAX_DIR = 999999999
WITHOUT_BLOCK_POINTERS_FILE_NAME = 'wbp.bin'
METADATA_FILE_NAME = '_.json'
BLOCK_LENGTH = 36


class EmptyBufferException(Exception):
    pass


class Dir(object):
    def __init__(self, dir: str, _type: type):
        self.dir: str = dir
        self.type: type = _type


class MemManager(object):
    def __init__(self, len):
        pass

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, trace):
        pass


def get_file_hash(file_path: str) -> str:
    # Create a hash object
    hash = hashlib.sha3_256()
    # Open the file in binary mode
    with open(file_path, 'rb') as file:
        # Read the contents of the file in chunks
        chunk = file.read(1024)
        while chunk:
            # Update the hash with the chunk
            hash.update(chunk)
            # Read the next chunk
            chunk = file.read(1024)
        # Calculate the final hash
        file_hash: str = hash.hexdigest()
        # Return the hash
        return file_hash


class Signal():
    # The parser use change() when reads a signal on the buffer.
    # The serializer use wait() for stop to send the buffer if it've to do it.
    # It's thread safe because the open var is only used by one thread (the parser) with the change method.
    def __init__(self, exist: bool = True) -> None:
        self.exist = exist
        if exist: self.open = True
        if exist: self.condition = Condition()

    def change(self):
        if self.exist:
            if self.open:
                self.open = False  # Stop the input buffer.
            else:
                with self.condition:
                    self.condition.notify_all()
                self.open = True  # Continue the input buffer.

    def wait(self):
        if self.exist and not self.open:
            with self.condition:
                self.condition.wait()


## Enviroment ##

class Enviroment(type):
    # Using singleton pattern
    _instances = {}
    cache_dir = os.path.abspath(os.curdir) + '/__cache__/'
    block_dir = os.path.abspath(os.curdir) + '/__block__/'
    block_depth = 1
    skip_wbp_generation = False
    mem_manager = lambda len: MemManager(len=len)
    hash_type: bytes = bytes.fromhex("a7ffc6f8bf1ed76651c14756a061d662f580ff4de43b49fa82d80a4b80f8434a")  # SHA3_256

    def __call__(cls):
        if cls not in cls._instances:
            os.makedirs(cls.cache_dir, exist_ok=True)
            os.makedirs(cls.block_dir, exist_ok=True)
            cls._instances[cls] = super(Enviroment, cls).__call__()
        return cls._instances[cls]


def modify_env(
        cache_dir:           typing.Optional[str]        = None,
        mem_manager:         typing.Optional[MemManager] = None,
        hash_type:           typing.Optional[bytes]      = None,
        block_depth:         typing.Optional[int]        = None,
        block_dir:           typing.Optional[str]        = None,
        skip_wbp_generation: bool                        = False
):
    if cache_dir: Enviroment.cache_dir = cache_dir + 'grpcbigbuffer/'
    if mem_manager: Enviroment.mem_manager = mem_manager
    if hash_type and hash_type != Enviroment.hash_type:
        Enviroment.hash_type = hash_type
        # Si se modifica el algoritmo hash de los bloques, se pierde compatibilidad con el registro previo.
        rmtree(Enviroment.block_dir)
    if block_depth: Enviroment.block_depth = block_depth
    if block_dir: Enviroment.block_dir = block_dir
    Enviroment.skip_wbp_generation = skip_wbp_generation


def create_lengths_tree(
        pointer_container: typing.Dict[str, typing.List[typing.List[int]]]
) -> typing.Dict[int, typing.Union[typing.Dict, str]]:
    """
        Create a tree of the pointers where the leafs are the block id's.
    """
    tree: typing.Dict[int, typing.Union[typing.Dict, str]] = {}
    for key, list_pointers in pointer_container.items():
        for pointers in list_pointers:
            current_level = tree
            for pointer in pointers[:-1]:
                if pointer not in current_level:
                    current_level[pointer] = {}
                current_level = current_level[pointer]
            current_level[pointers[-1]] = key
    return tree


def encode_bytes(n: int) -> bytes:
    # https://github.com/fmoo/python-varint/blob/master/varint.py
    def _byte(b):
        return bytes((b,))

    buf = b''
    while True:
        towrite = n & 0x7f
        n >>= 7
        if n:
            buf += _byte(towrite | 0x80)
        else:
            buf += _byte(towrite)
            break
    return buf


def entries_of_multiblock_directory(directory: str) -> typing.List[str]:
    """The ordered list of paths a multiblock directory expands to.

    The same shape as the `file_list` `block_driver.generate_wbp_file` builds:
    the directory's own parts, interleaved with the blocks it points at.
    """
    with open(os.path.join(directory, METADATA_FILE_NAME), 'r') as f:
        _json = json.load(f)
    return [
        os.path.join(directory, str(e)) if type(e) == int
        else os.path.join(Enviroment.block_dir, e[0])
        for e in _json
    ]


def seek_expanded_position(position: int, file_list: typing.List[str]) -> typing.Tuple[str, int]:
    """Map a position in the expanded stream onto (single file, offset within it).

    Every entry of `file_list` is measured by how much it contributes to the
    expansion, which for a multiblock *directory* block is the sum of its own
    expansion -- `os.path.getsize` would report the size of the dirent instead, a
    couple of hundred bytes standing in for however much content the block holds,
    silently shifting every position past it. And a position landing inside such a
    block resolves against that block's own entries, to any depth, rather than
    reaching an `open()` that would raise IsADirectoryError.
    """
    remaining: int = position
    for path in file_list:
        length: int = getsize(path)
        if remaining < length:
            if os.path.isdir(path):
                return seek_expanded_position(remaining, entries_of_multiblock_directory(path))
            return path, remaining
        remaining -= length
    raise ValueError(f"Position {position} is out of buffer range.")


def get_varint_at_position(position, file_list) -> int:
    path, offset = seek_expanded_position(position=position, file_list=file_list)
    with open(path, "rb") as file:
        file.seek(offset)
        result = 0
        shift = 0
        while True:
            byte = file.read(1)
            if not byte:
                break
            byte = ord(byte)
            result |= (byte & 0x7F) << shift
            if not byte & 0x80:
                break
            shift += 7
        return result


def get_expanded_block_length(block_name: str, _seen: typing.Optional[typing.Set[str]] = None) -> int:
    """How many bytes `reader.read_block` emits for this block.

    A block is stored in one of two shapes, and the length differs between them:
    a single file, whose content is streamed verbatim, or a *multiblock
    directory* with its own `_.json`, whose content is the expansion of that
    directory (its parts, plus its sub-blocks expanded the same way, to any
    depth). Measuring a directory block with `os.path.getsize` returns the size
    of the dirent -- a couple of hundred bytes standing in for however much
    content the block actually holds -- so every caller that has to know how far
    a pointer expands must come through here.
    """
    if _seen is None:
        _seen = set()
    if block_name in _seen:
        raise Exception(f'bee-rpc: detected recursive loop when measuring block {block_name}')

    path = os.path.join(Enviroment.block_dir, block_name)
    if not os.path.isdir(path):
        return os.path.getsize(path)

    # `_seen` is the recursion *stack*, not a set of everything already measured:
    # deduplicated storage means one block is legitimately referenced many times
    # from the same object, and only a block that contains itself is a loop.
    _seen.add(block_name)
    try:
        return getsize(path, _seen=_seen)
    finally:
        _seen.discard(block_name)


def get_pruned_block_length(block_name: str) -> int:
    """What a block pointer adds beyond the BLOCK_LENGTH bytes of the pointer itself."""
    return get_expanded_block_length(block_name=block_name) - BLOCK_LENGTH

def getsize(path: str, _seen: typing.Optional[typing.Set[str]] = None) -> int:
    if not os.path.exists(path): 
        return 0
    
    if os.path.isdir(path): 
        with open(os.path.join(path, METADATA_FILE_NAME), 'rb') as f:
            _json = json.load(f)
        
        total_size = 0
        for e in _json:
            if type(e) == int:
                total_size += os.path.getsize(os.path.join(path, str(e)))
            
            else:
                block_id: str = e[0]
                if type(block_id) != str:
                    _msg = f"'bee-rpc error on block metadata file ( _.json ).' for block {block_id} on utils.getsize"
                    raise Exception(_msg)
                
                # The pointer is not stored in the parts, so the whole expansion
                # of the sub-block is what this reference contributes -- not
                # `get_pruned_block_length`, which deliberately discounts the
                # BLOCK_LENGTH bytes a pointer occupies where one is present.
                total_size += get_expanded_block_length(block_name=block_id, _seen=_seen)
                
        return total_size
    
    else:
        return os.path.getsize(path)