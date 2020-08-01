from dataclasses import dataclass
from unittest import TestCase

from labctl.experiment import (
    BaseInputParameters,
    BaseOutputData,
    Experiment,
)
from labctl.experiment.sequence import ExperimentSequence


@dataclass(frozen=True)
class OutputData(BaseOutputData):
    pass


@dataclass(frozen=True)
class InputParameters(BaseInputParameters):
    sampling_rate_in_hz: float = 1.0
    duration_in_seconds: float = 3600


class TestExperiment(Experiment[InputParameters, OutputData]):
    def start(self) -> None:
        pass

    def measure(self) -> OutputData:
        return OutputData()

    def stop(self) -> None:
        pass


class ExperimentSequenceTest(TestCase):
    def test_parsing(self) -> None:
        sequence = ExperimentSequence(
            """
---
sequence:
  - experiment_type: labctl.experiment.tests.test_sequence.TestExperiment
  - experiment_type: labctl.experiment.tests.test_sequence.TestExperiment
"""
        )

        self.assertEquals(len(sequence.experiments), 2)

        first_experiment = sequence.experiments[0]
        self.assertIsInstance(first_experiment, TestExperiment)