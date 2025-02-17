import os
import tempfile
import anndata

import numpy as np
import pandas
import bayestme.utils
import bayestme.common
from bayestme import gene_filtering, data


def test_select_top_genes_by_standard_deviation():
    # Given: Three spots and three genes, the first two of which have large variation in counts
    raw_counts = np.array([[199, 200, 1], [10000, 10001, 2], [1, 3, 3]], dtype=np.int64)

    locations = np.array([(x, 0) for x in range(3)])

    tissue_mask = np.array([True for _ in range(3)])

    gene_names = np.array(["keep_me1", "keep_me2", "filter"])
    barcodes = np.array([f"barcode{i}" for i in range(3)])

    dataset_without_obs_names = data.SpatialExpressionDataset.from_arrays(
        raw_counts=raw_counts,
        tissue_mask=tissue_mask,
        positions=locations,
        gene_names=gene_names,
        layout=bayestme.common.Layout.SQUARE,
        edges=bayestme.utils.get_edges(locations, bayestme.common.Layout.SQUARE),
    )

    dataset_with_obs_names = data.SpatialExpressionDataset.from_arrays(
        raw_counts=raw_counts,
        tissue_mask=tissue_mask,
        positions=locations,
        gene_names=gene_names,
        layout=bayestme.common.Layout.SQUARE,
        barcodes=barcodes,
        edges=bayestme.utils.get_edges(locations, bayestme.common.Layout.SQUARE),
    )

    for dataset in [dataset_with_obs_names, dataset_without_obs_names]:
        # When: select_top_genes_by_standard_deviation is called to select the top 2 genes
        n_genes_filter = 2
        result = gene_filtering.select_top_genes_by_standard_deviation(
            dataset, n_genes_filter
        )

        (n_spots_in, n_genes) = result.counts.shape

        # Then: the 2 high variation genes are selected
        assert n_genes == n_genes_filter
        assert n_spots_in == 3
        np.testing.assert_equal(
            result.counts,
            np.array([[199, 200], [10000, 10001], [1, 3]], dtype=np.int64),
        )
        np.testing.assert_equal(result.gene_names, np.array(["keep_me1", "keep_me2"]))


def test_filter_genes_by_spot_threshold():
    # Given: Three spots and three genes, the first two of which appear in 66% of spots, the third gene never appears
    raw_counts = np.array([[1, 1, 0], [1, 1, 0], [0, 0, 0]], dtype=np.int64)

    locations = np.array([(x, 0) for x in range(3)])

    tissue_mask = np.array([True for _ in range(3)])

    gene_names = np.array(["filter1", "filter2", "keep_me"])

    barcodes = np.array([f"barcode{i}" for i in range(3)])

    dataset_without_obs_names = data.SpatialExpressionDataset.from_arrays(
        raw_counts=raw_counts,
        tissue_mask=tissue_mask,
        positions=locations,
        gene_names=gene_names,
        layout=bayestme.common.Layout.SQUARE,
        edges=bayestme.utils.get_edges(locations, bayestme.common.Layout.SQUARE),
    )

    dataset_with_obs_names = data.SpatialExpressionDataset.from_arrays(
        raw_counts=raw_counts,
        tissue_mask=tissue_mask,
        positions=locations,
        gene_names=gene_names,
        layout=bayestme.common.Layout.SQUARE,
        barcodes=barcodes,
        edges=bayestme.utils.get_edges(locations, bayestme.common.Layout.SQUARE),
    )

    for dataset in [dataset_with_obs_names, dataset_without_obs_names]:
        # When: filter_genes_by_spot_threshold is called with threshold 0.5

        result = gene_filtering.filter_genes_by_spot_threshold(
            dataset, spot_threshold=0.5
        )

        (n_spots_in, n_genes) = result.counts.shape

        # Then: only the gene which appears in 0% of spots is kept
        assert n_genes == 1
        np.testing.assert_equal(
            result.counts, np.array([[0], [0], [0]], dtype=np.int64)
        )
        np.testing.assert_equal(result.gene_names, np.array(["keep_me"]))


def test_filter_ribosome_genes():
    # Given: Three genes, one of which has a name that matches the ribosome gene name pattern
    raw_counts = np.array([[7, 1, 2], [8, 2, 3], [9, 3, 4]], dtype=np.int64)

    locations = np.array([(x, 0) for x in range(3)])

    tissue_mask = np.array([True for _ in range(3)])

    gene_names = np.array(["RPL333", "other", "other2"])
    barcodes = np.array([f"barcode{i}" for i in range(3)])
    dataset_without_obs_names = data.SpatialExpressionDataset.from_arrays(
        raw_counts=raw_counts,
        tissue_mask=tissue_mask,
        positions=locations,
        gene_names=gene_names,
        layout=bayestme.common.Layout.SQUARE,
        edges=bayestme.utils.get_edges(locations, bayestme.common.Layout.SQUARE),
    )

    dataset_with_obs_names = data.SpatialExpressionDataset.from_arrays(
        raw_counts=raw_counts,
        tissue_mask=tissue_mask,
        positions=locations,
        gene_names=gene_names,
        layout=bayestme.common.Layout.SQUARE,
        barcodes=barcodes,
        edges=bayestme.utils.get_edges(locations, bayestme.common.Layout.SQUARE),
    )

    for dataset in [dataset_with_obs_names, dataset_without_obs_names]:
        # When: filter_ribosome_genes is called
        result = gene_filtering.filter_ribosome_genes(dataset)

        (n_spots_in, n_genes) = result.counts.shape

        # Then: only the two genes with non matching names are kept
        assert n_genes == 2
        np.testing.assert_equal(
            result.counts, np.array([[1, 2], [2, 3], [3, 4]], dtype=np.int64)
        )
        np.testing.assert_equal(result.gene_names, np.array(["other", "other2"]))


def test_filter_list_of_genes():
    # Given: Three genes
    raw_counts = np.array([[7, 1, 2], [8, 2, 3], [9, 3, 4]], dtype=np.int64)

    locations = np.array([(x, 0) for x in range(3)])

    tissue_mask = np.array([True for _ in range(3)])
    gene_names = np.array(["RPL333", "other", "other2"])
    barcodes = np.array([f"barcode{i}" for i in range(3)])
    dataset_without_obs_names = data.SpatialExpressionDataset.from_arrays(
        raw_counts=raw_counts,
        tissue_mask=tissue_mask,
        positions=locations,
        gene_names=gene_names,
        layout=bayestme.common.Layout.SQUARE,
        edges=bayestme.utils.get_edges(locations, bayestme.common.Layout.SQUARE),
    )

    dataset_with_obs_names = data.SpatialExpressionDataset.from_arrays(
        raw_counts=raw_counts,
        tissue_mask=tissue_mask,
        positions=locations,
        gene_names=gene_names,
        layout=bayestme.common.Layout.SQUARE,
        barcodes=barcodes,
        edges=bayestme.utils.get_edges(locations, bayestme.common.Layout.SQUARE),
    )

    for dataset in [dataset_with_obs_names, dataset_without_obs_names]:
        # When: filter_list_of_genes is called
        result = gene_filtering.filter_list_of_genes(dataset, ["other", "other2"])

        (n_spots_in, n_genes) = result.counts.shape

        # Then: only the gene not on the list remains
        assert n_genes == 1
        np.testing.assert_equal(
            result.counts, np.array([[7], [8], [9]], dtype=np.int64)
        )
        np.testing.assert_equal(result.gene_names, np.array(["RPL333"]))


def test_filter_stdata_to_match_expression_truth():
    ad = anndata.AnnData(
        X=np.random.poisson(10, size=(50, 5)),
        obs=pandas.DataFrame(
            {
                "sample": ["sample"] * 50,
                "celltype": ["type 1", "type 2", "type 3", "type 4", "type 5"] * 10,
            }
        ),
    )

    ad.var_names = ["LINC01409", "LINC01128", "LINC00115", "FAM41C", "SAMD11"]

    tmpdir = tempfile.mkdtemp()

    ad.write_h5ad(os.path.join(tmpdir, "expression_truth.csv"))

    raw_counts = np.array([[7, 1, 2], [8, 2, 3], [9, 3, 4]], dtype=np.int64)

    locations = np.array([(x, 0) for x in range(3)])

    tissue_mask = np.array([True for _ in range(3)])

    gene_names = np.array(["LINC01409", "LINC01128", "other2"])
    dataset = data.SpatialExpressionDataset.from_arrays(
        raw_counts=raw_counts,
        tissue_mask=tissue_mask,
        positions=locations,
        gene_names=gene_names,
        layout=bayestme.common.Layout.SQUARE,
        edges=bayestme.utils.get_edges(locations, bayestme.common.Layout.SQUARE),
    )

    filtered_dataset = gene_filtering.filter_stdata_to_match_expression_truth(
        dataset, os.path.join(tmpdir, "expression_truth.csv")
    )

    np.testing.assert_equal(
        filtered_dataset.gene_names, np.array(["LINC01409", "LINC01128"])
    )
