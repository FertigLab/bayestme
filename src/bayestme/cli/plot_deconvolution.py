import argparse
import logging
import bayestme.logging

from bayestme import data, deconvolution

logger = logging.getLogger(__name__)


def get_parser():
    parser = argparse.ArgumentParser(description='Plot deconvolution results')
    parser.add_argument('--adata', type=str,
                        help='Input file, AnnData in h5 format. Expected to be annotated with deconvolution results.')
    parser.add_argument('--output-dir', type=str,
                        help='Output directory.')
    parser.add_argument('--cell-type-names',
                        default=None,
                        help='A comma separated list of cell type names to use for plots.'
                             'For example --cell-type-names "type 1, type 2, type 3"')
    bayestme.logging.add_logging_args(parser)

    return parser


def main():
    args = get_parser().parse_args()

    stdata = data.SpatialExpressionDataset.read_h5(args.adata)

    if args.cell_type_names is not None:
        cell_type_names = [name.strip() for name in args.cell_type_names.split(',')]
    else:
        cell_type_names = None

    deconvolution.plot_deconvolution(
        stdata=stdata,
        output_dir=args.output_dir,
        cell_type_names=cell_type_names)
