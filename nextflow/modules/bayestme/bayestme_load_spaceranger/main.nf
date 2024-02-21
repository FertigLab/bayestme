process BAYESTME_LOAD_SPACERANGER {
    tag "$meta.id"
    label 'process_single'
    container "${ workflow.containerEngine == 'singularity' && !task.ext.singularity_pull_docker_container ?
        'docker://jeffquinnmsk/bayestme:21c53649d85be0642a9e3c797132f1b3088a4a36' :
        'docker.io/jeffquinnmsk/bayestme:21c53649d85be0642a9e3c797132f1b3088a4a36' }"

    input:
    tuple val(meta), path(spaceranger_dir)

    output:
    tuple val(meta), path("${prefix}/dataset.h5ad"), emit: adata
    path  "versions.yml"                 , emit: versions

    when:
    task.ext.when == null || task.ext.when

    script:
    prefix = task.ext.prefix ?: "${meta.id}"
    def args = task.ext.args ?: ""
    """
    mkdir "${prefix}"
    load_spaceranger --input ${spaceranger_dir} \
        --output "${prefix}/dataset.h5ad" \
        ${args}

    cat <<-END_VERSIONS > versions.yml
    "${task.process}":
        bayestme: \$( python -c 'from importlib.metadata import version;print(version("bayestme"))' )
    END_VERSIONS
    """
}
