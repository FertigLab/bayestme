include { DECONVOLUTION } from './deconvolution'

process LOAD_SPACERANGER {
    label 'small_mem'

    input:
        path spaceranger_input_dir

    output:
        path 'dataset.h5ad', emit: result

    script:
    """
    load_spaceranger --input ${spaceranger_input_dir} --output dataset.h5ad
    """
}

def create_expression_truth_flag(expression_truth_values) {
    if (expression_truth_values == null || expression_truth_values.length == 0) {
        return ""
    } else {
        var expression_truth_flag = ""
        for (expression_truth_value in expression_truth_values) {
            expression_truth_flag += "--expression-truth ${expression_truth_value} "
        }

        return expression_truth_flag
    }
}

process FILTER_GENES {
    label 'small_mem'
    publishDir "${params.outdir}/filter_genes"

    input:
        path dataset

    output:
        path 'dataset_filtered.h5ad', emit: result

    script:
    def filter_ribosomal_genes_flag = params.filter_ribosomal_genes == null ? "" : "--filter-ribosomal-genes"
    def n_top_by_standard_deviation_flag = params.n_top_by_standard_deviation == null ? "": "--n-top-by-standard-deviation ${params.n_top_by_standard_deviation}"
    def spot_threshold_flag = params.spot_threshold == null ? "" : "--spot-threshold ${params.spot_threshold}"
    def expression_truth_flag = create_expression_truth_flag(params.expression_truth_files)
    """
    filter_genes --adata ${dataset} \
        ${filter_ribosomal_genes_flag} \
        ${n_top_by_standard_deviation_flag} \
        ${spot_threshold_flag} \
        ${expression_truth_flag} \
        --output dataset_filtered.h5ad
    """
}

process BLEEDING_CORRECTION {
    label 'big_mem'
    publishDir "${params.outdir}/bleeding_correction"

    input:
        path dataset

    output:
        path 'dataset_filtered_corrected.h5ad', emit: adata_output
        path 'bleed_correction_results.h5', emit: bleed_correction_output

    script:
    def n_top_flag = params.bleed_correction_n_top_genes == null ? "" : "--n-top ${params.bleed_correction_n_top_genes}"
    def bleed_correction_n_em_steps_flag = params.bleed_correction_n_em_steps == null ? "" : "--max-steps ${params.bleed_correction_n_em_steps}"
    def bleed_correction_local_weight_flag = params.bleed_correction_local_weight == null ? "" : "--local-weight ${params.bleed_correction_local_weight}"
    """
    bleeding_correction --adata ${dataset} \
        ${n_top_flag} \
        ${bleed_correction_n_em_steps_flag} \
        ${bleed_correction_local_weight_flag} \
        --adata-output dataset_filtered_corrected.h5ad \
        --bleed-out bleed_correction_results.h5
    """
}

process PLOT_BLEEDING_CORRECTION {
    label 'small_mem'
    publishDir "${params.outdir}/bleeding_correction_plots"

    input:
        path filtered_anndata
        path bleed_corrected_anndata
        path bleed_correction_results

    output:
        path '*.pdf', emit: result

    script:
    """
    plot_bleeding_correction --raw-adata ${filtered_anndata} \
        --corrected-adata ${bleed_corrected_anndata} \
        --bleed-correction-results ${bleed_correction_results} \
        --output-dir .
    """
}

def create_lambda_values_flag(lambda_values) {
    if (lambda_values == null) {
        return ""
    } else {
        var lambda_values_flag = ""
        for (lambda_value in lambda_values) {
            lambda_values_flag += "--spatial-smoothing-values ${lambda_value} "
        }

        return lambda_values_flag
    }
}

process PHENOTYPE_SELECTION {
    label 'big_mem'

    input:
        val job_index
        path adata
        val phenotype_selection_spatial_smoothing_values
        val n_components_min
        val n_components_max

    output:
        path 'fold_*.h5ad', emit: result

    script:
    def n_fold_flag = "--n-fold ${params.phenotype_selection_n_fold}"
    def n_splits_flag = "--n-splits ${params.phenotype_selection_n_splits}"
    def n_samples_flag = "--n-samples ${params.phenotype_selection_n_samples}"
    def n_burn_flag = "--n-burn ${params.phenotype_selection_n_burn}"
    def n_thin_flag = "--n-thin ${params.phenotype_selection_n_thin}"
    def n_components_min_flag = "--n-components-min ${n_components_min}"
    def n_components_max_flag = "--n-components-max ${n_components_max}"
    def phenotype_selection_spatial_smoothing_values_flag = create_lambda_values_flag(phenotype_selection_spatial_smoothing_values)
    def phenotype_selection_background_noise_flag = params.background_noise ? "--background-noise" : ""
    def phenotype_selection_lda_initialization_flag = params.lda_initialization ? "--lda-initialization" : ""
    def inference_type_flag = "--inference-type ${params.inference_type}"
    """
    phenotype_selection --adata ${adata} \
        --output-dir . \
        --job-index ${job_index} \
        ${n_fold_flag} \
        ${n_splits_flag} \
        ${n_samples_flag} \
        ${n_burn_flag} \
        ${n_thin_flag} \
        ${n_components_min_flag} \
        ${n_components_max_flag} \
        ${phenotype_selection_spatial_smoothing_values_flag} \
        ${phenotype_selection_background_noise_flag} \
        ${phenotype_selection_lda_initialization_flag} \
        ${inference_type_flag}
    """
}

process SPATIAL_EXPRESSION {
    label 'big_mem'
    publishDir "${params.outdir}/spatial_differential_expression"

    input:
        path adata
        path deconvolution_samples

    output:
        path 'sde_samples.h5', emit: samples

    script:
    def n_spatial_patterns_flag = "--n-spatial-patterns ${params.spatial_expression_n_spatial_patterns}"
    def n_samples_flag = "--n-samples ${params.spatial_expression_n_samples}"
    def n_burn_flag = "--n-burn ${params.spatial_expression_n_burn}"
    def n_thin_flag = "--n-thin ${params.spatial_expression_n_thin}"
    def n_gene_flag = "--n-gene ${params.spatial_expression_n_genes}"
    def simple_flag = params.use_simple_spatial_expression_model ? "--simple" : ""
    def alpha0_flag = "--alpha0 ${params.spatial_expression_alpha0}"
    def prior_var_flag = "--prior-var ${params.spatial_expression_prior_var}"
    def n_cell_min_flag = "--n-cell-min ${params.spatial_expression_n_cell_min}"
    def seed_flag = "--seed ${params.seed}"
    """
    spatial_expression --adata ${adata} \
        --output sde_samples.h5 \
        --deconvolve-results ${deconvolution_samples} \
        ${n_spatial_patterns_flag} \
        ${n_samples_flag} \
        ${n_burn_flag} \
        ${n_thin_flag} \
        ${n_gene_flag} \
        ${simple_flag} \
        ${alpha0_flag} \
        ${prior_var_flag} \
        ${n_cell_min_flag}
    """
}

def create_cell_type_names_flag(cell_type_names) {
    if (cell_type_names == null || cell_type_names.length == 0) {
        return ""
    } else {
        var cell_type_names_flag = "--cell-type-names "
        for (cell_type_name in cell_type_names) {
            cell_type_names_flag += "${cell_type_name},"
        }
        return cell_type_names_flag[0..-2]
    }
}

process PLOT_SPATIAL_EXPRESSION {
    label 'small_mem'
    publishDir "${params.outdir}/spatial_differential_expression_plots"

    input:
        path sde_samples
        path deconvolution_samples
        path adata

    output:
        path '*.pdf', emit: result, optional: true

    script:
    def cell_type_names_flag = create_cell_type_names_flag(params.cell_type_names)
    """
    plot_spatial_expression --adata ${adata} \
        --deconvolution-result ${deconvolution_samples} \
        --sde-result ${sde_samples} \
        ${cell_type_names_flag} \
        --moran-i-score-threshold ${params.significant_spatial_pattern_moran_i_score_threshold} \
        --tissue-threshold ${params.significant_spatial_pattern_tissue_threshold} \
        --gene-spatial-pattern-proportion-threshold ${params.significant_spatial_pattern_gene_spatial_pattern_proportion_threshold} \
        --output-dir .
    """
}

process READ_PHENOTYPE_SELECTION_RESULTS {
    label 'small_mem'
    publishDir "${params.outdir}/phenotype_selection_plots"

    input:
        path phenotype_selection_result
        val phenotype_selection_spatial_smoothing_values
    output:
        env LAMBDA, emit: lambda
        env N_COMPONENTS, emit: n_components
        path "*.pdf", emit: plots

    script:
    def phenotype_selection_spatial_smoothing_values_flag = create_lambda_values_flag(phenotype_selection_spatial_smoothing_values)
    """
    process_phenotype_selection_results \
        --plot-output . \
        --phenotype-selection-outputs ${phenotype_selection_result}* \
        ${phenotype_selection_spatial_smoothing_values_flag} \
        --output-lambda lambda \
        --output-n-components n_components

    LAMBDA=`cat lambda`
    N_COMPONENTS=`cat n_components`
    """
}

def calculate_n_phenotype_selection_jobs(lambdas, min_n_components, max_n_components, n_folds) {
    log.info "${lambdas}"
    return lambdas.size() * ((max_n_components + 1) - min_n_components) * n_folds
}

workflow BAYESTME {
    if (params.input_adata == null) {
        LOAD_SPACERANGER(file(params.spaceranger_dir, type: "dir"))
    }

    var phenotype_selection_spatial_smoothing_values = null

    if (params.inference_type == "SVI" && params.phenotype_selection_spatial_smoothing_values == null) {
        log.info "params.inference_type: ${params.inference_type}"
        phenotype_selection_spatial_smoothing_values = [0.5, 1, 2, 3, 5]
    } else if (params.inference_type == "MCMC" && params.phenotype_selection_spatial_smoothing_values == null) {
        log.info "params.inference_type: ${params.inference_type}"
        phenotype_selection_spatial_smoothing_values = [1, 10, 100, 1000, 10000]
    } else {
        log.info "params.inference_type: ${params.inference_type}"
        phenotype_selection_spatial_smoothing_values = params.phenotype_selection_spatial_smoothing_values
    }

    log.info "phenotype_selection_spatial_smoothing_values: ${phenotype_selection_spatial_smoothing_values}"

    var adata = params.input_adata == null ? LOAD_SPACERANGER.out.result : file(params.input_adata)

    FILTER_GENES(adata)

    BLEEDING_CORRECTION(FILTER_GENES.out.result)

    PLOT_BLEEDING_CORRECTION(FILTER_GENES.out.result,
        BLEEDING_CORRECTION.out.adata_output,
        BLEEDING_CORRECTION.out.bleed_correction_output)

    if (params.spatial_smoothing_parameter == null && params.n_components == null) {
        log.info "No values supplied for spatial_smoothing_parameter and n_components, will run phenotype selection."
        log.info "${params.phenotype_selection_spatial_smoothing_values}"

        var n_phenotype_jobs = calculate_n_phenotype_selection_jobs(
            phenotype_selection_spatial_smoothing_values,
            params.phenotype_selection_n_components_min,
            params.phenotype_selection_n_components_max,
            params.phenotype_selection_n_fold)

        log.info "Will need to run ${n_phenotype_jobs} jobs for phenotype selection."

        job_indices = Channel.of(0..(n_phenotype_jobs-1))

        PHENOTYPE_SELECTION(
            job_indices,
            BLEEDING_CORRECTION.out.adata_output,
            phenotype_selection_spatial_smoothing_values,
            params.phenotype_selection_n_components_min,
            params.phenotype_selection_n_components_max)
        READ_PHENOTYPE_SELECTION_RESULTS( PHENOTYPE_SELECTION.out.result.collect(), phenotype_selection_spatial_smoothing_values )
    } else if (params.spatial_smoothing_parameter == null && params.n_components != null) {
        log.info "No value supplied for spatial_smoothing_parameter, will run phenotype selection."
        log.info "${params.phenotype_selection_spatial_smoothing_values}"
        var n_phenotype_jobs = calculate_n_phenotype_selection_jobs(
            phenotype_selection_spatial_smoothing_values,
            params.n_components,
            params.n_components,
            params.phenotype_selection_n_fold)

        log.info "Will need to run ${n_phenotype_jobs} jobs for phenotype selection."

        job_indices = Channel.of(0..(n_phenotype_jobs-1))

        PHENOTYPE_SELECTION(
            job_indices,
            BLEEDING_CORRECTION.out.adata_output,
            phenotype_selection_spatial_smoothing_values,
            params.n_components,
            params.n_components)
        READ_PHENOTYPE_SELECTION_RESULTS( PHENOTYPE_SELECTION.out.result.collect(), phenotype_selection_spatial_smoothing_values )
    } else {
        log.info "Got values ${params.spatial_smoothing_parameter} and ${params.n_components} for spatial_smoothing_parameter and n_components, will skip phenotype selection."
    }

    def n_components = params.n_components == null ? READ_PHENOTYPE_SELECTION_RESULTS.out.n_components : params.n_components
    def lambda = params.spatial_smoothing_parameter == null ? READ_PHENOTYPE_SELECTION_RESULTS.out.lambda : params.spatial_smoothing_parameter

    DECONVOLUTION (BLEEDING_CORRECTION.out.adata_output,
        n_components,
        lambda,
        params.n_marker_genes,
        params.marker_gene_alpha_cutoff,
        params.marker_gene_method,
        params.deconvolution_use_spatial_guide,
        params.inference_type
    )

    if (params.run_spatial_expression) {
        SPATIAL_EXPRESSION( DECONVOLUTION.out.adata, DECONVOLUTION.out.samples )
        PLOT_SPATIAL_EXPRESSION( SPATIAL_EXPRESSION.out.samples, DECONVOLUTION.out.samples, DECONVOLUTION.out.adata )
    } else {
        log.info "Skipping spatial expression analysis"
    }
}
