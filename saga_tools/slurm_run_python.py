"""
This is a wrapper script to make it easier to run Python scripts
on ISI VISTA's internal SLURM-based compute cluster.

You provide it with two YAML parameter files.
The first specifies information about the cluster setup.
The second specifies information about the particular job you wish to run.

##################
Cluster Parameters
##################
* *partition*: the cluster partition to run on, e.g. gaia or ephemeral.
* *conda_base_path*: path to the base of the conda install (not the *bin* directory)
* *conda_environment*: name of the conda environment to run in
* *spack_environment*: (optional): the spack environment, if any, to run in. Cannot appear with *spack_packages*.
* *spack_packages*: (optional): a YAML list of Spack packages to load (in *module@version* format).
* *spack_root*: the spack installation to use (necessary only if *spack_environment* or *spack_modules*) is specified.
   This is usually the path to a working copy of a spack repository.
* *log_base_directory*: directory to write the job logs to.
   Logs are named after the *job_name*, with any forward slashes becoming directories.

##################
Job Parameters
##################
* *entry_point*: the name of the module to run, e.g. vistautils.scripts.foo
* *memory*: the amount of memory to reserve on the node, e.g. 4G.
* *working_directory* (optional)
* *num_gpus* (optional, default 0): the number of GPUs to reserve.
* *num_cpus* (optional, default 1): the number of CPUs to reserve.
* *job_name* (optional, defaults to entry point name): the name to use for this job in SLURM.
* *echo_template* (optional boolean, default False): whether to echo
  the generated SLURM template (for debugging).
* *slurm_script_path* (optional): the file to write the generated
   SLURM batch script to (for debugging).

"""
import argparse
import os
import subprocess
from pathlib import Path
from typing import Optional, Tuple

from attr import attrib, attrs
from attr.validators import instance_of, optional, deep_iterable

from immutablecollections import immutabledict
from vistautils.memory_amount import MemoryAmount, MemoryUnit
from vistautils.parameters import Parameters, YAMLParametersLoader
from vistautils.range import Range

import temppathlib


def main(cluster_params: Parameters, job_param_file: Path) -> None:
    runner = SlurmPythonRunner.from_parameters(cluster_params)
    job_params = YAMLParametersLoader().load(job_param_file)
    entry_point = job_params.string("entry_point")
    memory = MemoryAmount.parse(job_params.string("memory"))
    runner.run_entry_point(
        entry_point_name=entry_point,
        param_file=job_param_file,
        partition=cluster_params.string("partition"),
        working_directory=job_params.optional_creatable_directory("working_directory")
        or Path(os.getcwd()),
        num_gpus=job_params.integer("num_gpus", default=0, valid_range=Range.at_least(0)),
        num_cpus=job_params.integer("num_cpus", default=1, valid_range=Range.at_least(1)),
        job_name=job_params.string("job_name", default=entry_point),
        memory_request=memory,
        echo_template=cluster_params.boolean("echo_template", default=False),
        slurm_script_path=job_params.optional_creatable_file("slurm_script_path"),
    )


@attrs(frozen=True, slots=True, kw_only=True)
class SpackPackage:
    package_name: str = attrib(validator=instance_of(str))
    version: str = attrib(validator=instance_of(str))

    @staticmethod
    def parse(package_specifier: str) -> "SpackPackage":
        parts = package_specifier.split("@")
        if len(parts) == 2:
            return SpackPackage(package_name=parts[0],
                                version=parts[1])
        else:
            raise RuntimeError(f"Expected a package specified of the form packaged@version but got {package_specifier}")

    def __str__(self) -> str:
        return f"{self.package_name}@{self.version}"

@attrs(frozen=True, slots=True, kw_only=True)
class SpackConfiguration:
    spack_root: Path = attrib(validator=instance_of(Path))
    spack_environment: Optional[str] = attrib(validator=optional(instance_of(str)),
                                              default=None)
    spack_packages: Optional[Tuple[SpackPackage]] = attrib(validator=optional(deep_iterable(instance_of(SpackPackage))),
                                                           default=tuple())

    SPACK_ROOT_PARAM = "spack_root"
    SPACK_ENVIRONMENT_PARAM = "spack_environment"
    SPACK_PACKAGES_PARAM = "spack_packages"

    @staticmethod
    def from_parameters(params: Parameters) -> Optional["SpackConfiguration"]:
        if SpackConfiguration.SPACK_ENVIRONMENT_PARAM in params:
            if SpackConfiguration.SPACK_PACKAGES_PARAM in params:
                raise RuntimeError(f"{SpackConfiguration.SPACK_ENVIRONMENT_PARAM} "
                                   f"and {SpackConfiguration.SPACK_PACKAGES_PARAM} are mutually exclusive")
            return SpackConfiguration(
                spack_root=params.existing_directory(SpackConfiguration.SPACK_ROOT_PARAM),
                spack_environment=params.string(SpackConfiguration.SPACK_ENVIRONMENT_PARAM)
            )
        elif SpackConfiguration.SPACK_PACKAGES_PARAM in params:
            if SpackConfiguration.SPACK_ENVIRONMENT_PARAM in params:
                raise RuntimeError(f"{SpackConfiguration.SPACK_ENVIRONMENT_PARAM} "
                                   f"and {SpackConfiguration.SPACK_PACKAGES_PARAM} are mutually exclusive")
            return SpackConfiguration(
                spack_root=params.existing_directory(SpackConfiguration.SPACK_ROOT_PARAM),
                spack_packages=[SpackPackage.parse(package_specifier) for package_specifier in
                            params.arbitrary_list(SpackConfiguration.SPACK_PACKAGES_PARAM)],
            )
        else:
            return None

    def __attrs_post_init__(self) -> None:
        if bool(self.spack_environment) == bool(self.spack_packages):
            raise RuntimeError("A Spack configuration requires either an environment or a list of packages, "
                               "but not both.`")

    def sbatch_lines(self) -> str:
        if self.spack_environment:
            config_lines = SPACK_ENVIRONMENT_TEMPLATE.format(
                spack_root=self.spack_root,
                spack_environment=self.spack_environment
            )
        else:
            config_lines = "\n".join(f"spack load {package}" for package in self.spack_packages)
        return "\n".join([
            SPACK_COMMON_TEMPLATE.format(spack_root=self.spack_root),
            config_lines,
            "\n"])

SPACK_COMMON_TEMPLATE = """
. "{spack_root}"/share/spack/setup-env.sh
"""

SPACK_ENVIRONMENT_TEMPLATE = """
spack env activate {spack_environment}
"""

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
                conda_environment=params.string(CondaConfiguration.CONDA_ENVIRONMENT_PARAM)
            )
        else:
            return None

    def sbatch_lines(self) -> str:
        return CONDA_SBATCH_TEMPLATE.format(conda_base_path=self.conda_base_path,
                                            conda_environment=self.conda_environment)

CONDA_SBATCH_TEMPLATE = """
source "{conda_base_path}"/etc/profile.d/conda.sh
conda activate {conda_environment}
"""


@attrs(frozen=True, slots=True, kw_only=True)
class SlurmPythonRunner:
    log_base_directory: Path = attrib(validator=instance_of(Path))
    conda_config: Optional[CondaConfiguration] = attrib(validator=optional(instance_of(CondaConfiguration)))
    spack_config: Optional[SpackConfiguration] = attrib(validator=optional(instance_of(SpackConfiguration)))

    @staticmethod
    def from_parameters(params: Parameters) -> "SlurmPythonRunner":
        return SlurmPythonRunner(
            conda_config=CondaConfiguration.from_parameters(params),
            spack_config=SpackConfiguration.from_parameters(params),
            log_base_directory=params.creatable_directory("log_directory").absolute(),
        )

    def run_entry_point(
        self,
        entry_point_name: str,
        param_file: Path,
        *,
        partition: str,
        working_directory: Path,
        # We deliberately don't set a default memory request because we want users
        # to think about if explicitly.
        memory_request: MemoryAmount,
        num_gpus: int = 0,
        num_cpus: int = 1,
        job_name: Optional[str] = None,
        slurm_script_path: Optional[Path] = None,
        echo_template: bool = False,
    ):
        slurm_script_directory = slurm_script_path.parent if slurm_script_path else None
        job_log_directory = self._job_log_directory(job_name)
        with temppathlib.TmpDirIfNecessary(path=slurm_script_directory) as tmp_dir:
            if not slurm_script_path:
                slurm_script_path = tmp_dir.path / f"{job_name}.sbatch"

            # Whether we use an account parameter or a quality of service parameter
            # depends on whether we are running on a project partition
            # or one of the available-to-everyone-but-you-can-be-killed-at-any-time partitions.
            if partition in ("scavenge", "ephemeral"):
                account_or_qos = f"#SBATCH --qos={partition}"
            else:
                account_or_qos = f"#SBATCH --account={partition}"

            slurm_template_content = SLURM_BATCH_TEMPLATE.format(
                partition=partition,
                account_or_qos=account_or_qos,
                job_name=job_name,
                memory_string=self._to_slurm_memory_string(memory_request),
                num_cpus=num_cpus,
                num_gpus=num_gpus,
                stdout_log_path=job_log_directory / f"{job_name}.log",
                spack_lines=self.spack_config.sbatch_lines() if self.spack_config else "",
                conda_lines=self.conda_config.sbatch_lines() if self.conda_config else "",
                working_directory=working_directory,
                entry_point=entry_point_name,
                param_file=param_file.absolute(),
            )
            slurm_script_path.write_text(  # type: ignore
                slurm_template_content, encoding="utf-8"
            )
            if echo_template:
                print(slurm_template_content)
            subprocess.run(
                ["sbatch", str(slurm_script_path.absolute())],  # type: ignore
                # Raise an exception on failure
                check=True,
            )

    def _job_log_directory(self, job_name: str) -> Path:
        """
        Gets the directory to write the job logs to.

        This will be `log_base_directory` unless the job name contains forward slashes.
        If so, a subdirectory will be created under `log_base_directory`,
        with each */*-separated component except the last becoming a directory level.

        For example, if the job name is */foo/bar/baz*
        and `log_base_directory` is */home/fred/logs*,
        the returned directory will be
        */home/fred/logs/foo/bar*.
        """
        parts = job_name.split("/")
        if len(parts) > 1:
            path_components = [self.log_base_directory]
            # The last portion of the job name does not form part of the directory
            # because it is used to name the log file itself.
            path_components.extend([parts[:-1]])
            return Path(*path_components)
        return self.log_base_directory

    _SLURM_MEMORY_UNITS = immutabledict(
        [
            (MemoryUnit.KILOBYTES, "K"),
            (MemoryUnit.MEGABYTES, "M"),
            (MemoryUnit.GIGABYTES, "G"),
            (MemoryUnit.TERABYTES, "T"),
        ]
    )

    def _to_slurm_memory_string(self, memory_request: MemoryAmount) -> str:
        return (
            f"{memory_request.amount}"
            f"{SlurmPythonRunner._SLURM_MEMORY_UNITS[memory_request.unit]}"
        )


SLURM_BATCH_TEMPLATE = """#!/usr/bin/env bash

{account_or_qos}
#SBATCH --partition={partition}
#SBATCH --job-name={job_name}
#SBATCH --output={stdout_log_path}
#SBATCH --mem={memory_string}
#SBATCH --ntasks=1
#SBATCH --gpus-per-task={num_gpus}
#SBATCH --cpus-per-task={num_cpus}

set -euo pipefail

# This is needed because SLURM jobs are run from a non-interactive shell,
# but conda expects PS1 (the prompt variable) to be set.
if [[ -z ${{PS1+x}} ]]
  then
    export PS1=""
fi

{conda_lines}
{spack_lines}

cd {working_directory}
python -m {entry_point} {param_file}
"""

if __name__ == "__main__":
    parser = argparse.ArgumentParser(  # pylint:disable=invalid-name
        description="Run a Python script on SLURM"
    )
    parser.add_argument(
        "cluster_parameters",
        type=Path,
        help="Param file with general information about the SLURM cluster",
    )
    parser.add_argument(
        "job_parameters", type=Path, help="Param file with job-specific parameters"
    )
    args = parser.parse_args()  # pylint:disable=invalid-name

    main(
        cluster_params=YAMLParametersLoader().load(args.cluster_parameters),
        job_param_file=args.job_parameters,
    )
