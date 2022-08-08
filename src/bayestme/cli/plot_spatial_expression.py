import argparse

from bayestme import data, spatial_expression


def get_parser():
    parser = argparse.ArgumentParser(description='Plot spatial differential expression results')
    parser.add_argument('--stdata', type=str,
                        help='Input file, SpatialExpressionDataset in h5 format')
    parser.add_argument('--deconvolution-result', type=str,
                        help='Input file, DeconvolutionResult in h5 format')
    parser.add_argument('--sde-result', type=str,
                        help='Input file, SpatialDifferentialExpressionResult in h5 format')
    parser.add_argument('--output-dir', type=str,
                        help='Output directory')
    parser.add_argument('--cell-type-names',
                        default=None,
                        help='A comma separated list of cell type names to use for plots.'
                             'For example --cell-type-names "type 1, type 2, type 3"')
    return parser


def main():
    args = get_parser().parse_args()

    stdata = data.SpatialExpressionDataset.read_h5(args.stdata)
    deconvolution_result = data.DeconvolutionResult.read_h5(args.deconvolution_result)
    sde_result = data.SpatialDifferentialExpressionResult.read_h5(args.sde_result)

    if args.cell_type_names is not None:
        cell_type_names = [name.strip() for name in args.cell_type_names.split(',')]
    else:
        cell_type_names = None

    spatial_expression.plot_significant_spatial_patterns(
        stdata=stdata,
        decon_result=deconvolution_result,
        sde_result=sde_result,
        output_dir=args.output_dir,
        cell_type_names=cell_type_names)
