import os
import shutil
import tempfile
from unittest import mock

import numpy as np

import bayestme.synthetic_data
from bayestme import data
from bayestme.cli import deconvolve
from bayestme.common import InferenceType
from bayestme.data_test import generate_toy_stdataset


def test_deconvolve():
    dataset = generate_toy_stdataset()
    tmpdir = tempfile.mkdtemp()

    input_path = os.path.join(tmpdir, "data.h5")
    output_path = os.path.join(tmpdir, "deconvolve.h5")
    adata_output_path = os.path.join(tmpdir, "data_out.h5")

    deconvolve_rv = bayestme.synthetic_data.create_toy_deconvolve_result(
        n_nodes=dataset.n_spot_in, n_components=5, n_samples=100, n_gene=dataset.n_gene
    )

    command_line_arguments = [
        "deconvolve",
        "--adata",
        input_path,
        "--adata-output",
        adata_output_path,
        "--output",
        output_path,
        "--seed",
        "42",
        "--spatial-smoothing-parameter",
        "1000",
        "--n-samples",
        "100",
        "--n-components",
        "5",
        "--no-use-spatial-guide",
        "--n-svi-steps",
        "4",
    ]

    try:
        dataset.save(input_path)

        with mock.patch("sys.argv", command_line_arguments):
            with mock.patch(
                "bayestme.deconvolution.sample_from_posterior"
            ) as deconvolve_mock:
                deconvolve_mock.return_value = deconvolve_rv

                deconvolve.main()

                data.DeconvolutionResult.read_h5(output_path)
                data.SpatialExpressionDataset.read_h5(adata_output_path)

                deconvolve_mock.assert_called_once_with(
                    data=mock.ANY,
                    n_components=5,
                    spatial_smoothing_parameter=1000.0,
                    n_samples=100,
                    expression_truth=None,
                    n_svi_steps=4,
                    use_spatial_guide=False,
                    rng=mock.ANY,
                )

    finally:
        shutil.rmtree(tmpdir)


def test_deconvolve_with_expression_truth():
    dataset = generate_toy_stdataset()
    tmpdir = tempfile.mkdtemp()

    input_path = os.path.join(tmpdir, "data.h5")
    output_path = os.path.join(tmpdir, "deconvolve.h5")
    adata_output_path = os.path.join(tmpdir, "data_out.h5")
    deconvolve_rv = bayestme.synthetic_data.create_toy_deconvolve_result(
        n_nodes=dataset.n_spot_in, n_components=5, n_samples=100, n_gene=dataset.n_gene
    )

    command_line_arguments = [
        "deconvolve",
        "--adata",
        input_path,
        "--adata-output",
        adata_output_path,
        "--output",
        output_path,
        "--seed",
        "42",
        "--spatial-smoothing-parameter",
        "1000",
        "--n-samples",
        "100",
        "--n-svi-steps",
        "99",
        "--use-spatial-guide",
        "--expression-truth",
        "xxx",
    ]

    try:
        dataset.save(input_path)

        with mock.patch("sys.argv", command_line_arguments):
            with mock.patch(
                "bayestme.deconvolution.sample_from_posterior"
            ) as deconvolve_mock:
                with mock.patch(
                    "bayestme.expression_truth.calculate_celltype_profile_prior_from_adata"
                ) as load_expression_truth_mock:
                    expression_truth = np.zeros((9, 10))
                    load_expression_truth_mock.return_value = expression_truth
                    deconvolve_mock.return_value = deconvolve_rv

                    deconvolve.main()

                    data.DeconvolutionResult.read_h5(output_path)
                    data.SpatialExpressionDataset.read_h5(adata_output_path)

                    deconvolve_mock.assert_called_once_with(
                        data=mock.ANY,
                        n_components=9,
                        spatial_smoothing_parameter=1000.0,
                        n_samples=100,
                        n_svi_steps=99,
                        expression_truth=mock.ANY,
                        use_spatial_guide=True,
                        rng=mock.ANY,
                    )
    finally:
        shutil.rmtree(tmpdir)
