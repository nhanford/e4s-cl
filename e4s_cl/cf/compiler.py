"""
Determine what compiler vendor was used to compile a given binary, by checking the .comments ELF section
"""
from pathlib import Path
from elftools.elf.elffile import ELFFile
from elftools.common.exceptions import ELFError
from e4s_cl.logger import get_logger

LOGGER = get_logger(__name__)


def _gnu_check(string: str) -> bool:
    return 'GCC' in string


def _llvm_check(string: str) -> bool:
    return 'clang' in string


def _intel_check(_: str) -> bool:
    return False


def _amd_check(string: str) -> bool:
    return 'AMD' in string


def _pgi_check(_: str) -> bool:
    return False


def _armclang_check(_: str) -> bool:
    return False


def _fujitsu_check(_: str) -> bool:
    return False


class CompilerVendor:
    """
    Enum with values describing compiler vendors
    """
    GNU = 0
    LLVM = 1
    INTEL = 2
    AMD = 3
    PGI = 4
    ARMCLANG = 5
    FUJITSU = 6

    checks = {
        GNU: _gnu_check,
        LLVM: _llvm_check,
        INTEL: _intel_check,
        AMD: _amd_check,
        PGI: _pgi_check,
        ARMCLANG: _armclang_check,
        FUJITSU: _fujitsu_check
    }

    # ROCm-compiled binaries contained 'AMD', 'clang' and 'GCC'
    # Establishing an order for the checks is a simple way
    # of ensuring the right value is returned
    precendence = [AMD, LLVM, GNU]


def _get_comment(elf_file: Path) -> str:
    """
    Returns the contents of the .comment sections of the ELF file passed as an argument
    """
    try:
        with open(elf_file, 'rb') as data:
            elf = ELFFile(data)
            comment_sections = filter(lambda x: x.name == '.comment',
                                      elf.iter_sections())
            return ' - '.join(
                map(lambda x: x.data().decode(), comment_sections))
    except (PermissionError, FileNotFoundError, IsADirectoryError,
            ELFError) as err:
        LOGGER.debug("Error reading comments of file %s: %s", str(elf_file),
                     str(err))
        return ''


def compiler_vendor(elf_file: Path) -> int:
    """
    Returns a value from CompilerVendor according to the contents of the .comment section of a binary
    """
    comment = _get_comment(elf_file)

    for vendor in CompilerVendor.precendence:
        check = CompilerVendor.checks.get(vendor)
        if check and check(comment):
            return vendor

    # By default, return GNU
    return CompilerVendor.GNU
