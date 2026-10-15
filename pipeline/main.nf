// pocketscan: for each UniProt accession, fetch the AlphaFold model, run fpocket,
// add structural context, and write the result to PostgreSQL.
//
//   export POCKETSCAN_DATABASE_URL=postgresql+psycopg://...
//   uv run nextflow run main.nf --job_id 7 --accessions P08100,Q9Y6K9
//
// One protein failing must not fail the batch: a failed protein is marked failed in
// the database (with a reason) and the others carry on.

// Parameters and their defaults are declared in nextflow.config.
//
// Network blips are retried; after that the protein is dropped from the channel
// (`ignore` keeps the rest of the batch running) and REPORT_FAILURE records it.

process FETCH {
    tag "${accession}"
    errorStrategy { task.attempt <= 2 ? 'retry' : 'ignore' }
    maxRetries 2
    publishDir path: { "${params.outdir}/${accession}" }, mode: 'copy'

    input:
    val accession

    output:
    tuple val(accession), path('meta.json'), path('model.cif')

    script:
    """
    fetch_alphafold.py ${accession}
    """
}

process FPOCKET {
    tag "${accession}"
    errorStrategy 'ignore'   // deterministic: retrying will not help
    publishDir path: { "${params.outdir}/${accession}" }, mode: 'copy'

    input:
    tuple val(accession), path(meta), path(model)

    output:
    tuple val(accession), path(meta), path(model), path('model_out')

    script:
    """
    fpocket -f ${model} \\
        -m ${params.fpocket_min_alpha_sphere_radius} \\
        -M ${params.fpocket_max_alpha_sphere_radius} \\
        -i ${params.fpocket_min_alpha_spheres}
    """
}

process ANALYSE {
    tag "${accession}"
    errorStrategy 'ignore'
    publishDir path: { "${params.outdir}/${accession}" }, mode: 'copy'

    input:
    tuple val(accession), path(meta), path(model), path(fpocket_dir)

    output:
    tuple val(accession), path('result.json')

    script:
    def base = file(params.outdir).resolve(accession)
    def params_json = groovy.json.JsonOutput.toJson([
        min_alpha_sphere_radius: params.fpocket_min_alpha_sphere_radius,
        max_alpha_sphere_radius: params.fpocket_max_alpha_sphere_radius,
        min_alpha_spheres      : params.fpocket_min_alpha_spheres,
    ])
    """
    analyse.py \\
        --meta ${meta} --model ${model} --fpocket-dir ${fpocket_dir} \\
        --tool-version '${params.tool_version}' \\
        --params '${params_json}' \\
        --structure-uri '${base.resolve('model.cif').toUri()}' \\
        --output-uri '${base.resolve('model_out').toUri()}'
    """
}

process RECORD {
    tag "${accession}"
    errorStrategy 'retry'
    maxRetries 2

    input:
    tuple val(accession), path(result)

    output:
    tuple val(accession), val(true)

    script:
    """
    python -m pocketscan_api.ingest result ${result} \\
        --job-id ${params.job_id} --accession ${accession}
    """
}

process REPORT_FAILURE {
    tag "${accession}"
    errorStrategy 'retry'
    maxRetries 2

    input:
    tuple val(accession), val(reason)

    script:
    """
    python -m pocketscan_api.ingest fail \\
        --job-id ${params.job_id} --accession ${accession} --error '${reason}'
    """
}

workflow {
    if (!params.job_id || !params.accessions) {
        error "usage: nextflow run main.nf --job_id <id> --accessions P08100,Q9Y6K9"
    }

    accessions = Channel.fromList(params.accessions.tokenize(',').collect { it.trim() }.unique())

    fetched  = FETCH(accessions)
    folded  = FPOCKET(fetched)
    analysed = ANALYSE(folded)
    RECORD(analysed)

    // A step that gave up emits nothing, so find the proteins that dropped out
    // by joining each stage against the one before it.
    never_fetched = accessions.map { acc -> tuple(acc, true) }
        .join(fetched.map { it -> tuple(it[0], true) }, remainder: true)
        .filter { it[2] == null }
        .map { it -> tuple(it[0], 'AlphaFold model not found or could not be downloaded') }

    never_analysed = fetched.map { it -> tuple(it[0], true) }
        .join(analysed.map { it -> tuple(it[0], true) }, remainder: true)
        .filter { it[2] == null }
        .map { it -> tuple(it[0], 'fpocket or the pocket analysis failed') }

    REPORT_FAILURE(never_fetched.mix(never_analysed))
}
