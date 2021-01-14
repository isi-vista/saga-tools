from pathlib import Path
from typing import Optional

from attr import attrib, attrs
from attr.validators import instance_of

from vistautils.parameters import Parameters


@attrs(frozen=True, slots=True, kw_only=True)
class CondaConfiguration:
    conda_base_path: Path = attrib(validator=instance_of(Path))
    conda_environment: str = attrib(validator=instance_of(str))

    CONDA_ENVIRONMENT_PARAM = "conda_environment"

    @staticmethod
    def from_parameters(params: Parameters) -> Optional["CondaConfiguration"]:
        if CondaConfiguration.CONDA_ENVIRONMENT_PARAM in params:
            return CondaConfiguration(
                conda_base_path=params.existing_directory("conda_base_path"),
                conda_environment=params.string(
                    CondaConfiguration.CONDA_ENVIRONMENT_PARAM
                ),
            )
        else:
            return None

    def sbatch_lines(self) -> str:
        return CONDA_SBATCH_TEMPLATE.format(
            conda_base_path=self.conda_base_path, conda_environment=self.conda_environment
        )


CONDA_SBATCH_TEMPLATE = """
source "{conda_base_path}"/etc/profile.d/conda.sh
conda activate {conda_environment}
"""
