#!/usr/bin/env python2.7
import os

from toil.job import PromisedRequirement

from toil_scripts.gatk_germline.common import output_file_job
from toil_scripts.tools.variant_filters import gatk_select_variants, \
    gatk_variant_filtration, gatk_combine_variants


def hard_filter_pipeline(job, uuid, vcf_id, config):
    """
    Runs GATK Hard Filtering on a Genomic VCF file and uploads the results.

    0: Start                0 --> 1 --> 3 --> 5 --> 6
    1: Select SNPs                |           |
    2: Select INDELs              +-> 2 --> 4 +
    3: Apply SNP Filter
    4: Apply INDEL Filter
    5: Merge SNP and INDEL VCFs
    6: Write filtered VCF to output directory

    :param job: Toil Job instance
    :param str uuid: Unique sample identifier
    :param str vcf_id: VCF FileStoreID
    :param Namespace config: Pipeline configuration options and shared files
    :return: SNP and INDEL FileStoreIDs
    :rtype: tuple
    """
    job.fileStore.logToMaster('Running Hard Filter on {}'.format(uuid))

    # Get the total size of the genome reference
    genome_ref_size = config.genome_fasta.size + config.genome_fai.size + config.genome_dict.size

    # The SelectVariants disk requirement depends on the input VCF, the genome reference files,
    # and the output VCF. The output VCF is smaller than the input VCF. The disk requirement
    # is identical for SNPs and INDELs.
    select_variants_disk = PromisedRequirement(lambda vcf, ref_size: 2 * vcf.size + ref_size,
                                               vcf_id,
                                               genome_ref_size)
    select_snps = job.wrapJobFn(gatk_select_variants,
                                'SNP',
                                vcf_id,
                                config.genome_fasta,
                                config.genome_fai,
                                config.genome_dict,
                                memory=config.xmx,
                                disk=select_variants_disk)

    # The VariantFiltration disk requirement depends on the input VCF, the genome reference files,
    # and the output VCF. The filtered VCF is smaller than the input VCF.
    snp_filter_disk = PromisedRequirement(lambda vcf, ref_size: 2 * vcf.size + ref_size,
                                          select_snps.rv(),
                                          genome_ref_size)
    # GATK hard filters:
    # https://software.broadinstitute.org/gatk/documentation/article?id=2806
    snp_filter_name = 'GERMLINE_SNP_FILTER'   # documents filter in header
    snp_filter_expression = '"QD < 2.0 || FS > 60.0 || MQ < 40.0 || MQRankSum < -12.5 || ReadPosRankSum < -8.0"'

    snp_filter = job.wrapJobFn(gatk_variant_filtration,
                               select_snps.rv(),
                               snp_filter_name,
                               snp_filter_expression,
                               config.genome_fasta,
                               config.genome_fai,
                               config.genome_dict,
                               memory=config.xmx,
                               disk=snp_filter_disk)

    select_indels = job.wrapJobFn(gatk_select_variants,
                                  'INDEL',
                                  vcf_id,
                                  config.genome_fasta,
                                  config.genome_fai,
                                  config.genome_dict,
                                  memory=config.xmx,
                                  disk=select_variants_disk)


    indel_filter_disk = PromisedRequirement(lambda vcf, ref_size: 2 * vcf.size + ref_size,
                                            select_indels.rv(),
                                            genome_ref_size)

    indel_filter_name = 'GERMLINE_INDEL_FILTER'
    indel_filter_expression = '"QD < 2.0 || FS > 200.0 || ReadPosRankSum < -20.0"'
    indel_filter = job.wrapJobFn(gatk_variant_filtration,
                                 select_indels.rv(),
                                 indel_filter_name,
                                 indel_filter_expression,
                                 config.genome_fasta,
                                 config.genome_fai,
                                 config.genome_dict,
                                 memory=config.xmx,
                                 disk=indel_filter_disk)

    # The CombineVariants disk requirement depends on the SNP and INDEL input VCFs and the
    # genome reference files. The combined VCF is approximately the same size as the input files.
    combine_vcfs_disk = PromisedRequirement(lambda vcf1, vcf2, ref_size:
                                            2 * (vcf1.size + vcf2.size) + ref_size,
                                            indel_filter.rv(),
                                            snp_filter.rv(),
                                            genome_ref_size)
    combine_vcfs = job.wrapJobFn(gatk_combine_variants,
                                 {'SNPs': snp_filter.rv(), 'INDELs': indel_filter.rv()},
                                 config.genome_fasta,
                                 config.genome_fai,
                                 config.genome_dict,
                                 merge_option='UNSORTED',  # Merges variants from a single sample
                                 memory=config.xmx,
                                 disk=combine_vcfs_disk)

    job.addChild(select_snps)
    job.addChild(select_indels)

    select_snps.addChild(snp_filter)
    snp_filter.addChild(combine_vcfs)

    select_indels.addChild(indel_filter)
    indel_filter.addChild(combine_vcfs)

    # Output the hard filtered VCF
    output_dir = os.path.join(config.output_dir, uuid)
    output_filename = '%s.hard_filter%s.vcf' % (uuid, config.suffix)
    output_vcf = job.wrapJobFn(output_file_job,
                               output_filename,
                               combine_vcfs.rv(),
                               output_dir,
                               s3_key_path=config.ssec,
                               disk=PromisedRequirement(lambda x: x.size, combine_vcfs.rv()))
    combine_vcfs.addChild(output_vcf)
    return combine_vcfs.rv()

def main():
    """
    Runs GATK hard filters on a VCF file
    """
    import argparse

    from toil.job import Job
    import yaml

    from toil_scripts.gatk_germline.germline import download_shared_files
    from toil_scripts.lib.urls import download_url_job

    parser = argparse.ArgumentParser(description=main.__doc__,
                                     formatter_class=argparse.RawTextHelpFormatter)

    parser.add_argument('--sample',
                        default=None,
                        nargs=2,
                        type=str,
                        help='Space delimited sample UUID and GVCF file in the format: uuid url')

    parser.add_argument('--config',
                        required=True,
                        type=str,
                        help='Path or URL to Toil germline config file')

    parser.add_argument('--output-dir',
                        default=None,
                        help='Path/URL to output directory')

    Job.Runner.addToilOptions(parser)
    options = parser.parse_args()

    # Parse inputs
    inputs = {x.replace('-', '_'): y for x, y in
              yaml.load(open(options.config).read()).iteritems()}

    inputs = argparse.Namespace(**inputs)

    inputs.run_bwa = False
    inputs.preprocess = False
    inputs.run_vqsr = False
    inputs.run_oncotator = False
    inputs.annotations = ['QualByDepth',
                          'FisherStrand',
                          'StrandOddsRatio',
                          'ReadPosRankSumTest',
                          'MappingQualityRankSumTest',
                          'RMSMappingQuality',
                          'InbreedingCoeff']

    shared_files = Job.wrapJobFn(download_shared_files, inputs).encapsulate()

    uuid, url = options.sample
    download_sample = shared_files.addFollowOnJobFn(download_url_job,
                                                    url,
                                                    name='toil.vcf',
                                                    s3_key_path=None,
                                                    disk=inputs.file_size)

    download_sample.addFollowOnJobFn(hard_filter_pipeline,
                                     uuid,
                                     download_sample.rv(),
                                     shared_files.rv())

    Job.Runner.startToil(shared_files, options)

if __name__ == '__main__':
    main()

