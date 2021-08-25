import os
from pathlib import Path
from functools import lru_cache
from e4s_cl import logger
from e4s_cl.cf.containers import Container

LOGGER = logger.get_logger(__name__)

__TRANSLATE = {"OMPI": "OPENMPI", "INTEL": "INTELMPI", "MPICH": "MPICH"}


def wi4mpi_enabled() -> bool:
    # Convoluted way to have True or False instead of the contents of the key
    return not os.environ.get("WI4MPI_VERSION") is None


@lru_cache
def wi4mpi_root() -> Path:
    string = os.environ.get("WI4MPI_ROOT")

    if string is None:
        LOGGER.error("Getting WI4MPI root failed")
        return Path("")

    return Path(string)


# TODO unit test
#def __read_cfg(cfg_file: Path) -> dict[str, str]:
def __read_cfg(cfg_file: Path):
    config = {}

    try:
        with open(cfg_file, 'r') as cfg:
            while line := cfg.readline().strip():
                if line.startswith('#') or not '=' in line:
                    continue

                parts = line.split('=')

                if len(parts) != 2:
                    continue

                config.update({parts[0]: parts[1].strip('"')})
    except OSError as err:
        LOGGER.debug("Error accessing configuration %s: %s",
                     cfg_file.as_posix(), str(err))
        pass

    return config


#def wi4mpi_config(install_dir: Path) -> dict[str, str]:
@lru_cache
def wi4mpi_config(install_dir: Path):
    global_cfg = __read_cfg(install_dir.joinpath('etc/wi4mpi.cfg'))
    user_cfg = __read_cfg(
        Path(os.path.expanduser('~')).joinpath('.wi4mpi.cfg'))

    global_cfg.update(user_cfg)

    return global_cfg


def wi4mpi_import(container: Container, install_dir: Path) -> None:
    """
    Bind to a container the necessary files required for wi4mpi to run
    """
    container.bind_file(install_dir.as_posix())

    config = wi4mpi_config(install_dir)

    for (key, value) in config.items():
        if 'ROOT' in key and value:
            container.bind_file(value)
            container.add_ld_library_path(
                Path(value).joinpath('lib').as_posix())


#def wi4mpi_libraries() -> list[Path]:
def wi4mpi_libraries(install_dir: Path):
    config = wi4mpi_config(install_dir)

    source = os.environ.get("WI4MPI_FROM", "")
    target = os.environ.get("WI4MPI_TO", "")

    if not (source and target):
        LOGGER.error("Missing environment variables ")
        return []

    wrapper_lib = install_dir.joinpath('libexec', 'wi4mpi',
                                       "libwi4mpi_%s_%s.so" % (source, target))

    def _get_lib(identifier: str) -> Path:
        root = Path(
            config.get("%s_DEFAULT_ROOT" % __TRANSLATE.get(identifier), ""))
        return root.joinpath('lib', 'libmpi.so')

    source_lib = _get_lib(source)
    target_lib = _get_lib(target)

    return [wrapper_lib, source_lib, target_lib]


def wi4mpi_libpath(install_dir: Path):
    """
    Select all WI4MPI-relevant elements from the LD_LIBRARY_PATH
    """
    ld_library_path = os.environ.get('LD_LIBRARY_PATH', '').split(':')

    for filename in ld_library_path:
        if install_dir.as_posix() in filename:
            yield Path(filename)
