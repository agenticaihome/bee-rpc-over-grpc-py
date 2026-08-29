from typing import Dict, List

from bee_rpc.utils import get_varint_at_position, get_pruned_block_length


def validate_lengths_tree(
        blocks: Dict[str, List[List[int]]],
        file_list: List[str],
        pointer_lengths: Dict[int, int]
) -> bool:
    """
    Validate the lengths of blocks in a tree structure.

    Args:
        blocks (Dict[str, List[List[int]]]): A dictionary mapping block names to lists of block indices.
        file_list (List[str]): A list of file names or positions.
        pointer_lengths (Dict[int, int]): How long the pointer written at each position is.

    Returns:
        bool: True if all block lengths are valid, False otherwise.
    """

    def print_debug_info_for_block(block_name, block_index_position):
        """
        Print debug information for a specific block.

        Args:
            block_name (str): The name of the block.
            block_index_position (int): The position of the block index.

        """
        position_length = get_varint_at_position(block_index_position, file_list=file_list)
        block_length = get_pruned_block_length(
            block_name=block_name, pointer_length=pointer_lengths[block_index_position])

        print(f"\nDebugging Information for Block '{block_name}':")
        print(f"Block Index Position: {block_index_position}")
        print(f"Position Length: {position_length}")
        print(f"Block Length: {block_length}\n")

    print(f"\nBlocks: {blocks}")

    for block, pointer_lists in blocks.items():
        for pointer_list in pointer_lists:
            block_index_position = pointer_list[-1]
            position_length = get_varint_at_position(block_index_position, file_list=file_list)
            block_length = get_pruned_block_length(
                block_name=block, pointer_length=pointer_lengths[block_index_position])

            if block_length > position_length:
                print(f"\nValidation Failed for Block '{block}'")
                print(f"Block Index Position: {block_index_position}")
                print(f"Position Length: {position_length}")
                print(f"Block Length: {block_length}\n")
                print_debug_info_for_block(block, block_index_position)
                return False

    return True
