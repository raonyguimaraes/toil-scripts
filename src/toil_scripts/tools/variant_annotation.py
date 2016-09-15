import os
import tarfile

from toil_scripts.lib.programs import docker_call


def gatk_genotype_gvcfs(job,
                        gvcfs,
                        ref, fai, ref_dict,
                        annotations=None,
                        emit_threshold=10.0, call_threshold=30.0,
                        unsafe_mode=False):
    """
    Runs GenotypeGVCFs on one or more gVCFs generated by HaplotypeCaller.

    :param JobFunctionWrappingJob job: passed automatically by Toil
    :param dict gvcfs: Dictionary of GVCF FileStoreIDs {sample identifier: FileStoreID}
    :param str ref: FileStoreID for the reference genome fasta file
    :param str fai: FileStoreID for the reference genome index file
    :param str ref_dict: FileStoreID for the reference genome sequence dictionary
    :param list[str] annotations: Optional list of GATK variant annotations. Default: None.
    :param float emit_threshold: Minimum phred-scale confidence threshold for
                                 a variant to be emitted. GATK default: 10.0
    :param float call_threshold: Minimum phred-scale confidence threshold for
                                 a variant to be called. GATK default: 30.0
    :param bool unsafe_mode: If True, runs gatk UNSAFE mode: "-U ALLOW_SEQ_DICT_INCOMPATIBILITY"
    :return: VCF FileStoreID
    :rtype: str
    """
    inputs = {'genome.fa': ref,
              'genome.fa.fai': fai,
              'genome.dict': ref_dict}
    inputs.update(gvcfs)

    work_dir = job.fileStore.getLocalTempDir()
    for name, file_store_id in inputs.iteritems():
        job.fileStore.readGlobalFile(file_store_id, os.path.join(work_dir, name))

    command = ['-T', 'GenotypeGVCFs',
               '-R', '/data/genome.fa',
               '--out', 'genotyped.vcf',
               '-stand_emit_conf', str(emit_threshold),
               '-stand_call_conf', str(call_threshold)]

    if annotations:
        for annotation in annotations:
            command.extend(['-A', annotation])

    # Include all GVCFs for joint genotyping
    for uuid in gvcfs.keys():
        command.extend(['--variant', os.path.join('/data', uuid)])

    if unsafe_mode:
        command.extend(['-U', 'ALLOW_SEQ_DICT_INCOMPATIBILITY'])

    job.fileStore.logToMaster('Running GATK GenotypeGVCFs\n'
                              'Emit threshold: {emit_threshold}\n'
                              'Call threshold: {call_threshold}\n\n'
                              'Annotations:\n{annotations}\n\n'
                              'Samples:\n{samples}\n'.format(emit_threshold=emit_threshold,
                                                             call_threshold=call_threshold,
                                                             annotations='\n'.join(annotations) if annotations else '',
                                                             samples='\n'.join(gvcfs.keys())))

    docker_call(work_dir=work_dir,
                env={'JAVA_OPTS': '-Djava.io.tmpdir=/data/ -Xmx{}'.format(job.memory)},
                parameters=command,
                tool='quay.io/ucsc_cgl/gatk:3.5--dba6dae49156168a909c43330350c6161dc7ecc2',
                inputs=inputs.keys(),
                outputs={'genotyped.vcf': None})

    return job.fileStore.writeGlobalFile(os.path.join(work_dir, 'genotyped.vcf'))


def run_oncotator(job, vcf_id, oncotator_db):
    """
    Uses Oncotator to add cancer relevant variant annotations to a VCF file. Oncotator can accept
    other genome builds, but the output VCF is based on hg19.

    :param JobFunctionWrappingJob job: passed automatically by Toil
    :param str vcf_id: FileStoreID for VCF file
    :param str oncotator_db: FileStoreID for Oncotator database
    :return: Annotated VCF FileStoreID
    :rtype: str
    """
    job.fileStore.logToMaster('Running Oncotator')

    inputs = {'input.vcf': vcf_id,
              'oncotator_db': oncotator_db}

    work_dir = job.fileStore.getLocalTempDir()
    for name, file_store_id in inputs.iteritems():
        inputs[name] = job.fileStore.readGlobalFile(file_store_id, os.path.join(work_dir, name))

    # The Oncotator database may be tar/gzipped
    if tarfile.is_tarfile(inputs['oncotator_db']):
        tar = tarfile.open(inputs['oncotator_db'])
        tar.extractall(path=work_dir)
        # Get the extracted database directory name
        inputs['oncotator_db'] = tar.getmembers()[0].name
        tar.close()

    command = ['-i', 'VCF',
               '-o', 'VCF',
               '--db-dir', inputs['oncotator_db'],
               'input.vcf',
               'annotated.vcf',
               'hg19']  # Oncotator annotations are based on hg19

    docker_call(work_dir=work_dir,
                env={'_JAVA_OPTIONS': '-Djava.io.tmpdir=/data/ -Xmx{}'.format(job.memory)},
                parameters=command,
                tool='jpfeil/oncotator:1.9--8fffc356981862d50cfacd711b753700b886b605',
                inputs=inputs.keys(),
                outputs={'annotated.vcf': None})

    return job.fileStore.writeGlobalFile(os.path.join(work_dir, 'annotated.vcf'))
