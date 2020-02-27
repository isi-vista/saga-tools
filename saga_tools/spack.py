from pathlib import Path
from typing import Optional, Tuple

from attr import attrib, attrs
from attr.validators import deep_iterable, instance_of, optional

from vistautils.parameters import Parameters


@attrs(frozen=True, slots=True, kw_only=True)
class SpackPackage:
    package_name: str = attrib(validator=instance_of(str))
    version: str = attrib(validator=instance_of(str))

    @staticmethod
    def parse(package_specifier: str) -> "SpackPackage":
        parts = package_specifier.split("@")
        if len(parts) == 2:
            return SpackPackage(package_name=parts[0], version=parts[1])
        else:
            raise RuntimeError(
                f"Expected a package specified of the form packaged@version but got {package_specifier}"
            )

    def __str__(self) -> str:
        return f"{self.package_name}@{self.version}"


@attrs(frozen=True, slots=True, kw_only=True)
class SpackConfiguration:
    spack_root: Path = attrib(validator=instance_of(Path))
    spack_environment: Optional[str] = attrib(
        validator=optional(instance_of(str)), default=None
    )
    spack_packages: Optional[Tuple[SpackPackage]] = attrib(
        validator=optional(deep_iterable(instance_of(SpackPackage))), default=tuple()
    )

    SPACK_ROOT_PARAM = "spack_root"
    SPACK_ENVIRONMENT_PARAM = "spack_environment"
    SPACK_PACKAGES_PARAM = "spack_packages"

    @staticmethod
    def from_parameters(params: Parameters) -> Optional["SpackConfiguration"]:
        if SpackConfiguration.SPACK_ENVIRONMENT_PARAM in params:
            if SpackConfiguration.SPACK_PACKAGES_PARAM in params:
                raise RuntimeError(
                    f"{SpackConfiguration.SPACK_ENVIRONMENT_PARAM} "
                    f"and {SpackConfiguration.SPACK_PACKAGES_PARAM} are mutually exclusive"
                )
            return SpackConfiguration(
                spack_root=params.existing_directory(SpackConfiguration.SPACK_ROOT_PARAM),
                spack_environment=params.string(
                    SpackConfiguration.SPACK_ENVIRONMENT_PARAM
                ),
            )
        elif SpackConfiguration.SPACK_PACKAGES_PARAM in params:
            if SpackConfiguration.SPACK_ENVIRONMENT_PARAM in params:
                raise RuntimeError(
                    f"{SpackConfiguration.SPACK_ENVIRONMENT_PARAM} "
                    f"and {SpackConfiguration.SPACK_PACKAGES_PARAM} are mutually exclusive"
                )
            return SpackConfiguration(
                spack_root=params.existing_directory(SpackConfiguration.SPACK_ROOT_PARAM),
                spack_packages=[
                    SpackPackage.parse(package_specifier)
                    for package_specifier in params.arbitrary_list(
                        SpackConfiguration.SPACK_PACKAGES_PARAM
                    )
                ],
            )
        else:
            return None

    def __attrs_post_init__(self) -> None:
        if bool(self.spack_environment) == bool(self.spack_packages):
            raise RuntimeError(
                "A Spack configuration requires either an environment or a list of packages, "
                "but not both.`"
            )

    def sbatch_lines(self) -> str:
        if self.spack_environment:
            config_lines = SPACK_ENVIRONMENT_TEMPLATE.format(
                spack_root=self.spack_root, spack_environment=self.spack_environment
            )
        else:
            config_lines = "\n".join(
                f"spack load {package}" for package in self.spack_packages
            )
        return "\n".join(
            [SPACK_COMMON_TEMPLATE.format(spack_root=self.spack_root), config_lines, "\n"]
        )


SPACK_COMMON_TEMPLATE = """
. "{spack_root}"/share/spack/setup-env.sh
"""

SPACK_ENVIRONMENT_TEMPLATE = """
spack env activate {spack_environment}
"""
